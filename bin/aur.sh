#!/bin/zsh
# (c) 2014-2015 Taeyeon Mori
# vim: ft=sh:ts=2:sw=2:et

AUR_DEFAULT_HOST="https://aur.archlinux.org/"

# Load libraries and configuraion
source "$DOTFILES/lib/libzsh-utils.zsh"
source "$DOTFILES/etc/aur.conf"

function throw {
  err "$2"
  clean_exit $1
}

function clean_exit {
  exit ${1-0}
}


# ------------------------------------------------------------------------------
# Parse commandline: anything prefixed with - is a makepkg option, others are package names
packages=()
makepkg_args=()

aur_get=aur_get_aur4
DL_ONLY=false
ASK=false
AUR_HOST="$AUR_DEFAULT_HOST"
ADD_UPDATES=false
RECURSE_DEPS=false
NEED_COWER=false
LIST_ONLY=false
EXCLUDE=
ASDEPS=true

add_makepkg_arg() {
  makepkg_args=("${makepkg_args[@]}" "$1")
}

_proxy_args=0
_next_arg=
process_arg() {
  local cx="$1"
  if [ $_proxy_args -gt 0 ]; then
    add_makepkg_arg "$cx"
    _proxy_args=$[$_proxy_args - 1]
    continue
  fi
  if [ -n "$_next_arg" ]; then
    case "$_next_arg" in
      --aur-host)
        AUR_HOST="$cx";;
      --exclude)
        EXCLUDE=",$cx";;
    esac
    _next_arg=
    continue
  fi
  case "$cx" in
    # aur.sh options
    --old-aur)
      warn "[AUR] Using old AUR methods (--old-aur)"
      aur_get=aur_get_old;;
    -X|--download-only)
      warn "[AUR] Building was disabled (-X)"
      DL_ONLY=true;;
    --ask)
      ASK=true;;
    --aur-host|--exclude) # need more args
      _next_arg="$cx";;
    -u|--update)
      [ -n "$MODE" ] && throw 255 "Can only use one flag from the 'aur.sh command' category"
      NEED_COWER=true
      ADD_UPDATES=true;;
    -S|--recurse-deps)
      NEED_COWER=true
      RECURSE_DEPS=true
      add_makepkg_arg -is;;
    -L|--list-only)
      LIST_ONLY=true;;
    -h|--help)
      echo "Usage $0 [-h|-u] [-S] [-L|-X] [makepkg options] <packages>"
      echo "Taeyeon's aur.sh (c) 2014-2015 Taeyeon Mori (not related to http://aur.sh)"
      echo
      echo "A simple AUR client realized in bash/zsh"
      echo
      echo "aur.sh options:"
      echo "  -h, --help    Display this message"
      echo "  -u, --update  Build all updated AUR packages [c]"
      echo "  -S, --recurse-deps"
      echo "                Recursively build & install all dependencies [c]"
      echo "                Implies -is"
      echo "  -L, --list-only"
      echo "                Only list all affected packages"
      echo "  -X, --download-only"
      echo "                Only download the PKGBUILDs from AUR, don't build."
      echo "  --aur-host <url>"
      echo "                Use a different AUR server. default: https://aur.archlinux.org/"
      echo "  --old-aur     Use the old (non-git) AUR methods"
      echo "  --ask         Ask before installing packages (removes --noconfirm)"
      echo "  --clean       Clean up leaftover temporary files (of failed builds) and exit"
      echo "  --exclude <pkgs>"
      echo "                Exclude packages from -u"
      echo "  --asexplicit  Don't pass --asdeps to makepkg"
      echo
      echo "Useful makepkg options:"
      echo "  -i            Install package after building it"
      echo "  -s            Install dependencies from official repos"
      echo "  --pkg <list>  Only build selected packages (when working with split packages)"
      echo
      echo "NOTE: options marked [c] require cower to be installed (\$ aur.sh -is cower)"
      echo "      However, certain cower-only features are automatically enabled when cower is found."
      exit 0
      ;;
    --clean)
      local temp="${TMPDIR-/tmp}"
      for tmp in `find "$temp" -name 'aur.sh.*'`; do
        if [ -e "$tmp/aur.sh.running" ] && [ -e "/proc/${tmp%%.}" ]; then
          err "Cannot remove '$tmp', aur.sh instance seems to be running"
        else
          msg "Removing '$tmp'.."
          rm -rf "$tmp"
        fi
      done
      color 35 echo "Cleaned leftover temporary files."
      exit 0;;
    --asexplicit)
      ASDEPS=false;;
    # Makepkg args
    --pkg|--key|--config|-p) # These take an additional value
      _proxy_args=1
      add_makepkg_arg "$cx";;
    -*)
      add_makepkg_arg "$cx";;
    # Package names
    *)
      packages=("${packages[@]}" "$cx");;
  esac
}

