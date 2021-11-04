#include <iostream>
#include <filesystem>
#include <unordered_set>
#include <fstream>

#include "koutil.hpp"
#include "kofd.hpp"
#include "koos.hpp"

namespace fs = std::filesystem;

void usage(const char *prog) {
    std::cout << "Usage: " << prog << " [option...] <newhome> [prog] [arg...]" << std::endl
              << "  (c) 2019 Taeyeon Mori" << std::endl
              << std::endl
              << "  This program allows confining an application to it's own home directory" << std::endl
              << "  without chainging the literal home directory path." << std::endl
              << std::endl
              << "Options:" << std::endl
              << "  -h        Display this help text" << std::endl
              << "  -H HOME   Override the home directory path" << std::endl
              << "  -w        Don't make / read-only" << std::endl
              << "  -W        Preserve working directory" << std::endl
              //<< "  -s        Make (the rest of) /home inaccessible" << std::endl
              //<< "  -S        Make /media and /mnt inaccessible as well (implies -s)" << std::endl
              //<< "  -x PATH   Make path inaccessible" << std::endl
              << std::endl
              << "Parameters:" << std::endl
              << "   newhome  The new home directory path" << std::endl
              << "   prog     The executable to run (defaults to $SHELL)" << std::endl
              << "   arg...   The executable parameters" << std::endl;
}

struct params {
    fs::path home, newhome;
    bool rw = false,
         nohome = false,
         nomnt = false,
         pwd = true;
    std::unordered_set<std::string> hide;
    const char *const *argv = nullptr;
};

int bindfile(const params &p, fs::path path) {
    auto opath = p.home / path;
    if (fs::exists(opath)) {
        auto npath = p.newhome / path;

        if (!fs::exists(npath)) {
            if (fs::is_directory(opath))
                fs::create_directories(npath);
            else {
                fs::create_directories(npath.parent_path());
                auto touch = std::ofstream(npath);
            }
        }

        if(ko::os::bind(opath, npath, 0))
            return -1;
        return ko::os::bind(npath, npath, MS_REMOUNT|MS_RDONLY);
    }
    return 0;
}

int pmain(params p) {
    auto uid = getuid(),
         gid = getgid();
    auto [e, eloc] = ko::util::cvshort()
        .then("unshare",           ::unshare, CLONE_NEWUSER|CLONE_NEWNS)
        .then("bind Xauthority",   bindfile, p, ".Xauthority")
        .then("bind pulse cookie", bindfile, p, ".config/pulse/cookie")
        .then("bind home",         ko::os::bind, p.newhome, p.home, MS_REC)
        .ifthen("make / ro",       !p.rw, ko::os::bind, "/", "/", MS_REMOUNT|MS_RDONLY)
        .ifthen("chdir",           p.pwd, ::chdir, p.home.c_str())
        .then([uid,gid]() -> ko::util::cvresult {
                auto dir = ko::fd::opendir("/proc/self");
                if (!dir)
                    return {-1, "open /proc/self"};
                if (!ko::fd::dump("deny", "setgroups", 0644, dir))
                    return {-1, "write setgroups"};
                if (!ko::fd::dump(ko::util::str(gid, " ", gid, " 1\n"), "gid_map", 0644, dir))
                    return {-1, "write gid_map"};
                if (!ko::fd::dump(ko::util::str(uid, " ", uid, " 1\n"), "uid_map", 0644, dir))
                    return {-1, "write uid_map"};
                return {0, nullptr};
                })
        .then("setresgid", ::setresgid, gid, gid, gid)
        .then("setresuid", ::setresuid, uid, uid, uid)
        .then("exec",      ::execvp, p.argv[0], const_cast<char *const *>(p.argv));
    perror(eloc);
    return e;
}

int main(int argc, char **argv) {
    static const char *exec_argv[] = {getenv("SHELL"), nullptr};
    params p{
        .home = ko::os::get_home(),
        .argv = exec_argv
    };

    constexpr auto spec = "+hH:wsSxW";

    while (true) {
        auto opt = getopt(argc, const_cast<char *const *>(argv), spec);

        if (opt == -1)
            break;
        else if (opt == '?' || opt == 'h') {
            usage(argv[0]);
            return opt == 'h' ? 0 : 1;
        }
        else if (opt == 'H')
            p.home = ::optarg;
        else if (opt == 'w')
            p.rw = true;
        else if (opt == 'W')
            p.pwd = false;
        else if (opt == 's' || opt == 'S') {
            p.hide.emplace("/home");
            if (opt == 'S') {
                p.hide.emplace("/media");
                p.hide.emplace("/mnt");
            }
        }
        else if (opt == 'x')
            p.hide.emplace(::optarg);
    }

    if (argc == ::optind) {
        std::cout << "Error: missing mandatory newhome argument, see `" << argv[0] << " -h`" << std::endl;
        return 2;
    }

    p.newhome = argv[::optind++];

    if (argc > ::optind)
        p.argv = &argv[::optind];

    return pmain(p);
}

