// (c) 2020 Taeyeon Mori
// 

#include "koutil.hpp"
#include "kofs.hpp"
#include "kofd.hpp"
#include "koos.hpp"

#include <cstdlib>
#include <sstream>
#include <iostream>
#include <filesystem>

#include <unistd.h>
#include <pwd.h>
#include <mntent.h>


struct params {
    std::filesystem::path motd;
    bool ro = true;
    bool protect = true;
    char *const *argv = nullptr;
};

void usage(const char *prog) {
    std::cout << "Usage: " << prog << " [-m MOTD] [ARGV...]" << std::endl
              << std::endl
              << "Options:" << std::endl
              << "    -m MOTD     Specify a file to be displayed on login" << std::endl
              << "    ARGV        Specify the shell executable and arguments" << std::endl
              << "                By default, the shell from /etc/passwd is used with argument -l" << std::endl
              ;
}

params parse_args(int argc, char **argv) {
    params p{};

    constexpr auto spec = "+hm:";

    while (true) {
        auto opt = getopt(argc, const_cast<char *const *>(argv), spec);

        if (opt == -1)
            break;
        else if (opt == '?' || opt == 'h') {
            usage(argv[0]);
            exit(opt == 'h' ? 0 : 1);
        } else if (opt == 'm') {
            p.motd = ::optarg;
        }
    }

    if (argc > ::optind)
        p.argv = const_cast<char *const *>(&argv[::optind]);
    
    return p;
}

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

struct mntent_context {
    FILE *mounts;

    mntent_context(char const *fname) {
        mounts = setmntent(fname, "r");
    }

    operator bool() {
        return mounts != nullptr;
    }

    ~mntent_context() {
        if (mounts != nullptr)
            endmntent(mounts);
    }

    mntent *next() {
        return getmntent(mounts);
    }
};

int ro_all_mounts() {
    // Change all current mounts to readonly
    auto mounts = mntent_context("/proc/mounts");
    if (!mounts)
        return 1;
    
    mntent *ent;
    while ((ent = mounts.next()) != nullptr) {
        if (ko::os::bind(ent->mnt_dir, ent->mnt_dir, MS_REMOUNT|MS_RDONLY))
            return 1;
    }

    return 0;
}

int protect_self() {
    // Hide self by by bind-mounting /dev/zero on top. Make it harder to exploit any vulns, just in case
    // Though this does give away the name of the executable...
    auto path = ko::fd::readlink("/proc/self/exe");
    if (path.empty())
        return 1;
    return ko::os::bind("/dev/null", path);
}

int main(int argc, char **argv) {
    params p = parse_args(argc, argv);
    uid_t ruid, euid, suid;
    gid_t rgid, egid, sgid;
    passwd *passwd;
    std::string options;
    const char *default_shell_argv[] = {nullptr, "-l", nullptr}; // gets executable name from user passwd record

    // Use shell from passwd if no command is given in argv
    if (p.argv == nullptr)
        p.argv = const_cast<char *const*>(default_shell_argv);

    auto [e, eloc] = ko::util::cvshort()
        .then("getresuid",          getresuid, &ruid, &euid, &suid)
        .then("getresgid",          getresgid, &rgid, &egid, &sgid)
        .then("getpwuid",           [ruid,euid,&passwd]() {
            // Check root perms
            if (euid != 0)
                die(3, "Must be suid root");
            // Retrieve user info
            errno = 0;
            passwd = getpwuid(ruid);
            if (errno != 0)
                return 5;
            else if (passwd == nullptr)
                die(4, "Calling user ID not known to system");
            return 0;
        })
        .then("setegid",            ::setegid, 0)
        .then("unshare",            ::unshare, CLONE_NEWNS)
        .then("make ns slave",      ko::os::mount, "", "/", "", MS_REC|MS_SLAVE, nullptr)
        .ifthen("make fs readonly", p.ro, ro_all_mounts)
        .ifthen("protect self",     p.protect, protect_self)
        .then("mount tmp",          ko::os::mount, "tmpfs", "/tmp", "tmpfs", MS_NOEXEC|MS_NODEV|MS_NOSUID, nullptr)
        .then([ruid,rgid,suid,&options,passwd,&default_shell_argv]() -> ko::util::cvresult {
            // Create directories
            auto d = ko::fd::opendir("/tmp");
            auto r = ko::util::cvshort()
                .then("fchown tmp", ::fchown, (int)d, ruid, rgid)
                .then("setegid",    ::setegid, rgid)
                .then("seteuid",    ::seteuid, ruid)
                .then("mkdir .home",  ko::fd::mkdir, ".home", 0750, (int)d)
                .then("mkdir work",   ko::fd::mkdir, ".home/work", 0750, (int)d)
                .then("mkdir top",    ko::fd::mkdir, ".home/top", 0750, (int)d)
                .then("seteuid root", ::seteuid, suid);
            if (r) {
                // Build option string
                options = ko::util::str("lowerdir=", passwd->pw_dir, ",upperdir=/tmp/.home/top,workdir=/tmp/.home/work");
                // Use shell from passwd
                default_shell_argv[0] = passwd->pw_shell;
            }
            return r;
        })
        .then("mount overlay",      ko::os::mount, "overlay", passwd->pw_dir, "overlay", 0, (void*)options.c_str())
        .ifthen("show motd",        !p.motd.empty(), [&p]() {
            auto f = ko::fd::open(p.motd, O_RDONLY);
            if (!f)
                return 1;
            struct stat st;
            if (::fstat(f, &st))
                return 1;
            return ko::fd::fcopy(f, STDOUT_FILENO, st.st_size) ? 0 : 1;
        })
        .then("chdir home",         ::chdir, passwd->pw_dir)
        .then("drop gid",           ::setresgid, rgid, rgid, rgid)
        .then("drop uid",           ::setresuid, ruid, ruid, ruid)
        .then("exec",               ::execvp, p.argv[0], p.argv);

    perror(eloc);
    return e;
}

