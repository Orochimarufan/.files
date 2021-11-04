// ============================================================================
// kofs.hpp
// ko::fs
// (c) 2019 Taeyeon Mori <taeyeon at oro.sodimm.me>
// ============================================================================
// Misc. Filesystem functions

#pragma once

#include <dirent.h>
#include <unistd.h>

#include <string>
#include <filesystem>

namespace ko::fs {
using namespace std::filesystem;

/**
 * Helper struct for functions that require a c-string path
 */
struct cpath {
    const char *path;
    
    inline cpath(const char *path) : path(path) {}
    inline cpath(const fs::path &path) : path(path.c_str()) {}
    inline cpath(const std::string &path) : path(path.c_str()) {}
    
    inline operator const char *() const {
        return path;
    }
};

class dir_ptr {
    DIR *ptr;
    
public:
    dir_ptr(int fd) {
        ptr = ::fdopendir(fd);
    }
    
    dir_ptr(const cpath &path) {
        ptr = ::opendir(path);
    }
    
    bool operator !() {
        return ptr == nullptr;
    }
    
    ~dir_ptr() {
        ::closedir(ptr);
    }

    dirent const *readdir() {
        return ::readdir(ptr);
    }

    // Iterator
    class iterator {
        dir_ptr &dir;
        dirent const *here = nullptr;
        bool done = false;
        int error = 0;

        friend class dir_ptr;

        iterator(dir_ptr &dir, bool done) : dir(dir), done(done) {
            ++(*this);
        }

    public:
        iterator &operator ++() {
            if (!done) {
                auto errno_bak = errno;
                here = dir.readdir();
                if (here == nullptr) {
                    done = true;
                    if (errno != errno_bak)
                        error = errno;
                }
            }
            return *this;
        }

        dirent const &operator *() {
            return *here;
        }

        operator bool() {
            return !done;
        }

        bool operator ==(iterator const &other) const {
            return dir.ptr == other.dir.ptr && (here == other.here || done == other.done);
        }

        int get_errno() {
            return error;
        }
    };

    iterator begin() {
        return iterator(*this, false);
    }

    iterator end() {
        return iterator(*this, true);
    }
};
} // namespace ko::fs
