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
    echo -en "\e[0m"
    return $?
}

# Append to array
push() {
    local arr="$1"; shift

    for val in "$@"; do
        eval "$arr[\${#$arr[@]}]=\"\$val\""
    done
}
