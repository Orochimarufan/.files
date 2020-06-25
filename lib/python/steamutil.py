# Discover Steam install and games
# (c) 2020 Taeyeon Mori CC-BY-SA

import sys, os
import re, fnmatch, datetime

from pathlib import Path
from typing import List, Iterable, Dict, Tuple, Callable, Optional, Union

from vdfparser import VdfParser, DeepDict


class CachedProperty:
    """ A property that is only computed once per instance and then replaces
        itself with an ordinary attribute. Deleting the attribute resets the
        property.

        Source: https://github.com/bottlepy/bottle/commit/fa7733e075da0d790d809aa3d2f53071897e6f76
        """

    def __init__(self, func):
        self.__doc__ = getattr(func, '__doc__')
        self.func = func

    def __get__(self, obj, cls):
        if obj is None:
            return self
        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value


class DictPathRoProperty:
    __slots__ = "property", "path", "default"
    _nodefault = object()

    def __init__(self, property: str, path: Tuple[str], default=_nodefault):
        self.property = property
        self.path = path
        self.default = default
    
    def __get__(self, obj, cls):
        if obj is None:
            return self
        d = getattr(obj, self.property)
        try:
            for pc in self.path:
                d = d[pc]
        except KeyError:
            if self.default is not self._nodefault:
                return self.default
            raise
        else:
            return d


class DictPathProperty(DictPathRoProperty):
    __slots__ = ()

    def _get_create_parent(self, obj) -> Dict:
        d = getattr(obj, self.property)
        for pc in self.path[:-1]:
            try:
                d = d[pc]
            except KeyError:
                nd = {}
                d[pc] = nd
                d = nd
        return d

    def __set__(self, obj, value):
        self._get_create_parent(obj)[self.path[-1]] = value
    
    def __delete__(self, obj):
        del self._get_create_parent(obj)[self.path[-1]]


_vdf = VdfParser()


class MalformedManifestError(Exception):
    @property
    def filename(self):
        return self.args[1]


class App:
    steam: 'Steam'
    library_folder: 'LibraryFolder'
    steamapps_path: Path
    manifest_path: Path
    manifest: DeepDict

    def __init__(self, libfolder, manifest_path: Path, *, manifest_data=None):
        self.steam = libfolder.steam
        self.library_folder = libfolder
        self.steamapps_path = libfolder.steamapps_path

        self.manifest_path = manifest_path
        if manifest_data is None:
            with open(manifest_path) as f:
                self.manifest = _vdf.parse(f)
        else:
            self.manifest = manifest_data

        if "AppState" not in self.manifest:
            raise MalformedManifestError("App manifest doesn't have AppState key", self.manifest_path)
    
    def __repr__(self):
        return "<steamutil.App %d '%s' @ \"%s\">" % (self.appid, self.name, self.install_path)
    
    # Basic info
    @property
    def appid(self) -> int:
        return int(self.manifest["AppState"]["appid"])

    name  = DictPathRoProperty("manifest", ("AppState", "name"))
    language = DictPathRoProperty("manifest", ("AppState", "UserConfig", "language"), None)
    install_dir = DictPathRoProperty("manifest", ("AppState", "installdir"))
    
    @CachedProperty
    def install_path(self) -> Path:
        return self.steamapps_path / "common" / self.install_dir
    
    def get_userdata_path(self, user_id: Union[int, 'LoginUser']) -> Path:
        return self.steam.get_userdata_path(user_id) / str(self.appid)
    
    # Workshop
    # TODO
    @CachedProperty
    def workshop_path(self) -> Path:
        return self.steamapps_path / "workshop" / "content" / str(self.appid)

    # Steam Play info
    @CachedProperty
    def compat_path(self) -> Path:
        return self.steamapps_path / "compatdata" / str(self.appid)
    
    @CachedProperty
    def compat_drive(self) -> Path:
        return self.compat_path / "pfx" / "drive_c"
    
    # Install size
    declared_install_size = DictPathRoProperty("manifest", ("AppState", "SizeOnDisk"), 0)
    
    def compute_install_size(self) -> int:
        def sum_size(p: Path):
            acc = 0
            for x in p.iterdir():
                if x.is_dir():
                    acc += sum_size(x)
                else:
                    acc += x.stat().st_size
            return acc
        return sum_size(self.install_path)


