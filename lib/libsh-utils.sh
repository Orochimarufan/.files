# Shell Utitlities library
# Should work in both bash and zsh
# (c) 2014-2015 Taeyeon Mori
# I <3 predicates :)

# [predicate] Mute command
quiet() {
    "$@" >/dev/null 2>&1
    return $?
}

# [predicate] Colorize output
color() {
    local COLOR=$1 && shift
    echo -en "\e[${COLOR}m"
    "$@"
    local res=$?
    echo -en "\e[0m"
    return $res
}

