// ============================================================================
// ko::util koutil.hpp
// (c) 2019 Taeyeon Mori <taeyeon at oro.sodimm.me>
// ============================================================================
// Miscellaneous utilities

#pragma once

#include <cstring>
#include <sstream>
#include <string>
#include <utility>
#include <tuple>


namespace ko::util {
// ------------------------------------------------------------------
// Misc.
/// Build a string from fragments using ostringstream
template <typename... Args>
inline std::string str(Args... args) {
    auto sstream = std::ostringstream();
    (sstream <<...<< args);
    return sstream.str();
}

// ------------------------------------------------------------------
// Cvresult
/// A more verbose result type with a very terse error location indicator
using cvresult = std::pair<int, const char *>;

/// Allows short-circuiting c-style return values
struct cvshort {
    int _state = 0;
    const char *_where = nullptr;

    template <typename F, typename... Args>
    inline cvshort &then(F fn, Args... args) {
        if (_state == 0)
            std::tie(_state, _where) = fn(args...);
        return *this;
    }

    template <typename F, typename... Args>
    inline cvshort &then(const char *name, F fn, Args... args) {
        if (_state == 0) {
            _state = fn(args...);
            if (_state != 0)
                _where = name;
        }

        return *this;
    }

    template <typename F, typename... Args>
    inline cvshort &ifthen(bool cond, F fn, Args... args) {
        if (_state == 0 && cond)
            std::tie(_state, _where) = fn(args...);
        return *this;
    }

    template <typename F, typename... Args>
    inline cvshort &ifthen(const char *name, bool cond, F fn, Args... args) {
        if (_state == 0 && cond) {
            _state = fn(args...);
            if (_state != 0)
                _where = name;
        }

        return *this;
    }

    operator bool() const {
        return _state == 0;
    }

    int state() const {
        return _state;
    }

    const char *where() const {
        return _where;
    }

    operator cvresult() {
        return {_state, _where};
    }
};

} // namespace ko::util
