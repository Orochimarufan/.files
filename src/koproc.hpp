// ============================================================================
// ko::util koutil.hpp
// (c) 2019 Taeyeon Mori <taeyeon at oro.sodimm.me>
// ============================================================================
// Managing child processes

#pragma once

#include <sched.h>
#include <semaphore.h>
#include <sys/types.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

#include "kofd.hpp"
#include "kofd_pipe.hpp"

#include <atomic>
#include <array>
#include <functional>
#include <iostream>
#include <memory>
#include <optional>
#include <tuple>
#include <utility>


namespace ko::proc {
// ------------------------------------------------------------------
// Simple popen implementaion
using popen_result_t = std::pair<pid_t, std::unique_ptr<fd::pipe>>;

/**
 * Spawn a process and connect it's stdin and stdout to a pipe
 * @param exec_fn An exec-style function to call in the new process.
 * @param args The arguments to exec_fn
 * @return The PID and a pipe object
 * @warning As this uses vfork(), exec_fn must actually call some kind of exec
 *          before the parent process can resume.
 */
template <typename F, typename... Args>
inline popen_result_t popen_impl(F exec_fn, Args... exec_args) {
    // Open 2 pipes
    auto pipefd = std::array<std::array<int, 2>, 2>{};

    if (::pipe2(pipefd[0].data(), 0))
        return {-1, nullptr};
    if (::pipe2(pipefd[1].data(), 0)) {
        ::close(pipefd[0][0]);
        ::close(pipefd[0][1]);
        return {-1, nullptr};
    }

    // Fork
    auto pid = vfork();
    if (pid == 0) {
        // Close parent ends
        ::close(pipefd[0][1]);
        ::close(pipefd[1][0]);

        // Set up stdin and stdout
        if (::dup2(pipefd[0][0], 0) != 0 || ::dup2(pipefd[1][1], 1) != 1)
            _exit(-1);

        // Close superfluous child ends
        ::close(pipefd[0][0]);
        ::close(pipefd[1][1]);

        // exec
        _exit(exec_fn(exec_args...));
    }

    // Close child ends
    ::close(pipefd[0][0]);
    ::close(pipefd[1][1]);

    // Abort if fork failed
    if (pid < 0) {
        ::close(pipefd[0][1]);
        ::close(pipefd[1][0]);
        return {pid, nullptr};
    }

    // return stuff
    return {pid, std::make_unique<fd::pipe>(pipefd[1][0], pipefd[0][1])};
}

/**
 * Spawn a process and connect it's stdin and stdout to a pipe
 * @param argv The process argv
 * @return The PID and a pipe object
 * @note argv[0] is the process image path
 */
popen_result_t popen(const char **argv) {
    return popen_impl(::execv, const_cast<char*>(argv[0]), const_cast<char**>(argv));
}

/**
 * Spawn a process and connect it's stdin and stdout to a pipe
 * @param argv The process argv
 * @return The PID and a pipe object
 * @note argv[0] is the process image name or path
 */
popen_result_t popenp(const char **argv) {
    return popen_impl(::execvp, const_cast<char*>(argv[0]), const_cast<char**>(argv));
}


// ------------------------------------------------------------------
/// Process Synchronization
namespace sync {
namespace detail {
    class semaphore_pair {
        std::atomic_int refs;
        bool shared;
        sem_t sems[2];

        semaphore_pair(bool shared) :
            refs(0), shared(shared)
        {
            int bshared = shared ? 1 : 0;
            sem_init(&sems[0], bshared, 0);
            sem_init(&sems[1], bshared, 0);
        }

    public:
        ~semaphore_pair() {
            sem_destroy(&sems[0]);
            sem_destroy(&sems[1]);
        }

        static semaphore_pair *create(bool shared = false) {
            if (shared) {
                void *mem = mmap(nullptr, sizeof(semaphore_pair), PROT_READ|PROT_WRITE, MAP_ANONYMOUS|MAP_SHARED, -1, 0);
                if (mem == MAP_FAILED)
                    return nullptr;
                return new (mem) semaphore_pair(true);
            } else {
                return new semaphore_pair(false);
            }
        }

        semaphore_pair *retain() {
            refs++;
            return this;
        }

        void release() {
            auto v = refs.fetch_sub(1);
            if (v == 1) {
                if (shared) {
                    this->~semaphore_pair();
                    munmap(this, sizeof(semaphore_pair));
                } else {
                    delete this;
                }
            }
        }

        sem_t *sem(int n) {
            return &sems[n%2];
        }
    };
}

/**
 * Contains a set of semaphores for bidirectional synchronization
 */
class semapair {
    detail::semaphore_pair *sems;
    int offset;

    semapair(detail::semaphore_pair *sems, int offset) :
        sems(sems->retain()),
        offset(offset)
    {}

    friend std::array<semapair, 2> make_semapair(bool);

public:
    semapair(const semapair &o) :
        sems(o.sems->retain()),
        offset(o.offset)
    {}

    semapair(semapair &&o) :
        sems(o.sems),
        offset(o.offset)
    {
        o.sems = nullptr;
    }

    ~semapair() {
        if (sems)
            sems->release();
    }

    inline void wait() {
        sem_wait(sems->sem(offset));
    }

    inline void post() {
        sem_post(sems->sem(offset+1));
    }

    inline void yield() {
        post();
        wait();
    }
};

inline std::array<semapair, 2> make_semapair(bool shared) {
    auto stuff = detail::semaphore_pair::create(shared);
    return {{ {stuff, 0}, {stuff, 1} }};
}
} // namespace sync (ko::proc::sync)


// ------------------------------------------------------------------
// Clone wrappers
using void_callback_t = std::pair<void(*)(void *), void *>;

/**
 * Represents a cloned child process with potential cleanup
 */
class child_ref {
    pid_t _pid = -1;

