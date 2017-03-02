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
-----------------------------------------------------------
Decorators for defining xconv profiles
"""

from .profileman import index

from functools import wraps


__all__ = [
    "profile",
    "description",
    "output",
    "defines",
    "features",
    "singleaudio"
]

# == Misc. helpers ==
def __update(f, name, update):
    if hasattr(f, name):
        getattr(f, name).update(update);
    else:
        setattr(f, name, update)

def __defaults(obj, **defs):
    for k, v in defs.items():
        if not hasattr(obj, k):
            setattr(obj, k, v)


# == Profile Decorators ==
def profile(f):
    """
    Define a XConv Profile

    Note: Should be outermost decorator
    """
    __defaults(f,
        description=None,
        container=None,
        ext=None,
        defines={},
        features={})
    index[f.__name__] = f
    return f


def description(desc):
    """ Add a profile description """
    def apply(f):
        f.description = desc
        return f
    return apply


def output(container=None, ext=None):
    """ Add output file information """
    def apply(f):
        if container:
            f.container = container
            f.ext = "mkv" if container == "matroska" else container
        if ext:
            f.ext = ext
        return f
    return apply


def defines(**defs):
    """ Document supported defines with description """
    def apply(f):
        __update(f, "defines", defs)
        return f
    return apply


def features(**features):
    """ Set opaque feature flags """
    def apply(f):
        __update(f, "features", features)
        return f
    return apply


def singleaudio(profile):
    """
    Operate on a single audio stream (The first one found)

    The stream will be passed to the decorated function in the "stream" keyword
    """
    @wraps(profile)
    def wrapper(task, **kwds):
        try:
            audio_stream = next(task.iter_audio_streams())
        except StopIteration:
            print("No audio track in '%s'" % "', '".join(map(lambda x: x.name, task.inputs)))
            return False
        return profile(task, stream=audio_stream, **kwds)
    __update(wrapper, "features", {"singleaudio": None})
    return wrapper
