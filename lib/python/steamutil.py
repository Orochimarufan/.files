# Discover Steam install and games
# (c) 2020 Taeyeon Mori CC-BY-SA

import sys, os
import re, fnmatch, datetime

from pathlib import Path
from typing import List, Iterable, Dict, Tuple, Callable, Optional, Union

from vdfparser import VdfParser, DeepDict, AppInfoFile, LowerCaseNormalizingDict


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
    __slots__ = "property", "path", "default", "type"
    _nodefault = object()
    _id = lambda x: x

    def __init__(self, property: str, path: Tuple[str], default=_nodefault, type=_id):
        self.property = property
        self.path = path
        self.default = default
        self.type = type
    
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
            return self.type(d)


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


class AppInfo:
    steam: 'Steam'
    appid: int
    
    def __init__(self, steam, appid, *, appinfo_data=None):
        self.steam = steam
        self.appid = appid
        if appinfo_data is not None:
            self.__dict__["appinfo"] = appinfo_data

    def __repr__(self):
        return "<steamutil.AppInfo #%7d '%s' (%s)>" % (self.appid, self.name, self.install_dir)

    installed   = False
    
    # AppInfo
    @CachedProperty
    def appinfo(self):
        # FIXME: properly close AppInfoFile but also deal with always-open appinfo
        return self.steam.appinfo[self.appid]

    @property
    def launch_configs(self):
        return self.appinfo["appinfo"]["config"]["launch"].values()

    name        = DictPathRoProperty("appinfo", ("appinfo", "common", "name"), default=None)
    oslist      = DictPathRoProperty("appinfo", ("appinfo", "common", "oslist"), type=lambda s: s.split(","))
    install_dir = DictPathRoProperty("appinfo", ("appinfo", "config", "installdir"), default=None)
    languages   = DictPathRoProperty("appinfo", ("appinfo", "common", "supported_languages"))
    gameid      = DictPathRoProperty("appinfo", ("appinfo", "common", "gameid"), type=int)
    
    # Misc.
    def get_userdata_path(self, user_id: Union[int, 'LoginUser']) -> Path:
        return self.steam.get_userdata_path(user_id) / str(self.appid)
    
    @property
    def is_native(self):
        return sys.platform in self.oslist

    @CachedProperty
    def compat_tool(self) -> dict:
        mapping = self.steam.compat_tool_mapping
        appid = str(self.appid)
        # User override
        if appid in mapping and mapping[appid]["name"]:
            tool = dict(mapping[appid])
            tool["source"] = "user"
            return tool
        # Steam play manifest
        manifest = self.steam.steamplay_manifest["extended"]["app_mappings"]
        if appid in manifest:
            tool = dict(manifest[appid])
            tool["name"] = tool["tool"]
            tool["source"] = "valve"
            return tool
        # User default
        tool = dict(mapping["0"])
        tool["source"] = "default"
        return tool