class LibraryFolder:
    steam: 'Steam'
    path: Path

    def __init__(self, steam: 'Steam', path: Path):
        self.steam = steam
        self.path = path
    
    def __repr__(self):
        return "<steamutil.LibraryFolder @ \"%s\">" % self.path

    # Paths
    @CachedProperty
    def steamapps_path(self) -> Path:
        steamapps = self.path / "steamapps"
        if not steamapps.exists():
            # Emulate case-insensitivity
            cased = self.path / "SteamApps"
            if cased.exists():
                steamapps = cased
            else:
                # try to find other variation
                found = [d for d in self.path.iterdir() if d.is_dir() and d.name.lower() == "steamapps"]
                if len(found) > 1:
                    raise Exception("More than one steamapps folder in library folder", self.path)
                elif found:
                    return found[0]
            # if none exists, return non-existant default name
        return steamapps
    
    @property
    def common_path(self) -> Path:
        return self.steamapps_path / "common"

    @property
    def appmanifests(self) -> Iterable[Path]:
        return self.steamapps_path.glob("appmanifest_*.acf") # pylint:disable=no-member

    @property
    def apps(self) -> Iterable[App]:
        for mf in self.appmanifests:
            try:
                yield App(self, mf)
            except MalformedManifestError as e:
                print("Warning: Malformed app manifest:", e.filename)

    def get_app(self, appid: int) -> Optional[App]:
        manifest = self.steamapps_path / ("appmanifest_%d.acf" % appid)
        if manifest.exists():
            return App(self, manifest)

    def find_apps_re(self, regexp: str) -> Iterable[App]:
        reg = re.compile(r'"name"\s+".*%s.*"' % regexp, re.IGNORECASE)
        for manifest in self.appmanifests: #pylint:disable=not-an-iterable
            with open(manifest) as f:
                content = f.read()
            if reg.search(content):
                yield App(self, manifest, manifest_data=_vdf.parse_string(content))

    def find_apps(self, pattern: str) -> Iterable[App]:
        return self.find_apps_re(fnmatch.translate(pattern).rstrip("\\Z"))


