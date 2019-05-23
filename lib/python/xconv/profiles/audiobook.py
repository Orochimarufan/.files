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

import os
import math

from ..profile import *


abdefines = dict(
    bitrate = "Use custom target bitrate",
    stereo  = "Use 2 channels (Ignored for mono source streams)",
    fancy   = "Use higher bitrates (48k mono/64k stereo)",
    ogg     = "Use the .ogg file extension (Currently required on Android)",
)

def apply_stream(stream, defines):
    """ Apply the audiobook profile to an output stream """
    stream.codec = "libopus"
    stream.channels = 1
    stream.bitrate = 40_000

    stream.set(vbr="on", application="voip")

    # High Quality
    if "fancy" in defines:
        stream.bitrate = 48_000
        stream.set(application="audio")

    # Stereo Options
    if stream.source.channels > 1 and "stereo" in defines:
        stream.channels = 2
        stream.bitrate = 48_000

        if "fancy" in defines:
            stream.bitrate = 64_000

    # Custom bitrate
    if "bitrate" in defines:
        stream.bitrate = defines["bitrate"]

    # Limit to input bitrate
    stream.bitrate = min(stream.bitrate, stream.source.bitrate)


metadefines = dict(
    title="Name of the book",
    series="Series the book belongs to",
    author="Name of the book's author",
    performer="Name of the audiobook's reader/narrator",
    genre="Name of the genre. Default is Audiobook",
    publisher="Name of the recording company",
    language="Language",
)


def apply_metadata(ob, defines):
    ob.apply_meta(defines, "language", "author", "performer", publisher="organization", title="album")
    ob.meta(genre=defines.get("genre", "Audiobook"))


@profile
@description("Encode Opus Audiobook")
@output(container="ogg", ext="opus")
@defines(**abdefines, **metadefines)
@singleaudio
def audiobook(task, stream, defines):
    if "ogg" in defines:
        task.change_format(ext="ogg")

    apply_stream(task.map_stream(stream), defines)

    apply_metadata(task.output, defines)

    return True


# Create multiple files from a single big one
@profile
@description("Split & Encode Opus Audiobook from M4B chapters")
@output(container="ogg", ext="opus")
@features(no_single_output=True)
@defines(ignore_ends="Ignore chapter end marks and continue until next chapter starts",
         chapter_only_names="Don't include the input filename in the output filename",
         **abdefines, **metadefines)
@singleaudio
def from_chapters(task, stream, defines):
    # Read chapters from input
    if "ignore_ends" in defines:
        # Make sure nothing is cut out because of
        # broken chapter (end) markers
        it = iter(task.iter_chapters())
        first_chapter = next(it)

        chapters = [{"title": first_chapter.title}]

        for chapter in it:
            chapters[-1]["to"] = chapter.start_time
            chapters.append({"ss": chapter.start_time,
                             "title": chapter.title})

    else:
        chapters = [{"ss": chapter.start_time,
                     "to": chapter.end_time,
                     "title": chapter.title}
                    for chapter in task.iter_chapters()]

    # Output filenames
    ext = "ogg" if "ogg" in defines else "opus"

    if "chapter_only_names" in defines:
        fn_template = os.path.join(task.output_directory, "%%s.%s" % ext)
    else:
        fn_template = "%s - %%s.%s" % (task.output_prefix, ext)

    # Set up output files
    for chapter in chapters:
        out = task.add_output(fn_template % chapter.pop("title"), "ogg")

        out.set(**chapter)

        apply_stream(out.map_stream(stream), defines)

        apply_metadata(out, defines)

    return True


@profile
@description("Split & Encode Opus Audiobook from Audible AAX")
@output(container="ogg", ext="opus")
@features(no_single_output=True)
@defines(key="Audible activation_bytes (required)",
         cover_file="Filename for the extracted cover (Default: <album>.jpg)",
         #dont_embed_cover="Don't try to embed the cover",
         artist_tag="Specify the tag to store the artist name (Default: author)",
         performer="Add a performer tag",
         #album="Override book title",
         **abdefines)
def audible(task, defines):
    if len(task.inputs) != 1:
        print("audiobook.audible profile must be applied to a single AAX file!")
        return False

    input = task.inputs[0]
    if "key" not in defines:
        if input.metadata["major_brand"].lower() == "aax":
            print("Audible activation_bytes must be specified in the 'key' define!")
            return False
    else:
        input.set(activation_bytes=defines["key"])

    audio = input.audio_streams[0]

    # Extract cover
    cover = input.video_streams[0]
    cover_file = defines.get("cover_file", True)
    if cover_file != "":
        if cover_file is True:
            cover_file = input.album + ".jpg"
        elif "." not in cover_file:
            cover_file += ".jpg"
        cof = task.add_output(os.path.join(task.output_directory, cover_file))
        cof.map_stream(cover).set(c="copy")

    ext = "ogg" if "ogg" in defines else "opus"
    chaps = len(input.chapters)
    ct_fmt = "%%s %%0%dd - %%s.%s" % (math.ceil(math.log10(chaps)), ext)
    add_meta = {defines.get("artist_tag", "author"): input.artist}
    #album = defines.get("album", input.album)

    for chapter in input.chapters:
        no = chapter.index + 1
        title = " - ".join((input.album, chapter.title))
        filename = os.path.join(task.output_directory, ct_fmt % (input.album, no, chapter.title))
        out = task.add_output(filename)
        out.set(ss = chapter.start_time,
                to = chapter.end_time,
                map_metadata = "-1",
                reorder_streams = False)
        out.meta(title = title,
                 album = input.title,
                 tracknumber = "%d/%d" % (no, chaps),
                 **add_meta)
        out.apply_meta(input.metadata, "copyright", "genre", "date", comment="description")
        out.apply_meta(defines, "performer", publisher="organization")
        apply_stream(out.map_stream(audio), defines)
        #if not "dont_embed_cover" in defines:
        #    out.map_stream(cover) # Not sure how to make ffmpeg add covers to ogg

    return True



@profile
@description("Split into uniform pieces & Encode Opus Audiobook")
@output(container="ogg", ext="opus")
@features(no_single_output=True)
@defines(interval="Length of a piece in minutes (default 30)",
         minimum="Don't open a new piece if it's shorter than this (default 5)",
         **abdefines)
@singleaudio
def explode(task, stream, defines):
    interval = float(defines.get("interval", 30)) * 60
    min_intv = float(defines.get("minimum", 5)) * 60

    last_duration = stream.duration % interval
    npieces = int(stream.duration // interval) + (1 if last_duration > min_intv else 0)

    ext = "ogg" if "ogg" in defines else "opus"

    if npieces > 1:
        fn_template = "%s - %%02i.%s" % (task.output_prefix, ext)
        out = task.add_output(fn_template % 1, "ogg")

        for i in range(1, npieces):
            ts = i * interval
            out.set(to=ts)
            out = task.add_output(fn_template % (i + 1), "ogg")
            out.set(ss=ts)

    else:
        task.add_output("%s.%s" % (task.output_prefix, ext), "ogg")

    for out in task.outputs:
        apply_stream(out.map_stream(stream), defines)

    return True
