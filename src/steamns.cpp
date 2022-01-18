// Isolate steam in a namespace
// (c) 2019 Taeyeon mori <taeyeon at oro.sodimm.me>

#include "kons_clone.hpp"

#include <cstdlib>
#include <sstream>
#include <iostream>
#include <fstream>
#include <filesystem>

#include <unistd.h>
#include <sys/signalfd.h>


namespace fs = std::filesystem;

// TODO: XDG_RUNTIME_DIR etc

constexpr auto ROOT_DIR = ".local/steam";
constexpr auto DEFAULT_CMD = std::array<char const *const, 2>{"/bin/bash", nullptr};
constexpr auto STEAM_USER = "steamuser";

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

// Report to parent process
template <typename T>
class proc_future {
    sem_t ready;
    T value;
    
    proc_future(int shared) {
        sem_init(&ready, shared, 0);
    }
    
    ~proc_future() {
        sem_destroy(&ready);
    }

public:
    T wait() {
        sem_wait(&ready);
        return value;
    }
    
    void post(const T &v) {
        value = v;
        sem_post(&ready);
    }
    
    static proc_future<T> *create() {
        auto shm = mmap(nullptr, sizeof(proc_future<T>), PROT_READ|PROT_WRITE, MAP_ANONYMOUS|MAP_SHARED, -1, 0);
        if (shm == MAP_FAILED)
            return nullptr;
        return new (shm) proc_future<T>(1);
    }
    
    // in shared VM, unmap() must be skipped
    static proc_future<T> *create_private() {
        auto shm = mmap(nullptr, sizeof(proc_future<T>), PROT_READ|PROT_WRITE, MAP_ANONYMOUS|MAP_PRIVATE, -1, 0);
        if (shm == MAP_FAILED)
            return nullptr;
        return new (shm) proc_future<T>(0);
    }
    
    // Waiting process must call destroy()
    void destroy() {
        this->~proc_future();
        munmap(this, sizeof(proc_future<T>));
    }
    
    // Posting process must call unmap() instead
    void unmap() {
        munmap(this, sizeof(proc_future<T>));
    }
};


// ========================================================
// Namespace spawn process
// ========================================================
namespace nsproc {
    struct config {
        fs::path root_path, home_path, pwd;
        char *const *exec_argv; // must be nullptr-terminated
        uid_t uid, gid;
        bool mounts, gui_mounts, system_ro, keep_root, dummy_mode, pid_ns, use_host_root;
        std::optional<fs::path> setup_exec;
        int ns_path_fd;
    };

    int pid1() {
        sigset_t mask;
        sigemptyset(&mask);
        sigaddset(&mask, SIGCHLD);

        if (sigprocmask(SIG_BLOCK, &mask, NULL) == -1)
            return xerror("sigprocmask");
        
        int sfd = signalfd(-1, &mask, 0);
        if (sfd == -1)
            return xerror("signalfd");
        
        fd_set fds;
        struct timeval const tv = {.tv_sec = 60,.tv_usec = 0};

        while (true) {
            FD_ZERO(&fds);
            FD_SET(sfd, &fds);

            struct timeval _tv = tv;
            int retval = select(sfd + 1, &fds, NULL, NULL, &_tv);

            if (retval < 0)
                return xerror("select");
            else if (retval) {
                struct signalfd_siginfo si;
                int s = read(sfd, &si, sizeof(si));
                if (s != sizeof(si))
                    return xerror("signalfd_read");
                if (si.ssi_signo != SIGCHLD) {
                    std::cerr << "Warn: Got signal != SIGCHLD" << std::endl;
                }

                // Reap children
                while (true) {
                    pid_t w = ::waitpid(-1, NULL, WNOHANG);

                    if (w == 0) {
                        break;
                    } else if (w == -1) {
                        if (errno == ECHILD)
                            break;
                        else
                            // XXX: Should this abort?
                            perror("waitpid");
                    }
                }
            }

            // Check if there are still processes in namespace
            auto dir = ko::fs::dir_ptr("/proc");
            int count = 0;
            for (auto ent : dir) {
                if (!isdigit(ent.d_name[0]))
                    continue;
                count++;
            }
            if (count <= 1)
                return 0;
        }
    }