class UserAppConfig:
    user: 'LoginUser'
    appid: int

    def __init__(self, user, appid):
        self.user = user
        self.appid = appid
    
    def __repr__(self):
        return "<steamutil.UserAppConfig appid=%d for account %s>" % (self.appid, self.user.account_name)
    
    @property
    def _data(self):
        try:
            return self.user.localconfig["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["Apps"][str(self.appid)]
        except KeyError:
            return {} # TODO
    
    @property
    def last_played(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(int(self._data.get("LastPlayed", "0")))
    
    @property
    def playtime(self) -> datetime.time:
        t = int(self._data.get("Playtime", "0"))
        return datetime.time(t // 60, t % 60)
    
    @property
    def playtime_two_weeks(self) -> datetime.time:
        t = int(self._data.get("Playtime2wks", "0"))
        return datetime.time(t // 60, t % 60)
    
    launch_options = DictPathProperty("_data", ("LaunchOptions",), None)


class LoginUser:
    steam: 'Steam'
    id: int
    info: Dict[str, str]

    def __init__(self, steam, id: int, info: Dict):
        self.steam = steam
        self.id = id
        self.info = info
    
    def __repr__(self):
        return "<steamutil.LoginUser %d %s '%s'>" % (self.id , self.account_name, self.username)
    
    @property
    def account_id(self):
        """ 32-bit account ID """
        return self.id & 0xffffffff
    
    account_name = DictPathRoProperty("info", ("AccountName",))
    username = DictPathRoProperty("info", ("PersonaName",))

    @CachedProperty
    def userdata_path(self) -> Path:
        return self.steam.get_userdata_path(self)
    
    @property
    def localconfig_vdf(self) -> Path:
        return self.userdata_path / "config" / "localconfig.vdf"
    
    @CachedProperty
    def localconfig(self) -> DeepDict:
        with open(self.localconfig_vdf) as f:
            return _vdf.parse(f)
    
    # Game config
    def get_app_config(self, app: Union[int, App]) -> Optional[UserAppConfig]:
        if isinstance(app, App):
            app = app.appid
        return UserAppConfig(self, app)


class Steam:
    root: Path

    def __init__(self, install_path=None):
        self.root = install_path if install_path is not None else self.find_install_path()
        if self.root is None:
            raise Exception("Could not find Steam")
    
    def __repr__(self):
        return "<steamutil.Steam @ \"%s\">" % self.root

    @staticmethod
    def find_install_path() -> Optional[Path]:
        # TODO: Windows
        # Linux
        if sys.platform.startswith("linux"):
            # Try ~/.steam first
            dotsteam = Path(os.path.expanduser("~/.steam"))
            if dotsteam.exists():
                steamroot = (dotsteam / "root").resolve()
                if steamroot.exists():
                    return steamroot
            # Try ~/.local/share/Steam, classic ~/Steam
            data_dir = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
            for path in data_dir, Path("~").expanduser():
                for name in "Steam", "SteamBeta":
                    steamroot = path / name
                    if steamroot.exists():
                        return steamroot
        elif sys.platform.startswith("win"):
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "SOFTWARE\\Valve\\Steam")
                path, t = winreg.QueryValueEx(key, "steampath")
                if (t == winreg.REG_SZ):
                    return Path(path)
            except WindowsError:
                pass
            # try PROGRAMFILES
            pfiles = (os.environ.get("ProgramFiles(x86)", "C:\Program Files (x86)"),
                      os.environ.get("ProgramFiles", "C:\Program Files"))
            for path in pfiles:
                if path.exists():
                    path /= "Steam"
                    if path.exists():
                        return path

    # Various paths
    @property
    def libraryfolders_vdf(self) -> Path:
        """ The libraryfolders.vdf file listing all configured library locations """
        return self.root / "steamapps" / "libraryfolders.vdf"
    
    @property
    def config_vdf(self) -> Path:
        return self.root / "config" / "config.vdf"
    
    @property
    def loginusers_vdf(self) -> Path:
        return self.root / "config" / "loginusers.vdf"
    
    # Users
    @CachedProperty
    def most_recent_user(self) -> Optional[LoginUser]:
        try:
            with open(self.loginusers_vdf) as f:
                data = _vdf.parse(f)
            for id, info in data["users"].items():
                if info["mostrecent"] == "1":
                    return LoginUser(self, int(id), info)
        except KeyError:
            pass
        return None
    
    def get_userdata_path(self, user_id: Union[int, LoginUser]) -> Path:
        if isinstance(user_id, LoginUser):
            user_id = user_id.account_id
        return self.root / "userdata" / str(user_id)

    # Game/App Library
    @CachedProperty
    def library_folder_paths(self) -> List[Path]:
        with open(self.libraryfolders_vdf) as f:
            return [Path(v) for k,v in _vdf.parse(f)["LibraryFolders"].items() if k.isdigit()]
    
    @CachedProperty
    def library_folders(self) -> List[LibraryFolder]:
        return [LibraryFolder(self, self.root)] + [LibraryFolder(self, p) for p in self.library_folder_paths] #pylint:disable=not-an-iterable
    
    @property
    def apps(self) -> Iterable[App]:
        for lf in self.library_folders: #pylint:disable=not-an-iterable
            yield from lf.apps
    
    def get_app(self, id: int) -> Optional[App]:
        for lf in self.library_folders: #pylint:disable=not-an-iterable
            app = lf.get_app(id)
            if app is not None:
                return app

    def find_apps(self, pattern: str) -> Iterable[App]:
        for lf in self.library_folders: #pylint:disable=not-an-iterable
            yield from lf.find_apps(pattern)
    
    def find_app(self, pattern: str) -> Optional[App]:
        for app in self.find_apps(pattern):
            return app
    