class App(AppInfo):
    steam: 'Steam'
    library_folder: 'LibraryFolder'
    steamapps_path: Path
    manifest_path: Path
    manifest: DeepDict

    def __init__(self, libfolder, manifest_path: Path, *, manifest_data=None):
        self.library_folder = libfolder
        self.steamapps_path = libfolder.steamapps_path

        self.manifest_path = manifest_path
        if manifest_data is None:
            with open(manifest_path, encoding="utf-8") as f:
                self.manifest = _vdf.parse(f)
        else:
            self.manifest = manifest_data

        if "AppState" not in self.manifest:
            raise MalformedManifestError("App manifest doesn't have AppState key", self.manifest_path)
    
        super().__init__(libfolder.steam, int(self.manifest["AppState"]["appid"]))
    
    installed = True
    
    def __repr__(self):
        return "<steamutil.App     #%7d '%s' @ \"%s\">" % (self.appid, self.name, self.install_path)

    # Basic info
    name  = DictPathRoProperty("manifest", ("AppState", "name"))
    language = DictPathRoProperty("manifest", ("AppState", "UserConfig", "language"), None)
    install_dir = DictPathRoProperty("manifest", ("AppState", "installdir"))
    
    @CachedProperty
    def install_path(self) -> Path:
        return self.steamapps_path / "common" / self.install_dir
    
    # Workshop
    # TODO
    @CachedProperty
    def workshop_path(self) -> Path:
        return self.steamapps_path / "workshop" / "content" / str(self.appid)

    # Steam Play info
    @property
    def is_steam_play(self):
        uc = self.manifest["AppState"].get("UserConfig")
        if uc and "platform_override_source" in uc:
            return uc["platform_override_source"]
    
    @property
    def is_proton_app(self):
        uc = self.manifest["AppState"].get("UserConfig")
        if uc and "platform_override_source" in uc:
            return uc["platform_override_source"] == "windows" and uc["platform_override_dest"] == "linux"

    @CachedProperty
    def compat_path(self) -> Path:
        return self.steamapps_path / "compatdata" / str(self.appid)
    
    @CachedProperty
    def compat_drive(self) -> Path:
        return self.compat_path / "pfx" / "drive_c"
    
    # Install size
    declared_install_size = DictPathRoProperty("manifest", ("AppState", "SizeOnDisk"), 0, type=int)
    
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
            with open(manifest, encoding="utf-8") as f:
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
        with open(self.localconfig_vdf, encoding="utf-8") as f:
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
            pfiles = (os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
                      os.environ.get("ProgramFiles", "C:\\Program Files"))
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
            # Apparently, Steam doesn't care about case in the config/*.vdf keys
            vdf_ci = VdfParser(factory=LowerCaseNormalizingDict)
            with open(self.loginusers_vdf, encoding="utf-8") as f:
                data = vdf_ci.parse(f)
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
    
    # Config
    @CachedProperty
    def config(self) -> DeepDict:
        with open(self.config_vdf, encoding="utf-8") as f:
            return _vdf.parse(f)
    
    config_install_store = DictPathProperty("config", ("InstallConfigStore",))
    config_software_steam = DictPathProperty("config", ("InstallConfigStore", "Software", "Valve", "Steam"))
    compat_tool_mapping = DictPathProperty("config_software_steam", ("CompatToolMapping",))

    # AppInfo cache
    @CachedProperty
    def appinfo_vdf(self):
        return self.root / "appcache" / "appinfo.vdf"
    
    @property
    def appinfo(self) -> AppInfoFile:
        return AppInfoFile.open(self.appinfo_vdf)
    
    @CachedProperty
    def steamplay_manifest(self) -> DeepDict:
        with self.appinfo as info:
            return info[891390]["appinfo"]

    @CachedProperty
    def compat_tools(self) -> {str:{}}:
        tools = {}
        # Find official proton installs
        valve = self.steamplay_manifest["extended"]["compat_tools"]
        for name, t in valve.items():
            app = self.get_app(t["appid"])
            if app:
                tool = dict(t)
                tool["install_path"] = app.install_path
                tools[name] = tool
        # Find custom compat tools
        manifests = []
        for p in (self.root / "compatibilitytools.d").iterdir():
            if p.suffix == ".vdf":
                manifests.append(p)
            elif p.is_dir():
                c = p / "compatibilitytool.vdf"
                if c.exists():
                    manifests.append(c)
        for mfst_path in manifests:
            with open(mfst_path, encoding="utf-8") as f:
                mfst = _vdf.parse(f)
            for name, t in mfst["compatibilitytools"]["compat_tools"].items():
                # TODO warn duplicate name
                t["install_path"] = mfst_path.parent / t["install_path"]
                tools[name] = t
        return tools

    # Game/App Library
    @CachedProperty
    def library_folder_paths(self) -> List[Path]:
        with open(self.libraryfolders_vdf, encoding="utf-8") as f:
            return [Path(v) for k,v in _vdf.parse(f)["LibraryFolders"].items() if k.isdigit()]
    
    @CachedProperty
    def library_folders(self) -> List[LibraryFolder]:
        return [LibraryFolder(self, self.root)] + [LibraryFolder(self, p) for p in self.library_folder_paths] #pylint:disable=not-an-iterable
    
    @property
    def apps(self) -> Iterable[App]:
        for lf in self.library_folders: #pylint:disable=not-an-iterable
            yield from lf.apps
    
    def get_app(self, id: int, installed=True) -> Optional[App]:
        for lf in self.library_folders: #pylint:disable=not-an-iterable
            app = lf.get_app(id)
            if app is not None:
                return app
        if not installed:
            for appid, appinfo in self.appinfo.items():
                if appid == id:
                    return AppInfo(self, appid, appinfo_data=appinfo)

    def find_apps_re(self, regexp: str, installed=True) -> Iterable[App]:
        """ Find all apps by regular expression """
        if not installed:
            # Search whole appinfo cache
            reg = re.compile(regexp, re.IGNORECASE)
            broken_ids = set()
            try:
                for appid, appinfo in self.appinfo.items():
                    # Skip broken entries
                    try:
                        name = appinfo["appinfo"]["common"]["name"]
                    except KeyError:
                        broken_ids.add(appid)
                        continue
                    if reg.search(name):
                        for lf in self.library_folders: #pylint:disable=not-an-iterable
                            app = lf.get_app(appid)
                            if app:
                                yield app
                                break
                        else:
                            yield AppInfo(self, appid, appinfo_data=appinfo)
            except:
                import traceback
                traceback.print_exc()
                print("[SteamUtil] Warning: could not read non-installed apps from Steam appinfo cache. Searching locally")
            else:
                return
            finally:
                if broken_ids:
                    print("[SteamUtil] Warning: found broken entries in appinfo cache:", ",".join(map(str, broken_ids)))
        # Search local manifests directly
        reg = re.compile(r'"name"\s+".*%s.*"' % regexp, re.IGNORECASE)
        for lf in self.library_folders: #pylint:disable=not-an-iterable
            for manifest in lf.appmanifests: #pylint:disable=not-an-iterable
                with open(manifest, encoding="utf-8") as f:
                    content = f.read()
                if reg.search(content):
                    yield App(lf, manifest, manifest_data=_vdf.parse_string(content))

    def find_apps(self, pattern: str, installed=True) -> Iterable[App]:
        return self.find_apps_re(fnmatch.translate(pattern).rstrip("\\Z"), installed=installed)

    def find_app(self, pattern: str, installed=True) -> Optional[App]:
        for app in self.find_apps(pattern, installed=installed):
            return app