    int exec_app(const config &conf) {
        if (conf.pwd.empty()) {
            // Go to home is_directory
            auto home = ko::os::get_home();
            fs::create_directories(home);
            chdir(home.c_str());
        } else if (chdir(conf.pwd.c_str())) {
            die_errno(50, "Could not preserve working directory (Maybe -k is required?)");
        }

        // Env.
        setenv("TMPDIR", "/tmp", 1); // Any subfolders may not exist
        setenv("PULSE_SERVER", ko::util::str("unix:/run/user/", conf.uid, "/pulse/native").c_str(), 0);

        // Run provided setup cmd
        if (conf.setup_exec) {
            const char* argv[2] = {conf.setup_exec.value().c_str(), nullptr};
            auto proc = ko::proc::simple_spawn(argv);
            proc.wait();
        }

        // Drop Permissions
        setresgid(conf.gid, conf.gid, conf.gid);
        setresuid(conf.uid, conf.uid, conf.uid);

        // Exec
        execvpe(conf.exec_argv[0], conf.exec_argv, environ);
        return xerror("exec");
    }

    int nsproc_create(const config &conf, proc_future<int> *report) {
        // Mount Namespace
        fs::path root = conf.root_path;
        if (conf.mounts) {
            // Slightly hacky
            auto run_media_path = ko::util::str("/run/media/", getenv("USER"));
            auto [err, where] = ko::util::cvshort()
                // Mount base system: /, /proc, /sys, /dev, /tmp, /run
                .then([&conf, &root]() -> ko::util::cvresult {
                    if (conf.use_host_root) {
                        root = ko::fs::create_temporary_directory();
                        auto rel_home = conf.home_path.relative_path();
                        if (root.empty())
                            return {1, "create temporary directory"};
                        return ko::util::cvshort()
                            .then("bind_host_root",
                                ko::os::bind, "/", root, MS_REC|MS_SLAVE)
                            // Make / read-only
                            .ifthen("remount_ro", conf.system_ro,
                                ko::os::bind, "/", root, MS_REMOUNT|MS_RDONLY)
                            .ifthen("mount_tmp", fs::exists(root / "tmp"),
                                ko::os::mount, "tmp", root / "tmp", "tmpfs", 0, nullptr)
                            .ifthen("mount_run", fs::exists(root / "run"),
                                ko::os::mount, "run", root / "run", "tmpfs", 0, nullptr)
                            .then("bind_home",
                                ko::os::bind, conf.root_path / rel_home, root / rel_home, MS_REC|MS_SLAVE);
                    } else {
                        return ko::util::cvshort()
                            .then(ko::ns::mount::mount_core, root)
                            // Mount /usr readonly because file permissions are useless in a single-uid namespace
                            .ifthen(conf.system_ro && fs::exists(root / "usr"),
                                ko::ns::mount::protect_path, root / "usr")
                            .ifthen(conf.system_ro && fs::exists(root / "etc"),
                                ko::ns::mount::protect_path, root / "etc")
                            // Recursively bind in /media and /run/media/$USER for games
                            .ifthen("bind_media", fs::exists("/media") && fs::exists(root / "media"),
                                ko::os::bind, "/media", root / "media", MS_REC)
                            // Add a dummy user to /etc/passwd
                            .then("bind_passwd", [&conf, &root]() {
                                auto etc_passwd = root / "etc/passwd";
                                auto tmp_passwd = root / "tmp/passwd";

                                if (fs::exists(etc_passwd)) {
                                    fs::copy(etc_passwd, tmp_passwd);
                                    auto s = std::fstream(tmp_passwd, std::fstream::out | std::fstream::app);
                                    s << std::endl << STEAM_USER << ":x:" << conf.uid << ":" << conf.gid << ":Steam Container User:" << conf.home_path.native() << ":/bin/bash" << std::endl;
                                    s.close();
                                    return ko::os::bind(tmp_passwd, etc_passwd);
                                }
                                return 0;
                            });
                    }
                })
                .ifthen("bind_run_media", fs::exists(run_media_path), [&conf, &root, &run_media_path] () {
                      auto target_path =  conf.use_host_root ? (root / run_media_path) : (root / "run/media" / STEAM_USER);
                      std::error_code ec;
                      fs::create_directories(target_path, ec);
                      if (ec)
                          return 1;
                      return ko::os::bind(run_media_path, target_path, MS_REC);
                })
                // Mount different things required by gui apps
                .ifthen(conf.gui_mounts,
                      ko::ns::mount::mount_gui, root, conf.home_path.relative_path(), ko::util::str("run/user/", conf.uid))
                // Finally, pivot_root
                .then(ko::ns::mount::pivot_root, root, "mnt", conf.keep_root);

            if (err) {
                if (report) report->post(1);
                errno = err;
                return xerror(where);
            }
        }
        
        if (report) report->post(0);
        
        // Run Application
        if (!conf.dummy_mode)
            return exec_app(conf);
        else
            return pid1();
    }

