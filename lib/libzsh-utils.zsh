# ZSH Utitlities library
# Zsh-only extensions to libsh-utils.sh
# (c) 2014-2015 Taeyeon Mori
# I <3 predicates :)

source "${0%/*}/libsh-utils.sh"

alias msg="color 34 echo"
alias warn="color 33 echo"
alias err="color 31 echo"

# Ask a question
function ask {
    local RESULT
    echo -en "\e[35m$1"
    [[ -n "${(P)2}" ]] && echo -n " [${(P)2}]"
    echo -n ": "
    color 36 read $3 RESULT
    [[ -n "$RESULT" ]] && eval $2=\""$RESULT"\"
}

# Get random choice
function random_choice {
    if quiet which shuf; then
        shuf -n1 -e "$@"
    else
        local NUMBER=${RANDOM%$#+1}
        echo ${(P)NUMBER}
    fi
}

# Print the a relative path from the second directory to the first,
# defaulting the second directory to $PWD if none is specified.
# SOURCE: http://www.zsh.org/mla/users/2002/msg00267.html
function relpath {
	[[ $1 != /* ]] && print $1 && return

	local dir=${2:-$PWD}
	[[ $1 == $dir ]] && print . && return

	local -a cur abs
	cur=(${(ps:/:)dir})    # Split 'current' directory into cur
	abs=(${(ps:/:)1})      # Split target directory into abs

	local min
	((min = $#cur < $#abs ? $#cur : $#abs))
	local i=1
	while ((i <= $min)) && [[ $abs[1] == $cur[$i] ]]
	do
		abs[1]=()         # Strip common prefix from target directory
		((i=i+1))
	done

	# Figure out how many parents to get to common root
	local relpath=
	while ((i <= $#cur))
	do
		relpath=../$relpath
		((i=i+1))
	done

	relpath=$relpath${(j:/:)abs}
	print ${relpath%/}
}
