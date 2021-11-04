// ============================================================================
// kofd.hpp
// ko::fd
// (c) 2019 Taeyeon Mori <taeyeon at oro.sodimm.me>
// ============================================================================
// File descriptor functions

#pragma once

#include "kofs.hpp"

#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/sendfile.h>
#include <sys/ioctl.h>
#include <sys/mount.h> // linux/fs.h includes linux/mount.h which overrides some of the things from sys/mount.h
#include <linux/fs.h>
#include <unistd.h>

#include <cstring>
#include <string>
#include <utility>
#include <optional>


// ==================================================================
namespace ko::fd {
// ------------------------------------------------------------------
// Working with file descriptors

/**
 * Auto-close move-only filedescriptor wrapper
 */
class fd {
    int _fd;

public:
    fd() :
        _fd(-1)
    {}

    fd(int fd) :
        _fd(fd)
    {}

    fd(fd const &) = delete;

    fd(fd &&o) :
        _fd(o.move())
    {}

    fd &operator=(int fd) {
        if (_fd >= 0)
            ::close(_fd);
        _fd = fd;
        return *this;
    }

    fd &operator=(fd &&o) {
        if (_fd >= 0)
            ::close(_fd);
        _fd = o.move();
        return *this;
    }

    ~fd() {
        if (_fd >= 0)
            ::close(_fd);
    }

    /**
     * Boolean operator
     * @note This differs from a raw int fd
     */
    operator bool() const {
        return _fd >= 0;
    }

    /**
     * Negation operator
     * @note This differs from a raw int fd
     */
    bool operator !() const {
        return _fd < 0;
    }

    // Comparison
    bool operator ==(int i) const {
        return _fd == i;
    }

    bool operator !=(int i) const{
        return _fd != i;
    }
    
    bool operator <(int i) const {
        return _fd < i;
    }
    
    bool operator >(int i) const {
        return _fd > i;
    }
    
    bool operator <=(int i) const {
        return _fd <= i;
    }
    
    bool operator >=(int i) const {
        return _fd >= i;
    }

    /**
     * Get the raw int fd
     * @note This is not allowed on temporaries
     * @note Use move() instead to transfer ownership.
     * @see move()
     */
    operator int() & {
        return _fd;
    }

    /**
     * Disown this object
     * @note 
     */
    int move() {
        auto tmp = _fd;
        _fd = -1;
        return tmp;
    }
    
    /**
     * Close the file descriptor early
     */
    bool close() {
        if (_fd < 0) return false;
        if (::close(_fd) && errno != EBADF) return false;
        _fd = -1;
        return true;
    }
    
