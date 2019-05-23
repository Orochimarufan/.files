#!/bin/zsh
# (c) 2014-2018 Taeyeon Mori
# vim: ft=sh:ts=2:sw=2:et

AUR_DEFAULT_HOST="https://aur.archlinux.org/"

# Load libraries and configuraion
source "$DOTFILES/lib/libzsh-utils.zsh"
source "$DOTFILES/etc/aur.conf"

function throw {
  # throw <exit code> <err msg>
  err "$2"
  clean_exit $1
}

function clean_exit {
  # clean_exit <exit code>
  exit ${1-0}
}


# Load ZSH Extensions
autoload is-at-least

function is-exactly {
  [[ "$1" == "$2" ]]
  return $?
}

function is-at-most {
  ! is-at-least "$1" "$2" || is-exactly "$1" "$2"
  return $?
}

function is-less {
  ! is-at-least "$1" "$2"
  return $?
}

function is-more {
  ! is-at-most "$1" "$2"
  return $?
}

function check_bool {
  [[ -n "$1" ]] && $1
  return $?
}


# ------------------------------------------------------------------------------
# Parse commandline: anything prefixed with - is a makepkg option, others are package names
PROG="$0"

packages=()
makepkg_args=()

aur_get=aur_get_aur4
DL_ONLY=false
ASK=false
AUR_HOST="$AUR_DEFAULT_HOST"
ADD_UPDATES=false
ADD_SCMPKGS=false
ADD_PYTHON=false
RECURSE_DEPS=false
NEED_COWER=false
NEED_ROOT=false
LIST_ONLY=false
IGNORE_ERRORS=false
EXCLUDE=
ASDEPS=false
NEEDED=true
NOCONFIRM=true
USECUSTOM=true
LOCAL_ONLY=false
NOCLEAN=false

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
      --threads)
        if [ "${cx:0:1}" = "-" -o "${cx:0:1}" = "+" ]; then
          export MAKEPKG_MAKETHREADS=$[`nproc` + $cx]
        elif [ "$cx" = 0 ]; then
          export MAKEPKG_MAKETHREADS=`nproc`
        else
          export MAKEPKG_MAKETHREADS=$cx
        fi;;
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
    -a|--ask)
      ASK=true;;
    --offline)
      LOCAL_ONLY=true;;
    --aur-host|--exclude) # need more args
      _next_arg="$cx";;
    --no-custom)
      USECUSTOM=false;;
    --noclean)
      NOCLEAN=true;;
    -j|--threads)
      _next_arg=--threads;;
    -1)
      export MAKEPKG_MAKETHREADS=$[`nproc` - 1];;
    -u|--update)
      NEED_COWER=true
      ADD_UPDATES=true;;
    -g|--scm-packages|--scm-update)
      ADD_SCMPKGS=true;;
    --python-update)
      ADD_PYTHON=true
      NEEDED=false
      add_makepkg_arg -f;;
    -S|--recurse-deps)
      NEED_COWER=true
      RECURSE_DEPS=true
      NEED_ROOT=true
      add_makepkg_arg -i;;
    -L|--list-only)
      LIST_ONLY=true;;
    -E|--ignore-errors)
      IGNORE_ERRORS=true;;
    -h|--help)
      echo "Usage $PROG [options] <packages>"
      echo "Taeyeon's aur.sh (c) 2014-2016 Taeyeon Mori (not related to http://aur.sh)"
      echo
      echo "A simple AUR client realized in zsh"
      echo
      echo "aur.sh options:"
      echo "  -h, --help    Display this message"
      echo "  -u, --update  Build all updated AUR packages [c]"
      echo "  -g, --scm-update, --scm-packages"
      echo "                Try to rebuild all *-git packages"
      echo "  --python-update"
      echo "                Rebuild all python-* packages after new python release"
      echo "                Equivalent to: $PROG -f \`pacman -Qm | grep 'python-.\\+'\`"
      echo "                Note: Doesn't honor AURSH_IGNORE_UPDATES"
      echo "  -S, --recurse-deps"
      echo "                Recursively build & install all dependencies [c]"
      echo "                Implies -i (Auto-install built packages)"
      echo "  -L, --list-only"
      echo "                Only list all affected packages"
      echo "  -X, --download-only"
      echo "                Only download the PKGBUILDs from AUR, don't build."
      echo "  --offline     Don't try to download new PKGBUILDs"
      echo "  -E, --ignore-errors"
      echo "                Continue with the next package even after a failure."
      echo "  -j, --threads [+-]<n>"
      echo "                Set \$MAKEPKG_MAKETHREADS to be used in makepkg.conf"
      echo "                Values prefixed with + or - are added to the number of host cpus"
      echo "  -1            Short for '--threads -1'"
      echo "  -a, --ask     Review changes before building packages"
      echo "  --exclude <pkgs>"
      echo "                Exclude packages (Useful with -u, -g, --python-update)"
      echo "  --no-custom   Don't use custom packages from $CUSTOMDIR"
      echo "  --noclean     Don't clean up temporary build directory when done."
      echo
      echo "  --clean       Clean up leaftover temporary files (of previous (failed) builds) and exit"
      echo
      echo "AUR backend options:"
      echo "  --aur-host <url>"
      echo "                Use a different AUR server. default: https://aur.archlinux.org/"
      echo "  --old-aur     Use the old (non-git) AUR methods"
      echo
      echo "Makepkg/Pacman options:"
      echo "  -i            Install package after building it (requires superuser)"
      echo "  -s            Install dependencies from official repos (requires superuser)"
      echo "  -r            Remove installed dependencies after build"
      echo "  --pkg <list>  Only build selected packages (when working with split packages)"
      echo "  --asdeps      Pass --asdeps to pacman for all installed packages"
      echo "  --reinstall   Reinstall installed packages, even when version info matches."
      echo "  --needed      Opposite of --reinstall (default)"
      echo "  --noconfirm   Skip makepkg/pacman confirmation prompts (default)"
      echo "  -o, --nobuild Download and extract sources only. Implies --noclean"
      echo "  -f, --force   Force rebuilding of built packages. Implies --reinstall"
      echo "  --no-         Negate options: --no-asdeps --no-noconfirm"
      echo
      echo "NOTE: options marked [c] require cower to be installed (\$ $PROG -is cower)"
      echo "      However, certain cower-only features are automatically enabled when cower is found."
      exit 0
      ;;
    # Clean up files from failed operations
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
    # Inverted makepkg args
    --asdeps)
      ASDEPS=true;;
    --no-asdeps)
      ASDEPS=false;;
    --asexplicit)
      echo "NOTE: --asexplicit and --no-asexplicit are DEPRECATED."
      ASDEPS=false;;
    --no-asexplicit)
      echo "NOTE: --asexplicit and --no-asexplicit are DEPRECATED."
      ASDEPS=true;;
    --needed|--no-reinstall)
      NEEDED=true;;
    --reinstall|--no-needed)
      NEEDED=false;;
    --noconfirm)
      NOCONFIRM=true;;
    --no-noconfirm)
      NOCONFIRM=false;;
    # Makepkg args
    -f|--force)
      NEEDED=false;
      add_makepkg_arg "$cx";;
    -o|--nobuild) # Remember some stuff for own use
      NOCLEAN=true
      add_makepkg_arg "$cx";;
    -i|--install|-s|--syncdeps)
      NEED_ROOT=true
      add_makepkg_arg "$cx";;
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

