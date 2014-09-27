#!/bin/bash
# libssh-agent 0.1
# (c) 2013-2014 Orochimarufan
#
# Managing SSH keys and agents

LSA_VERSION=0.1

# === Tools ===
# Echo colored text to STDERR
echocolor() {
  # (int color, string... text)
  local COLOR=$1 && shift
  echo -e "\e[${COLOR}m$*\e[0m" >&2
}

# Look for keys in ssh argv
ssh_keys_from_argv() {
  # (string... argv) -> global "KEYS"
  local EX=false
  declare -ga KEYS
  
  for arg in "$@"; do
    if $EX; then
      KEYS=("${KEYS[@]}" "$arg")
      EX=false
    else
      [ "$arg" = "-i" ] && EX=true
    fi
  done
}

# === Private Functions ===
# Private SSH Agent instance management
PRIVATE_SSH_AGENT=false

private_ssh_agent_start() {
  echocolor 35 "Starting private SSH Agent."
  PRIVATE_SSH_AGENT_P_PID=$SSH_AGENT_PID
  PRIVATE_SSH_AGENT_P_SOCK=$SSH_AUTH_SOCK
  # We don't want the PID printed.
  eval `ssh-agent -s` >/dev/null
  PRIVATE_SSH_AGENT=true
}

private_ssh_agent_stop() {
  echocolor 35 "Stopping private SSH Agent."
  # We don't need the output.
  eval `ssh-agent -ks` >/dev/null
  PRIVATE_SSH_AGENT=false
  export SSH_AGENT_PID=$PRIVATE_SSH_AGENT_P_PID
  export SSH_AUTH_SOCK=$PRIVATE_SSH_AGENT_P_SOCK
}

gnome_keyring_ssh_agent_ckeck() {
  # the GNOME Keyring agent doesn't support ecdsa keys.
  local PID=$1; shift
  
  # FIXME: Linux specific!
  # FIXME: is this reliable?
  CMDLINE="/proc/$PID/cmdline"
  if grep -qi gnome-session "$CMDLINE" 2>/dev/null; then
    echocolor 33 "Warning: Detected GNOME Keyring, lacking ECDSA support."
    for key in "$@"; do
      if grep -q "BEGIN EC PRIVATE KEY" "$key"; then
        echocolor 31 "Found ECDSA Identity: $key"
        echocolor 31 "Identities contain ECDSA key(s). Forcing creation of a private OpenSSH agent."
        return 1
      fi
    done
  fi
  return 0
}

#  === Public API ===
# Check for running agent or start a new one
# Keys will be added if they don't exist.
# Setting start to false will basically do a dry run.
# You should use the aliases below.
ssh_agent() {
  # (bool start, string... keys)
  local START=$1 && shift
  
  local KEYS="`ssh-add -l 2>/dev/null`"
  { [ $? -eq 2 ] || ! gnome_keyring_ssh_agent_ckeck $SSH_AGENT_PID "$@" || $START && test -n "$LSA_FORCE_AGENT"; } && \
    { $START && private_ssh_agent_start || return 2; }
  
  local RT=0
  for key in "$@"; do
    echo "$KEYS" | grep -q "$key" \
      || { $START && ssh-add "$key"; } \
      || { RT=1; echocolor 34 "SSH Agent is missing a key: $key"; }
  done
  return $RT
}

ssh_agent_dry() {
  # (string... keys)
  ssh_agent false "$@"
}

ssh_agent_begin() {
  # (string... keys)
  ssh_agent true "$@"
}

ssh_agent_end() {
  # (void)
  $PRIVATE_SSH_AGENT && private_ssh_agent_stop
}