    // Joining Existing
    // Must associate pid namespace in parent process first!
    int nsproc_join_parent(const config &conf) {
        auto [err, where] = ko::util::cvshort()
            .then("setns_p_user", ko::ns::setns, "user", CLONE_NEWUSER, conf.ns_path_fd)
            .then("setns_p_pid", ko::ns::setns, "pid", CLONE_NEWPID, conf.ns_path_fd);
        if (err)
            return xerror(where);
        return 0;
    }

    int nsproc_join_child(const config &conf) {
        auto [err, where] = ko::util::cvshort()
            //.then("setns_c_user", ko::ns::setns, "user", CLONE_NEWUSER, conf.ns_path_fd)
            .then("setns_c_mnt", ko::ns::setns, "mnt", CLONE_NEWNS, conf.ns_path_fd);
        if (err)
            return xerror(where);

        return exec_app(conf);
    }
}

// ========================================================
// Main
// ========================================================
void usage(const char *prog) {
    std::cout << "Usage:" << std::endl
              << "    " << prog << " -h" << std::endl
              << "    " << prog << " [-rMGk] [-p <path>] [-e <path>] [--] <argv...>" << std::endl
              << "    " << prog << " -c <path> [-MGk] [-p <path>] [-e <path>] [--] <argv...>" << std::endl
              << "    " << prog << " -j <path> [-e <path>] [--] <argv...>" << std::endl
              << std::endl
              << "General Options:" << std::endl
              << "  -h        Display this help text" << std::endl
              << std::endl
              << "Namespace Sharing Options:" << std::endl
              << "  -c <path> Create joinable namespace" << std::endl
              << "  -j <path> Join namespaces identified by path" << std::endl
              << "Note: Passing the single-character '-' will use '$root_path/.namespace'" << std::endl
              << std::endl
              << "Namespace Joining Options:" << std::endl
              << "  -p <path> The path to use for '-j-'" << std::endl
              << "  -D        Automatically spawn a instance of '" << prog << " -Dc'" << std::endl
              << "            into the background if the ns path doesn't exist." << std::endl
              << "Note: -D can be combined with most options from the NS Creation section below" << std::endl
              << "      but those options are ignored unless the ns must be created" << std::endl
              << std::endl
              << "Namespace Creation Options:" << std::endl
              << "  -r        Run in fakeroot mode (implies -W)" << std::endl
              << "  -H        Use host rootfs (only mount steamns home" << std::endl
              << "  -p <path> Use custom root path" << std::endl
              << "  -M        Don't set up mouts (implies -G)" << std::endl
              << "  -G        Don't set up GUI-related mounts" << std::endl
              << "  -W        Don't make system paths read-only (/usr, /etc)" << std::endl
              << "  -k        Keep the original root filesystem at /mnt" << std::endl
              << "  -w        Preserve working directory (may require -k)" << std::endl
              << "  -e <path> Exceute a file during namespace setup" << std::endl
              << "  -D        Don't run any program, but idle to keep the namespace active." << std::endl
              << "            This also takes care of reaping Zombies if it is PID 1." << std::endl;
}

struct config {
    fs::path root_path;
    const char *const *exec_argv = DEFAULT_CMD.data();
    bool fakeroot = false,
         mounts = true,
         gui_mounts = true,
         keep_root = false,
         keep_pwd = false,
         dummy_mode = false,
         pid_ns = true,
         ns_create = false,
         system_ro = true,
         use_host_root = false;
    std::optional<fs::path> ns_path,
                            ns_setup_exec;
};

