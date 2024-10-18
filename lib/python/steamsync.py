#!/usr/bin/env python3

import sys
import os
import fnmatch
import re
import itertools
import functools
import operator
import shutil
import tarfile
import time

from abc import ABCMeta, abstractmethod
from copy import copy
from getpass import getuser
from pathlib import PurePath, Path
from typing import Iterable, Tuple, Dict, List, Union, Set, Callable, Any, Optional, TypeVar, Generic, Sequence, overload, Literal, TypedDict
from warnings import warn

from propex import SettableCachedProperty, cached_property
from steamutil import Steam, App


### -----------------------------------------------------------------
#  Clone Abstraction
### -----------------------------------------------------------------
_Clone = TypeVar("_Clone", bound="Cloneable")

class Cloneable:
    __slots__ = ()

    def clone(self: _Clone, **update) -> _Clone:
        # XXX: Implement directly?
        obj = copy(self)
        for k, v in update.items():
            setattr(obj, k, v)
        return obj


### -----------------------------------------------------------------
#  Sync Abstractions
### -----------------------------------------------------------------
PathOrStr = Union[PurePath, os.PathLike, str]
_SyncPath = TypeVar("_SyncPath", bound="SyncPath")


class ISyncContext:
    target_path: Path


class ISyncOp(metaclass=ABCMeta):
    parent: ISyncContext

    @property
    @abstractmethod
    def target_path(self) -> Path: ...

    @abstractmethod
    def _do_copy(self, ops: List[Tuple[Path, Path]]) -> bool: ...

    @abstractmethod
    def report_error(self, msg: Sequence[str]): ...


class SyncPath(Cloneable):
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

    op: ISyncOp
    local: Path
    common: PurePath

    def __init__(self, op: ISyncOp, local: PathOrStr, common: PathOrStr="."):
        self.op = op
        self.local = Path(local)
        self.common = PurePath(common)

    @property
    def path(self) -> Path:
        return Path(self.local, self.common)

    def exists(self) -> bool:
        """ Chech whether local path exists """
        return self.path.exists()

    ## Change paths
    def prefix(self: _SyncPath, component: PathOrStr) -> _SyncPath:
        """ Return a new SyncPath that has a component prefixed to the local path """
        return self.clone(local=self.local/component)

    def __truediv__(self: _SyncPath, component: PathOrStr) -> _SyncPath:
        """ Return a new SyncPath that nas a component added """
        return self.clone(common=self.common/component)

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


class _SyncSetCommon(metaclass=ABCMeta):
    @property
    @abstractmethod
    def files_from_local(self) -> Set[Path]: ...
    @property
    @abstractmethod
    def files_from_target(self) -> Set[Path]: ...
    @property
    @abstractmethod
    def files_unmodified(self) -> Set[Path]: ...

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

    @abstractmethod
    def commit(self, *, make_inconsistent=False) -> bool: ...

    def execute(self, *, make_inconsistent=False) -> bool:
        warn("SyncSet.execute() was renamed to commit()", DeprecationWarning)
        return self.commit(make_inconsistent=make_inconsistent)


class SyncSet(_SyncSetCommon):
    """
    A SyncSet represents a set of files to be synchronized
      from a local to a target location represented by a SyncPath
    """
    FileStatSet = Dict[Path, Tuple[Path, os.stat_result]]

    op: ISyncOp
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

    @cached_property
    def files_from_local(self) -> Set[Path]:
        return self._sync_set(self.local, self.target)

    @cached_property
    def files_from_target(self) -> Set[Path]:
        return self._sync_set(self.target, self.local)

    @cached_property
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

    def commit(self, *, make_inconsistent=False) -> bool:
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
    ### XXX: Is this safe with how files_* do relative paths??
    def _union_set(self, attrname) -> Set[Path]:
        if not self:
            return set()
        return functools.reduce(operator.or_, map(operator.attrgetter(attrname), self))

    @cached_property
    def files_from_local(self) -> Set[Path]:
        return self._union_set("files_from_local")

    @cached_property
    def files_from_target(self) -> Set[Path]:
        return self._union_set("files_from_target")

    @cached_property
    def files_unmodified(self) -> Set[Path]:
        return self._union_set("files_unmodified")

    def commit(self, *, make_inconsistent=False) -> bool:
        res = True
        for sset in self:
            res = res and sset.execute(make_inconsistent=make_inconsistent)
        return res


