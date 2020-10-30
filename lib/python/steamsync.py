#!/usr/bin/env python3

import sys, os

import fnmatch
import re
import itertools
import functools
import operator
import shutil
import tarfile
import time

from pathlib import Path
from typing import Tuple, Dict, List, Union, Set, Callable, Any

from steamutil import Steam, App, CachedProperty, MalformedManifestError


### -----------------------------------------------------------------
#  Sync Abstractions
### -----------------------------------------------------------------
class SyncPath:
    """
    A SyncPath represents a pair of paths:
        local/common ; target/common
    Whereby target is the location being synched to and local is
      the prefix the data is synched from on the local machine.
    Common has components common to both paths.

    Usually, you'd set the local prefix and then the common part.
        e.g.: op.home.prefix(".my_game") / "Savegames"
            whereby "Savegames" is included in the resulting target
            path, but ".my_game" is not.

    Note that SyncPath should be considered immutable. Relevant
      methods return a new instance.
    """
    __slots__ = "op", "local", "common"

    op: 'AbstractSyncOp'
    local: Path
    common: Path

    def __init__(self, op, local, common="."):
        self.op = op
        self.local = Path(local)
        self.common  = Path(common)

    ## Change paths
    def prefix(self, component: Union[str, Path]) -> 'SyncPath':
        """ Return a new SyncPath that has a component prefixed to the local path """
        return SyncPath(self.op, self.local / component, self.common)

    def __truediv__(self, component: Union[str, Path]) -> 'SyncPath':
        """ Return a new SyncPath that nas a component added """
        return SyncPath(self.op, self.local, self.common / component)

    ## Retrieve paths
    @property
    def path(self) -> Path:
        """ Get the local path """
        return self.local / self.common

    def exists(self) -> bool:
        """ Chech whether local path exists """
        return self.path.exists()

    @property
    def target_path(self) -> Path:
        """ Get the sync target path """
        return self.op.target_path / self.common

    ## Begin a SyncSet
    def __enter__(self) -> 'SyncSet':
        return SyncSet(self)

    def __exit__(self, type, value, traceback):
        # Todo: auto-commit?
        pass


class _SyncSetCommon:
    def show_confirm(self, skip=True) -> bool:
        # XXX: move to SyncOp?
        print("  Local is newer: ", ", ".join(map(str, self.files_from_local)))
        print("  Target is newer: ", ", ".join(map(str, self.files_from_target)))
        print("  Unmodified: ", ", ".join(map(str, self.files_unmodified)))

        if skip and not self.files_from_local and not self.files_from_target:
            print("    \033[31mNoting to do!\033[0m")
            return False

        print("Continue? <Y/n> ", end="")
        resp = input().strip()
        if resp.lower() in ("y", "yes", ""):
            return True
        return False


class SyncSet(_SyncSetCommon):
    """
    A SyncSet represents a set of files to be synchronized
      from a local to a target location represented by a SyncPath
    """
    FileStatSet = Dict[Path, Tuple[Path, os.stat_result]]

    op: 'AbstractSyncOp'
    spath: SyncPath
    local: FileStatSet
    target: FileStatSet
    changeset: int
    backup_dir: str = "_backup"

    def __init__(self, path):
        self.op = path.op
        self.spath = path
        self.local = {}
        self.target = {}

    @property
    def path(self) -> Path:
        """ The local path """
        return self.spath.path

    @property
    def target_path(self) -> Path:
        """ The target path """
        return self.spath.target_path

    # Modify inclusion
    def _collect_files(self, anchor: Path, patterns: List[str]):
        files: SyncSet.FileStatSet = {}
        def add_file(f):
            if f.is_file():
                relative = f.relative_to(anchor)
                if relative.parts[0] == self.backup_dir:
                    return
                files[relative] = f, f.stat()
            elif f.is_dir():
                for f in f.iterdir():
                    add_file(f)
        for f in set(itertools.chain.from_iterable(anchor.glob(g) for g in patterns)):
            add_file(f)
        return files

    def add(self, *patterns):
        self.local.update(self._collect_files(self.path, patterns))
        self.target.update(self._collect_files(self.target_path, patterns))
        self._inval()

    def __iadd__(self, pattern: str) -> 'SyncSet':
        self.add(pattern)
        return self

    # Calculate changes
    def _inval(self):
        for cache in "files_from_local", "files_from_target", "files_unmodified":
            if cache in self.__dict__:
                del self.__dict__[cache]

    @staticmethod
    def _sync_set(src_files: FileStatSet, dst_files: FileStatSet) -> Set[Path]:
        """
        Return a set of files that need to be updated from src to dst.
        """
        return {f
                for f, (_, sst) in src_files.items()
                if f not in dst_files or sst.st_mtime > dst_files[f][1].st_mtime
        }

    @CachedProperty
    def files_from_local(self) -> Set[Path]:
        return self._sync_set(self.local, self.target)

    @CachedProperty
    def files_from_target(self) -> Set[Path]:
        return self._sync_set(self.target, self.local)

    @CachedProperty
    def files_unmodified(self) -> Set[Path]:
        return (self.local.keys() | self.target.keys()) - (self.files_from_local | self.files_from_target)

    def backup(self):
        if not self.files_from_local:
            print("    \033[35mBackup not needed\033[0m")
        else:
            backup_file = self.target_path / self.backup_dir / time.strftime("%Y%m%d_%H%M.tar.xz")
            print("    \033[35mBacking up to \033[36m%s\033[35m...\033[0m" % backup_file)

            backup_file.parent.mkdir(parents=True,exist_ok=True)
            with tarfile.open(backup_file, "x:xz") as tf:
                for name, (path, _) in self.target.items():
                    tf.add(path, name)

    def execute(self, *, make_inconsistent=False) -> bool:
        operations = []
        if self.files_from_local:
            if self.files_from_target and not make_inconsistent:
                self.op.report_error(["Both sides have changed files. Synchronizing would lead to inconsistent and possibly broken savegames."])
                return False
            operations += [(self.path / p, self.target_path / p) for p in self.files_from_local] #pylint:disable=not-an-iterable

        if self.files_from_target:
            operations += [(self.target_path / p, self.path / p) for p in self.files_from_target] #pylint:disable=not-an-iterable

        return self.op._do_copy(operations)