for cx in "$@"; do
  case "$cx" in
    --*)
      process_arg "$cx";;
    -*)
      for c in `echo "${cx:1}" | grep -o .`; do
        process_arg "-$c"
      done;;
    *)
      process_arg "$cx";;
  esac
done


# Cower Detection
USE_COWER=false

if cower --version >/dev/null; then
  USE_COWER=true # Auto-enable cower support if installed.
elif $NEED_COWER; then
  throw 31 "Options requiring cower have been selected but cower was not found."
else
  warn "Could not detect cower on the system."
fi

if [ "$aur_get" != "aur_get_aur4" ] || [ "$AUR_HOST" != "$AUR_DEFAULT_HOST" ]; then
  USE_COWER=false
  $NEED_COWER &&
    throw 31 "--old-aur and --aur-host are currently not supported with cower features" ||
    warn "Features depending on cower cannot be used with --old-aur and --aur-host. Disabling them."
fi

if ! $USE_COWER; then
  warn "Cower will not be used. Not all features are available without it."
  warn "Specifically, split packages cannot be detected without cower."
fi


# -------------------------------------------------------------------------
# aur functions
aur_get_old() {
  [ -d "$1/.git" ] && err "Local copy of $1 is a Git clone from AUR v4. Don't use --old-aur with it!" && return 32
  curl "$AUR_HOST/packages/${1:0:2}/$1/$1.tar.gz" | tar xz
}

aur_get_aur4() {
  if [ -d "$1/.git" ]; then (
    cd "$1"
    git pull
  ) else
    if [ -e "$1" ]; then
      warn "$1 PKGBUILD directory exists but is not a git clone."
      ans=n
      ask "Overwrite $1?" ans
      [ "$ans" = "y" ] || [ "$ans" = "yes" ] || [ "$ans" = "Y" ] || return 32
      rm -rf "$1"
    fi
    git clone "$AUR_HOST/$1.git" "$1"
  fi
}

# ----------------------------------------------------------------------------
# Actual work starts here
# Print some info
msg "[AUR] AURDIR=$AURDIR; PKGDEST=$PKGDEST"

if $ADD_UPDATES; then
  [ -n "$packages" ] && throw 31 "You cannot specify package names when using --update"
  OFS="$IFS"
  IFS=$'\n'
  for update in `cower -u`; do
    packages=("${packages[@]}" "`echo $update | cut -d' ' -f2`")
  done
  IFS="$OFS"

  msg "[AUR] Updates available for: ${packages[*]}"

  if [ -n "$EXCLUDE" -o -n "$AURSH_IGNORE_UPDATES" ]; then
    packages=(`echo ${packages[@]} | sed -re "s/$(echo $EXCLUDE $AURSH_IGNORE_UPDATES | sed -e 's/[ ,]/|/g')//g"`)
  fi
fi

if [ -z "$packages" ]; then
  warn "[AUR] Nothing to do."
  exit 0
else
  msg "[AUR] Package set: ${packages[*]}"
fi

