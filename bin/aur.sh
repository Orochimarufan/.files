#!/bin/zsh
# (c) 2014-2015 Taeyeon Mori
# vim: ft=sh:ts=2:sw=2:et

# Load libraries and configuraion
source "$DOTFILES/lib/libzsh-utils.zsh"
source "$DOTFILES/etc/aur.conf"

function throw {
  err "$2"
  exit $1
}

# Figure out build directory
tmpbuild=${TMPDIR-/tmp}/aur.sh.$$
build="${BUILDDIR:-$tmpbuild}"
test -d "$build" || mkdir -p "$build" || exit 1

# ------------------------------------------------------------------------------
# Parse commandline: anything prefixed with - is a makepkg option, others are package names
packages=()
makepkg_args=()

aur_get=aur_get_aur4
DL_ONLY=false
ASK=false

add_makepkg_arg() {
  makepkg_args=("${makepkg_args[@]}" "$1")
}

_proxy_args=0
for cx in "$@"; do
  if [ $_proxy_args -gt 0 ]; then
    add_makepkg_arg "$cx"
    _proxy_args=$[$_proxy_args - 1]
    continue
  fi
  case "$cx" in
    --old-aur)
      warn "[AUR] Using old AUR (--old-aur)"
      aur_get=aur_get_old;;
    -X|--download-only)
      warn "[AUR] Building was disabled (-X)"
      DL_ONLY=true;;
    --ask)
      ASK=true;;
    -h|--help)
      echo "Usage $0 [-h] [-X] [makepkg options] <packages>"
      echo "Taeyeon's aur.sh (c) 2014-2015 Taeyeon Mori (not related to http://aur.sh)"
      echo
      echo "A simple AUR client realized in bash/zsh"
      echo
      echo "aur.sh options:"
      echo "  -h, --help    Display this message"
      echo "  -X, --download-only"
      echo "                Only download the PKGBUILDs from AUR, don't build"
      echo "  --old-aur     Use the old (non-git) AUR"
      echo "  --ask         Ask before installing packages (removes --noconfirm)"
      echo
      echo "Useful makepkg options:"
      echo "  -i            Install package after building it"
      echo "  -s            Install dependencies from official repos"
      echo "  --pkg <list>  Only build selected packages (when working with split packages)"
      exit 0
      ;;
    --pkg|--key|--config) # These take an additional value
      _proxy_args=1
      add_makepkg_arg "$cx";;
    -*)
      add_makepkg_arg "$cx";;
    *)
      packages=("${packages[@]}" "$cx");;
  esac
done


# -------------------------------------------------------------------------
# aur functions
aur_get_old() {
  [ -d "$1/.git" ] && err "Local copy of $1 is a Git clone from AUR v4. Don't use --old-aur with it!" && return 32
  curl "https://aur.archlinux.org/packages/${1:0:2}/$1/$1.tar.gz" | tar xz
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
    git clone "https://aur4.archlinux.org/$1.git/" "$1"
  fi
}

# ----------------------------------------------------------------------------
# Actual work starts here
# Print some info
msg "[AUR] AURDIR=$AURDIR; PKGDEST=$PKGDEST"
test "$build" = "$PWD" || \
  msg "[AUR] Working in $build."
msg "[AUR] Building packages: $packages"

if ! $ASK && ! $DL_ONLY; then
  msg "[AUR] Updating sudo timestamp"
  sudo -v

  add_makepkg_arg "--noconfirm"
fi

# Process packages
for p in "${packages[@]}"; do

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

  if $DL_ONLY; then continue; fi

  # Copy it to the build directory $build and change there
  cp -r "$p" "$build"
  cd "$build/$p"

  # Update timestamp, but don't ask for pw if it expired
  sudo -vn

  # Run makepkg
  msg "[AUR] $p: Building..."
  makepkg "${makepkg_args[@]}" || \
    throw 1 "[AUR] $p: Makepkg failed!"

  msg "[AUR] $p: Done!"
done

msg "[AUR] All Done!"

# Remove the builddir if we previously created it.
cd "$AURDEST"
[ "$build" = "$tmpbuild" ] && \
  warn "[AUR] Removing temporary directory $tmpbuild" && \
  rm -rf "$tmpbuild"