    /**
     * Copy the file descriptor
     */
    fd dup() {
        return ::dup(_fd);
    }
};


//-------------------------------------------------------------------
// Opening file descriptors
// @{
/**
 * Open a file descriptor
 * @param path The path
 * @param flags The open(2) flags
 * @param dirfd The directory fd \p path may be relative to
 * @param cloexec Add O_CLOEXEC to \p flags
 * @return A \c fd file descriptor
 */
fd open(const fs::cpath &path, long flags, int dirfd=AT_FDCWD, bool cloexec=true) {
    return ::openat(dirfd, path, flags | (cloexec ? O_CLOEXEC : 0));
}

/**
 * Open a file descriptor, creating the file if it doesn't exist
 * @param path The path
 * @param flags The open(2) flags
 * @param mode The file mode to create with
 * @param dirfd The directory fd \p path may be relative to
 * @param cloexec Add O_CLOEXEC to \p flags
 * @return A \c fd file descriptor
 */
fd open_creat(const fs::cpath &path, long flags, mode_t mode, int dirfd=AT_FDCWD, bool cloexec=true) {
    return ::openat(dirfd, path, O_CREAT | flags | (cloexec ? O_CLOEXEC : 0), mode);
}

/**
 * Open a directory file descriptor
 * @param path The directory path
 * @param dirfd The directory fd \p path may be relative to
 * @return A \c fd directory file descriptor
 */
fd opendir(const fs::cpath &path, int dirfd=AT_FDCWD) {
    return ::openat(dirfd, path, O_DIRECTORY|O_RDONLY|O_CLOEXEC);
}

/**
 * Open a directory file descriptor with custom flags
 * @param path The directory path
 * @param flags The flags to pass to open(2)
 * @param dirfd The directory fd \p path may be relative to
 * @return A directory \c fd
 */
fd opendir2(const fs::cpath &path, long flags, int dirfd=AT_FDCWD) {
    return ::openat(dirfd, path, flags|O_DIRECTORY);
}
// @}


//-------------------------------------------------------------------
// Checking properties
// @{
/**
 * Check if a path exists
 * @param path The path
 * @param dirfd The directory fd \p path may be relative to
 * @return true if path exists
 */
bool exists(const fs::cpath &path, int dirfd=AT_FDCWD) {
    return !::faccessat(dirfd, path, F_OK, 0);
}

/**
 * Check if a path is a directory
 * @param path The path
 * @param dirfd The directory fd \p path may be relative to
 * @return true if path is a directory
 */
bool is_dir(const fs::cpath &path, int dirfd=AT_FDCWD) {
    struct stat st;
    if (::fstatat(dirfd, path, &st, 0))
        return false;
    return S_ISDIR(st.st_mode);
}

/**
 * Read the target of a symbolic link
 * @param path The symlink path
 * @param dirfd The directory fd \p path may be relative to
 * @return A fs::path. It is empty on error
 */
fs::path readlink(const fs::cpath &path, int dirfd=AT_FDCWD) {
    constexpr auto static_bufsize = 4096;
    char buf[static_bufsize];
    auto sz = ::readlinkat(dirfd, path, buf, static_bufsize);
    if (sz < 0)
        return {};
    if (sz < static_bufsize)
        return {buf, buf + sz};
    
    struct stat st;
    if (::fstatat(dirfd, path, &st, AT_SYMLINK_NOFOLLOW))
        return {};
    
    auto extbuf = std::make_unique<char[]>(st.st_size);
    sz = ::readlinkat(dirfd, path, extbuf.get(), sz);
    if (sz < 0)
        return {};
    return {&extbuf[0], &extbuf[sz]};
}

/**
 * Get the target if a file is a symbolic link or return the path as-is if it is something else
 * @param path The path
 * @param dirfd The directory fd \p path may be relative to
 * @param notexist_ok Whether or not to return the path as-is if it doesn't exist (default=true)
 * @return A fs::path, possibly relative to dirfd. It may be empty on error
 */
fs::path readlink_or_path(const fs::path &path, int dirfd=AT_FDCWD, bool notexist_ok=true) {
    auto target = readlink(path, dirfd);
    if (target.empty()) {
        if (errno == EINVAL || (errno == ENOENT && notexist_ok))
            return path;
        else
            return {};
    }
    // Make (relative) returned value relative to dirfd
    if (target.is_relative())
        return path.parent_path() / target;
    return target;
}

/**
 * Check if a directory is empty
 */
bool is_dir_empty(const fs::cpath &path, int dirfd=AT_FDCWD) {
    auto fd = opendir(path, dirfd);
    if (!fd)
        return false;
    auto dir = fs::dir_ptr(fd);
    if (!dir)
        return false;
    errno = 0;
    while (true) {
        auto res = dir.readdir();
        if (res == nullptr)
            return errno == 0;
        if (strcmp(".", res->d_name) && strcmp("..", res->d_name))
            return false;
    }
}
// @}


//-------------------------------------------------------------------
// Creating files and directories
// @{
/**
 * Create a symbolic link
 * @param target The link target.
 * @param path The path of the new symlink
 * @param dirfd The directory fd \p path may be relative to
 * @return 0 on success
 * @note target is relative to the directory containing the link, NOT dirfd
 */
int symlink(const fs::cpath &target, const fs::cpath &path, int dirfd=AT_FDCWD) {
    return ::symlinkat(target, dirfd, path);
}

/**
 * Create a directory
 * @param path The new directory path
 * @param mode The permissions to assign
 * @param dirfd The directory fd \p path may be relative to
 * @return 0 on success
 */
int mkdir(const fs::cpath &path, mode_t mode=0755, int dirfd=AT_FDCWD) {
    return ::mkdirat(dirfd, path, mode);
}

/**
 * Create all parent directories
 * @param path The path of the innermost directory to create
 * @param mode The permissions to assign
 * @param dirfd The directory fd \p path may be relative to
 * @return The number of directories created, or -1 on error
 */
int makedirs(const fs::path &path, mode_t mode=0755, int dirfd=AT_FDCWD) {
    struct stat st;
    // Treat empty path as .
    // Check if exists
    if (!fstatat(dirfd, path.empty() ? "." : path.c_str(), &st, 0)) {
        // If directory, we're fine.
        if (S_ISDIR(st.st_mode))
            return 0;
        // Else, this is an error
        errno = ENOTDIR;
        return -1;
    }
    // Propagate any error other than ENOENT
    if (errno != ENOENT || path.empty())
        return -1;
    // Ensure parents
    auto parents = makedirs(path.parent_path(), mode, dirfd);
    // Actually create directory
    if (mkdir(path, mode, dirfd))
        return -1;
    return parents + 1;
}

/**
 * Create a file if it doesn't exist
 * @param path The path of the file
 * @param mode The permissions to assign if it has to be created
 * @param dirfd The directory fd \p path may be relative to
 * @return 0 on success
 */
int touch(const fs::cpath &path, mode_t mode=0755, int dirfd=AT_FDCWD) {
    auto fd = open_creat(path, O_WRONLY, mode, dirfd);
    return fd ? 0 : -1;
}

/**
 * Remove a file
 * @param path The path of the file to remove
 * @param dirfd The directory fd \p may be relative to
 * @return 0 on success
 */
int unlink(const fs::cpath &path, int dirfd=AT_FDCWD) {
    return ::unlinkat(dirfd, path, 0);
}

/**
 * Remove a directory
 * @param path The path of the directory to remove
 * @param dirfd The directory fd \p may be relative to
 * @return 0 on success
 */
int rmdir(const fs::cpath &path, int dirfd=AT_FDCWD) {
    return ::unlinkat(dirfd, path, AT_REMOVEDIR);
}

/**
 * Copy a symbolic link
 * @param from The source symbolic link path
 * @param to The target symbolic link path (must not exist)
 * @param from_dirfd The directory fd \p from may be relative to
 * @param dirfd The directory fd \p to may be relative to
 * @return 0 on success
 */
int copy_symlink(const fs::cpath &from, fs::cpath to,
                 int from_dirfd=AT_FDCWD, int dirfd=AT_FDCWD) {
    auto target = readlink(from, from_dirfd);
    return ::symlinkat(target.c_str(), dirfd, to);
}
// @}


//-------------------------------------------------------------------
// File descriptor I/O
// @{
// Read
/**
 * Read until \p size bytes have been read or an error has been encoutnered
 * @param fd A file descriptor
 * @param dest The destination buffer
 * @param size The desired number of bytes read
 * @return The actual number of bytes read
 * @note If returned value != \p size, errno will be set. errno == 0 indicates EOF
 */
size_t read(int fd, char *dest, size_t size) {
    size_t have = 0;
    
    while (have < size) {
        auto got = ::read(fd, dest + have, size - have);
        
        if (got == 0) {
            errno = 0;
            break;
        } else if (got < 0)
            break;
        
        have += got;
    }
    
    return have;
}

/**
 * Read until \p size bytes have been read or an error has been encoutnered
 * @param fd A file descriptor
 * @param size The desired number of bytes read
 * @return The resulting string
 * @note If returned string.size() != \p size, errno will be set. errno == 0 indicates EOF
 */
std::string read(int fd, size_t size) {
    auto buf = std::string(size, 0);
    buf.resize(read(fd, buf.data(), size));
    return buf;
}

/**
 * Read until \p size bytes have been read, an error has been encoutnered, or the timeout is hit
 * @param fd A file descriptor
 * @param dest The destination buffer
 * @param size The desired number of bytes read
 * @param timeout The timeout that must not be exceeded between chunk reads
 * @return The actual number of bytes read
 * @note If returned value != \p size, errno will be set. errno == 0 indicates EOF.
 *       Timeout is indicated by ETIMEDOUT.
 */
size_t read(int fd, char *dest, size_t size, timeval timeout) {
    size_t have = 0;
    
    auto fds = fd_set();
    FD_ZERO(&fds);
    FD_SET(fd, &fds);
    
    while (have < size) {
        auto rv = select(fd + 1, &fds, nullptr, nullptr, &timeout);
        
        if (rv == 0) {
            errno = ETIMEDOUT;
            break;
        } else if (rv < 0) {
            break;
        }
        
        auto got = ::read(fd, dest + have, size - have);
        if (got == 0) {
            errno = 0;
            break;
        } else if (got < 0)
            break;

        have += got;
    }
    
    return have;
}

/**
 * Read until \p size bytes have been read, an error has been encoutnered, or the timeout is hit
 * @param fd A file descriptor
 * @param size The desired number of bytes read
 * @param timeout The timeout that must not be exceeded between chunk reads
 * @return The resulting string
 * @note If returned value != \p size, errno will be set. errno == 0 indicates EOF
 *       Timeout is indicated by ETIMEDOUT.
 */
std::string read(int fd, size_t size, timeval timeout) {
    auto buf = std::string(size, 0);
    buf.resize(read(fd, buf.data(), size, timeout));
    return buf;
}

/**
 * Read a POD type from a file descriptor
 * @tparam T The type
 * @param fd The file descriptor
 * @return The object on success, std::nullopt on failure
 * @note If std::nullopt is returned, errno will be set.
 */
template <typename T>
std::optional<T> read_bin(int fd) {
    char buf[sizeof(T)];
    if (read(fd, buf, sizeof(T)) == sizeof(T))
        return *reinterpret_cast<T*>(buf);
    else
        return std::nullopt;
}

// Write
/**
 * Write all bytes to a file descriptor unless an error occurs (blocking)
 * @param fd The file descriptor
 * @param buf The source buffer
 * @param size The number of bytes to write
 * @return The number of bytes written
 * @note If returned value != \p size, errno will be set.
 */
size_t write(int fd, const char *buf, size_t size) {
    size_t have = 0;
    
    while (have < size) {
        auto got = ::write(fd, buf + have, size - have);
        
        if (got == 0) {
            errno = 0;
            break;
        } else if (got < 0)
            break;
        
        have += got;
    }
    
    return have;
}

/**
 * Write all bytes to a file descriptor unless an error occurs (blocking)
 * @param fd The file descriptor
 * @param s A string to write
 * @return The number of bytes written
 * @note If returned value != \p s.size(), errno will be set.
 */
size_t write(int fd, const std::string &s) {
    return write(fd, s.data(), s.size());
}

/**
 * Write a POD object to a file descriptor
 * @tparam T The POD type
 * @param fd The file descriptor
 * @param v The object
 * @return The number of bytes written
 * @note If returned value != sizeof(T), errno will be set.
 */
template <typename T>
size_t write_bin(int fd, const T &v) {
    return write(fd, reinterpret_cast<const char*>(&v), sizeof(v));
}

// Shortcuts
/**
 * Read a file from disk
 * @param path The file path
 * @param dirfd The directory fd \p path may be relative to
 * @param max The maximum number of bytes to read
 * @return A pair of (data read, errno)
 * @note If data.size() == max, more data may be available.
 */
std::pair<std::string, int> cat(const fs::cpath &path, int dirfd=AT_FDCWD, size_t max=1024) {
    auto fd = open(path, O_RDONLY, dirfd);
    if (!fd)
        return {};
    auto r = read(fd, max);
    if (r.size() < max)
        return {r, errno};
    return {r, 0};
}

/**
 * Write a file to disk
 * @param s The data to write
 * @param path The path to write to
 * @param mode The mode to create the file with, if neccessary
 * @param dirfd The directory fd \p path may be relative to
 */
bool dump(const std::string &s, const fs::cpath &path, mode_t mode, int dirfd=AT_FDCWD) {
    auto fd = open_creat(path, O_WRONLY, mode, dirfd);
    if (!fd)
        return -1;
    return write(fd, s) == s.size();
}
// @}

//-------------------------------------------------------------------
// Copying Files
// @{
/**
 * Naively copy data between file descriptors
 * @param fs The source file descriptor
 * @param fd The destination file descriptor
 * @param len The number of bytes to copy
 */
bool fcopy_raw(int fs, int fd, size_t len) {
    constexpr size_t bufsz = 8192;
    char buf[bufsz];
    do {
        auto target = std::min(len, bufsz);
        auto nread = read(fs, buf, target);
        if (nread < target && errno != 0)
            return false;
        auto written = write(fd, buf, nread);
        if (written < nread)
            return false;
        if (nread < target)
            return true;
        len -= nread;
    } while (len > 0);
    return true;
}

/**
 * Copy data between file descriptors
 * @param fs The source file descriptor
 * @param fd The destination file descriptor
 * @param len The number of bytes to copy
 * @return false on failure with errno set
 * @note This attempts to use copy_file_range(2) and sendfile(2)
 *       before falling back to fcopy_raw
 */
bool fcopy(int fs, int fd, size_t len) {
    while (len > 0) {
        auto r = ::copy_file_range(fs, NULL, fd, NULL, len, 0);
        if (r < 0) {
            if (errno == ENOSYS || errno == EXDEV || errno == EINVAL)
                break;
            return fcopy_raw(fs, fd, len);
        }
        len -= r;
    }
    
    while (len > 0) {
        auto r = ::sendfile(fd, fs, NULL, len);
        if (r < 0)
            return fcopy_raw(fs, fd, len);
        len -= r;
    }
    
    return true;
}

/**
 * Copy a file
 * @param src The path to copy from
 * @param dst The path to copy to
 * @param src_dir The directory fd \p src may be relative to
 * @param dst_dir The directory fd \p dst may be relative to
 * @return false on failure with errno set
 * @note This variant will only try to preserve the file mode, no other attributes
 * @note Note that this function takes two separate directory fds
 * @note This will use reflink/FICLONE if supported.
 */
bool copy0(const fs::cpath &src, const fs::cpath &dst, int src_dir=AT_FDCWD, int dst_dir=AT_FDCWD) {
    struct stat st;
    if (::fstatat(src_dir, src, &st, 0))
        return false;

    auto fs = open(src, O_RDONLY, src_dir);
    if (!fs)
        return false;
    auto fd = open_creat(dst, O_WRONLY, st.st_mode, dst_dir);
    if (!fd)
        return false;

    // Try reflink
#ifdef FICLONE
    int ret = ::ioctl(fd, FICLONE, (int)fs);
    if (ret != -1)
        return ret == st.st_size;
#endif
    
    return fcopy(fs, fd, st.st_size);
}

// @}
} // namespace ko::fd