// Parse commandline arguments
// returns -1 on success, exit code otherwise
int parse_cmdline(config &conf, int argc, const char *const *argv) {
    constexpr auto spec = "+hp:rHkwWMGe:c:j:D";
    
    std::optional<fs::path> create_path, join_path;

    while (true) {
        auto opt = getopt(argc, const_cast<char *const *>(argv), spec);

        if (opt == -1)
            break;
        else if (opt == '?' || opt == 'h') {
            usage(argv[0]);
            return opt == 'h' ? 0 : 1;
        }

        else if (opt == 'r') {
            conf.fakeroot = true;
            conf.system_ro = false;
        }
        else if (opt == 'p')
            conf.root_path = ::optarg;
        else if (opt == 'M')
            conf.mounts = false;
        else if (opt == 'G')
            conf.gui_mounts = false;
        else if (opt == 'W')
            conf.system_ro = false;
        else if (opt == 'k')
            conf.keep_root = true;
        else if (opt == 'w')
            conf.keep_pwd = true;
        else if (opt == 'e')
            conf.ns_setup_exec = ::optarg;
        else if (opt == 'c')
            create_path = ::optarg;
        else if (opt == 'j')
            join_path = ::optarg;
        else if (opt == 'D')
            conf.dummy_mode = true;
        else if (opt == 'H')
            conf.use_host_root = true;
    }

    // Check sanity
    bool good = true;
    if (join_path) {
        if (create_path) {
            std::cerr << "Error: -c and -j cannot be combined" << std::endl;
            good = false;
        }

        // NOTE: let -p slip by to facilitate '-p<path> -j-' use-case
        if (!conf.dummy_mode && (!conf.mounts || !conf.gui_mounts || conf.keep_root || conf.use_host_root)) {
            std::cerr << "Error: -j cannot be combined with any namespace setup options (-MGk) unless -D is given" << std::endl;
            good = false;
        }

        conf.ns_path = join_path;
    }
    if (create_path) {
        conf.ns_path = create_path;
        conf.ns_create = true;
    }

    if (conf.ns_path) {
        // This is somewhat arbitrary but should prevent accidentally entering a fakeroot ns using -j
        if (conf.fakeroot) {
            std::cerr << "Error: -r cannot be combined with -c or -j" << std::endl;
            good = false;
        }
        if (conf.use_host_root) {
            std::cerr << "Error: -H cannot be combined with -c or -j" << std::endl;
            good = false;
        }
        
        // - Special default in -j and -c
        if (*conf.ns_path == "-")
            conf.ns_path = conf.root_path / ".namespace";
    } else if (conf.dummy_mode) {
        std::cerr << "Error: -D must be combined with -c or -j" << std::endl;
        good = false;
    }

    if (!good) {
        usage(argv[0]);
        return 5;
    }

    // Rest is child cmnd
    if (argc > ::optind)
        conf.exec_argv = &argv[::optind];

    return -1;
}

fs::path transpose_prefix(const fs::path &p, const fs::path &prefix, const fs::path &replace) {
    static const auto up = fs::path{".."};
    auto rel = fs::relative(p, prefix);
    for (auto &c : rel) {
        if (c == up)
            return {};
    }
    return replace / rel;
}

fs::path convert_path(const config &conf, const fs::path &p) {
    static const auto mounts = std::array<std::pair<fs::path,fs::path>, 2>{
        std::pair{conf.root_path, "/"},
        std::pair{"/media", "/media"}
    };
    for (auto &pr : mounts) {
        auto res = transpose_prefix(p, pr.first, pr.second);
        if (!res.empty())
            return res;
    }
    return fs::path{"/mnt"} / p;
}


