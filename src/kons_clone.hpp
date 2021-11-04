// ============================================================================
// kons_clone.hpp
// ko::ns::clone namespace
// (c) 2019 Taeyeon Mori <taeyeon at oro.sodimm.me>
// ============================================================================
// Small Linux namespace utility header
// Clone-related functions

#pragma once

#include "kons.hpp"
#include "koproc.hpp"

/**
 * clone namespace
 * Useful wrappers around the clone(2) syscall
 */
namespace ko::ns::clone {
namespace detail {
    template <typename ArgP>
    int uvclone_entry(void *arg) {
        auto [f, args, sync] = *reinterpret_cast<ArgP>(arg);
        sync.yield();
        return std::apply(f, args);
    }
}

/**
 * Spawn a process in a new user namespace
 * @param uidmap The uid map for the user namespace
 * @param gidmap The gid map for the user namespace
 * @param fn The function to call in the child process
 * @param stacksize The size of the process stack
 * @param flags The clone(2) flags (SIGCHLD|CLONE_VM|CLONE_NEWUSER implied)
 * @param args The function arguments
 */
template <typename U, typename G, typename F, typename... Args>
std::pair<proc::child_ref, int> uvclone(U uidmap, G gidmap, F fn, size_t stacksize, long flags, Args... args) {
    auto [sync, sync_c] = proc::sync::make_semapair(false);
    auto data = new std::tuple{fn, std::tuple{std::forward<Args>(args)...}, sync_c};

    auto proc = proc::detail::do_clone(detail::uvclone_entry<decltype(data)>, stacksize, CLONE_NEWUSER | CLONE_VM | flags, data);
    auto res = EINVAL;

    if (proc) {
        // Wait for child
        sync.wait();

        // Set maps
        auto pid = proc.pid();
        if (idmap::set(idmap::path(pid, "uid"), uidmap)) {
            if (idmap::disable_setgroups(pid)) {
                if (idmap::set(idmap::path(pid, "gid"), gidmap)) {
                    res = 0;
                }
            }
        }

        if (res)
            res = errno;

        sync.post();
    }

    return {std::move(proc), res};
}

/**
 * Spawn a process in a new single-user user namespace
 * @param uid The uid inside the user namespace
 * @param gid The gid inside the user namespace
 * @param fn The function to call in the child process
 * @param stacksize The size of the process stack
 * @param flags The clone(2) flags (SIGCHLD|CLONE_VM|CLONE_NEWUSER implied)
 * @param args The function arguments
 */
template <typename F, typename... Args>
inline std::pair<proc::child_ref, int> uvclone_single(uid_t uid, gid_t gid, F fn, size_t stacksize, long flags, Args... args) {
    return uvclone(idmap::single(uid, getuid()), idmap::single(gid, getgid()), fn, stacksize, flags, args...);
}
} // namespace ko::ns::clone
