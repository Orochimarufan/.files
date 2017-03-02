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


def load_profile(name):
    if name in index:
        return index[name]

    try:
        import_module(".profiles.%s" % name, __package__)
    except ImportError as e:
        print(e)
        pass

    if name in index:
        return index[name]

    load_all_profiles()

    if name in index:
        return index[name]

    raise ImportError("Could not find XConv profile '%s'" % name)


def load_all_profiles():
    for location in profilepaths:
        for mod in (x for x in Path(location).iterdir() if x.is_file() and x.suffix == ".py"):
            try:
                import_module(".profiles.%s" % mod.stem, __package__)
            except ImportError:
                pass

    return index
