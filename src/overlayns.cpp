// overlayns
// (c) 2021 Taeyeon Mori

#include <string>
#include <string_view>
#include <vector>
#include <unordered_map>
#include <list>
#include <variant>
#include <span>
#include <algorithm>
#include <numeric>
#include <spawn.h>

#include "kons_clone.hpp"

using namespace ko;
using namespace std::literals::string_literals;
using namespace std::literals::string_view_literals;

static constexpr auto vers = "0.5"sv;

void usage(char const * prog) {
    printf("Synopsis: %s [-h] [-o ovl-spec]... [-m mnt-spec]... <command...>\n"
           "\n"
           "Run a command in it's own mount namespace\n"
           "\n"
           "Spec options:\n"
           "    -m mnt-spec     Add a mount to the namespace\n"
           "    -o ovl-spec     Add an overlay to the namespace\n"
           "\n"
           "Mount spec:\n"
           "    A mount specification takes the following format:\n"
           "      -m <fstype>,<device>,<mountpoint>[,<option>...]\n"
           "    see mount(8) for more information on options.\n"
           "    Some options may not match exactly however.\n"
           "    Shortcuts are in place for bind mounts:\n"
           "      `-m bind,/a,/b` is equivalent to `-m ,/a,/b,bind`\n"
           "      `-m rbind,/a,/b` is equivalent to `-m ,/a,/b,bind,rec`\n"
           "\n"
           "Overlay spec:\n"
           "    An overlay specification takes the following form:\n"
           "      -o <mountpoint>,<option>...\n"
           "    Avaliable options are (in addition to standard mount options):\n"
           "      lowerdir=<path>   Mandatory, see mount(8)\n"
           "      upperdir=<path>   Mandatory, see mount(8)\n"
           "      workdir=<path>    Mandatory, see mount(8)\n"
           "      shadow            Replaces lowerdir=; Use mountpoint as lowerdir\n"
           "                        and shadow it's content\n"
           "      tmp               Replaces upperdir= and workdir=;\n"
           "                        Use a (new) temporary directory for both\n"
           "      copyfrom=<path>   Copy contents of <path> to upperdir before mounting\n"
           "\n"
           "overlayns %s (c) 2021 Taeyeon Mori\n"
           "\n",
           prog, vers.data());
}


auto str_split(std::string_view s, char c) {
    size_t start = 0, next = 0;
    std::vector<std::string_view> parts;
    while ((next = s.find(c, start)) != s.npos) {
        while (next > 0 && s[next-1] == '\\' && (next < 2 || s[next-2] != '\\')) {
            if ((next = s.find(c, next+1)) == s.npos)
                break;
        }
        parts.push_back(s.substr(start, next - start));
        start = next + 1;
    }
    parts.push_back(s.substr(start));
    return parts;
}

auto str_join(const std::span<std::string_view> &ss, char c) -> std::string {
    if (ss.empty())
        return {};
    auto sizes = std::vector<size_t>{};
    sizes.reserve(ss.size());
    std::ranges::transform(ss, std::back_inserter(sizes), [](const auto& s) {return s.size();});
    auto size = ss.size() - 1 + std::reduce(sizes.begin(), sizes.end());
    auto result = std::string();
    result.reserve(size);
    result = ss[0];
    std::for_each(ss.begin()+1, ss.end(), [&result, c](const auto &s) {
        result.push_back(c);
        result.append(s);
    });
    return result;
}


struct mount_spec {
    enum class mkdir_mode {
        never,
        maybe_this,
        maybe_all,
        require_this,
        require_all,
    };

    std::string_view type;
    std::string_view device;
    std::string_view mountpoint;
    uint64_t flags = 0;
    std::vector<std::string_view> args;
    mkdir_mode mkdir = mkdir_mode::never;

    struct parse_error {std::string_view msg;};

    auto apply_options(std::span<std::string_view> opts) -> std::list<parse_error> {
        static const std::unordered_map<std::string_view, uint64_t> flagnames = {
            {"remount", MS_REMOUNT},
            {"move", MS_MOVE},
            {"bind", MS_BIND},
            {"rec", MS_REC},
            // propagation
            {"shared", MS_SHARED},
            {"private", MS_PRIVATE},
            {"unbindable", MS_UNBINDABLE},
            {"slave", MS_SLAVE},
            // read
            {"rw", 0},
            {"ro", MS_RDONLY},
            // atime
            {"noatime", MS_NOATIME},
            {"nodiratime", MS_NODIRATIME},
            {"relatime", MS_RELATIME},
            {"strictatime", MS_STRICTATIME},
            // filetypes
            {"nodev", MS_NODEV},
            {"noexec", MS_NOEXEC},
            {"nosuid", MS_NOSUID},
            // misc
            {"dirsync", MS_DIRSYNC},
            {"lazytime", MS_LAZYTIME},
            {"silent", MS_SILENT},
            {"synchronous", MS_SYNCHRONOUS},
            {"mandlock", MS_MANDLOCK},
        };

        std::list<parse_error> errors;
        for (const std::string_view &opt : opts) {
            if (opt.starts_with("mkdir=")) {
                auto arg = opt.substr(6);
                if (arg == "never") {
                    mkdir = mkdir_mode::never;
                } else if (arg == "maybe") {
                    mkdir = mkdir_mode::maybe_all;
                } else if (arg == "require") {
                    mkdir = mkdir_mode::require_all;
                } else {
                    errors.push_back({"Unknown mkdir= argument"});
                }
            } else if (auto f = flagnames.find(opt); f != flagnames.end()) {
                flags |= f->second;
            } else {
                args.push_back(opt);
            }
        }

        return errors;
    }

