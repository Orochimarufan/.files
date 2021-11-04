// ============================================================================
// kofd_pipe.hpp
// ko::fd::pipe
// (c) 2019 Taeyeon Mori <taeyeon at oro.sodimm.me>
// ============================================================================
// bi-directional pipe implementation

#pragma once

#include "kofd.hpp"

#include <optional>


namespace ko::fd {
// ------------------------------------------------------------------
/**
 * Represents a bi-directional pair of file descriptors
 */
class pipe {
    int rfd, wfd;
    
public:
    pipe(fd &&fd) :
        rfd(fd.move()), wfd(rfd)
    {}

    pipe(fd &&rfd, fd &&wfd) :
        rfd(rfd.move()), wfd(wfd.move())
    {}

    explicit pipe(int rfd, int wfd) :
        rfd(rfd), wfd(wfd)
    {}
    
    ~pipe() {
        ::close(this->rfd);
        if (this->wfd != this->rfd)
            ::close(this->wfd);
    }
    
    // IO Functions, see namespace fd
    inline size_t read(char *dest, size_t size) {
        return ::ko::fd::read(this->rfd, dest, size);
    }
    
    inline std::string read(size_t size) {
        return ::ko::fd::read(this->rfd, size);
    }
    
    inline size_t read(char *dest, size_t size, timeval timeout) {
        return ::ko::fd::read(this->rfd, dest, size, timeout);
    }

    inline std::string read(size_t size, timeval timeout) {
        return ::ko::fd::read(this->rfd, size, timeout);
    }
    
    inline size_t write(const char *buf, size_t size) {
        return ::ko::fd::write(this->wfd, buf, size);
    }

    inline size_t write(const std::string &s) {
        return ::ko::fd::write(this->wfd, s);
    }

    template <typename T>
    inline size_t write_bin(const T &v) {
        return ::ko::fd::write_bin<T>(this->wfd, v);
    }
    
    template <typename T>
    inline std::optional<T> read_bin() {
        return ::ko::fd::read_bin<T>(this->rfd);
    }
};

} // namespace ko::fd