### -----------------------------------------------------------------
#  Common Paths
### -----------------------------------------------------------------
P = TypeVar('P', Path, SyncPath)

class AbstractCommonPaths:
    class Common(Generic[P], metaclass=ABCMeta):
        ## Abstract
        @abstractmethod
        def _path_factory(self, path: PathOrStr) -> P: pass

        ## Platform
        is_wine: bool
        is_windows: bool
        is_native_windows: bool
        is_native_linux: bool

        ## Common paths
        @property
        def home(self) -> P:
            return self._path_factory(Path.home())

        def from_(self, path: PathOrStr) -> P:
            return self._path_factory(path)

    class WindowsCommon(Common[P]):
        is_windows: bool = True
        is_native_linux: bool = False

        # abstract attribute
        @property
        @abstractmethod
        def drive_c(self) -> P: ...

        @property
        @abstractmethod
        def my_documents(self) -> P: ...

        @property
        @abstractmethod
        def appdata_roaming(self) -> P: ...

    class Windows(WindowsCommon[P]):
        is_native_windows: bool = True
        is_wine: bool = False

        @property
        def drive_c(self) -> P:
            return self._path_factory("C:\\")

        # Win32 API
        CSIDL_PERSONAL  = 0x0005
        CSIDL_APPDATA   = 0x001a

        @staticmethod
        def SHGetFolderPath(csidl: int) -> str:
            import ctypes.wintypes
            SHGFP_TYPE_CURRENT = 0   # Get current, not default value
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            shell32 = ctypes.windll.shell32 # type: ignore[attr-defined] # Windows only
            shell32.SHGetFolderPathW(None, csidl, None, SHGFP_TYPE_CURRENT, buf)
            return buf.value

        @cached_property
        def my_documents(self) -> P:
            """ Get the Windows "My Documents" folder """
            return self._path_factory(self.SHGetFolderPath(self.CSIDL_PERSONAL))

        @cached_property
        def appdata_roaming(self) -> P:
            return self._path_factory(self.SHGetFolderPath(self.CSIDL_APPDATA))

    class Wine(WindowsCommon[P]):
        is_native_windows: bool = False
        is_wine: bool = True
        _wine_prefix: Path

        def __init__(self, *, prefix, **kwds):
            super().__init__(**kwds)
            self._wine_prefix = prefix

        @property
        def wine_prefix(self) -> P:
            return self._path_factory(self._wine_prefix)

        @property
        def drive_c(self) -> P:
            return self._path_factory(self._wine_prefix / "drive_c")

        @overload
        @staticmethod
        def _find_file_ci(path: Path, candidates: Sequence[str], exclude: None=None) -> List[Path]: ...
        @overload
        @staticmethod
        def _find_file_ci(path: Path, candidates: None, exclude: Sequence[str]) -> List[Path]: ...
        @overload
        @staticmethod
        def _find_file_ci(path: Path, candidates: Sequence[str], exclude: Sequence[str]) -> List[Path]: ...

        @staticmethod
        def _find_file_ci(path: Path, candidates: Optional[Sequence[str]]=None, exclude: Optional[Sequence[str]]=None) -> List[Path]:
            """ Find directory entry with casefolding
            Note: candidates must already be lowercase """
            if not path.exists():
                return []
            entries: Dict[str, Path] = {p.name.lower(): p for p in path.iterdir() if p.is_dir()}
            results: List[Path] = []
            if candidates is not None:
                def gen():
                    for name in candidates:
                        p = entries.get(name)
                        if p is not None:
                            yield p
                results.extend(gen())
            if exclude is not None:
                results.extend((path for name, path in entries.items() if name not in exclude and path not in results))
            return results

        @cached_property
        def _wine_prefix_userprofile(self) -> Path:
            ## Try to find out the username in the prefix
            ## usually, this is the same as the system user, but
            ## e.g. Proton always uses 'steamuser'
            # XXX: make user name configurable or at least cache it?
            # BUG: mypy#7781 overload staticmethod is broken when called on instance
            candidates =  self.__class__._find_file_ci(self._wine_prefix / "drive_c" / "users", [getuser().lower(), 'steamuser'], ['public'])
            if not candidates:
                raise FileNotFoundError(f"Could not detect userprofile path in wine prefix {self.wine_prefix}")
            # XXX: be smarter?
            return candidates[0]

        @property
        def home(self) -> P:
            return self._path_factory(self._wine_prefix_userprofile)

        @cached_property
        def my_documents(self) -> P:
            """ Get the Windows "My Documents" folder """
            candidates = self._find_file_ci(self._wine_prefix_userprofile, ['my documents', 'documents'])
            if not candidates:
                raise FileNotFoundError(f"Could not find 'My Documents' folder in profile at '{self._wine_prefix_userprofile}'")
            return self._path_factory(candidates[0])

        @cached_property
        def appdata_roaming(self) -> P:
            candidates = self._find_file_ci(self._wine_prefix_userprofile, ['appdata', 'application data'])
            if not candidates:
                raise FileNotFoundError(f"Could not find 'AppData/Roaming' folder in profile at '{self._wine_prefix_userprofile}'")
            for candidate in candidates:
                roaming = self._find_file_ci(candidate, ['roaming'])
                if roaming:
                    return self._path_factory(roaming[0])
            return self._path_factory(candidates[0])

    class Linux(Common[P]):
        is_native_linux: bool = True
        is_native_windows: bool = False
        is_windows: bool = False
        is_wine: bool = False

        ## XDG
        # XXX: make it methods and search all locations?
        @cached_property
        def xdg_config_dir(self) -> P:
            raise NotImplementedError()

        @cached_property
        def xdg_data_dir(self) -> P:
            raise NotImplementedError()


