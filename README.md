Taeyeon's dotfiles (.files)
===========================

As of right now, only contains dotfiles for zsh, vim and git.

.files/install
--------------
A ZShell script to set up the dotfiles. It will also ask a few personal questions.
Run this on a new system to set it up

.files/zsh
----------
The ZSH part makes use of the Prezto framework (http://github.com/sorin-ionescu/prezto)


.files/git
----------
Contains the git configuration (.files/git/config)

\*/user-info
-----------
Contains user information collected at install time.
currently only .files/user-info and .files/git/user-info

.files/dotfiles
---------------
General dotfiles repository. Everything that doesn't need to be special-cased goes here.

$HOME
-----
All dotfiles are symlinked into the home directory or have a proxy file generated.

Known proxies: .gitconfig, .zshenv

\*.local
--------
Files ending on .local are ignored by git.