int main(int argc, char **argv) {
    auto home = ko::os::get_home();
    auto uid = getuid();
    auto gid = getgid();

    // Set defaults
    auto conf = config{
        .root_path = home / ROOT_DIR,
    };

    // Parse commandline
    auto perr = parse_cmdline(conf, argc, argv);
    if (perr != -1)
        return perr;

    // FIXME should lock something. Not sure what though. this can currently race
    if (conf.ns_path) {
        auto st = fs::symlink_status(*conf.ns_path);
        if (fs::exists(st)) {
            if (conf.ns_create) {
                std::cerr << "Error: File exists: " << *conf.ns_path << std::endl;
                return -EEXIST;
            } else {
                auto tgt = fs::status(*conf.ns_path);
                if (!fs::exists(tgt)) {
                    std::cerr << "Warning: Cleaning up stale ns link " << *conf.ns_path << " to " << fs::read_symlink(*conf.ns_path) << std::endl;
                    fs::remove(*conf.ns_path);
                }
            }
        } else if (!conf.ns_create && !conf.dummy_mode) {
            std::cerr << "Error: No such file: " << *conf.ns_path << std::endl;
            return -ENOENT;
        }
    }
    
    // Auto-create dummy instance
    auto parent_future = [&conf]() ->proc_future<int>* {
        if (!conf.ns_create && conf.dummy_mode && !fs::exists(*conf.ns_path)) {
            // Fork twice while communicating child pid
            auto f = proc_future<int>::create();
            if (!f)
                die_errno(31, "Could not allocate future for dummy process");
            auto vpid = ::vfork();
            if (vpid < 0)
                die_errno(32, "Could not spawn dummy process (-Dc)");
            else if (vpid == 0) {
                auto pid = ::fork();
                if (pid < 0)
                    _exit(1);
                else if (pid > 0)
                    _exit(0);
                // Daemon process here
                // Switch to creation mode
                conf.ns_create = true;
                return f;
            } else {
                // Parent process here
                // check if second fork failed
                int st = 0;
                waitpid(vpid, &st, 0);
                if (WEXITSTATUS(st) != 0)
                    die(33, "Could not spawn dummy process (-Dc); double fork failed");
                // Wait for ns creation
                auto pid = f->wait();
                f->destroy();
                if (pid < 0)
                    die(34, "Could not spawn dummy process (-Dc); reported failure");
                conf.ns_path = ko::util::str("/proc/", pid, "/ns");
            }
        }
        return nullptr;
    }();

    ko::fd::fd ns_path_fd = conf.ns_path ? ko::fd::opendir(*conf.ns_path) : ko::fd::fd(-1);

    // Create nsproc config
    auto nsconf = nsproc::config{
        .root_path = conf.root_path,
        .home_path = home,
        .pwd = conf.keep_pwd ? convert_path(conf, fs::current_path()) : fs::path{},
        .exec_argv = const_cast<char *const *>(conf.exec_argv),
        .uid = conf.fakeroot ? 0 : uid,
        .gid = conf.fakeroot ? 0 : gid,
        .mounts = conf.mounts,
        .gui_mounts = conf.gui_mounts,
        .system_ro = conf.system_ro,
        .keep_root = conf.keep_root,
        .dummy_mode = conf.dummy_mode,
        .pid_ns = conf.pid_ns,
        .use_host_root = conf.use_host_root,
        .setup_exec = conf.ns_setup_exec,
        .ns_path_fd = ns_path_fd,
    };

    constexpr auto stacksize = 1024*1024;

    // clone
    auto ns_future = conf.ns_create ? proc_future<int>::create_private() : nullptr;
    auto [proc, res] = conf.ns_path && !conf.ns_create ?
        [&nsconf]() -> std::pair<ko::proc::child_ref, int> {
            int e = nsproc::nsproc_join_parent(nsconf);
            if (e) return {-1, e};
            auto child = ko::proc::vclone(nsproc::nsproc_join_child, stacksize, 0, nsconf);
            return {std::move(child), 0};
        }() :
        ko::ns::clone::uvclone_single(nsconf.uid, nsconf.gid, nsproc::nsproc_create, stacksize, CLONE_NEWNS|CLONE_NEWPID, nsconf, ns_future);

    if (proc) {
        // Child should handle signals and then return
        static int _pid = proc.pid();
        signal(SIGINT, SIG_IGN); // assume sent to whole session
        signal(SIGTERM, [](int sig){
            kill(_pid, sig);
        });

        // Create ns_reference
        if (conf.ns_create) {
            if (ns_future) {
                // TODO consider the return value?
                ns_future->wait();
                ns_future->destroy();
            }
            // TODO move this out so it's independent of ns_create. But create_symlink can throw which would
            // lead to a locked-up parent.
            if (parent_future) {
                parent_future->post(_pid);
                parent_future->unmap();
            }
            fs::create_directory_symlink(ko::util::str("/proc/", proc.pid(), "/ns"), *conf.ns_path);
        }
        
        // Wait for child
        res = proc.wait();

        // Clean up ns path
        if (conf.ns_create)
            fs::remove(*conf.ns_path);

        return res;
    } else {
        if (parent_future)
            parent_future->post(-1);
        return proc.pid();
    }
}