class CommonPaths:
    class Mixin(AbstractCommonPaths.Common[Path]):
        def _path_factory(self, p: PathOrStr) -> Path:
            return Path(p)

    class LinuxPaths(AbstractCommonPaths.Linux[Path], Mixin):
        pass
    class WindowsPaths(AbstractCommonPaths.Windows[Path], Mixin):
        pass
    class WinePaths(AbstractCommonPaths.Wine[Path], Mixin):
        pass

    Paths = Union[LinuxPaths, WindowsPaths, WinePaths]
    NativePaths = Union[LinuxPaths, WindowsPaths]

    @overload
    @classmethod
    def create(c, wine_prefix: None) -> NativePaths: ...
    @overload
    @classmethod
    def create(c, wine_prefix: Path) -> WinePaths: ...

    @classmethod
    def create(c, wine_prefix: Optional[Path]=None) -> Paths:
        if wine_prefix is not None:
            return c.WinePaths(prefix=wine_prefix)
        elif sys.platform == 'win32':
            return c.WindowsPaths()
        else:
            return c.LinuxPaths()


class CommonSyncPaths:
    class Mixin(AbstractCommonPaths.Common[SyncPath]):
        op: 'AbstractSyncOp'

        def __init__(self, *, op: 'AbstractSyncOp', **kwds):
            # Not sure why this complains. Maybe because of the **kwds?
            super().__init__(**kwds) #type: ignore
            self.op = op

        def _path_factory(self, p: PathOrStr) -> SyncPath:
            return SyncPath(self.op, p)

    class LinuxPaths(AbstractCommonPaths.Linux[SyncPath], Mixin):
        pass
    class WindowsPaths(AbstractCommonPaths.Windows[SyncPath], Mixin):
        pass
    class WinePaths(AbstractCommonPaths.Wine[SyncPath], Mixin):
        pass

    Paths = Union[LinuxPaths, WindowsPaths, WinePaths]

    @classmethod
    def create(c, op: 'AbstractSyncOp', wine_prefix: Optional[Path]) -> Paths:
        if wine_prefix is not None:
            return c.WinePaths(op=op, prefix=wine_prefix)
        elif sys.platform == 'win32':
            return c.WindowsPaths(op=op)
        else:
            return c.LinuxPaths(op=op)


