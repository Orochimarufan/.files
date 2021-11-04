// Fake sudo using user namespace; Similar to fakeroot
// (c) 2020 Taeyeon Mori <taeyeon at oro.sodimm.me>

#include "kons.hpp"

#include <cstdlib>
#include <iostream>

#include <unistd.h>
#include <getopt.h>
#include <pwd.h>
#include <grp.h>


// Helpers
int xerror(const char *desc) {
    perror(desc);
    return -errno;
}

[[noreturn]] void die(int r, const char *msg) {
    std::cerr << msg << std::endl;
    exit(r);
}

[[noreturn]] void die_errno(int r, const char *msg) {
    perror(msg);
    exit(r);
}

// ========================================================
// Main
// ========================================================
void usage(const char *prog) {
    std::cout << "Usage:" << std::endl
              << "    " << prog << " -h | -K | -k | -V" << std::endl
              << "    " << prog << " -v [-k] [-u user] [-g group]" << std::endl
              << "    " << prog << " -e [-k] [-u user] [-g group] [--] file" << std::endl
              << "    " << prog << " [-bEHPk] [-u user] [-g group] [-i|-s] [--] command" << std::endl
              << std::endl
              << "General Options:" << std::endl
              << "  -h        Display this help text" << std::endl
              << std::endl;
}

struct config {
    const char *const *exec_argv = nullptr;
    bool background = false,
         preserve_env = false,
         editor = false,
         login = false,
         set_home = false,
         preserve_groups = false,
         run_shell = false;
    uid_t uid = 0;
    gid_t gid = 0;
};

template <typename F, typename R, typename T>
R get_pwd(F f, R std::remove_pointer_t<std::invoke_result_t<F,T>>::*fld, T nam) {
    auto s = f(nam);

    if (!s)
        die(20, "Could not resolve user or group");

    return s->*fld;
}

// Parse commandline arguments
// returns -1 on success, exit code otherwise
int parse_cmdline(config &conf, int argc, const char *const *argv) {
    constexpr auto spec = "+hbEeg:HiKkPpsu:Vv";
    constexpr option longspec[] = {{"help",0,nullptr,'h'},
                                   {"background",0,nullptr,'b'},
                                   {"preserve-env",2,nullptr,'E'},
                                   {"edit",0,nullptr,'e'},
                                   {"group",1,nullptr,'g'},
                                   {"set-home",0,nullptr,'H'},
                                   {"login",0,nullptr,'i'},
                                   {"remove-timestamp",0,nullptr,'K'},
                                   {"reset-timestamp",0,nullptr,'k'},
                                   {"preserve-groups",0,nullptr,'P'},
                                   {"prompt",1,nullptr,'p'},
                                   {"shell",0,nullptr,'s'},
                                   {"user",1,nullptr,'u'},
                                   {"version",0,nullptr,'V'},
                                   {"validate",0,nullptr,'v'},
                                   {nullptr,0,nullptr,0}};

    while (true) {
        auto opt = getopt_long(argc, const_cast<char *const *>(argv), spec, longspec, nullptr);

        if (opt == -1)
            break;
        else if (opt == '?' || opt == 'h') {
            usage(argv[0]);
            return opt == 'h' ? 0 : 1;
        }
        else if (opt == 'V') {
            std::cout << "fakensudo Namespace fake sudo version 0.1" << std::endl
                      << "(c) 2020 Taeyeon Mori" << std::endl;
            return 0;
        }

        else if (opt == 'b') conf.background = true;
        else if (opt == 'E') conf.preserve_env = true; // XXX: ignores the optinal list
        else if (opt == 'e') conf.editor = true;
        else if (opt == 'g') conf.gid = get_pwd(getgrnam, &group::gr_gid, optarg);
        else if (opt == 'H') conf.set_home = true;
        else if (opt == 'i') conf.login = true;
        else if (opt == 'K') return 0; // XXX: check for clashes
        else if (opt == 'k') /* pass */;
        else if (opt == 'P') conf.preserve_groups = true;
        else if (opt == 'p') /* pass */;
        else if (opt == 's') conf.run_shell = true;
        else if (opt == 'u') conf.uid = get_pwd(getpwnam, &passwd::pw_uid, optarg);
        else if (opt == 'v') return 0; // XXX: properly check options
        else die(10, "Unknown option encountered");
    }

    // Check sanity
    bool good = true;

    if (conf.run_shell || conf.login) {
        if (conf.run_shell && conf.login)
            good = false;
        if (conf.editor)
            good = false;
    } else if (::optind >= argc)
        good = false;

    if (!good) {
        usage(argv[0]);
        return 5;
    }

    // Rest is child cmnd
    if (argc > ::optind)
        conf.exec_argv = &argv[::optind];

    return -1;
}


int main(int argc, char **argv) {
    // Set defaults
    auto conf = config{};

    // Parse commandline
    auto perr = parse_cmdline(conf, argc, argv);
    if (perr != -1)
        return perr;

    auto uerr = ko::ns::unshare_single(conf.uid, conf.gid, CLONE_NEWUSER);
    if (uerr != 0)
        die_errno(31, "unshare");

    // Drop Permissions
    setresgid(conf.gid, conf.gid, conf.gid);
    setresuid(conf.uid, conf.uid, conf.uid);

    auto exec_argv = conf.exec_argv;
    if (conf.run_shell) {
        auto shell = getenv("SHELL");
        if (shell == nullptr)
            die(41, "Could not get SHELL from environment");
        if (conf.exec_argv == nullptr || *conf.exec_argv == nullptr)
            exec_argv = new char*[]{shell, nullptr};
        else
            die(200, "-s not fully implemented");
    } else if (conf.login) {
        auto shell = get_pwd(getpwuid, &passwd::pw_shell, conf.uid);
        if (shell == nullptr)
            die(41, "Could not get SHELL from passwd record");
        if (conf.exec_argv == nullptr || *conf.exec_argv == nullptr)
            exec_argv = new char*[]{shell, "-l", nullptr};
        else
            die(200, "-i not fully implemented");
    } else if (conf.editor) {
        die(200, "-e not implemented");
    }

    // Exec
    execvpe(exec_argv[0], const_cast<char *const*>(exec_argv), environ);
    die_errno(33, "exec");
}