# Inverted Makepkg args
$NEEDED && add_makepkg_arg "--needed"
$NOCONFIRM && add_makepkg_arg "--noconfirm"

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

[[ -z "$AUR_GIT_OPTIONS" ]] && AUR_GIT_OPTIONS=()
[[ -z "$AUR_GIT_PULL_OPTIONS" ]] && AUR_GIT_PULL_OPTIONS=(--rebase)
[[ -z "$AUR_GIT_CLONE_OPTIONS" ]] && AUR_GIT_CLONE_OPTIONS=()

aur_get_aur4() {
  if [ -d "$1/.git" ]; then (
    cd "$1"
    git "${AUR_GIT_OPTIONS[@]}" pull "${AUR_GIT_PULL_OPTIONS[@]}"
  ) else
    if [ -e "$1" ]; then
      warn "$1 PKGBUILD directory exists but is not a git clone."
      ans=n
      ask "Overwrite $1?" ans
      [ "$ans" = "y" ] || [ "$ans" = "yes" ] || [ "$ans" = "Y" ] || return 32
      rm -rf "$1"
    fi
    git "${AUR_GIT_OPTIONS[@]}" clone "${AUR_GIT_CLONE_OPTIONS[@]}" -- "$AUR_HOST/$1.git" "$1"
  fi
}

