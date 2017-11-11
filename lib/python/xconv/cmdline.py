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
Commandline Parsing
"""

from .profileman import load_all_profiles, load_profile
from . import version_info

from advancedav import version_info as aav_version_info

from argparse import ArgumentParser, Action
from pathlib import Path
from os.path import basename
from multiprocessing import cpu_count


version = "%s (AdvancedAV %s)" % (".".join(map(str, version_info)), ".".join(map(str, aav_version_info)))


# == Support code ==
class TerminalAction(Action):
    def __init__(self, option_strings, dest, nargs=0, default=None, **kwargs):
        super().__init__(option_strings, dest, nargs=nargs, default=default or {}, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        self.run(parser, *values)
        parser.exit()


class ProfilesAction(TerminalAction):
    def run(self, parser):
        print("Available Profiles:")
        for name, profile in sorted(load_all_profiles().items()):
            print("  %-25s %s" % (name, profile.description if profile.description else ""))


class ProfileInfoAction(TerminalAction):
    def __init__(self, option_strings, dest, nargs=1, default=None, **kwargs):
        super().__init__(option_strings, dest, nargs=nargs, default=default or {}, **kwargs)
    def run(self, parser, profile_name):
        profile = load_profile(profile_name)
        print("Profile '%s':" % profile_name)
        if profile.description:
            print("  Description: %s" % profile.description)
        if "output" in profile.features:
            output = profile.features["output"]
            output_info = []
            if output[0]:
                output_info.append("Format: %s" % output[0])
            if output[1]:
                output_info.append("File extension: %s" % output[0])
            if output_info:
                print("  Output: %s" % "; ".join(output_info))
        if profile.features:
            print("  Flags: %s" % ", ".join("%s(%r)" % (k, v) if v is not None else k for k, v in profile.features.items()))
        if profile.defines:
            print("  Supported defines:")
            for define in sorted(profile.defines.items()):
                print("    %s: %s" % define)


class DefineAction(Action):
    def __init__(self, option_strings, dest, nargs=1, default=None, **kwargs):
        super().__init__(option_strings, dest, nargs=nargs, default=default or {}, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        value = values[0]
        dest = getattr(namespace, self.dest)
        if "=" in value:
            k, v = value.split("=")
            dest[k] = v
        else:
            dest[value] = True


class ExtendAction(Action):
    def __init__(self, option_strings, dest, nargs="+", default=None, **kwargs):
        super().__init__(option_strings, dest, nargs=nargs, default=default, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        items = getattr(namespace, self.dest) or []
        items.extend(values)
        setattr(namespace, self.dest, items)


def parse_args(argv):
    prog = basename(argv[0])

    if prog == "__main__.py":
        prog = "python -m xconv"

    parser = ArgumentParser(prog=prog,
        usage="""%(prog)s [-h | -l | -i PROFILE]
       %(prog)s [option]... -p PROFILE [-DNAME[=VALUE]]... [-B] [-T] input output
       %(prog)s [option]... -p PROFILE [-DNAME[=VALUE]]...  -M  [-T] inputs... output
       %(prog)s [option]... -p PROFILE [-DNAME[=VALUE]]...  -C  [-T] inputs... output
       %(prog)s [option]... -p PROFILE [-DNAME[=VALUE]]... [-B] inputs... directory
       %(prog)s [option]... -p PROFILE [-DNAME[=VALUE]]... [-B] -t directory inputs...""",
        description="""FFmpeg wrapper based on AdvancedAV""")

    parser.add_argument("-V", "--version",              help="Show version and quit",                                               action="version",
        version="""XConv %s""" % version)

    # Available Options
    parser.add_argument("-v", "--verbose",              help="Enable verbose output",                                               action="store_true")
    parser.add_argument("-q", "--quiet",                help="Be less verbose",                                                     action="store_true")
    parser.add_argument("-j", "--concurrent",           help="Run ffmpeg concurrently using at most N instances [%(default)s]", metavar="N", default=cpu_count())
    profile = parser.add_argument_group("Profile")
    profile.add_argument("-l", "--list-profiles",       help="List profiles and quit",                                              action=ProfilesAction)
    profile.add_argument("-i", "--profile-info",        help="Give info about a profile and quit",          metavar="PROFILE",      action=ProfileInfoAction)
    profile.add_argument("-p", "--profile",             help="Specify the profile",                         metavar="PROFILE",      required=True)
    profile.add_argument("-D", "--define",              help="Define an option to be used by the profile",  metavar="NAME[=VALUE]", action=DefineAction)
    mode = parser.add_argument_group("Mode").add_mutually_exclusive_group()
    mode.add_argument("-B", "--batch",                  help="Batch process every input file into an output file (default)",        action="store_true")
    mode.add_argument("-M", "--merge",                  help="Merge streams from all inputs",                                       action="store_true")
    mode.add_argument("-C", "--concat",                 help="Concatenate streams from inputs",                                     action="store_true")
    files = parser.add_argument_group("Files")
    files.add_argument("inputs",                        help="The input file(s)",                                                   nargs="+")
    files.add_argument("output",                        help="The output filename or directory (unless -t is given)",               nargs="?") # always empty
    files.add_argument("-u", "--update",                help="Only work on files that don't already exist",                         action="store_true")
    files.add_argument("-c", "--create-directory",      help="Create directories if they don't exist",                              action="store_true")
    target = files.add_mutually_exclusive_group()
    target.add_argument("-t", "--target-directory",     help="Output into a directory",                     metavar="DIRECTORY",    type=Path)
    target.add_argument("-T", "--no-target-directory",  help="Treat output as a normal file",                                       action="store_true")
    files.add_argument("-S", "--subdirectory",          help="Work in a subdirectory of here and -t (use glob patterns for inputs)")
    files.add_argument("-K", "--copy-files",            help="Copy all following files unmodified",         metavar="FILE",         action=ExtendAction)
    progs = parser.add_argument_group("Programs")
    progs.add_argument("--ffmpeg",                      help="Path to the ffmpeg executable",                                       default="ffmpeg")
    progs.add_argument("--ffprobe",                     help="Path to the ffprobe executable",                                      default="ffprobe")

    # Parse arguments
    args = parser.parse_args(argv[1:])

    # Figure out output path
    # ----------------------
    # Fill in args.output
    # args.output will never be filled in by argparse, since inputs consumes everything
    if args.target_directory:
        args.output = args.target_directory
    elif len(args.inputs) < 2:
        parser.error("Neither --target-directory nor output is given")
    else:
        args.output = Path(args.inputs.pop(-1))

    if args.subdirectory:
        subdir = Path(args.subdirectory)#.resolve()
        outdir = Path(args.output, args.subdirectory)#.resolve()

        if outdir.exists() and not outdir.is_dir():
            parser.error("--subdirectory only works with output directories. '%s' exists and isn't a directory")

        inputs = args.inputs
        args.inputs = []
        for pattern in inputs:
            args.inputs.extend(subdir.glob(pattern))

        files = args.copy_files
        args.copy_files = []
        for pattern in files:
            args.copy_files.extend(subdir.glob(pattern))

        args.output_directory = args.output = outdir
        args.output_filename = None

    else:
        # Check if we're outputting to a directory
        multiple_outputs = args.copy_files or not (args.merge or args.concat) and len(args.inputs) > 1

        if args.target_directory or args.output.is_dir() or multiple_outputs:
            if args.no_target_directory:
                if multiple_outputs:
                    parser.error("Passed --no-target-directory, but operation would have multiple outputs. (See --merge or --concat)")
                else:
                    parser.error("Passed --no-target-directory, but '%s' is an existing directory." % args.output)
            args.output_filename = None
            args.output_directory = args.output
        else:
            args.output_filename = args.output.name
            args.output_directory = args.output.parent

    return args