    std::optional<void_callback_t> cleanup = {};

    bool _done = false;
    int _status = -1;
    
    inline void _check_clean() {
        if (cleanup)
            std::cerr << "Warning: ko::proc::child_ref with cleanup destroyed without waiting" << std::endl;
    }

public:
    child_ref(pid_t pid) :
        _pid(pid)
    {}

    child_ref(pid_t pid, void_callback_t cleanup_cb) :
        _pid(pid), cleanup(cleanup_cb)
    {}

    child_ref(child_ref &&o) :
        _pid(o._pid), cleanup(o.cleanup),
        _done(o._done), _status(o._status)
    {
        o._pid = -1;
        o.cleanup = {};
    }
    
    child_ref &operator =(child_ref &&o) {
        _check_clean();
        _pid = o._pid;
        cleanup = std::move(o.cleanup);
        _done = o._done;
        _status = o._status;
        o._pid = -1;
        o.cleanup = {};
        return *this;
    }
        

    ~child_ref() {
        _check_clean();
    }

    operator bool() {
        return _pid > 0;
    }

    int wait() {
        if (!_done) {
            waitpid(_pid, &_status, 0);
            if (cleanup) {
                auto [f, arg] = cleanup.value();
                f(arg);
                cleanup = {};
            }
            _done = true;
        }
        return WEXITSTATUS(_status);
    }
    
    std::pair<bool, int> poll() {
        if (!_done) {
            if(waitpid(_pid, &_status, WNOHANG) == 0)
                return {false, 0};
            if (cleanup) {
                auto [f, arg] = cleanup.value();
                f(arg);
                cleanup = {};
            }
            _done = true;
        }
        return {true, WEXITSTATUS(_status)};
    }

    pid_t pid() {
        return _pid;
    }

    int status() {
        return WEXITSTATUS(_status);
    }

    bool waited() {
        return _done;
    }
};

namespace detail {
    // Cleanup
    struct cleanup_data {
        uint8_t *stack = nullptr;
        size_t stack_size;

        void *args_copy = nullptr;
    };

    template <typename ArgP>
    void cleanup(void *d) {
        auto data = reinterpret_cast<cleanup_data*>(d);

        if (data->args_copy)
            delete reinterpret_cast<ArgP>(data->args_copy);

        if (data->stack)
            munmap(data->stack, data->stack_size);

        delete data;
    }

    template <typename ArgP>
    inline void_callback_t make_cleanup_cb(uint8_t *stack, size_t stack_size, ArgP data) {
        return { cleanup<ArgP>, new cleanup_data{stack, stack_size, data} };
    }

    // Entrypoints
    template <typename ArgP>
    int vclone_entry(void *arg) {
        // XXX Does this work with non-movable types?
        auto [f, args] = std::move(*reinterpret_cast<ArgP>(arg));
        return std::apply(f, args);
    }

    // Common work function
    template <typename D>
    inline child_ref do_clone(int(*entry)(void*), size_t stacksize, int flags, D *data) {
        // Allocate stack
        auto stack = reinterpret_cast<uint8_t*>(
            mmap(nullptr, stacksize, PROT_WRITE|PROT_READ, MAP_ANONYMOUS|MAP_PRIVATE, -1, 0));
        if (stack == MAP_FAILED)
            return {-ENOMEM};

        // Clone
        // SIGCHLD is required for child_ref and cleanup to work.
        auto pid = ::clone(entry, stack + stacksize, SIGCHLD | flags, data);

        // Discard everything if failed
        if (pid < 0) {
            if (data)
                delete data;
            if (stack)
                munmap(stack, stacksize);
            return {pid};
        }

        // Return child_ref with cleanup
        return {pid, make_cleanup_cb(stack, stacksize, data)};
    }
}

/**
 * Spawn a process sharing the same virtual memory
 * @param fn The function to call in the new process
 * @param stacksize The size of the new process stack
 * @param flags The clone(2) flags (SIGCHLD|CLONE_VM implied)
 * @param args The function arguments
 */
template <typename F, typename... Args>
child_ref vclone(F fn, size_t stacksize, long flags, Args... args) {
    auto data = new std::pair{fn, std::tuple{std::forward<Args>(args)...}};
    return detail::do_clone(detail::vclone_entry<decltype(data)>, stacksize, CLONE_VM | flags, data);
}

/**
 * Spawn a process sharing the same virtual memory with synchronization primitives
 * @param fn The function to call in the new process [int fn(ko::proc::sync::semapair, args...)]
 * @param stacksize The size of the new process stack
 * @param flags The clone(2) flags (SIGCHLD|CLONE_VM implied)
 * @param args The function arguments
 */
template <typename F, typename... Args>
std::pair<child_ref, sync::semapair> svclone(F fn, size_t stacksize, long flags, Args... args) {
    auto [sem_a, sem_b] = sync::make_semapair(false);
    auto data = new std::pair{fn, std::tuple{sem_b, std::forward<Args>(args)...}};
    return {detail::do_clone(detail::vclone_entry<decltype(data)>, stacksize, CLONE_VM | flags, data), sem_a};
}

/**
 * Spawn a child process and immediately execvp() a new image
 * @param argv The argument list for the new process.
 * @note argv[0] is used as the image name/path
 */
child_ref simple_spawn(const char *const *argv) {
    auto pid = ::fork();
    if (pid == 0)
        ::_exit(::execvp(argv[0], const_cast<char *const*>(argv)));
    return {pid};
}

} // namespace ko::proc (ko::proc)
