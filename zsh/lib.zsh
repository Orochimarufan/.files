#!/bin/zsh
# ZSH Utitlities library
# (c) 2014 MORI Taeyeon
# I <3 predicates :)

# [predicate] Mute command
function quiet {
    "$@" >/dev/null 2>&1
    return $?
}

# [predicate] Colorize output
function color {
    local COLOR=$1 && shift
    echo -en "\e[${COLOR}m"
    "$@"
    echo -en "\e[0m"
    return $?
}

alias msg="color 34 echo"
alias err="color 31 echo"

# Ask a question
function ask() {
    local RESULT
    echo -en "\e[35m$1"
    [[ -n "${(P)2}" ]] && echo -n " [${(P)2}]"
    echo -n ": "
    color 36 read $3 RESULT
    [[ -n "$RESULT" ]] && eval $2=\""$RESULT"\"
}

# Get random choice
function random_choice() {
    if quiet which shuf; then
        shuf -n1 -e "$@"
    else
        local NUMBER=${RANDOM%$#+1}
        echo ${!NUMBER}
    fi
}

