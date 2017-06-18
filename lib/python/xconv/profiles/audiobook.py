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


abdefines = dict(
    stereo="Use two channels at 48k",
    bitrate="Use custom target bitrate",
    fancy="Use 56kbps stereo (For dramatic audiobooks with a lot of music and effects)"
)

def apply(stream, defines):
    stream.set(codec="libopus",
            vbr="on",
            b="40k",
            ac="1",
            application="voip")
    if stream.source.channels > 1:
        if "stereo" in defines:
            stream.set(ac="2",
                    b="48k")
        if "fancy" in defines:
            stream.set(ac="2",
                    b="56k",
                    application="audio")
    if "bitrate" in defines:
        stream.bitrate = defines["bitrate"]
    # At most input bitrate; we wouldn't gain anything since opus should be same or better compression
    stream.bitrate = min(stream.bitrate, stream.source.bitrate)


@profile
@description("Encode Opus Audiobook")
@output(container="ogg", ext="ogg")
@defines(**abdefines)
@singleaudio
def audiobook(task, stream, defines):
    apply(task.map_stream(stream), defines)
    return True
