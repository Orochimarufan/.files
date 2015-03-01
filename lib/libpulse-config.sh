#!/bin/bash

# PulseAudio startup script
# (c) 2014-2015 Taeyeon Mori
# Do what the fuck you want with it. (No warranty, etc)

source "${DOTFILES-$(dirname "${BASH_SOURCE-$0}")/..}/lib/libsh-utils.sh" #"

# Paths
PA_CONFIG_DIR="${XDG_CONFIG_DIR-$HOME/.config}/pulse"
PA_HOSTS_DIR="$PA_CONFIG_DIR/machines.d"

# PulseAudio
PA_EXECUTABLE="/usr/bin/pulseaudio"

# == Look for a host-specific config file. ==
# It should be located in $MACHINES_DIR and named "<hostname>.pa", with <hostname> all lower-case.
# If none is found, PA will be started using the default files ($PULSE_DIR/default.pa, /etc/pulse/default.pa)
pa_find_host_config() {
    test -n "$PA_HOST_CONFIG" && return
    declare -g PA_HOST_CONFIG_NAME="${HOSTNAME,,}.pa"
    declare -g PA_HOST_CONFIG_FILE="$PA_HOSTS_DIR/$PA_HOST_CONFIG_NAME"
    if test -e "$PA_HOST_CONFIG_FILE"; then
        color 33 echo "Using machine configuration: $PA_HOST_CONFIG_NAME"
        declare -g PA_HOST_CONFIG="$PA_HOST_CONFIG_FILE"
    fi
}

pa_find_config() {
    test -n "$PA_CONFIG" && return
    pa_find_host_config
    if test -n "$PA_HOST_CONFIG"; then
        declare -g PA_CONFIG="$PA_HOST_CONFIG"
    elif test -e "$PA_CONFIG_DIR/default.pa"; then
        color 33 echo "Using default configuration: default.pa"
        declare -g PA_CONFIG="$PA_CONFIG_DIR/default.pa"
    elif test -e "/etc/pulse/default.pa"; then
        color 33 echo "Using global default configuration: /etc/pulse/default.pa"
        declare -g PA_CONFIG="/etc/pulse/default.pa"
    fi
}


# Parse tunnel load-module line
pa_parse_tunnel_line() {
    declare -g TUN_NAME=`echo $1 | grep -oP '(sink|source)_name=[^ ]+' | cut -f2 -d=`
    declare -g TUN_SERVER=`echo $1 | grep -oP 'server=[^ ]+' | cut -f2 -d=`
    declare -g TUN_DEVICE=`echo $1 | grep -oP '(sink|source)=[^ ]+' | cut -f2 -d=`
    declare -g TUN_DESCRIPTION=`echo $1 | grep -oP "device.description='[^']+'" | cut -f2 -d=`
}

pa_find_config_lines() {
    if test -n "$2"; then
        local cfg="$2"
    else
        pa_find_config
        local cfg="$PA_CONFIG"
    fi
    local IFS=$'\n'
    declare -ga PA_CONFIG_LINES=(`grep "$1" "$cfg"`)
}
