Random Sources
==============
Playground for random utilities, mostly unprivileged single-user linux namespaces

Binaries
--------

### chome
Bind mount a different directory on top of $HOME to (partially) isolate a process

### fakensudo
Pretend to be root (uid 0) by running in a single-user namespace mapping one's own UID to 0

### keepassxc-print
Retrieve passwords from KeePassXC on the commandline via the browser interface.

### overlayns
Run a command in a custom mount namespace. Like `unshare -mUc` with the added possibility of setting up custom mounts in the namespace before running the target application

### ssh-overlay-kiosk
Create an emphemeral home directory for each invocation.

### steamns
Isolate steam (and other 32-bit apps) in an unprivileged single-user-namespace "chroot"

Libraries
---------

### keepassxc-browser.hpp
Very simple library for interacting with KeePassXC's browser interface from native code

Depends on libsodium, jsoncpp, ko::proc

### ko::fd
Convenient wrapper around Linux APIs with dirfd support

kofd\_pipe.hpp adds a class for working with pairs of uni-directional pipes

Depends on ko::fs

### ko::fs
Misc. filesystem utilities

- cpath: Type that is trivially convertible to const char\* and from std::string and std::filesystem::path
- dir\_ptr: Convenient iterator-based wrapper around the dirent API

### ko::ns
Utilities for working with Linux Namespaces (unshare, clone, setns)

Depends on ko::util, ko::fd, ko::os

- ko::ns::idmap: Functions for writing /proc/$$/Xidmap
- ko::ns::mount: Functions for setting up mount namespaces
- ko::ns::clone: Helpers for spawning processes in new namespaces (kons\_clone.hpp, requires ko::proc)

### ko::os
Misc. OS helpers

Depends on ko:: fs

- get\_home()
- is\_mountpoint()

### ko::proc
Utilities for spawning and managing child processes

Depends on pthread, ko::fd

- popen[p]: Spawn subprocess and communicate via pipes
- sync::semapair: Synchronization across processes
- child\_ref: Child process reference with cleanup
- [s]vclone: Wrappers around linux clone(CLONE\_VM)
- simple\_spawn: Trivial fork(); execvp() primitive

### ko::util
Misc. utilities

- str: Type-safe-ly concatenate all arguments
- cvshort: Short-circuit continuation using C-Style return codes

