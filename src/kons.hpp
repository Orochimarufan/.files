/*
 * Small Linux Namespace utility header
 * (c) 2019 Taeyeon Mori <taeyeon AT oro.sodimm.me>
 */

#pragma once

#include "koutil.hpp"
#include "kofd.hpp"
#include "koos.hpp"

#include <sched.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

#include <array>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>


namespace ko::ns {

/**
 * idmap namespace
 * Contains functions for setting /proc/pid/[ug]id_map
 */
namespace idmap {
    /// An entry in [ug]id_map
    struct entry {
        uid_t start;
        uid_t host_start;
        unsigned long count;
    };

    /// Write the idmap <map> to <path>
    template <typename Container>
    inline bool set(fs::path path, Container map) {
        auto stream = std::ofstream(path);
        for (entry &e : map)
            stream << e.start << ' ' << e.host_start << ' ' << e.count << '\n';
        stream.close();
        return stream.good();
    }

    /// Disable setgroups() syscall for process <pid>
    /// This is required for unprivileged user namespaces
    bool disable_setgroups(pid_t pid) {
        auto stream = std::ofstream(util::str("/proc/", pid, "/setgroups"));
        stream << "deny";
        stream.close();
        return stream.good();
    }

    /// Return an idmap mapping a single ID
    inline constexpr std::array<entry, 1> single(uid_t id, uid_t host_id) {
        return {{ {id, host_id, 1} }};
    }

    /// Get the path to the <map_type> map for <pid>
    /// <map_type> may be "uid" or "pid"
    inline fs::path path(pid_t pid, const char *map_type) {
        return util::str("/proc/", pid, "/", map_type, "_map");
    }
}


/**
 * namespace kons::mount
 * Stuff related to setting up the mount namespace
 */
namespace mount {
    using os::mount;
    using os::bind;

    // Mount all the basic filesystems
    util::cvresult mount_core(const fs::path &root) {
        return util::cvshort()
        .ifthen("mount_root",   !os::is_mountpoint(root),   bind, root, root, 0)
        .ifthen("mount_proc",   fs::exists(root / "proc"),  mount, "proc", root / "proc", "proc", 0, nullptr)
        .ifthen("mount_sys",    fs::exists(root / "sys"),   bind, "/sys", root / "sys", MS_REC)
        .ifthen("mount_dev",    fs::exists(root / "dev"),   bind, "/dev", root / "dev", MS_REC)
        .ifthen("mount_tmp",    fs::exists(root / "tmp"),   mount, "tmp", root / "tmp", "tmpfs", 0, nullptr)
        .ifthen("mount_run",    fs::exists(root / "run"),   mount, "run", root / "run", "tmpfs", 0, nullptr);
    }

    /// Write-protect path to mitigate broken filesystem permissions in single-user ns
    util::cvresult protect_path(const fs::path &path) {
        return util::cvshort()
        .then("bind_protect", bind, path, path, MS_REC)
        .then("bind_protect_ro", bind, path, path, MS_REC|MS_REMOUNT|MS_RDONLY);
    }

