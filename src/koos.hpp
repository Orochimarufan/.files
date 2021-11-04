// ============================================================================
// koos.hpp
// ko::os
// (c) 2019 Taeyeon Mori <taeyeon at oro.sodimm.me>
// ============================================================================
// Misc. OS interfaces

#pragma once

#include "kofs.hpp"

#include <mntent.h>
#include <pwd.h>
#include <sys/mount.h>


namespace ko::os {
/// Try to get the current user home directory
fs::path get_home() {
    const char *home_env = getenv("HOME");

    if (home_env)
        return fs::path(home_env);

    auto pwd = getpwuid(getuid());

    if (pwd)
        return fs::path(pwd->pw_dir);

    return fs::path("/");
}

// ------------------------------------------------------------------
// Mounting filesystems
inline int mount(const fs::cpath &src, const fs::cpath &dst, const char *type, long flags=0, void *args=nullptr) {
    auto res = ::mount(src, dst, type, flags, args);
    if (res)
        return errno;
    return 0;
}

inline int bind(const fs::cpath &src, const fs::cpath &dst, long flags=0) {
    return mount(src, dst, nullptr, MS_BIND | flags, nullptr);
}

/// Check if a path is a mount point
bool is_mountpoint(const fs::cpath &path) {
    auto fp = setmntent("/proc/self/mounts", "r");
    if (!fp) {
        perror("mntent");
        return false;
    }

    bool found = false;

    while (auto ent = getmntent(fp)) {
        if (!strcmp(path, ent->mnt_dir)) {
            found = true;
            break;
        }
    }

    endmntent(fp);

    return found;
}

} // namespace ko::os
