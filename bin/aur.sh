#!/bin/zsh
# vim: ft=sh:ts=2:sw=2:et

source "$DOTFILES/zsh/lib.zsh"
source "$DOTFILES/etc/aur.conf"

function throw {
  err "$2"
  exit $1
}

tmpbuild=$TMPDIR/aur.sh.$$
build="${BUILDDIR:-$tmpbuild}"
test -d "$build" || mkdir -p "$build" || exit 1

packages=(${@##-*})
makepkg_flags=(${@##[^\-]*})

msg "[AUR] AURDIR=$AURDIR; PKGDEST=$PKGDEST"
test "$build" = "$PWD" || \
  msg "[AUR] Working in $build."
msg "[AUR] Building packages: $packages"

for p in "${packages[@]}"; do
  cd "$AURDIR"

  msg "[AUR] $p: Getting PKGBUILD"
  {
    test -d $p && \
    test -f $p/PKGBUILD && \
    grep -q "#CUSTOMPKG" $p/PKGBUILD && \
    warn "[AUR] $p: Found #CUSTOMPKG; not updating PKGBUILD from AUR!" \
  } || \
    { curl https://aur.archlinux.org/packages/${p:0:2}/$p/$p.tar.gz | tar xz } || \
    throw 2 "[AUR] $p: Couldn't download package"

  cd $p

  msg "[AUR] $p: Building..."
  makepkg "${makepkg_flags[@]}" || \
    throw 1 "[AUR] $p: Makepkg failed!"

  msg "[AUR] $p: Done!"
done

msg "[AUR] All Done!"

test "$build" = "$tmpbuild" && \
  warn "[AUR] Removing temporary directory $tmpbuild" && \
  rm -rf "$tmpbuild"

