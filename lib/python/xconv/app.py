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

from .profileman import load_profile
from .cmdline import parse_args, version

import advancedav

from os.path import isdir, join as build_path, basename, dirname, splitext, exists, abspath
from os import environ, makedirs, mkdir
from shutil import copyfile
from pathlib import Path


# == Extend AAV ==
class OutputFile(advancedav.OutputFile):
    def change_format(self, format=None, ext=None):
        # Diverge from decorated format.
        # Watch out for args.genout!!
        if format:
            self.container = format
        if ext:
            self.name = splitext(self.name)[0] + "." + ext


class SimpleTask(advancedav.SimpleTask):
    output_factory = OutputFile


# == App ==
def make_outfile(args, profile, infile):
    if not args.output_filename:
        if hasattr(profile, "ext"):
            return build_path(args.output_directory, ".".join((splitext(basename(infile))[0], profile.ext if profile.ext else "bin")))
        else:
            return build_path(args.output_directory, basename(infile))
    else:
        return args.output


def main(argv):
    import logging

    # Parse commandline
    args = parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    profile = load_profile(args.profile)

    print("\033[36mXConv %s (c) Taeyeon Mori\033[0m" % version)
    print("\033[34mProfile: %s\033[0m" % args.profile)

    if args.create_directory:
        makedirs(args.output_directory, exist_ok=True)

    if not args.output_filename and not isdir(args.output_directory):
        print("\033[31mOutput location '%s' is not a directory.\033[0m" % args.output_directory)
        return -1

    # Initialize AAV
    aav = advancedav.SimpleAV(ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)

    if args.quiet:
        aav.global_conv_args = "-loglevel", "warning"

    aav.global_args += "-hide_banner",

    # Collect Tasks
    tasks = []

    print("\033[35mCollecting Tasks..\033[0m")

    if args.merge:
        task = SimpleTask(aav, make_outfile(args, profile, args.inputs[0]), profile.container)

        for input in args.inputs:
            task.add_input(input)

        tasks.append(task)

    elif args.concat:
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(mode="w", delete=False)

        with tmp:
            tmp.write("ffconcat version 1.0\n")
            tmp.write("# XConv concat file\n")
            for f in map(abspath, args.inputs):
                print("\033[36m  Concatenating %s\033[0m" % basename(f))
                tmp.write("file '%s'\n" % f)

        task = SimpleTask(aav, make_outfile(args, profile, args.inputs[0]), profile.container)

        options(task.add_input(tmp.name),
            f="concat",
            safe="0")

        tasks.append(task)

    else:
        for input in args.inputs:
            out = make_outfile(args, profile, input)
            if args.update and exists(out):
                continue
            task = SimpleTask(aav, out, profile.container)
            task.add_input(input)
            tasks.append(task)

    print("\033[35mPreparing Tasks..\033[0m")

    # Prepare profile parameters
    pkw = {}
    if profile.defines:
        pkw["defines"] = args.define
    if profile.features:
        if "argshax" in profile.features:
            pkw["args"] = args

    # Apply profile
    for task in tasks:
        print("\033[32m  Applying profile for '%s'\033[0m" % basename(task.name), end="\033[K\r")
        res = profile(task, **pkw)
        if not res:
            print("\033[31m  Failed to apply profile for '%s'\033[0m\033[K" % basename(task.name))
            return 1

    print("\033[35mExecuting Tasks..\033[0m\033[K")

    # Commit
    for task in tasks:
        print("\033[32m  Processing '%s'\033[0m" % basename(task.name))
        task.commit()

    # Clean up
    if args.concat:
        os.unlink(tmp.name)

    # Copy files
    if args.copy_files:
        print("\033[35mCopying Files..\033[0m\033[K")
        for file in args.copy_files:
            print("\033[32m  Copying '%s'\033[0m\033[K" % basename(file))
            copyfile(file, build_path(args.output_directory, basename(file)))

    print("\033[35mDone.\033[0m\033[K")

    return 0