### -----------------------------------------------------------------
#  Steam autocloud UFS
### -----------------------------------------------------------------
class SteamUfs:
    # Schema
    Platform = Literal["windows", "linux", "macos", "all"]
    Root = Literal["gameinstall", "LinuxHome", "LinuxXdgDataHome", "MacHome", "WinMyDocuments", "WinAppDataRoaming", "WinAppDataLocal"]

    class Entry(TypedDict, total=False):
        platforms: dict[int, 'SteamUfs.Platform']
        root: 'SteamUfs.Root'
        path: str
        pattern: str
        siblings: str # ??? ref: #220
        recursive: bool # ???

    class Override(TypedDict):
        platforms: dict[int, 'SteamUfs.Platform']
        oldroot: 'SteamUfs.Root'
        newroot: 'SteamUfs.Root'
        path: str
        replace: bool

    class Ufs(TypedDict, total=False):
        quota: int
        maxnumfiles: int
        hidecloudui: int
        ignoreexternalfiles: int
        savefiles: dict[int, 'SteamUfs.Entry']

    # Context
    user_id: int
    paths: CommonSyncPaths.Paths

    def __init__(self, paths: CommonSyncPaths.Paths, user_id: int=0):
        self.user_id = user_id
        self.paths = paths

    steam3_types = 'IUMGAPCgT a' # https://developer.valvesoftware.com/wiki/SteamID#Types_of_Steam_Accounts
    @property
    def user_id_steam3(self) -> str:
        account = self.user_id & 0xFFFFFFFF
        type = self.steam3_types[self.user_id >> 52 & 0xF]
        universe = self.user_id >> 56
        return f"[{type}:{universe}:{account}]"

    @property
    def ufs_platform(self) -> Platform:
        if self.paths.is_windows:
            return "windows"
        elif self.paths.is_native_linux:
            return "linux"
        raise NotImplementedError()

    # Path placeholders
    path_subst_vars = {
        "64BitSteamID": lambda self: str(self.user_id),
        "Steam3AccountID": lambda self: self.user_id_steam3,
    }
    path_subst_expr = re.compile(fr'\{{({"|".join(path_subst_vars.keys())})\}}')

    def path_subst(self, path: str) -> str:
        return self.path_subst_expr.sub(lambda m: self.path_subst_vars[m.group(1)](self), path)

    # Resolution
    def eval_entry(self, entry: Entry, gameinstall: SyncPath) -> Optional[SyncSet]:
        # Filter by platform
        if "platforms" in entry:
            platforms = [platform.lower() for platform in entry["platforms"].values()]
            if "all" not in platforms and self.ufs_platform not in platforms:
                return None

        # Find root anchor
        root = entry["root"]
        if root == "gameinstall":
            path = gameinstall
        elif root in ("LinuxHome", "MacHome"):
            path = self.paths.home
        elif isinstance(self.paths, AbstractCommonPaths.WindowsCommon):
            if root == "WinMyDocuments":
                path = self.paths.my_documents
            elif root == "WinAppDataRoaming":
                path = self.paths.appdata_roaming
        else:
            raise NotImplementedError("Steam Cloud UFS root %s not implemented on %s" % (root, self.paths.__class__.__name__))

        # Add relative path
        # XXX: Should path be prefixed or included in the target. Are there even apps with multiple ufs entries?
        # For now, take last component?
        if "path" in entry and entry["path"]:
            rpath = Path(self.path_subst(entry["path"]))
            if rpath.anchor:
                # Fix paths with leading slash/backslash XXX: is this valid?
                rpath = rpath.relative_to(rpath.anchor)
            if len(rpath.parts) > 1:
                path = path.prefix(rpath.parent)
            path /= rpath.name

        # Add files by pattern
        sset = SyncSet(path)
        sset.add(entry["pattern"])

        # XXX: what about siblings and recursive keys?
        return sset

    def eval(self, ufs: Ufs, gameinstall: SyncPath) -> SyncMultiSet:
        sms = SyncMultiSet()

        for entry in ufs.get("savefiles", {}).values():
            ss = self.eval_entry(entry, gameinstall)

            if ss is not None:
                sms.append(ss)

        return sms


### -----------------------------------------------------------------
#  Sync Operation
### -----------------------------------------------------------------
_AbstractSyncOp = TypeVar("_AbstractSyncOp", bound="AbstractSyncOp")


class AbstractSyncOp(ISyncOp):
    parent: ISyncContext
    name: str # Abstract

    def __init__(self, parent: ISyncContext):
        self.parent = parent

    # Paths
    @cached_property
    def paths(self) -> CommonSyncPaths.Paths:
        return CommonSyncPaths.create(self, None)

    def __getattr__(self, name):
        return getattr(self.paths, name)

    # Properties
    @SettableCachedProperty
    def slug(self) -> str:
        """ Name of the destination folder """
        return self.name

    @property
    def target_path(self) -> Path:
        """ Full path to copy saves to """
        return self.parent.target_path / self.slug

    def __call__(self: _AbstractSyncOp, func: Callable[[_AbstractSyncOp], Any]):
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

    def report_error(self, msg: Iterable[str]):
        print("\033[31m"+"\n".join("  " + ln for ln in msg)+"\033[0m")


