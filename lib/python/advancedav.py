"""
AdvancedAV FFmpeg commandline generator v3.0 [Library Edition]
-----------------------------------------------------------
    AdvancedAV helps with constructing FFmpeg commandline arguments.

    It can automatically parse input files with the help of FFmpeg's ffprobe tool (WiP)
    and allows programatically mapping streams to output files and setting metadata on them.
-----------------------------------------------------------
    Copyright 2014-2017 Taeyeon Mori

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

import os
import sys
import json
import logging
import subprocess
import collections
import itertools

from abc import ABCMeta, abstractmethod
from typing import Iterable, Mapping, Sequence, Iterator, MutableMapping
from pathlib import Path, PurePath


__all__ = "AdvancedAVError", "AdvancedAV", "SimpleAV"

version_info = 2, 99, 0

# Constants
DEFAULT_CONTAINER = "matroska"

S_AUDIO = "a"
S_VIDEO = "v"
S_SUBTITLE = "s"
S_ATTACHMENT = "t"
S_DATA = "d"
S_UNKNOWN = "u"


# == Exceptions ==
class AdvancedAVError(Exception):
    pass


# == Helpers ==
def ffmpeg_int(no: str) -> int:
    if isinstance(no, str):
        factor = 1
        base = 1000
        if no[-1].lower() == "b":
            factor *= 8
            no = no[:-1]
        if no[-1].lower() == "i":
            base = 1024
            no = no[:-1]
        if not no[-1].isdigit():
            factor *= base ** (["k", "m", "g"].index(no[-1].lower()) + 1)
            no = no[:-1]
        return int(no) * factor
    return int(no)


# == Base Classes ==
class ObjectWithOptions:
    """
    Options refer to ffmpeg commandline arguments, referring to a specific Task, File or Stream.

    Option values can be:
        - str: pass value
        - int: convert to string, pass value
        - list, tuple: pass option multiple times, with different values
        - True: pass option without value
        - None: pass option without value (deprecated)

    For option names, refer to the FFmpeg documentation.

    Subclasses must provide an 'options' slot.
    """
    __slots__ = ()

    def __init__(self, *, options=None, **more):
        super().__init__(**more)
        self.options = options or {}

    def apply(self, source, *names, **omap):
        """
        Selectively apply options from a dictionary.

        Option names passed as strings will be applied as-is,
        option names passed as keyword arguments will be applied as though they were named the argument's value

        :return: self, for method chaining
        """
        for name in names:
            if name in source:
                self.options[name] = source[name]
        if omap:
            for define, option in omap.items():
                if define in source:
                    self.options[option] = source[define]
        return self

    def set(self, **options):
        """
        Set options on this object

        Applies all keyword arguments as options

        :return: self, for method chaining
        """
        self.options.update(options)
        return self


class ObjectWithMetadata:
    __slots__ = ()

    def __init__(self, *, metadata=None, **more):
        super().__init__(**more)
        self.metadata = metadata or {}

    def apply_meta(self, source, *names, **mmap):
        for name in names:
            if name in source:
                self.metadata[name] = source[name]
        if mmap:
            for name, key in mmap.items():
                if name in source:
                    self.metadata[key] = source[name]
        return self

    def meta(self, **metadata):
        self.metadata.update(metadata)
        return self


# == Descriptors ==
class DescriptorBase:
    __slots__ = "owner", "name"

    def __init__(self, default_name="(Name Unknown)"):
        self.owner = None
        self.name = default_name

    def __set_name__(self, owner, name):
        self.owner = owner
        self.name = name

    repr_info = ""

    def __repr__(self):
        return "<%s %s of %s%s>" % (type(self).__name__, self.name, self.owner, self.repr_info)


class InformationProperty(DescriptorBase):
    """
    A read-only property referring ffprobe information
    """
    __slots__ = "path", "type"

    def __init__(self, *path, type=lambda x: x):
        super().__init__()
        self.path = path
        self.type = type

    @property
    def repr_info(self):
        return " referring to %s" % self.path

    def __get__(self, object, obj_type=None):
        info = object.information
        try:
            for seg in self.path:
                info = info[seg]
        except (KeyError, IndexError):
            return None
        else:
            return self.type(info)


class OptionProperty(DescriptorBase):
    """
    A read-write descriptor referring to ffmpeg options

    Unset options will return None,
    setting an option to None will unset it.

    Note: This differs from deprecated behaviour when setting options directly,
          which will cause the option to be passed without arguments.
    """
    __slots__ = "candidates", "type"

    def __init__(self, *candidates, type=lambda x: x):
        super().__init__()
        self.candidates = candidates
        self.type = type

    @property
    def repr_info(self):
        return " referencing option %s" % self.candidates[0]

    def __get__(self, object, obj_type=None):
        for candidate in self.candidates:
            if candidate in object.options:
                return self.type(object.options[candidate])
        else:
            return None

    def __set__(self, object, value):
        for candidate in self.candidates:
            if candidate in object.options:
                del object.options[candidate]
        if value is not None:
            object.options[self.candidates[0]] = value

    def __delete__(self, object):
        self.__set__(object, None)


# === Stream Classes ===
class Stream:
    """
    Abstract stream base class

    One continuous stream of data muxed into a container format
    """
    __slots__ = "file",

    def __init__(self, file: "File", **more):
        super().__init__(**more)
        self.file = file

    @property
    def index(self):
        return 0

    @property
    def pertype_index(self):
        return None

    @property
    def type(self):
        return S_UNKNOWN

    @property
    def stream_spec(self):
        """ The StreamSpecification in the form of "<type>:<#stream_of_type>" or "<#stream>" """
        if self.pertype_index is not None:
            return "{}:{}".format(self.type, self.pertype_index)
        else:
            return str(self.index)

    def __repr__(self):
        return "<%s \"%s\"#%i (%s#%i)>" % (type(self).__name__, self.file.name, self.index, self.type, self.pertype_index)


# Input Streams
class InputStream(Stream):
    """
    Holds information about an input stream
    """
    __slots__ = "information", "pertype_index"

    def __init__(self, file: "InputFile", info: dict, pertype_index: int=None):
        super().__init__(file)

        self.information = info
        self.pertype_index = pertype_index

    @property
    def type(self):
        return self.information["codec_type"][0]

    index       = InformationProperty("index", type=int)

    codec       = InformationProperty("codec_name")
    codec_name  = InformationProperty("codec_long_name")
    profile     = InformationProperty("profile")

    duration    = InformationProperty("duration", type=float)
    duration_ts = InformationProperty("duration_ts", type=int)

    start_time  = InformationProperty("start_time")

    bitrate     = InformationProperty("bit_rate", type=int)
    max_bitrate = InformationProperty("max_bit_rate", type=int)
    nb_frames   = InformationProperty("nb_frames", type=int)

    @property
    def disposition(self):
        try:
            return tuple(k for k, v in self.information["disposition"].items() if v)
        except KeyError:
            return ()

    language    = InformationProperty("tags", "language")


class InputAudioStream(InputStream):
    __slots__ = ()

    def  __init__(self, file: "InputFile", info: dict, pertype_index: int=None):
        if info["codec_type"][0] != S_AUDIO:
            raise ValueError("Cannot create %s from stream info of type %s" % (type(self).__name__, info["codec_type"]))

        super().__init__(file, info)

    @property
    def type(self):
        return S_AUDIO

    sample_format   = InformationProperty("sample_format")
    sample_rate     = InformationProperty("sample_rate", type=int)

    channels        = InformationProperty("channels", type=int)
    channel_layout  = InformationProperty("channel_layout")


def input_stream_factory(file, info, pertype_index=None):
    return {
        "audio": InputAudioStream,
    }.get(info["codec_type"], InputStream)(file, info, pertype_index)


# Output Streams
class OutputStream(Stream, ObjectWithOptions, ObjectWithMetadata):
    """
    Holds information about a mapped output stream
    """
    __slots__ = "index", "pertype_index", "source", "options", "metadata"

    # TODO: support other parameters like frame resolution

    def __init__(self, file: "OutputFile", source: InputStream, stream_id: int, stream_pertype_id: int=None,
                 options: Mapping=None, metadata: MutableMapping=None):
        super().__init__(file=file, options=options, metadata=metadata)
        self.index = stream_id
        self.pertype_index = stream_pertype_id
        self.source = source

    @property
    def type(self):
        return self.source.type

    def _update_indices(self, index: int, pertype_index: int=None):
        """ Update the Stream indices """
        self.index = index
        if pertype_index is not None:
            self.pertype_index = pertype_index

    codec = OptionProperty("codec", "c")

    bitrate = OptionProperty("b", type=ffmpeg_int)


class OutputVideoStream(OutputStream):
    def downscale(self, width, height):
        # Scale while keeping aspect ratio; never upscale.
        self.options["filter_complex"] = "scale=iw*min(1\,min(%i/iw\,%i/ih)):-1" % (width, height)
        return self


def output_stream_factory(file, source, *args, **more):
    return {
        S_VIDEO: OutputVideoStream,
    }.get(source.type, OutputStream)(file, source, *args, **more)


# === File Classes ===
class File(ObjectWithOptions):
    """
    ABC for Input- and Output-Files
    """
    __slots__ = "_streams", "_streams_by_type", "options", "path"

    def __init__(self, path: Path, options: dict=None, **more):
        super().__init__(options=options, **more)

        self.path = Path(path)

        self._streams = []
        """ :type: list[Stream] """

        self._streams_by_type = collections.defaultdict(list)
        """ :type: dict[str, list[Stream]] """

    # Filename
    @property
    def name(self):
        """
        The file's name
        Changed in 3.0: previously, full path
        """
        return self.path.name

    @name.setter
    def name(self, value):
        self.path = self.path.with_name(value)

    @property
    def filename(self):
        """
        The file's full path as string
        """
        return str(self.path)

    @filename.setter
    def filename(self, value):
        self.path = Path(value)

    # Streams
    def _add_stream(self, stream: Stream):
        """ Add a stream """
        stream._update_indices(len(self._streams), len(self._streams_by_type[stream.type]))
        self._streams.append(stream)
        self._streams_by_type[stream.type].append(stream)

    @property
    def streams(self) -> Sequence:
        """ The streams contained in this file

        :rtype: Sequence[Stream]
        """
        return self._streams

    @property
    def video_streams(self) -> Sequence:
        """ All video streams

        :rtype: Sequence[Stream]
        """
        return self._streams_by_type[S_VIDEO]

    @property
    def audio_streams(self) -> Sequence:
        """ All audio streams

        :rtype: Sequence[Stream]
        """
        return self._streams_by_type[S_AUDIO]

    @property
    def subtitle_streams(self) -> Sequence:
        """ All subtitle streams

        :rtype: Sequence[Stream]
        """
        return self._streams_by_type[S_SUBTITLE]

    @property
    def attachment_streams(self) -> Sequence:
        """ All attachment streams (i.e. Fonts)

        :rtype: Sequence[Stream]
        """
        return self._streams_by_type[S_ATTACHMENT]

    @property
    def data_streams(self) -> Sequence:
        """ All data streams

        :rtype: Sequence[Stream]
        """
        return self._streams_by_type[S_DATA]

    def __repr__(self):
        return "<%s \"%s\">" % (type(self).__name__, self.name)


class InputFileChapter:
    __slots__ = "file", "information"

    def __init__(self, file, info):
        self.file = file
        self.information = info

    def __repr__(self):
        return "<InputFileChapter #%i of %s from %.0fs to %.0fs (%s)>" \
                % (self.index, self.file, self.start_time, self.end_time, self.title)

    start_time  = InformationProperty("start_time", type=float)
    end_time    = InformationProperty("end_time", type=float)

    index       = InformationProperty("id", type=int)
    title       = InformationProperty("tags", "title")


class InputFile(File):
    """
    Holds information about an input file

    :note: Modifying the options after accessing the streams results in undefined
            behaviour! (Currently: Changes will only apply to conv call)
    """
    __slots__ = "pp", "_information"

    stream_factory = staticmethod(input_stream_factory)

    def __init__(self, pp: "AdvancedAV", path: str, options: Mapping=None, info=None):
        super().__init__(path, options=dict(options.items()) if options else None)

        self.pp = pp
        self._information = info

    @property
    def information(self):
        if self._information is None:
            self._initialize_info()
        return self._information

    # -- Initialize
    ffprobe_args = "-show_format", "-show_streams", "-show_chapters", "-print_format", "json"

    def _initialize_info(self):
        probe = self.pp.call_probe(tuple(Task.argv_options(self.options))
                                    + self.ffprobe_args
                                    + ("-i", self.filename))
        self._information = json.loads(probe)

    def _initialize_streams(self):
        """ Parse the ffprobe output

        The locale of the probe output in \param probe should be C!
        """
        for sinfo in self.information["streams"]:
            stype = sinfo["codec_type"][0]
            stream = self.stream_factory(self, sinfo, len(self._streams_by_type[stype]))
            self._streams.append(stream)
            self._streams_by_type[stype].append(stream)

    # -- Streams
    @property
    def streams(self) -> Sequence:
        """ Collect the available streams

        :rtype: Sequence[InputStream]
        """
        if not self._streams:
            self._initialize_streams()
        return self._streams

    @property
    def video_streams(self) -> Sequence:
        """ All video streams

        :rtype: Sequence[InputStream]
        """
        if not self._streams:
            self._initialize_streams()
        return self._streams_by_type[S_VIDEO]

    @property
    def audio_streams(self) -> Sequence:
        """ All audio streams

        :rtype: Sequence[InputStream]
        """
        if not self._streams:
            self._initialize_streams()
        return self._streams_by_type[S_AUDIO]

    @property
    def subtitle_streams(self) -> Sequence:
        """ All subtitle streams

        :rtype: Sequence[InputStream]
        """
        if not self._streams:
            self._initialize_streams()
        return self._streams_by_type[S_SUBTITLE]

    @property
    def attachment_streams(self) -> Sequence:
        """ All attachment streams (i.e. Fonts)

        :rtype: Sequence[InputStream]
        """
        if not self._streams:
            self._initialize_streams()
        return self._streams_by_type[S_ATTACHMENT]

    @property
    def data_streams(self) -> Sequence:
        """ All data streams

        :rtype: Sequence[InputStream]
        """
        if not self._streams:
            self._initialize_streams()
        return self._streams_by_type[S_DATA]

    # Information
    nb_streams  = InformationProperty("format", "nb_streams", type=int)

    duration    = InformationProperty("format", "duration", type=float)

    size        = InformationProperty("format", "size", type=int)
    bitrate     = InformationProperty("format", "bit_rate", type=int)

    # Metadata
    metadata    = InformationProperty("format", "tags")

    title       = InformationProperty("format", "tags", "title")
    artist      = InformationProperty("format", "tags", "artist")
    album       = InformationProperty("format", "tags", "album")

    # Chapters
    @property
    def chapters(self) -> Sequence[InputFileChapter]:
        return list(InputFileChapter(self, i) for i in self.information["chapters"])


class OutputFile(File, ObjectWithMetadata):
    """
    Holds information about an output file
    """
    __slots__ = "task", "container", "_mapped_sources", "metadata"

    stream_factory = staticmethod(output_stream_factory)

    def __init__(self, task: "Task", name: str, container=DEFAULT_CONTAINER,
            options: Mapping=None, metadata: Mapping=None):
        super().__init__(name, options=options, metadata=metadata)

        self.options.setdefault("c", "copy")

        self.task = task

        self.container = container
        """ :type: dict[str, str] """

        self._mapped_sources = set()
        """ :type: set[InputStream] """

    # -- Map Streams
    def map_stream_(self, stream: InputStream, codec: str=None, options: Mapping=None) -> OutputStream:
        """ map_stream() minus add_input_file

        map_stream() needs to ensure that the file the stream originates from is registered as input to this Task.
        However, when called repeatedly on streams of the same file, that is superflous.
        """
        out = self.stream_factory(self, stream, -1, -1, codec, options)

        self._add_stream(out)
        self._mapped_sources.add(stream)

        self.task.pp.to_debug("Mapping Stream %s => %s (%i)",
                              self.task.qualified_input_stream_spec(stream),
                              out.stream_spec,
                              self.task.outputs.index(self))
        return out

    def map_stream(self, stream: InputStream, codec: str=None, options: Mapping=None) -> OutputStream:
        """ Map an input stream to the output

        Note that this will add multiple copies of an input stream to the output when called multiple times
        on the same input stream. Check with is_stream_mapped() beforehand if the stream might already be mapped.
        """
        self.task.add_input(stream.file)
        return self.map_stream_(stream, codec, options)

    def is_stream_mapped(self, stream: InputStream) -> bool:
        """ Test if an input stream is already mapped """
        return stream in self._mapped_sources

    def get_mapped_stream(self, stream: InputStream) -> OutputStream:
        """ Get the output stream this input stream is mapped to """
        for out in self._streams:
            if out.source == stream:
                return out

    # -- Map multiple Streams
    def map_all_streams(self, file: "str | InputFile", return_existing: bool=False) -> Sequence:
        """ Map all streams in \param file

        Note that this will only map streams that are not already mapped.

        :rtype: Sequence[OutputStream]
        """
        out_streams = []
        for stream in self.task.add_input(file).streams:
            if stream in self._mapped_sources:
                if return_existing:
                    out_streams.append(self.get_mapped_stream(stream))
            else:
                out_streams.append(self.map_stream_(stream))

        return out_streams

    def merge_all_files(self, files: Iterable, return_existing: bool=False) -> Sequence:
        """ Map all streams from multiple files

        Like map_all_streams(), this will only map streams that are not already mapped.

        :type files: Iterable[str | InputFile]
        :rtype: Sequence[OutputStream]
        """
        out_streams = []
        for file in files:
            for stream in self.task.add_input(file).streams:
                if stream in self._mapped_sources:
                    if return_existing:
                        out_streams.append(self.get_mapped_stream(stream))
                else:
                    out_streams.append(self.map_stream_(stream))

        return out_streams

    # -- Sort Streams
    def reorder_streams(self):
        """ Sort the mapped streams by type """
        self._streams.clear()

        for stream in itertools.chain(self.video_streams,
                                      self.audio_streams,
                                      self.subtitle_streams):
            stream._update_indices(len(self._streams))
            self._streams.append(stream)
        return self


# === Task Classes ===
class Task:
    """
    Holds information about an AV-processing Task.

    A Task is a collection of Input- and Output-Files and related options.
    While OutputFiles are bound to one task at a time, InputFiles can be reused across Tasks.
    """

    output_factory = OutputFile

    def __init__(self, pp: "AdvancedAV"):
        super().__init__()

        self.pp = pp

        self.inputs = []
        """ :type: list[InputFile] """
        self.inputs_by_name = {}
        """ :type: dict[str, InputFile] """

        self.outputs = []
        """ :type: list[OutputFile] """

    # -- Manage Inputs
    def add_input(self, file: "str | InputFile") -> InputFile:
        """ Register an input file

        When \param file is already registered as input file to this Task, do nothing.

        :param file: Can be either the filename of an input file or an InputFile object.
                        The latter will be created if the former is passed.
        """
        if  isinstance(file, PurePath): # Pathlib support
            file = str(file)
        if  isinstance(file, str):
            if file in self.inputs_by_name:
                return self.inputs_by_name[file]

            file = self.pp.create_input(file)

        if file not in self.inputs:
            self.pp.to_debug("Adding input file #%i: %s", len(self.inputs), file.name)
            self.inputs.append(file)
            self.inputs_by_name[file.filename] = file

        return file

    def qualified_input_stream_spec(self, stream: InputStream) -> str:
        """ Construct the qualified input stream spec (combination of input file number and stream spec)

        None will be returned if stream's file isn't registered as an input to this Task
        """
        file_index = self.inputs.index(stream.file)
        if file_index >= 0:
            return "{}:{}".format(file_index, stream.stream_spec)

    # -- Manage Outputs
    def add_output(self, filename: str, container: str=DEFAULT_CONTAINER, options: Mapping=None) -> OutputFile:
        """ Add an output file

        NOTE: Contrary to add_input this will NOT take an OutputFile instance and return it.
        """
        for outfile in self.outputs:
            if outfile.filename == filename:
                raise AdvancedAVError("Output File '%s' already added." % filename)
        else:
            outfile = self.output_factory(self, filename, container, options)
            self.pp.to_debug("New output file #%i: %s", len(self.outputs), filename)
            self.outputs.append(outfile)
            return outfile

    # -- Manage Streams
    def iter_video_streams(self) -> Iterator:
        for input_ in self.inputs:
            yield from input_.video_streams

    def iter_audio_streams(self) -> Iterator:
        for input_ in self.inputs:
            yield from input_.audio_streams

    def iter_subtitle_streams(self) -> Iterator:
        for input_ in self.inputs:
            yield from input_.subtitle_streams

    def iter_attachment_streams(self) -> Iterator:
        for input_ in self.inputs:
            yield from input_.attachment_streams

    def iter_data_streams(self) -> Iterator:
        for input_ in self.inputs:
            yield from input_.data_streams

    def iter_streams(self) -> Iterator:
        for input_ in self.inputs:
            yield from input_.streams

    def iter_chapters(self) -> Iterator[InputFileChapter]:
        for input_ in self.inputs:
            yield from input_.chapters

    # -- FFmpeg
    @staticmethod
    def argv_options(options: Mapping, qualifier: str=None) -> Iterator:
        """ Yield arbitrary options

        :type options: Mapping[str, str]
        :rtype: Iterator[str]
        """
        if qualifier is None:
            opt_fmt = "-%s"
        else:
            opt_fmt = "-%%s:%s" % qualifier
        for option, value in options.items():
            yield opt_fmt % option
            if isinstance(value, (tuple, list)):
                yield str(value[0])
                for x in value[1:]:
                    yield opt_fmt % option
                    yield str(x)
            elif value is not True and value is not None:
                yield str(value)

    @staticmethod
    def argv_metadata(metadata: Mapping, qualifier: str=None) -> Iterator:
        """ Yield arbitrary metadata

        :type metadata: Mapping[str, str]
        :rtype: Iterator[str]
        """
        if qualifier is None:
            opt = "-metadata"
        else:
            opt = "-metadata:%s" % qualifier
        for meta in metadata.items():
            yield opt
            yield "%s=%s" % meta

    def generate_args(self) -> Iterator:
        """ Generate the ffmpeg commandline for this task

        :rtype: Iterator[str]
        """
        # Inputs
        for input_ in self.inputs:
            # Input options
            yield from self.argv_options(input_.options)

            # Add Input
            yield "-i"
            filename = input_.filename
            if filename[0] == '-':
                yield "./" + filename
            else:
                yield filename

        # Outputs
        for output in self.outputs:
            # Global Metadata & Additional Options
            yield from self.argv_metadata(output.metadata)
            yield from self.argv_options(output.options)

            # Map Streams, sorted by type
            output.reorder_streams()

            for stream in output.streams:
                yield "-map"
                yield self.qualified_input_stream_spec(stream.source)

                if stream.codec is not None:
                    yield "-c:%s" % stream.stream_spec
                    yield stream.codec

                yield from self.argv_metadata(stream.metadata, stream.stream_spec)
                yield from self.argv_options(stream.options, stream.stream_spec)

            # Container
            if output.container is not None:
                yield "-f"
                yield output.container

            # Output Filename, prevent it from being interpreted as option
            out_fn = output.filename
            yield out_fn if out_fn[0] != "-" else "./" + out_fn

    def commit(self, additional_args: Iterable=()):
        """
        Commit the changes.

        additional_args is used to pass global arguments to ffmpeg. (like -y)

        :type additional_args: Iterable[str]
        :raises: AdvancedAVError when FFmpeg fails
        """
        self.pp.call_conv(itertools.chain(additional_args, self.generate_args()))


class SimpleTask(Task):
    """
    A simple task with only one output file

    All members of the OutputFile can be accessed on the SimpleTask directly, as well as the usual Task methods.
    Usage of add_output should be avoided however, because it would lead to confusion.
    """
    def __init__(self, pp: "AdvancedAV", filename: str, container: str=DEFAULT_CONTAINER, options: Mapping=None):
        super().__init__(pp)

        self.output = self.add_output(filename, container, options)

    def __getattr__(self, attr: str):
        """ You can directly access the OutputFile from the SimpleTask instance """
        return getattr(self.output, attr)

    # Allow assignment to these OutputFile members
    def _redir(attr, name):
        def redir_get(self):
            return getattr(getattr(self, attr), name)
        def redir_set(self, value):
            setattr(getattr(self, attr), name, value)
        return property(redir_get, redir_set)

    container = _redir("output", "container")
    metadata = _redir("output", "metadata")
    options = _redir("output", "options")
    name = _redir("output", "name") # Deprecated! use filename instead. 'name' will be reused in the future
    filename = _redir("output", "name")

    del _redir


# === Interface Class ===
class AdvancedAV(metaclass=ABCMeta):
    input_factory = InputFile

    # ---- Output ----
    @abstractmethod
    def get_logger(self):
        """
        Get a stdlib logger to output to
        """
        pass

    def to_screen(self, text, *fmt):
        self.get_logger().log(text % fmt)

    def to_debug(self, text, *fmt):
        self.get_logger().debug(text % fmt)

    # ---- FFmpeg ----
    @abstractmethod
    def call_conv(self, args: Iterable):
        """
        Call ffmpeg.
        :param args: Iterable[str] The ffprobe arguments
        It should throw an AdvancedAVError if the call fails
        """
        pass

    @abstractmethod
    def call_probe(self, args: Iterable) -> str:
        """
        Call ffprobe.
        :param args: Iterable[str] The ffprobe arguments
        :return: str the standard output
        It should throw an AdvancedAVError if the call fails
        NOTE: Make sure the locale is set to C so the regexes match
        """
        pass

    # ---- Create Tasks ----
    def create_task(self) -> Task:
        """
        Create a AdvancedAV Task.
        """
        return Task(self)

    def create_job(self, filename: str, container: str=DEFAULT_CONTAINER, options: Mapping=None) -> SimpleTask:
        """
        Create a simple AdvandecAV task
        :param filename: str The resulting filename
        :param container: str The output container format
        :param options: Additional Options for the output file
        :return: SimpleTask An AdvancedAV Task
        """
        return SimpleTask(self, filename, container, options)

    # ---- Create InputFiles ----
    def create_input(self, filename: str, options=None):
        """
        Create a InputFile instance
        :param filename: str The filename
        :param optiona: Mapping Additional Options
        :return: A InputFile instance
        NOTE that Task.add_input is usually the preferred way to create inputs
        """
        return self.input_factory(self, filename, options=options)


class SimpleAV(AdvancedAV):
    """
    A simple Implementation of the AdvancedAV interface.

    It uses the python logging module for messages and expects the ffmpeg/ffprobe executables as arguments
    """
    global_args = ()
    global_conv_args = ()
    global_probe_args = ()

    def __init__(self, *, ffmpeg="ffmpeg", ffprobe="ffprobe", logger=None, ffmpeg_output=True):
        if logger is None:
            self.logger = logging.getLogger("advancedav.SimpleAV")
        else:
            self.logger = logger
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self.ffmpeg_output = ffmpeg_output
        self.logger.debug("SimpleAV initialized.")

    def get_logger(self):
        return self.logger

    _posix_env = dict(os.environ)
    _posix_env["LANG"] = _posix_env["LC_ALL"] = "C"

    def call_conv(self, args: Iterable):
        """ Actually call ffmpeg

        :type args: Iterable[str]
        """
        argv = tuple(itertools.chain((self._ffmpeg,), self.global_args, self.global_conv_args, args))

        self.to_debug("Running Command: %s", argv)

        output = None if self.ffmpeg_output else subprocess.DEVNULL

        subprocess.call(argv, stdout=output, stderr=output)

    def call_probe(self, args: Iterable):
        """ Call ffprobe (With LANG=LC_ALL=C)

        :type args: Iterable[str]
        """
        argv = tuple(itertools.chain((self._ffprobe,), self.global_args, self.global_probe_args, args))

        self.to_debug("Running Command: %s", argv)

        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self._posix_env)

        out, err = proc.communicate()

        if proc.returncode != 0:
            err = err.decode("utf-8", "replace")
            msg = err.strip().split('\n')[-1]
            raise AdvancedAVError(msg)

        return out.decode("utf-8", "replace")
