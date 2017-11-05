Taeyeon's dotfiles (.files)
===========================


.files/install
--------------
A ZShell script to set up the dotfiles. It will also ask a few questions.
Run this on a new system to set it up.


.files/zsh
----------
The ZSH part makes use of the Prezto framework (http://github.com/sorin-ionescu/prezto)

##### ZSH configuration files
- zshenv    : executed by all zsh instances
- zprofile  : executed by any top-level shell
- zshrc     : executed by interactive shells (loads prezto)
- preztorc  : contains prezto-specific configuration
- zlogin    : executed by login shells
- zlogout   : executed when a login shell exits

- functions/        : Added to fpath
    - prompt\_tae\_setup: `tae` prompt setup
- zplug/            : Zplug home directory


.files/bin
----------
Contains utility applications I'd hate to miss

#### (Z) Shell scripts
- argshell          : Run the same program multiple times with a common prefix of arguments
- aur.sh            : Quite sophisticated AUR helper
- ffpsp(-batch)     : Use HandBrakeCLI to encode videos to be compatible with Sony's PSP.
- fix-steam-runtime.sh: Fix Steam runtime on Arch Linux (And others with "too new" libstdc++ and friends)
- force-run-elf     : Try to execute a non-executable ELF file by passing it to the appropriate interpreter
- paloop            : Loop a pulseaudio source to a sink.
- remembersong      : Save the currently playing song name and artist to a text file.
- schedshut         : Shutdown when a specific task/process finishes.
- start             : Start a (graphical) app in the background; Like windows command of same name.
- syncfat           : Copy files to a Windows volume while removing invalid characters from filenames.
- unpack\_shift     : Unpack archives with different filename encoding

#### Python scripts
- animelib          : Manually organize a collection of tv series
- animelib3         : Try to automagically organize tv series as best as possible
- fileinterp.py     : Play back a python script file as if it had been entered into a prompt.
- mountpart         : Mount a partition in a whole-disk raw image file.
- nosaver           : Try to inhibit the screensaver.
- patchdir          : Patch a folder structure with files from an archive.
- sm-song-package   : Try to automatically create a .smzip of songs for StepMania.
- transportlinks    : Fixup symlinks after moving the target files.
- videothumb        : Create (PSP compatible) thumbnails for video files.
- visualsleep       : Sleep command with countdown timer.
- xconv             : A simple, profile-based, batch-enabled "frontend" to ffmpeg.

###### Broken
- mpr               : Control and listen to mpd stream at the same time.
- prepare\_steam    : Try to fix up steam libraries on removable media.
- stayawake         : Pause media playback when user falls asleep.


.files/etc
----------
Contains configuration for those utilities

Currently contains:
- aur.conf          : Configuration for aur.sh
- user-info         : The user information entered at install time, in shell-readable form
- prepare\_steam.vdf: Config file for prepare\_steam


.files/lib
----------
Contains support libraries

#### (Z) Shell
- libsh-utils.sh    : A collection of useful shell functions
- libzsh-utils.zsh  : More utility shell functions, but using zsh-specific features
- libpulse-config.sh: Functions for working with the pulseaudio configs in .files/config/pulse
- libssh-agent.sh   : Functions for working with the ssh-agent

#### Python
- advancedav.py     : A very overengineered way to construct complex ffmpeg commandlines
- animelib.py       : Library version on animelib script
- vdfparser.py      : A simple parser for Valve's VDF Key/Value format
- xconv/            : Supporting library for xconv media conversion utility
    - profiles/     : (Virtual) package containing xconv profiles


.files/git
----------
Contains the git configuration (.files/git/config)

Changes made through `git config --global` have to be manually applied to
.files/git/config (from ~/.gitconfig) to persist them

Also note that git uses its own version of user-info (.files/git/user-info)


.files/dotfiles
---------------
Misc. dotfiles

- makepkg.conf      : Arch/Pacman makepkg configuration. See also aur.sh and aur.conf
- vimrc             : Original vim configuration

##### X11
- XCompose          : Compose definitions
- xinputrc          : X11 input device configuration
- xprofile          : X11 startup script


.files/config
-------------
XDG configuration directory

- systemd/user      : Systemd user units
    - ssh-agent     : Service unit to keep a per-user ssh-agent instance
- nvim              : NeoVim configuration


.files/texmf
------------
Contains LaTeX classes

- Intridea beamer theme
- 'jatools' package with some Japanese-related things


$HOME
-----
All dotfiles are symlinked into the home directory or have a proxy file generated.

Currently employed proxies: .gitconfig, .zshenv


\*.local
--------
Files ending on .local are ignored by git.

Currently, valid .local files are:
- zsh/zprofile.local
- zsh/zshrc.local

