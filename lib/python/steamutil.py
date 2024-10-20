# Discover Steam install and games
# (c) 2020 Taeyeon Mori CC-BY-SA

import datetime
import fnmatch
import os
import re
import sys

from pathlib import Path
from typing import List, Iterable, Dict, Literal, Mapping, Tuple, Optional, Union, Any, cast, overload

from vdfparser import VdfParser, DeepDict, AppInfoFile, LowerCaseNormalizingDict, dd_getpath
from propex import SettableCachedProperty, DictPathProperty, DictPathRoProperty, cached_property


_vdf = VdfParser()
_vdf_ci = VdfParser(factory=LowerCaseNormalizingDict)


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
    @cached_property
    def appinfo(self):
        # FIXME: properly close AppInfoFile but also deal with always-open appinfo
        return self.steam.appinfo[self.appid]

    @property
    def launch_configs(self):
        return self.appinfo["appinfo"]["config"]["launch"].values()

    name        = DictPathRoProperty[Optional[str]]("appinfo", ("appinfo", "common", "name"), default=None)
    oslist      = DictPathRoProperty[List[str]]    ("appinfo", ("appinfo", "common", "oslist"), type=lambda s: s.split(","))
    install_dir = DictPathRoProperty[Optional[str]]("appinfo", ("appinfo", "config", "installdir"), default=None)
    languages   = DictPathRoProperty[Any]          ("appinfo", ("appinfo", "common", "supported_languages"))
    gameid      = DictPathRoProperty[int]          ("appinfo", ("appinfo", "common", "gameid"), type=int)

    # Misc.
    def get_userdata_path(self, user_id: Union[int, 'LoginUser']) -> Path:
        return self.steam.get_userdata_path(user_id) / str(self.appid)

    @property
    def is_native(self):
        """ Whether the app has a version native to the current platform """
        return sys.platform in self.oslist

    @cached_property
    def compat_tool(self) -> dict:
        """ The compatibility tool selected for this app.
        Note: this will still return a default if no tool is used
        """
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

        super().__init__(libfolder.steam, int(dd_getpath(self.manifest, ("AppState", "appid"), t=str)))

    installed = True

    def __repr__(self):
        return "<steamutil.App     #%7d '%s' @ \"%s\">" % (self.appid, self.name, self.install_path)

    # Basic info
    name  = DictPathRoProperty[Optional[str]]("manifest", ("AppState", "name"), None)
    language = DictPathRoProperty[Optional[str]]("manifest", ("AppState", "UserConfig", "language"), None)
    install_dir = DictPathRoProperty[Optional[str]]("manifest", ("AppState", "installdir"), None)

    @cached_property
    def install_path(self) -> Path:
        return self.steamapps_path / "common" / self.install_dir

    # Workshop
    # TODO
    @cached_property
    def workshop_path(self) -> Path:
        return self.steamapps_path / "workshop" / "content" / str(self.appid)

    # Steam Play info
    @property
    def platform_override(self) -> Tuple[Optional[str], Optional[str]]:
        uc = dd_getpath(self.manifest, ("AppState", "UserConfig"), None, t=dict)
        if uc:
            return uc.get("platform_override_source", None), uc.get("platform_override_dest", None)
        return None, None

    @property
    def is_steam_play(self) -> Union[str, bool]:
        """ Whether app needs a compatibility tool to run """
        if (po := self.platform_override[0]) is not None:
            return po
        return not self.is_native

    @property
    def is_proton_app(self) -> Optional[bool]:
        """ Whether app needs (specifically) Proton to run """
        # XXX: Should this try to figure out if selected compat tool is actually proton?
        return self.platform_override[0] == "windows" or not self.is_native and "windows" in self.oslist

    @cached_property
    def compat_path(self) -> Path:
        return self.steamapps_path / "compatdata" / str(self.appid)

    @cached_property
    def compat_prefix(self) -> Path:
        return self.compat_path / "pfx"

    @cached_property
    def compat_drive(self) -> Path:
        return self.compat_prefix / "drive_c"

    # Install size
    declared_install_size = DictPathRoProperty[int]("manifest", ("AppState", "SizeOnDisk"), 0, type=int)

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
    @cached_property
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
        return None

    def find_apps_re(self, regexp: str) -> Iterable[App]:
        reg = re.compile(r'"name"\s+".*%s.*"' % regexp, re.IGNORECASE)
        for manifest in self.appmanifests:
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
        return dd_getpath(self.user.localconfig, ("UserLocalConfigStore", "Software", "Valve", "Steam", ("Apps", "apps"), str(self.appid)), {}, t=dict)

    @property
    def last_played(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(int(self._data.get("LastPlayed", 0)))

    @property
    def playtime(self) -> datetime.time:
        return datetime.time(minute=int(self._data.get("Playtime", 0)))

    @property
    def playtime_two_weeks(self) -> datetime.time:
        return datetime.time(minute=int(self._data.get("Playtime2wks", 0)))

    launch_options = DictPathProperty[Optional[DeepDict]]("_data", ("LaunchOptions",), None)


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

    account_name = DictPathRoProperty[str]("info", ("AccountName",))
    username = DictPathRoProperty[str]("info", ("PersonaName",))

    @cached_property
    def userdata_path(self) -> Path:
        return self.steam.get_userdata_path(self)

    @property
    def localconfig_vdf(self) -> Path:
        return self.userdata_path / "config" / "localconfig.vdf"

    @cached_property
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
        # Linux
        if sys.platform.startswith("linux"):
            # Try ~/.steam first
            dotsteam = Path("~/.steam").expanduser()
            if dotsteam.exists():
                steamroot = (dotsteam / "root").resolve()
                if steamroot.exists():
                    return steamroot
            # Try ~/.local/share/Steam, classic ~/Steam
            data_dir = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
            for path in data_dir, Path("~").expanduser():
                for name in "Steam", "SteamBeta":
                    steamroot = path / name
                    if (steamroot / "steamapps" / "libraryfolders.vdf").exists():
                        return steamroot
            # Try Flatpak
            appdir = Path("~/.var/app/com.valvesoftware.Steam").expanduser()
            if appdir.exists():
                return (appdir / ".steam" / "root").resolve()
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
        return None

    @property
    def is_flatpak(self) -> bool:
        return self.root.is_relative_to(Path("~/.var/app/com.valvesoftware.Steam").expanduser())

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
    @cached_property
    def most_recent_user(self) -> Optional[LoginUser]:
        try:
            # Apparently, Steam doesn't care about case in the config/*.vdf keys
            with open(self.loginusers_vdf, encoding="utf-8") as f:
                data = _vdf_ci.parse(f)
            for id, info in cast(Mapping[str, Dict], data["users"]).items():
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
    @cached_property
    def config(self) -> DeepDict:
        with open(self.config_vdf, encoding="utf-8") as f:
            return _vdf.parse(f)

    config_install_store = DictPathProperty[Dict]("config", ("InstallConfigStore",))
    config_software_steam = DictPathProperty[Dict]("config", ("InstallConfigStore", "Software", "Valve", "Steam"))
    compat_tool_mapping = DictPathProperty[Dict]("config", ("InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping"))

    # AppInfo cache
    @cached_property
    def appinfo_vdf(self):
        return self.root / "appcache" / "appinfo.vdf"

    @cached_property
    def appinfo(self) -> AppInfoFile:
        return AppInfoFile.open(self.appinfo_vdf)

    @SettableCachedProperty
    def steamplay_manifest(self) -> DeepDict:
        with self.appinfo as info:
            return info[891390]["appinfo"]

    @cached_property
    def compat_tools(self) -> Dict[str, Dict]:
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
        compattools_d = self.root / "compatibilitytools.d"
        if compattools_d.exists():
            manifests = []
            for p in compattools_d.iterdir():
                if p.suffix == ".vdf":
                    manifests.append(p)
                elif p.is_dir():
                    c = p / "compatibilitytool.vdf"
                    if c.exists():
                        manifests.append(c)
            for mfst_path in manifests:
                with open(mfst_path, encoding="utf-8") as f:
                    mfst = _vdf.parse(f)
                for name, t in dd_getpath(mfst, ("compatibilitytools", "compat_tools"), t=dict).items():
                    # TODO warn duplicate name
                    t["install_path"] = mfst_path.parent / t["install_path"]
                    tools[name] = t
        return tools

    # Game/App Library
    @cached_property
    def library_folder_paths(self) -> List[Path]:
        with open(self.libraryfolders_vdf, encoding="utf-8") as f:
            data = _vdf_ci.parse(f)
        def gen():
            for k, v in dd_getpath(data, ("LibraryFolders",), t=dict).items():
                if k.isdigit():
                    if isinstance(v, str):
                        yield Path(v)
                    elif 'path' in v:
                        yield Path(v['path'])
                    else:
                        raise ValueError("Unknown format of libraryfolders.vdf")
        return list(gen())

    @cached_property
    def library_folders(self) -> List[LibraryFolder]:
        return [LibraryFolder(self, self.root)] + [LibraryFolder(self, p) for p in self.library_folder_paths]

    @property
    def apps(self) -> Iterable[App]:
        for lf in self.library_folders:
            yield from lf.apps

    @overload
    def get_app(self, id: int, installed: Literal[True]=True) -> Optional[App]: ...
    @overload
    def get_app(self, id: int, installed: Literal[False]) -> Optional[AppInfo]: ...

    def get_app(self, id: int, installed=True) -> Optional[AppInfo]:
        for lf in self.library_folders:
            app = lf.get_app(id)
            if app is not None:
                return app
        if not installed:
            for appinfo in self.appinfo:
                if appinfo.id == id:
                    return AppInfo(self, id, appinfo_data=appinfo)
        return None

    @overload
    def find_apps_re(self, regexp: str, installed: Literal[True]) -> Iterable[App]: ...
    @overload
    def find_apps_re(self, regexp: str, installed: Literal[False]) -> Iterable[AppInfo]: ...

    def find_apps_re(self, regexp: str, installed=True) -> Iterable[AppInfo]:
        """ Find all apps by regular expression """
        if not installed:
            # Search whole appinfo cache
            reg = re.compile(regexp, re.IGNORECASE)
            broken_ids = set()
            try:
                for appinfo in self.appinfo:
                    # Skip broken entries
                    try:
                        name = appinfo["appinfo"]["common"]["name"]
                    except KeyError:
                        broken_ids.add(appinfo.id)
                        continue
                    if reg.search(name):
                        for lf in self.library_folders:
                            app = lf.get_app(appinfo.id)
                            if app:
                                yield app
                                break
                        else:
                            yield AppInfo(self, appinfo.id, appinfo_data=appinfo)
            except Exception:
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
        for lf in self.library_folders:
            for manifest in lf.appmanifests:
                with open(manifest, encoding="utf-8") as f:
                    content = f.read()
                if reg.search(content):
                    yield App(lf, manifest, manifest_data=_vdf.parse_string(content))

    def find_apps(self, pattern: str, installed=True) -> Iterable[App]:
        return self.find_apps_re(fnmatch.translate(pattern).rstrip("\\Z"), installed=installed)

    def find_app(self, pattern: str, installed=True) -> Optional[App]:
        for app in self.find_apps(pattern, installed=installed):
            return app
        return None