# Figure out build directory
if ! $DL_ONLY && ! $LIST_ONLY; then
  tmpbuild=${TMPDIR-/tmp}/aur.sh.$$
  build="${BUILDDIR:-$tmpbuild}"
  test -d "$build" || mkdir -p "$build" || throw 1 "Couldn't create build directory"

  clean_exit() {
    rm "$build/aur.sh.running" 2>/dev/null || true
    exit ${1-0}
  }
  trap clean_exit TERM
  trap clean_exit INT
  touch "$build/aur.sh.running"

  test "$build" = "$PWD" || \
    msg "[AUR] Working in $build."
  msg "[AUR] Building packages: $packages"

  if ! $ASK; then
    msg "[AUR] Updating sudo timestamp"
    sudo -v

    add_makepkg_arg "--noconfirm"
  fi

  $ASDEPS && add_makepkg_arg "--asdeps"

  msg "[AUR] Makepkg args: ${makepkg_args[*]}"
fi


AFFECTED_PKGS=()

# Package processing
build_package() {
  local p="$1" # package name
  local COWER_INFO="$2"

  if $USE_COWER; then
    [ -z "$COWER_INFO" ] && COWER_INFO=`cower -i $p`

    info_grep() {
      echo "$COWER_INFO" | grep "$@" | cut -d: -f2
    }

    local PACKBASE=`info_grep PackageBase | sed -e 's/^\s*//' -e 's/\s*$//'`
    if [ -n "$PACKBASE" ]; then
      color 35 echo "[AUR] $p: Is a split package. Selecting base package '$PACKBASE' instead."
      warn "[AUR] Operations on specific sub-packages require the base package to be specified along with --pkg."
      build_package "$PACKBASE" "`echo "$COWER_INFO" | grep -v PackageBase`"
      return $?
    fi

    local DEPENDS=`info_grep -i depends`
    if $RECURSE_DEPS; then
      for dep in `echo $DEPENDS`; do
        if ! pacman -Qi "$dep" >/dev/null 2>&1 && cower -i "$dep" >/dev/null 2>&1; then # Check if it's an (un-installed) aur package
          color 35 echo "[AUR] $p: Building AUR dependency '$dep'..."
          build_package "$dep"
        fi
      done
    fi
  fi

  AFFECTED_PKGS=("${AFFECTED_PKGS[@]}" "$p")

  $LIST_ONLY && return

  # First, download the PKGBUILD from AUR, to $AURDEST
  cd "$AURDEST"
  msg "[AUR] $p: Getting PKGBUILD"
  {
    test -d $p && \
    test -f $p/PKGBUILD && \
    grep -q "#CUSTOMPKG" $p/PKGBUILD && \
    warn "[AUR] $p: Found #CUSTOMPKG; not updating PKGBUILD from AUR!" \
  } || \
    $aur_get "$p" || throw 2 "[AUR] $p: Couldn't download package"

  $DL_ONLY && return

  # Copy it to the build directory $build and change there
  cp -Lr "$p" "$build"
  cd "$build/$p"

  # Update timestamp, but don't ask for pw if it expired
  sudo -vn

  # Run makepkg
  msg "[AUR] $p: Building..."
  makepkg "${makepkg_args[@]}" || \
    throw 1 "[AUR] $p: Makepkg failed!"

  msg "[AUR] $p: Done!"
}

# Process packages
for p in "${packages[@]}"; do
  build_package "$p"
done

if $LIST_ONLY; then
  echo "Affected Packages: `echo "${AFFECTED_PKGS[@]}" | sed 's/ /\n/g' | awk '!_[$0]++{printf "%s ",$0}'`"
else
  msg "[AUR] All Done!"
fi

# Remove the builddir if we previously created it.
if ! $DL_ONLY && ! $LIST_ONLY; then
  cd "$AURDEST"
  [ "$build" = "$tmpbuild" ] && \
    warn "[AUR] Removing temporary directory $tmpbuild" && \
    rm -rf "$tmpbuild"
  clean_exit
fi