class SteamSyncOp(AbstractSyncOp):
    """ Sync Operation for Steam Apps """
    app: App

    def __init__(self, ssync, app):
        super().__init__(ssync)
        self.app = app

    @cached_property
    def paths(self) -> CommonSyncPaths.Paths:
        return CommonSyncPaths.create(self, self.app.compat_prefix if self.app.is_proton_app else None)

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

    ## Steam Cloud
    def steam_cloud_ufs(self) -> SyncMultiSet:
        if "ufs" not in self.app.appinfo["appinfo"] or "savefiles" not in self.app.appinfo["appinfo"]["ufs"]:
            raise ValueError("%r doesn't support Steam Cloud by way of UFS" % self.app)

        ufs = SteamUfs(self.paths, self.app.steam.most_recent_user.id) # FIXME: Specify user ID
        return ufs.eval(self.app.appinfo["appinfo"]["ufs"], self.game_directory)


class GenericSyncOp(AbstractSyncOp):
    """ Generic Sync Operation for Non-Steam Apps """

    def __init__(self, parent, name):
        super().__init__(parent)
        self.name = name


class GenericFoundSyncOp(GenericSyncOp):
    _found: Path

    def __init__(self, parent, name, found: Path):
        super().__init__(parent, name)
        self._found = found

    @property
    def found(self) -> SyncPath:
        return SyncPath(self, self._found)


class WineSyncOp(GenericFoundSyncOp):
    _wine_prefix: Path

    def __init__(self, parent, name, prefix: Path, found: Path):
        super().__init__(parent, name, found)
        self._wine_prefix = prefix

    @cached_property
    def paths(self) -> CommonSyncPaths.Paths:
        return CommonSyncPaths.create(self, self._wine_prefix)


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
class NoSteamSync(ISyncContext):
    target_path: Path

    def __init__(self, target_path: Path):
        self.target_path = Path(target_path)

    @cached_property
    def paths(self) -> CommonPaths.NativePaths:
        return CommonPaths.create(None)

    def generic(self, name, find: Optional[Callable[[CommonPaths.NativePaths], Path]], *, platform=None) -> Union[GenericSyncOp, SyncNoOp]:
        """ Non-Steam App """
        if platform is None or platform in sys.platform:
            if find is None:
                return GenericSyncOp(self, name)
            search_path = find(self.paths)
            if search_path.exists():
                return GenericFoundSyncOp(self, name, search_path)
        return AppNotFound

    def wine(self, name, prefixes: Sequence[PathOrStr], find: Callable[[CommonPaths.Paths], Path]) -> Union[WineSyncOp, GenericFoundSyncOp, SyncNoOp]:
        """
        Works the same as .generic() on Windows, but additionally searches any number of Wine-Prefixes when not running on Windows
        """
        if sys.platform == 'win32':
            search_path = find(self.paths)
            if search_path.exists():
                return GenericFoundSyncOp(self, name, search_path)
        else:
            for prefix in prefixes:
                prefixpath = Path(prefix)
                if not prefixpath.exists():
                    continue
                paths = CommonPaths.create(prefixpath)
                search_path = find(paths)
                if search_path.exists():
                    return WineSyncOp(self, name, prefixpath, search_path)
        return AppNotFound


class SteamSync(NoSteamSync):
    steam: Steam

    def __init__(self, target_path: Path, *, steam_path: Optional[Path] = None):
        super().__init__(target_path)
        self.steam = Steam(steam_path)

    # Get Information
    @cached_property
    def apps(self) -> List[App]:
        return list(self.steam.apps)

    # Get Sync Operation for a specific App
    def by_id(self, appid: int) -> Union[SteamSyncOp, SyncNoOp]:
        """ Steam App by AppID """
        app = self.steam.get_app(appid)
        if app is not None:
            return SteamSyncOp(self, app)
        else:
            return AppNotFound

    def by_name(self, pattern: str) -> Union[SteamSyncOp, SyncNoOp]:
        """ Steam App by Name """
        pt = re.compile(fnmatch.translate(pattern).rstrip("\\Z"), re.IGNORECASE)
        app = None
        for candidate in self.apps:
            if pt.search(candidate.name):
                if app is not None:
                    raise Exception("Encountered more than one possible App matching '%s'" % pattern)
                app = candidate
        if app is None:
            return AppNotFound
        return SteamSyncOp(self, app)
