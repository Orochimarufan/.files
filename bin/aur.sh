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

# Parse commandline: anything prefixed with - is a makepkg option
packages=()
flags=()
aur_get=aur_get_aur4 # new one not working yet
DL_ONLY=false

for cx in "$@"; do
  case "$cx" in
    --old-aur)
      warn "[AUR] Using old AUR (--old-aur)"
      aur_get=aur_get_old;;
    -X|--download-only)
      warn "[AUR] Building was disabled (-X)"
      DL_ONLY=true;;
    -h|--help)
      echo "Usage $0 [-h] [-X] [makepkg options] <packages>"
      echo
      echo "aur.sh options:"
      echo "  -h, --help    Display this message"
      echo "  -X, --download-only"
      echo "                Only download the PKGBUILDs from AUR, don't build"
      echo "  --old-aur     Use the old (non-git) AUR"
      echo
      echo "Useful makepkg options:"
      echo "  -i            Install package after building it"
      echo "  -s            Install dependencies from official repos"
      exit 0
      ;;
    -*)
      makepkg_flags=("${makepkg_flags[@]}" "$cx");;
    *)
      packages=("${packages[@]}" "$cx");;
  esac
done

# aur functions
aur_get_old() {
  [ -d "$1/.git" ] && error "Local copy of $1 is from AUR4. Cannot use --old-aur with it!" && return 32
  curl https://aur.archlinux.org/packages/${1:0:2}/$1/$1.tar.gz | tar xz
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
      rm -rf $1
    fi
    git clone https://aur4.archlinux.org/$1.git/
  fi
}

# Print some info
msg "[AUR] AURDIR=$AURDIR; PKGDEST=$PKGDEST"
test "$build" = "$PWD" || \
  msg "[AUR] Working in $build."
msg "[AUR] Building packages: $packages"

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
    $aur_get $p || throw 2 "[AUR] $p: Couldn't download package"

  if $DL_ONLY; then continue; fi

  # Copy it to the build directory $build and change there
  cp -r "$p" "$build"
  cd "$build/$p"

  # Run makepkg
  msg "[AUR] $p: Building..."
  makepkg "${makepkg_flags[@]}" || \
    throw 1 "[AUR] $p: Makepkg failed!"

  msg "[AUR] $p: Done!"
done

msg "[AUR] All Done!"

# Remove the builddir if we previously created it.
cd "$AURDEST"
test "$build" = "$tmpbuild" && \
  warn "[AUR] Removing temporary directory $tmpbuild" && \
  rm -rf "$tmpbuild"

