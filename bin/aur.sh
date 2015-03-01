#!/bin/zsh
# vim: ft=sh:ts=2:sw=2:et

# Load libraries and configuraion
source "$DOTFILES/lib/libzsh-utils.zsh"
source "$DOTFILES/etc/aur.conf"

function throw {
  err "$2"
  exit $1
}

# Figure out build directory
tmpbuild=$TMPDIR/aur.sh.$$
build="${BUILDDIR:-$tmpbuild}"
test -d "$build" || mkdir -p "$build" || exit 1

# Parse commandline: anything prefixed with - is a makepkg option
packages=(${@##-*})
makepkg_flags=(${@##[^\-]*})

if echo "${makepkg_flags[*]}" | grep -q "\\-X"; then
  warn "[AUR] Building was disabled (-X)"
  DL_ONLY=true
else
  DL_ONLY=false
fi

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
    { curl https://aur.archlinux.org/packages/${p:0:2}/$p/$p.tar.gz | tar xz } || \
    throw 2 "[AUR] $p: Couldn't download package"

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

