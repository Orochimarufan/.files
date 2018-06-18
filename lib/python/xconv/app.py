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
from functools import partial


# == Extend AAV ==
class OutputFile(advancedav.OutputFile):
    def change_format(self, format=None, ext=None):
        # Diverge from decorated format.
        # Watch out for args.genout!!
        if format:
            self.container = format
        if ext:
            self.name = splitext(self.name)[0] + "." + ext


class XconvMixin:
    output_factory = OutputFile


class SimpleTask(XconvMixin, advancedav.SimpleTask):
    pass


class AdvancedTask(XconvMixin, advancedav.Task):
    def __init__(self, aav, output_prefix):
        self.output_prefix = output_prefix
        self.output_directory = dirname(output_prefix)
        self.output_basename = basename(output_prefix)
        super().__init__(aav)


class Manager(advancedav.MultiAV):
    def _spawn_next(self, **b):
        task = self.queue[0][1]

        print("\033[32m  Processing '%s'\033[0m" % task_name(task))

        proc, f = super()._spawn_next(**b)

        f.then(partial(task_done, task)).catch(partial(task_fail, task))

        return proc, f

def task_done(task, res):
    print("\033[32m  Finished '%s'\033[0m" % task_name(task))

def task_fail(task, exc):
    print("\033[31m  Failed '%s': %s\033[0m" % (task_name(task), exc))


# == App ==
def make_basename(path, infile):
    return build_path(path, splitext(basename(infile))[0])


def make_outfile(path, infile, ext=None):
    name, oldext = splitext(basename(infile))
    return build_path(path, ".".join((name, ext if ext else oldext)))


def create_task(aav, profile, inputs, args, filename_from=None):
    is_advanced_task_profile = any(("advanced_task" in profile.features,
                                    "no_single_output" in profile.features))

    filename_from = filename_from or inputs[0]

    if not is_advanced_task_profile:
        fmt = advancedav.DEFAULT_CONTAINER
        ext = None
        if "output" in profile.features:
            fmt, ext = profile.features["output"]
        outfile = args.output if args.output_filename else make_outfile(args.output_directory, filename_from, ext)
        task = SimpleTask(aav, outfile, fmt)

    else:
        basename = args.output if args.output_filename else make_basename(args.output_directory, filename_from)
        task = AdvancedTask(aav, basename)


    for input in inputs:
        task.add_input(input)

    return task


def task_name(task):
    if hasattr(task, "name"):
        return basename(task.name)
    elif task.inputs or task.outputs:
        name = "ffT"
        if task.inputs:
            name += " <`%s`" % task.inputs[0].name
            if len(task.inputs) > 1:
                name += "..."
        if task.outputs:
            name += " >`%s`" % task.outputs[0].name
            if len(task.outputs) > 1:
                name += "..."
        return name
    else:
        return "(anon task %p)" % id(task)


def main(argv):
    import logging

    # Parse commandline
    args = parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    profile = load_profile(args.profile)

    print("\033[36mXConv %s (c) Taeyeon Mori\033[0m" % version)
    print("\033[34mProfile: %s\033[0m" % args.profile)

    unknown_defines = [n for n in args.define.keys() if n not in profile.defines]
    if unknown_defines:
        print("\033[33mWarning: Unknown defines %s; see '%s -i %s' for avaliable defines in this profile\033[0m" %
              (", ".join(unknown_defines), argv[0], args.profile))

    if args.create_directory:
        makedirs(args.output_directory, exist_ok=True)

    if not args.output_filename and not isdir(args.output_directory):
        print("\033[31mOutput location '%s' is not a directory.\033[0m" % args.output_directory)
        return -1

    # Initialize AAV
    aav = Manager(ffmpeg=args.ffmpeg, ffprobe=args.ffprobe, workers=args.concurrent)

    if args.quiet:
        aav.global_conv_args = "-loglevel", "warning"

    aav.global_args += "-hide_banner", "-stats"

    # Collect Tasks
    tasks = []

    print("\033[35mCollecting Tasks..\033[0m")

    if args.merge:
        tasks.append(create_task(aav, profile, args.inputs, args))

    elif args.concat:
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(mode="w", delete=False)

        with tmp:
            tmp.write("ffconcat version 1.0\n")
            tmp.write("# XConv concat file\n")
            for f in map(abspath, args.inputs):
                print("\033[36m  Concatenating %s\033[0m" % basename(f))
                tmp.write("file '%s'\n" % f)

        task = create_task(aav, profile, (), args, filename_from=args.inputs[0])

        task.add_input(tmp.name).set(f="concat", safe="0")

        tasks.append(task)

    else:
        for input in args.inputs:
            tasks.append(create_task(aav, profile, (input,), args))

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
        print("\033[32m  Applying profile for '%s'\033[0m" % task_name(task), end="\033[K\r")
        res = profile(task, **pkw)
        if not res:
            print("\033[31m  Failed to apply profile for '%s'\033[0m\033[K" % task_name(task))
            return 1

    if args.update:
        for task in tasks[:]:
            for output in [o for o in task.outputs if exists(o.filename)]:
                print("\033[33m  Skipping existing '%s' (--update)\033[0m\033[K" % output.name)
                task.outputs.remove(output)
            if not tasks.outputs:
                print("\033[33m  Skipping task '%s' because no output files are left\033[0m\033[K" % task_name(task))
                tasks.remove(task)

    print("\033[35mExecuting Tasks..\033[0m\033[K")

    # Paralellize
    if args.concurrent > 1 and not args.merge and not args.concat:
        tasks = sum([task.split(args.concurrent) for task in tasks], [])

    # Commit
        [t.commit2() for t in tasks]
        aav.process_queue()
        aav.wait()

    else:
        for task in tasks:
            print("\033[32m  Processing '%s'\033[0m" % task_name(task))
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
