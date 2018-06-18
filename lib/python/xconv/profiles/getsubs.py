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
Extract subtitle streams
"""

from ..profile import *


@profile
@description("Extract subtitle tracks")
@defines(format="Convert all subtitles to a specific format")
@features(no_single_output=True)
def getsubs(task, defines):
    for stream in task.iter_subtitle_streams():
        of = task.add_output("%s.%s.%s.%s" % (task.output_prefix, task.inputs.index(stream.file), stream.pertype_index, stream.codec), None) # TODO get real file extension
        os = of.map_stream(stream)
        if "format" in defines:
        	os.codec = defines["format"]
    return True
