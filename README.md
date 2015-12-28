Taeyeon's dotfiles (.files)
===========================

.files/install
--------------
A ZShell script to set up the dotfiles. It will also ask a few personal questions.
Run this on a new system to set it up.

.files/zsh
----------
The ZSH part makes use of the Prezto framework (http://github.com/sorin-ionescu/prezto)

Configuration happens in the z\* files in .files/zsh:
- zshenv    : executed by all zsh instances
- zprofile  : executed by any top-level shell
- zshrc     : executed by interactive shells (loads prezto)
- preztorc  : contains prezto-specific configuration
- zlogin    : executed by login shells
- zlogout   : executed when a login shell exits

.files/bin
----------
Contains utility applications I'd hate to miss

Notable ones are:
- xconv     : A simple, profile-based, batch-enabled "frontend" to ffmpeg.
- aconvert  : Pre-advancedav version of xconv. Has profiles for extracting audio.
- ffpsp\*   : Scripts to run HandBrakeCLI to convert videos for use with Sony's PSP.
- pulse-\*  : Tools to be used with my pulse configuration in .files/config/pulse
- paloop    : Loop a pulseaudio source to a sink
- aur.sh    : More powerfull version of the popular aur.sh script.
- schedshut : Shutdown when a specific task/process finishes.
- mountpart : Mount a partition in a whole-disk imagefile.
- argshell  : call the same application repeatedly, with a common set of arguments.
- fix-steam-runtime.sh : Fix Steam runtime on Arch Linux (And others with "too new" libstdc++ and friends)
- prepare\_steam : Manage Steam Library Folders on Removable Storage
- sm-song-package : Simplify creation of SM5-compliant song packages
- unpack\_shift : Unpack SHIFT-JIS archives
- stayawake : Pause music player when one falls asleep
- lns       : Make symbolic links without thinking about relative paths too hard
- visualsleep : A sleep utility with visual feedback


.files/etc
----------
Contains configuration for those utilities

Currently contains:
- aur.conf  : Configuration for aur.sh
- user-info : The user information entered at install time, in shell-readable form
- prepare\_steam.vdf : Config file for prepare\_steam

.files/lib
----------
Contains support libraries

Currently, that entails:
- libsh-utils.sh    : A collection of useful shell functions
- libzsh-utils.zsh  : More utility shell functions, but using zsh-specific features
- libpulse-config.sh: Functions for working with the pulseaudio configs in .files/config/pulse
- libssh-agent.sh   : Functions for working with the ssh-agent

As well as some python modules:
- advancedav.py     : A very overengineered way to construct complex ffmpeg commandlines
- vdfparser.py      : A simple parser for Valve's VDF Key/Value format

.files/git
----------
Contains the git configuration (.files/git/config)

NOTE that changes made though git config WILL NOT BE RESPECTED,
because it writes to ~/.gitconfig, which is a proxy that includes .files/git/config .

Also note that git uses its own version of user-info (.files/git/user-info)

.files/dotfiles
---------------
General dotfiles repository. Everything that doesn't need to be special-cased goes here.

.files/config
-------------
XDG configuration directory.
Items will be symlinked to ~/.config (NOT IMPLEMENTED)

$HOME
-----
All dotfiles are symlinked into the home directory or have a proxy file generated.

Known proxies: .gitconfig, .zshenv

\*.local
--------
Files ending on .local are ignored by git.

Currently, valid .local files are:
- zsh/zprofile.local
- zsh/zshrc.local