    static auto parse(std::string_view s) -> std::pair<mount_spec, std::list<parse_error>> {
        auto parts = str_split(s, ',');

        if (s.size() < 3) {
            std::cerr << "Incomplete mount spec: " << s << std::endl;
            return {{}, {{"Incomplete mount spec (need at least type,device,mountpoint"}}};
        }

        mount_spec spec = {
            .type = parts[0],
            .device = parts[1],
            .mountpoint = parts[2],
        };

        if (spec.type == "bind") {
            spec.flags |= MS_BIND;
            spec.type = "";
        } else if (spec.type == "rbind") {
            spec.flags |= MS_BIND | MS_REC;
            spec.type = "";
        }

        auto errors = spec.apply_options(std::span(parts).subspan(3));

        return {spec, errors};
    }

    int execute() {
        if (!fs::exists(mountpoint)) {
            if (mkdir == mkdir_mode::maybe_all || mkdir == mkdir_mode::require_all) {
                fs::create_directories(mountpoint);
            } else if (mkdir == mkdir_mode::maybe_this || mkdir == mkdir_mode::require_this) {
                fs::create_directory(mountpoint);
            } else {
                std::cerr << "Mountpoint doesn't exist: " << mountpoint;
                return 41;
            }
        } else if (mkdir == mkdir_mode::require_this || mkdir == mkdir_mode::require_all) {
            std::cerr << "Mountpoint exists but was required to be created: " << mountpoint;
            return 41;
        }

        std::string fstype{type},
                    dev{device},
                    dest{mountpoint},
                    margs = str_join(args, ',');
        
        //std::cerr << "Mount -t " << fstype << " " << dev << " " << dest << " -o " << margs << " -f " << flags << std::endl;

        auto res = os::mount(dev, dest, fstype.c_str(), flags, (void*)(margs.empty() ? nullptr : margs.c_str()));
        if (res) {
            std::cerr << "Failed mounting " << dev << " on " << dest << std::endl;
            perror("mount");
            return res;
        }
        return 0;
    }
};

struct copy_spec {
    std::string_view source;
    std::string_view dest;

    int execute() {
        std::error_code ec;
        fs::copy(source, dest, fs::copy_options::recursive, ec);
        if (ec.value())
            std::cerr << "Could not copy " << source << " to " << dest << ": " << ec.message() << std::endl;
        return ec.value();
    }
};

struct config {
    using step = std::variant<mount_spec, copy_spec>;
    std::list<step> recipe;
    std::list<fs::path> cleanup;
    char const * const * cmdline;
};


// Null coalescing helper
template <typename T>
T *nc(T *a, T *dflt) {
    return a ? a : dflt;
}

std::list<std::string> strings_g;