# ----------------------------------------------------------------------------
# package functions
declare -a AFFECTED_PKGS
declare -a FAILED_PKGS
declare -A PKG_INFO

function pkg_failed {
  # pkg_failed <pkg name> <exit code> <err msg>
  FAILED_PKGS=("${FAILED_PKGS[@]}" "$1")
  if $IGNORE_ERRORS; then
    err "$3"
  else
    throw "$2" "$3"
  fi
  return "$2"
}

# Metadata collection
parse_pkgbuild() {
  local p="$1"
  local path="$2"

  # Funky
  PKG_INFO[$p:Depends]="$( ( source "$path"; echo "$depends[@]"; ) )"
}

collect_package() {
  local p="$1" # package name
  local COWER_INFO="$2"

  # Skip dupes (prob. from dependencies)
  if (( $AFFECTED_PKGS[(I)$p] )); then
    return 0
  fi
  
  # Set Defaults
  PKG_INFO[$p:AsDeps]=$ASDEPS

  # Get package information
  if $USECUSTOM && [ -e "$CUSTOMDIR/$p" ]; then
    msg "[AUR] Found '$p' in '$CUSTOMDIR', Using that"
    cd "$CUSTOMDIR"
    PKG_INFO[$p:From]="$CUSTOMDIR/$p"
    parse_pkgbuild "$p" "$CUSTOMDIR/$p/PKGBUILD"
  else
    if $USE_COWER; then
      if [ -z "$COWER_INFO" ]; then
        COWER_INFO=`cower -i "$p"`
      fi

      PKG_INFO[$p:CowerInfo]="$COWER_INFO"

      info_grep() {
        echo "$COWER_INFO" | grep "$@" | cut -d: -f2
      }

      PKG_INFO[$p:PackageBase]=`info_grep PackageBase | sed -e 's/^\s*//' -e 's/\s*$//'`
      PKG_INFO[$p:Depends]=`info_grep -i depends`
      PKG_INFO[$p:Version]=`info_grep -i version`
    fi
  fi

  # Check for split package
  if [ -n "$PKG_INFO[$p:PackageBase]" ]; then
    color 35 echo "[AUR] $p: Is a split package. Selecting base package '$PKG_INFO[$p:PackageBase]' instead."
    warn "[AUR] Operations on specific sub-packages require the base package to be specified along with --pkg."
    collect_package "$PKG_INFO[$p:PackageBase]" "`echo "$PKG_INFO[$p:CowerInfo]" | grep -v PackageBase`"
    return $?
  fi

  # Check for dependencies
  if [ -n "$PKG_INFO[$p:Depends]" ]; then
    # process dependencies
    PKG_INFO[$p:Dependencies]=""
    for dep in ${(z)PKG_INFO[$p:Depends]}; do
      if echo "$dep" | grep -qE "[=<>]"; then # Parse Version constraints
        dereq=""
        case "$dep" in
          (*\<=*) dereq=is-at-most; delim="<=";;
          (*=\<*) dereq=is-at-most; delim="=<";;
          (*\>=*) dereq=is-at-least; delim=">=";;
          (*=\>*) dereq=is-at-least; delim="=>";;
          (*\<*) dereq=is-less; delim="<";;
          (*\>*) dereq=is-more; delim=">";;
          (*=*) dereq=is-exactly; delim="=";;
          (*) warn "[AUR] Faulty dependency: $dep";;
        esac
        if [ -n "$dereq" ]; then
          depname=${dep%$delim*}
          depver=${dep#*$delim}
          PKG_INFO[$p:Dependencies]="$PKG_INFO[$p:Dependencies] $depname"
          constraint=${depname// /}:VersionConstraints:$p
          if [ -n "$PKG_INFO[$constraint]" ]; then
            ct=1; while [ -n "$PKG_INFO[$constraint#$ct]" ]; do ct=$[$ct + 1]; done
            constraint="$constraint#$ct"
          fi
          PKG_INFO[$constraint]="$dereq ${depver// /}"
        fi
      else
        PKG_INFO[$p:Dependencies]="$PKG_INFO[$p:Dependencies] $dep"
      fi
    done

    for dep in ${(z)PKG_INFO[$p:Dependencies]}; do
      if (( $packages[(I)$dep] )); then # make sure queued dependencies are processed before dependants, even if a version is already installed
        collect_package "$dep"
      fi
      if $RECURSE_DEPS && ! pacman -Qi "$dep" >/dev/null 2>&1 && cower -i "$dep" >/dev/null 2>&1; then # Check if it's an (un-installed) aur package
        color 35 echo "[AUR] $p: Collecting AUR dependency '$dep'..."
        collect_package "$dep"
        # Mark as dependency
        PKG_INFO[$dep:AsDeps]=true
      fi
    done
  fi

  # Queue package for build
  if ! (( $AFFECTED_PKGS[(I)$p] )); then # Don't add split packages depending on themselves multiple times. FIXME: Properly handle cycles
    AFFECTED_PKGS=("${AFFECTED_PKGS[@]}" "$p")
  fi
}

# Package processing
fetch_package() {
  local p="$1"

  if [ -z "$PKG_INFO[$p:From]" ]; then
    # First, download the PKGBUILD from AUR, to $AURDEST
    cd "$AURDEST"
    msg "[AUR] $p: Getting PKGBUILD"
    {
      test -d $p && \
      test -f $p/PKGBUILD && \
      grep -q "#CUSTOMPKG" $p/PKGBUILD && \
      warn "[AUR] $p: Found #CUSTOMPKG; not updating PKGBUILD from AUR!" \
    } || \
      $aur_get "$p" || \
        warn "[AUR] $p: Couldn't download PKGBUILD from aur!"

    PKG_INFO[$p:From]="$AURDEST/$p"
  fi
}

build_package() {
  local p="$1" # package name

  # Copy it to the build directory $build and change there
  cp -Lr "$PKG_INFO[$p:From]" "$build/$p"
  cd "$build/$p"
  
  # Build makepkg args
  local add_args=()
  
  if check_bool $PKG_INFO[$p:AsDeps]; then
    add_args+=("--asdeps")
  fi

  # Run makepkg
  msg "[AUR] $p: Building..."
  makepkg "${makepkg_args[@]}" "${add_args[@]}" || \
    { pkg_failed "$p" 1 "[AUR] $p: Makepkg failed!"; return $? }

  msg "[AUR] $p: Done!"
}

# ============== Main ========================
# Actual work starts here
# Print some info
msg "[AUR] AURDIR=$AURDIR; PKGDEST=$PKGDEST"

# Check updates ------------------------
if $ADD_UPDATES || $ADD_SCMPKGS; then
  ignore=($(echo $AURSH_IGNORE_UPDATES | tr , " "))
  if (( ${#ignore} )); then
    msg "[AUR] Ignoring updates for: ${ignore[*]}"
  fi
fi

if $ADD_UPDATES; then
  declare -a updates

  for update in "${(f)$(cower -u)}"; do
    updates+=("${${(s: :)update}[2]}")
  done

  msg "[AUR] Updates available for: ${updates[*]}"

  if (( ${#ignore} )); then
    updates=(${updates:|ignore})
  fi

  packages+=("${updates[@]}")
fi

packages_from_filter() {
  zparseopts -D i=o_ignore a=o_add p:=o_print g:=o_global

  local -a pkgs

  pkgs=("${(@f)$(pacman -Qqm | grep "$1")}")

  if [ -n "$o_print" ]; then
    color 34 printf "${o_print[2]}" "${pkgs[*]}"
  fi

  if [ -n "$o_ignore" ] && (( ${#ignore} )); then
    pkgs=(${pkgs:|ignore})
  fi

  if [ -n "$o_add" ]; then
    packages+=("${pkgs[@]}")
  fi

  if [ -n "$o_global" ]; then
    declare -ga ${o_global[2]}
    eval "${o_global[2]}=(\"\${(@)pkg}\")"
  fi
}

if $ADD_SCMPKGS; then
  packages_from_filter -ai -p "[AUR] Adding installed scm packages: %s\n" '.\+-git'
fi

if $ADD_PYTHON; then
  packages_from_filter -a -p "[AUR] Adding installed python packages: %s\n" 'python-.\+'
fi

exclude=($(echo $EXCLUDE | tr , " "))
if (( ${#exclude} )); then
  msg "[AUR] Excluding Packages: ${exclude[*]}"
  packages=(${packages:|exclude})
fi

if [ -z "$packages" ]; then
  warn "[AUR] Nothing to do."
  clean_exit
fi

msg "[AUR] Package set (${#packages}): ${packages[*]}"

# Collect package metadata ---------------
for p in "${packages[@]}"; do
  collect_package "$p"
done

if (( ${#exclude} )); then
  all_affected_pkgs="${AFFECTED_PKGS[*]}"
  AFFECTED_PKGS=(${AFFECTED_PKGS:|exclude})
  if ! [[ "$all_affected_pkgs" == "${AFFECTED_PKGS[*]}" ]]; then
    warn "[AUR] Some dependencies have been excluded!"
  fi
fi

msg "[AUR] Affected Packages (${#AFFECTED_PKGS}): $AFFECTED_PKGS[@]"

# Check version constraints
for constraint in ${(@kM)PKG_INFO:#*:VersionConstraints:*}; do
  name=${constraint%%:*}
  if (( $AFFECTED_PKGS[(I)$name] )); then
    if ! ${(z)PKG_INFO[$constraint]} $PKG_INFO[$name:Version]; then
      warn "[AUR] Version constraint not satisfied: ${constraint##*:} requires that $name $PKG_INFO[$constraint]"
    fi
  fi
done

if $LIST_ONLY; then
  clean_exit
fi

if $ASK; then
  ans=y
  ask "[AUR] Continue?" ans
  if ! [ "$ans" = y -o "$ans" = Y -o "$ans" = YES -o "$ans" = Yes -o "$ans" = yes ]; then
    err "[AUR] Aborted by user"
    clean_exit 0
  fi
fi

# Fetch packages --------------------------
if ! $LOCAL_ONLY; then
  for p in "${AFFECTED_PKGS[@]}"; do
    fetch_package "$p"
  done
elif $DL_ONLY; then
  warn "[AUR] --offline and --download-only both given. Doing nothing. (Like --list-only)"
fi

if $DL_ONLY; then
  clean_exit
fi

# Add PKGBUILDs from cache
for p in "${AFFECTED_PKGS[@]}"; do
    if [ -z "$PKG_INFO[$p:From]" ]; then
      if [ -d "$AURDEST/$p" ]; then
        PKG_INFO[$p:From]="$AURDEST/$p"
      else
        pkg_failed "$p" 2 "[AUR] $p: Could not find PKGBUILD anywhere"
      fi
    fi
done

if (( ${#FAILED_PKGS} )); then
  warn "[AUR]: Failed to fetch packages (${#FAILED_PKGS}): ${FAILED_PKGS[*]}"
  AFFECTED_PKGS=(${AFFECTED_PKGS:|${FAILED_PKGS[@]}})
fi

# Build packages --------------------------
# Figure out build directory
tmpbuild="${TMPDIR-/tmp}/aur.sh.$$"
build="${BUILDDIR:-$tmpbuild}"
test -d "$build" || mkdir -p "$build" || throw 1 "Couldn't create build directory"

clean_exit() {
  rm "$build/aur.sh.running" 2>/dev/null || true
  [ -n "$SUDO_PROC" ] && kill $SUDO_PROC
  exit ${1-0}
}

trap clean_exit TERM
trap clean_exit INT
touch "$build/aur.sh.running"

test "$build" = "$PWD" || \
  msg "[AUR] Working in $build."

# Sudo
if $NEED_ROOT && $NOCONFIRM; then
  # Ask now
  msg "[AUR] Updating sudo timestamp"
  sudo -v
  # Keep up
  while true; do
    sleep 250
    sudo -vn
  done &
  SUDO_PROC=$!
fi

msg "[AUR] Makepkg args: ${makepkg_args[*]}"

# Build
for p in "${AFFECTED_PKGS[@]}"; do
  build_package "$p"
done


if (( ${#FAILED_PKGS} )); then
  warn "[AUR] All done, but some packages encountered errors (${#FAILED_PKGS}): ${FAILED_PKGS[*]}"
  clean_exit 255
fi

msg "[AUR] All Done!"


# Remove the builddir if we previously created it.
cd "$AURDEST"
if [ "$build" = "$tmpbuild" ]; then
  if $NOCLEAN; then
    msg "[AUR] Files in: $tmpbuild"
    warn "[AUR] Clean up later with aur.sh --clean"
  else
    warn "[AUR] Removing temporary directory $tmpbuild"
    rm -rf "$tmpbuild"
  fi
fi
clean_exit

