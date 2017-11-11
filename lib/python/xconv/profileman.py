#!/usr/bin/env python3
"""
xconv ffmpeg wrapper based on AdvancedAV
-----------------------------------------------------------
    AdvancedAV helps with constructing FFmpeg commandline arguments.

    It can automatically parse input files with the help of FFmpeg's ffprobe tool (WiP)
    and allows programatically mapping streams to output files and setting metadata on them.
-----------------------------------------------------------
    Copyright (c) 2015-2017 Taeyeon Mori

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from .profiles import __path__ as profilepaths

from importlib import import_module
from pathlib import Path


# == Profile Index ==
index = {}

profiles_package = __package__ + ".profiles"


def make_qname(module, name):
    """
    Create a qualified name for a profile
    """
    # The global profiles package is omitted from the front
    if module.startswith("%s." % profiles_package):
        module = module[len(profiles_package) + 1:]
    # But arbitrary packages can be specified by prepending :
    # This, among other things, allows to use profiles defined
    # in .py files in the working dir.
    else:
        module = ":" + module

    # If it's not deeply nested and the module name
    # and profile name are the same, the latter
    # can be omitted.
    if module.strip(":") != name:
        return "%s.%s" % (module, name)
    else:
        return module

    # Examples:
    # Profile xconv.profiles.opus/opus:
    #  - opus
    #  - opus.opus
    #  - :xconv.profiles.opus.opus
    # Watch out for xconv.profiles/opus (not valid):
    #  - :xconv.profiles.opus
    # Profile xconv.profiles.opus/stuff:
    #  - opus.stuff
    #  - :xconv.profiles.opus.stuff
    # Profile test/test:
    #  - :test
    #  - :test.test


def load_profile(name):
    """
    Find and load a XConv profile.
    """
    # Check if it's already loaded
    if name in index:
        return index[name]

    # See if it's a qualified name
    module = name.rsplit(".", 1)[0] if "." in name[1:] else name

    # Check if it's in the global profiles package or not
    if module[0] == ":":
        module = module[1:]
    else:
        module = "." + module

    # Try to import the module
    import_module(module, profiles_package)

    # Return the profile
    try:
        return index[name]
    except KeyError:
        # Fully qualifying the global profiles package is technically valid.
        if name.startswith(":%s." % profiles_package):
            qname = make_qname(*name[1:].rsplit(".", 1))
            if qname in index:
                return index[qname]
        raise ImportError("Module %s doesn't contain XConv profile %s" % (module, name))


def load_all_profiles():
    """
    Load all profile definitions
    """
    for location in profilepaths:
        for mod in (x for x in Path(location).iterdir() if x.is_file() and x.suffix == ".py"):
            try:
                import_module(".%s" % mod.stem, profiles_package)
            except ImportError:
                pass

    return index