class SyncMultiSet(list, _SyncSetCommon):
    """ Provides a convenient interface to a number of SyncSets """
    def _union_set(self, attrname) -> Set[Path]:
        if not self:
            return set()
        return functools.reduce(operator.or_, map(operator.attrgetter(attrname), self))

    @property
    def files_from_local(self) -> Set[Path]:
        return self._union_set("files_from_local")
    
    @property
    def files_from_target(self) -> Set[Path]:
        return self._union_set("files_from_target")
    
    @property
    def files_unmodified(self) -> Set[Path]:
        return self._union_set("files_unmodified")
    
    def execute(self, *, make_inconsistent=False) -> bool:
        for sset in self:
            sset.execute(make_inconsistent=make_inconsistent)


### -----------------------------------------------------------------
#  Sync Operation
### -----------------------------------------------------------------
class AbstractSyncOp:
    parent: 'SteamSync'

    def __init__(self, parent: 'SteamSync'):
        self.parent = parent

    # Properties
    @property
    def name(self):
        """ Name of the app """
        raise NotImplementedError()

    @property
    def slug(self):
        """ Name of the destination folder """
        return self.name

    @slug.setter
    def slug(self, value: str):
        dict(self)["slug"] = value

    @property
    def target_path(self) -> Path:
        """ Full path to copy saves to """
        return self.parent.target_path / self.slug

    def __call__(self, func: Callable[['AbstractSyncOp'], Any]):
        # For decorator use
        self._report_begin()
        return func(self)

    # Actual Copy Logic
    @staticmethod
    def _do_copy(ops: List[Tuple[Path, Path]]) -> bool:
        for src, dst in ops:
            if not dst.parent.exists():
                dst.parent.mkdir(parents=True)

            print("   \033[36m%s -> %s\033[0m" % (src, dst))
            shutil.copy2(src, dst)
        return True

    # UI
    def _report_begin(self):
        print("\033[34mNow Synchronizing App \033[36m%s\033[34m (%s)\033[0m"
                % (self.name, self.__class__.__name__.replace("SyncOp", "")))

    def report_error(self, msg: List[str]):
        print("\033[31m"+"\n".join("  " + l for l in msg)+"\033[0m")

    # Start from here
    @property
    def home(self):
        return SyncPath(self, self.parent.home_path)

    @CachedProperty
    def my_documents(self) -> SyncPath:
        """ Get the Windows "My Documents" folder """
        if sys.platform == "win32":
            def get_my_documents():
                import ctypes.wintypes
                CSIDL_PERSONAL = 5       # My Documents
                SHGFP_TYPE_CURRENT = 0   # Get current, not default value

                buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
                ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)

                return buf.value
            return SyncPath(self, get_my_documents())
        else:
            raise RuntimeError("Platform has unknown My Documents location")

    def from_(self, path: Path) -> SyncPath:
        return SyncPath(self, path)


