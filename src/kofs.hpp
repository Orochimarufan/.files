// ============================================================================
// kofs.hpp
// ko::fs
// (c) 2019 Taeyeon Mori <taeyeon at oro.sodimm.me>
// ============================================================================
// Misc. Filesystem functions

#pragma once

#include <dirent.h>
#include <unistd.h>
#include <stdlib.h>

#include <string>
#include <filesystem>

namespace ko::fs {
using namespace std::filesystem;

/**
 * Helper struct for functions that require a c-string path
 * @note Does not copy or own contents. original string/path object must be kept alive.
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

/**
 * Like Python tempfile.mkdtemp().
 * User-callable function to create and return a unique temporary
 *  directory.  The return value is the pathname of the directory.
 * @param prefix If given, the file name will begin with that prefix, otherwise a default prefix is used.
 * @param dir If given, the file will be created in that directory, otherwise a default directory is used.
 * The directory is readable, writable, and searchable only by the creating user.
 * Caller is responsible for deleting the directory when done with it.
 */
fs::path create_temporary_directory(std::string prefix={}, fs::path dir={}) {
    if (prefix.empty()) prefix = program_invocation_name;
    if (dir.empty()) dir = fs::temp_directory_path();
    auto ec = std::error_code{};
    if (!dir.is_absolute()) dir = fs::absolute(dir, ec);
    if (ec)
        return {};
    auto dirname = dir.string();
    auto size = dirname.length()+1+prefix.length()+1+6+1;
    char buf[size];
    if (snprintf(buf, size, "%s/%s-XXXXXX", dirname.c_str(), prefix.c_str())<0)
        return {};
    if (::mkdtemp(buf) == nullptr)
        return {};
    return {buf};
}

} // namespace ko::fs
