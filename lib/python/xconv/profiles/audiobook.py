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
Opus Audiobook profile
"""

from ..profile import *


@profile
@description("Encode Opus Audiobook")
@output(container="ogg", ext="ogg")
@defines(stereo="Use two channels",
         bitrate="Use custom target bitrate",
         fancy="Use 48kbps stereo (For dramatic audiobooks with a lot of music and effects)")
@singleaudio
def audiobook(task, stream, defines):
    out = (task.map_stream(stream)
        .set(codec="libopus",
            vbr="on",
            b="32k",
            ac="1",
            application="voip"))
    if "stereo" in defines:
        out.set(ac="2",
                b="36k")
    if "fancy" in defines:
        out.set(ac="2",
                b="48k",
                application="audio")
    if "bitrate" in defines:
        out.set(b=defines["bitrate"])
    return True