auto parse_overlay_spec(std::string_view s, config &cfg) -> std::list<mount_spec::parse_error> {
    auto parts = str_split(s, ',');

    if (parts.size() < 1)
        return {{"Incomplete overlay spec"}};

    mount_spec mspec = {"overlay", "overlay", parts[0]};

    struct {
        std::string_view lowerdir;
        std::string_view upperdir;
        std::string_view workdir;
        bool tmp = false, shadow = false;
        std::string_view copy_from;
    } x;

    auto options = std::vector<std::string_view>{};
    options.reserve(parts.size());

    std::copy_if(parts.begin()+1, parts.end(), std::back_inserter(options), [&x](const auto &opt) {
        if (opt.starts_with("lowerdir=")) {
            x.lowerdir = opt;
        } else if (opt.starts_with("upperdir=")) {
            x.upperdir = opt;
        } else if (opt.starts_with("workdir=")) {
            x.workdir = opt;
        } else if (opt.starts_with("copyfrom=")) {
            x.copy_from = opt.substr(9);
        } else if (opt == "tmp") {
            x.tmp = true;
        } else if (opt == "shadow") {
            x.shadow = true;
        } else {
            return true;
        }
        return false;
    });

    static constexpr auto lowerdir_opt = "lowerdir="sv;
    if (x.shadow) {
        // lowerdir == mountpoint
        auto& s = strings_g.emplace_back();
        s.reserve(x.lowerdir.empty() ? lowerdir_opt.size() + mspec.mountpoint.size() : x.lowerdir.size() + mspec.mountpoint.size());
        s = lowerdir_opt;
        s += mspec.mountpoint;
        if (!x.lowerdir.empty()) {
            s += ":";
            s += x.lowerdir.substr(lowerdir_opt.size());
        }
        x.lowerdir = s;
    }

    static constexpr auto upperdir_opt = "upperdir="sv;
    static constexpr auto upperdir_name = "/upper"sv;
    static constexpr auto workdir_opt = "workdir="sv;
    static constexpr auto workdir_name = "/work"sv;
    if (x.tmp) {
        auto tmpdir = std::string{nc((const char*)getenv("TMPDIR"), "/tmp")};
        tmpdir.append("/overlayns-XXXXXX"sv);
        if (!mkdtemp(tmpdir.data())) {
            return {{"Could not create temporary directory for 'tmp' overlay option"sv}};
        }
        auto& upperdir = strings_g.emplace_back();
        upperdir.reserve(upperdir_opt.size() + tmpdir.size() + upperdir_name.size());
        upperdir = upperdir_opt;
        upperdir += tmpdir;
        upperdir += upperdir_name;
        x.upperdir = upperdir;
        fs::create_directory(x.upperdir.substr(upperdir_opt.size()));
        auto& workdir = strings_g.emplace_back();
        workdir.reserve(workdir_opt.size() + tmpdir.size() + workdir_name.size());
        workdir = workdir_opt;
        workdir += tmpdir;
        workdir += workdir_name;
        x.workdir = workdir;
        fs::create_directory(x.workdir.substr(workdir_opt.size()));
        cfg.cleanup.emplace_back(tmpdir);
    }

    std::list<mount_spec::parse_error> errors;

    if (x.lowerdir.empty()) {
        errors.push_back({"Missing lowerdir option"sv});
    } else {
        mspec.args.push_back(x.lowerdir);
    }

    if (x.upperdir.empty() != x.workdir.empty()) {
        errors.push_back({"Must specify upperdir and workdir both or neither"sv});
    } else if (!x.upperdir.empty()) {
        mspec.args.push_back(x.upperdir);
        mspec.args.push_back(x.workdir);
    }

    if (!errors.empty()) {
        return errors;
    }

    if (!x.copy_from.empty()) {
        cfg.recipe.emplace_back(copy_spec{x.copy_from, x.upperdir.substr(upperdir_opt.size())});
    }

    cfg.recipe.emplace_back(mspec);

    return errors;
}


int main(int argc, char*const* argv) {
    config cfg;

    // Commandline parsing
    constexpr auto argspec = "+ho:m:";

    for (auto opt = ::getopt(argc, argv, argspec); opt != -1; opt = ::getopt(argc, argv, argspec)) {
        if (opt == 'h' || opt == '?') {
            usage(argv[0]);
            return opt == '?' ? 1 : 0;
        } else if (opt == 'o') {
            auto err = parse_overlay_spec(::optarg, cfg);
            if (!err.empty()) {
                std::cerr << "Error parsing overlay spec: " << ::optarg << std::endl;
                for (const auto &e : err) {
                    std::cerr << "  " << e.msg << std::endl;
                }
                return 33;
            }
        } else if (opt == 'm') {
            auto [spec, err] = mount_spec::parse(::optarg);
            if (!err.empty()) {
                std::cerr << "Error parsing mount spec: " << ::optarg << std::endl;
                for (const auto &e : err) {
                    std::cerr << "  " << e.msg << std::endl;
                }
                return 33;
            } else {
                cfg.recipe.push_back({spec});
            }
        }
    }
    cfg.cmdline = &argv[::optind];

    if (!cfg.cmdline[0]) {
        std::cerr << "Missing child commandline" << std::endl;
        return 22;
    }

    // Unshare
    uid_t uid = getuid();
    gid_t gid = getgid();

    auto [child, ret] = ns::clone::uvclone_single(uid, gid, [&cfg](){
        // Execute recipe
        for (auto &step : cfg.recipe) {
            int res = 0;
            std::visit([&res](auto &spec) {
                res = spec.execute();
            }, step);
            if (res)
                return res;
        }

        return ::execvp(cfg.cmdline[0], const_cast<char*const*>(cfg.cmdline));
    }, 102400, CLONE_NEWNS);

    if (ret)
        return ret;

    // free memory
    //cfg.recipe.clear();
    //strings_g.clear();
    
    // execute child
    ret = child.wait();

    std::ranges::for_each(cfg.cleanup, [](const auto& p) {fs::remove_all(p);});

    return ret;
}
