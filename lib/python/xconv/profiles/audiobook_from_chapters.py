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
Opus Audiobook profile from m4b chapters
"""

from ..profile import *
from .audiobook import apply, abdefines


@profile
@description("Split & Encode Opus Audiobook from M4B chapters")
@output(container="ogg", ext="ogg")
@features(no_single_output=True)
@defines(**abdefines)
@singleaudio
def audiobook_from_chapters(task, stream, defines):
    for chapter in task.iter_chapters():
        apply(
            task.add_output(chapter.title + ".ogg", "ogg")
            .set(ss=chapter.start_time,
                 to=chapter.end_time)
            .map_stream(stream), defines)
    return True