class GenericSyncOp(AbstractSyncOp):
    """ Generic Sync Operation for Non-Steam Apps """
    name: str = None

    def __init__(self, parent, name):
        super().__init__(parent)
        self.name = name


class SteamSyncOp(AbstractSyncOp):
    """ Sync Operation for Steam Apps """
    app: App

    def __init__(self, ssync, app):
        super().__init__(ssync)
        self.app = app

    ## Implement AbstractSyncOp
    @property
    def name(self):
        return self.app.name

    @property
    def slug(self):
        return self.app.install_dir

    ## Addidtional information available through Steam
    @property
    def game_directory(self) -> SyncPath:
        return SyncPath(self, self.app.install_path)

    @CachedProperty
    def my_documents(self) -> SyncPath:
        if sys.platform.startswith("linux"):
            # TODO: what about native games?
            return SyncPath(self, self.app.compat_drive / "users/steamuser/My Documents")
        else:
            return super().my_documents

    @property
    def user_home(self) -> SyncPath:
        return SyncPath(self, self.parent.home_path)

    ## Steam Cloud
    def steam_cloud_ufs(self) -> SyncMultiSet:
        if "ufs" not in self.app.appinfo["appinfo"] or "savefiles" not in self.app.appinfo["appinfo"]["ufs"]:
            raise ValueError("%r doesn't support Steam Cloud by way of UFS" % self.app)
        sms = SyncMultiSet()

        if sys.platform.startswith("win") or self.app.is_proton_app:
            ufs_platform = "Windows"
        elif sys.platform.startswith("linux"):
            ufs_platform = "Linux"
        else:
            raise NotImplementedError("Steam Cloud UFS not (yet) supported on platform %s" % sys.platform)

        for ufs_def in self.app.appinfo["appinfo"]["ufs"]["savefiles"].values():
            # Filter by platform
            if "platforms" in ufs_def and ufs_platform not in ufs_def["platforms"].values():
                continue

            # Find root anchor
            root = ufs_def["root"]
            if root == "WinMyDocuments":
                path = self.my_documents
            elif root in ("LinuxHome", "MacHome"):
                path = self.user_home
            else:
                raise NotImplementedError("Steam Cloud UFS root %s not implemented for %r" % (root, self.app))

            # Add relative path
            # XXX: Should path be prefixed or included in the target. Are there even apps with multiple ufs entries?
            # For now, take last component?
            if "path" in ufs_def and ufs_def["path"]:
                rpath = Path(ufs_def["path"])
                if rpath.anchor:
                    # Fix paths with leading slash/backslash XXX: is this valid?
                    rpath = rpath.relative_to(rpath.anchor)
                if len(rpath.parts) > 1:
                    path = path.prefix(rpath.parent)
                path /= rpath.name

            # Add files by pattern
            sset = SyncSet(path)
            sset.add(ufs_def["pattern"])
            # XXX: what about platform and recursive keys?
            sms.append(sset)

        return sms


class SyncNoOp:
    """ No-Op Sync Operation """
    def __call__(self, func) -> None:
        pass

    def __bool__(self) -> bool:
        return False

AppNotFound = SyncNoOp()


### -----------------------------------------------------------------
#  Main Sync manager class
### -----------------------------------------------------------------
class SteamSync:
    target_path: Path
    steam: Steam
    home_path: Path

    def __init__(self, target_path: Path, *, steam_path: Path = None):
        self.target_path = Path(target_path)
        self.steam = Steam(steam_path)
        self.home_path = Path.home()

    # Get Information
    @CachedProperty
    def apps(self) -> List[App]:
        return list(self.steam.apps)

    # Get Sync Operation for a specific App
    def by_id(self, appid):
        """ Steam App by AppID """
        app = self.steam.get_app(appid)
        if app is not None:
            return SteamSyncOp(self, app)
        else:
            return AppNotFound

    def by_name(self, pattern):
        """ Steam App by Name """
        pt = re.compile(fnmatch.translate(pattern).rstrip("\\Z"), re.IGNORECASE)
        app = None
        for candidate in self.apps: #pylint:disable=not-an-iterable
            if pt.search(candidate.name):
                if app is not None:
                    raise Exception("Encountered more than one possible App matching '%s'" % pattern)
                app = candidate
        if app is None:
            return AppNotFound
        return SteamSyncOp(self, app)

    def generic(self, name, *, platform=None):
        """ Non-Steam App """
        if platform is not None and platform not in sys.platform:
            return AppNotFound
        return GenericSyncOp(self, name)
