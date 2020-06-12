#!/usr/bin/env python3

import sys, os

import fnmatch
import re
import itertools
import shutil

from pathlib import Path
from typing import Tuple, Dict, List, Union, Set, Callable, Any

from steamutil import Steam, App, CachedProperty


class AppNotFoundType:
    def __call__(self, func) -> None:
        pass

    def __bool__(self) -> bool:
        return False

AppNotFound = AppNotFoundType()


class SyncPath:
    __slots__ = "op", "local", "common"

    op: 'SyncOp'
    local: Path
    common: Path

    def __init__(self, op, local, common="."):
        self.op = op
        self.local = Path(local)
        self.common  = Path(common)
    
    def prefix(self, component: Union[str, Path]) -> 'SyncPath':
        return SyncPath(self.op, self.local / component, self.common)
    
    def __div__(self, component: Union[str, Path]) -> 'SyncPath':
        return SyncPath(self.op, self.local, self.common / component)
    
    @property
    def path(self) -> Path:
        return self.local / self.common
    
    @property
    def target_path(self) -> Path:
        return self.op.target_path / self.common
    
    def __enter__(self) -> 'SyncSet':
        return SyncSet(self)
    
    def __exit__(self, type, value, traceback):
        # Todo: auto-commit?
        pass


class SyncSet:
    FileStatSet = Dict[Path, Tuple[Path, os.stat_result]]

    op: 'SyncOp'
    spath: SyncPath
    local: FileStatSet
    target: FileStatSet
    changeset: int

    def __init__(self, path):
        self.op = path.op
        self.spath = path
        self.local = {}
        self.target = {}
    
    @property
    def path(self) -> Path:
        return self.spath.path
    
    @property
    def target_path(self) -> Path:
        return self.spath.target_path

    # Modify inclusion
    @staticmethod
    def _collect_files(anchor: Path, patterns: List[str]):
        files: SyncSet.FileStatSet = {}
        def add_file(f):
            if f.is_file():
                files[f.relative_to(anchor)] = f, f.stat()
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
    
    def show_confirm(self) -> bool:
        # XXX: move to SyncOp?
        print("  Local is newer: ", ", ".join(map(str, self.files_from_local)))
        print("  Target is newer: ", ", ".join(map(str, self.files_from_target)))
        print("  Unmodified: ", ", ".join(map(str, self.files_unmodified)))

        print("Press enter to continue")
        input()
        return True # TODO: Proper thingey

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


class SyncOp:
    parent: 'SteamSync'
    app: App

    def __init__(self, ssync, app):
        self.parent = ssync
        self.app = app
    
    def __call__(self, func: Callable[['SyncOp'],Any]):
        # For decorator use
        self._report_begin()
        return func(self)

    def _do_copy(self, ops: List[Tuple[Path, Path]]) -> bool:
        for src, dst in ops:
            if not dst.parent.exists():
                dst.parent.mkdir(parents=True)

            print("   \033[36m%s -> %s\033[0m" % (src, dst))
            shutil.copy2(src, dst)
        return True
    
    # UI
    def _report_begin(self):
        print("\033[34mNow Synchronizing App %s\033[0m" % self.app.name)

    def report_error(self, msg: List[str]):
        print("\033[31m"+"\n".join("  " + l for l in msg)+"\033[0m")
    
    @CachedProperty
    def target_path(self) -> Path:
        return self.parent.target_path / self.app.install_dir
    
    @CachedProperty
    def my_documents(self) -> SyncPath:
        """ Get the Windows "My Documents" folder """
        if sys.platform.startswith("linux"):
            # TODO: what about native games?
            return SyncPath(self, self.app.compat_drive / "users/steamuser/My Documents")
        elif sys.platform == "win32":
            def get_my_documents():
                import ctypes.wintypes
                CSIDL_PERSONAL = 5       # My Documents
                SHGFP_TYPE_CURRENT = 0   # Get current, not default value

                buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
                ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)

                return buf.value
            return SyncPath(self, get_my_documents())
        else:
            raise Exception("Platform not supported")
    
    @property
    def game_directory(self) -> SyncPath:
        return SyncPath(self, self.app.install_path)
    
    def from_(self, path: Path) -> SyncPath:
        return SyncPath(self, path)


class SteamSync:
    target_path: Path
    steam: Steam

    def __init__(self, target_path: Path, *, steam_path: Path = None):
        self.target_path = Path(target_path)
        self.steam = Steam(steam_path)
    
    @CachedProperty
    def apps(self) -> List[App]:
        return list(self.steam.apps)
    
    def by_id(self, appid):
        app = self.steam.get_app(appid)
        if app is not None:
            return SyncOp(self, app)
        else:
            return AppNotFound
    
    def by_name(self, pattern):
        pt = re.compile(fnmatch.translate(pattern).rstrip("\\Z"), re.IGNORECASE)
        app = None
        for candidate in self.apps: #pylint:disable=not-an-iterable
            if pt.search(candidate.name):
                if app is not None:
                    raise Exception("Encountered more than one possible App matching '%s'" % pattern)
                app = candidate
        return SyncOp(self, app)