    /// Bind in additional locations required by GUI programs
    /// Some of these are serious isolation breaches!
    /// Note that home and rundir must be relative and will be interpreted against both '/' and $root
    util::cvresult mount_gui(const fs::path &root, const fs::path &home, const fs::path &rundir) {
        auto path_from_env = [](const char *name, fs::path dflt, const char *prefix=nullptr) -> fs::path {
            auto var = getenv(name);
            if (var != nullptr) {
                if (prefix != nullptr) {
                    auto plen = strlen(prefix);
                    if (!strncmp(var, prefix, plen))
                        var += plen;
                }
                if (var[0] == '/')
                    return var+1;
            }
            return dflt;
        };
        auto path_from_env_rel = [](fs::path to, const char *name, const char *dflt) -> fs::path {
            auto var = getenv(name);
            if (var != nullptr)
                return to / var;
            return to / dflt;
        };
        // Bind-mount various paths required to get GUI apps to communicate with system services
        // X11, DBus (both buses, Steam does use the system bus), PulseAudio
        auto frags = std::array<fs::path, 9>{
            "tmp/.X11-unix",
            "run/dbus",
            "run/udev", // Udev database for correct ENV entries e.g. ID_INPUT_JOYSTICK markers
            //"etc/machine-id", // Pulseaudio will only connect with same machine-id by default. See below
            path_from_env("XAUTHORITY", home / ".Xauthority"),
            home / ".config/pulse/cookie",
            path_from_env("DBUS_SESSION_BUS_ADDRESS", rundir / "bus", "unix:path="),
            rundir / "pulse",
            rundir / "pipewire-0",
            path_from_env_rel(rundir, "WAYLAND_DISPLAY", "wayland-0"),
        };
        
        // /tmp/.X11-unix must be owned by user or root for wlroots xwayland to work (e.g. gamescope)
        // behaviour can be overridden by env var KONS_BIND_X11=all
        if (![&frags, root]() {
            auto x11_mount_mode = getenv("KONS_BIND_X11");
            if (x11_mount_mode && !strcasecmp("all", x11_mount_mode))
                return true;
            auto display = getenv("DISPLAY");
            if (!display)
                return false;
            if (display[0] == ':')
                display += 1;
            for (char *c = display; *c; c++)
                if (!isdigit(*c))
                    return false;
            auto dirname = root / frags[0];
            fs::create_directories(dirname);
            ::chmod(dirname.c_str(), 01777);
            auto sockname = frags[0] / util::str("X", display);
            fd::touch(root / sockname);
            frags[0] = sockname;
            return true;
        }()) {
            std::cerr << "Warn: Invalid $DISPLAY value; falling back to bind-mounting /tmp/.X11-unix whole" << std::endl;
        }

        // Pulseaudio will by default only connect to the server published in the X11 root window properties if the machine-ids match.
        // Either we bind-mount /etc/machine-id or we need to set PULSE_SERVER in the environment. Both are suboptimal hacks:
        // /etc/machine-id shoudn't be the same across two rootfs' but it might be acceptable since we're not running init.
        // OTOH, setting PULSE_SERVER can break with nonstandard configurations if they're not manually set in ENV. X11 publish is not enough.
        auto pulse = util::str("unix:/", rundir.c_str(), "/pulse/native");
        setenv("PULSE_SERVER", pulse.c_str(), 0); // Don't overwrite, assume that there's a reason it's set. May be TCP.
                                                  // If custom unix socket path, it could fail either way as it may not be included above.
        // NOTE that exec[vlp]e() must be used to make setenv() work.

        auto sh = util::cvshort();
        auto host_root = fs::path("/");
        for (auto frag : frags) {
            auto hpath = host_root / frag;

            if (fs::exists(hpath)) {
                auto path = root / frag;

                if (!fs::exists(path)) {
                    if (fs::is_directory(hpath))
                        fs::create_directories(path);
                    else {
                        fs::create_directories(path.parent_path());
                        auto touch = std::ofstream(path);
                    }
                }

                if (!(sh = sh.then("mount_gui", bind, hpath, path, 0)))
                    break;
            }
        }

        return sh;
    }

    /// Pivot the root to $new_root, optionally keeping the old one at $old_root.
    /// Note that the $old_root directory is required in the process either way.
    util::cvresult pivot_root(const fs::path &new_root, const fs::path &old_root, bool keep_old=true) {
        auto path = new_root / old_root;
        if (!fs::exists(path))
            fs::create_directories(path);

        return util::cvshort()
            .then("pivot_root", syscall, SYS_pivot_root, new_root.c_str(), path.c_str())
            .then("chdir_root", chdir, "/")
            .ifthen("umount_oldroot", !keep_old, umount2, old_root.c_str(), MNT_DETACH);
    }
} // namespace mount


/**
 * Unshare (at least) new single-user namespace
 * @param uid The uid inside the userns
 * @param gid The gid inside the userns
 * @param flags The unshare(2)/clone(2) flags (CLONE_NEWUSER implied)
 * @return Zero on success, -1 + errno on failure
 */
inline int unshare_single(uid_t uid, uid_t gid, long flags) {
    auto euid = geteuid();
    auto egid = getegid();
    auto r = ::unshare(flags | CLONE_NEWUSER);
    if (r != 0)
        return r;
    if (!idmap::set("/proc/self/uid_map", idmap::single(uid, euid)))
        return -1;
    if (!idmap::disable_setgroups(getpid()))
        return -1;
    if (!idmap::set("/proc/self/gid_map", idmap::single(gid, egid)))
        return -1;
    return 0;
}


inline int setns(const fs::cpath &path, int type, int dirfd=AT_FDCWD) {
    auto fd = ::openat(dirfd, path, O_RDONLY);
    if (fd < 0)
        return errno;
    auto res = ::setns(fd, type);
    ::close(fd);
    return res;
}

} // namespace ko::ns

