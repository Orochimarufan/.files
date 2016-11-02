"""
AdvancedAV FFmpeg commandline generator v2.0 [Library Edition]
-----------------------------------------------------------
    AdvancedAV helps with constructing FFmpeg commandline arguments.

    It can automatically parse input files with the help of FFmpeg's ffprobe tool (WiP)
    and allows programatically mapping streams to output files and setting metadata on them.
-----------------------------------------------------------
    Copyright 2014-2016 Taeyeon Mori

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
import re
import subprocess
import collections
import itertools

from abc import ABCMeta, abstractmethod
from collections.abc import Iterable, Mapping, Sequence, Iterator, MutableMapping

__all__ = "AdvancedAVError", "AdvancedAV", "SimpleAV"

version_info = 2, 1, 0

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


# == Base Classes ==
class ObjectWithOptions:
    __slots__ = ()

    def __init__(self, *, options=None, **more):
        super().__init__(**more)
        self.options = options or {}

    def apply(self, source, *names, **omap):
        for name in names:
            if name in source:
                self.options[name] = source[name]
        if omap:
            for define, option in omap.items():
                if define in source:
                    self.options[option] = source[define]
        return self

    def set(self, **options):
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


# === Stream Classes ===
class Stream:
    """
    Abstract stream base class

    One continuous stream of data muxed into a container format
    """
    __slots__ = "file", "type", "index", "pertype_index", "codec", "profile"

    def __init__(self, file: "File", type: str, index: int=None, pertype_index: int=None,
                 codec: str=None, profile: str=None, **more):
        super().__init__(**more)
        self.file = file
        self.type = type
        self.index = index
        self.pertype_index = pertype_index
        self.codec = codec
        self.profile = profile

    def _update_indices(self, index: int, pertype_index: int=None):
        """ Update the Stream indices """
        self.index = index
        if pertype_index is not None:
            self.pertype_index = pertype_index

    @property
    def stream_spec(self):
        """ The StreamSpecification in the form of "<type>:<#stream_of_type>" or "<#stream>" """
        if self.pertype_index is not None:
            return "{}:{}".format(self.type, self.pertype_index)
        else:
            return str(self.index)

    def __str__(self):
        return "<%s %s#%i: %s %s (%s)>" % (type(self).__name__, self.file.name, self.index,
                                           self.type, self.codec, self.profile)


class InputStream(Stream):
    """
    Holds information about an input stream
    """
    __slots__ = "language"

    def __init__(self, file: "InputFile", type_: str, index: int, language: str, codec: str, profile: str):
        super().__init__(file, type_, index, codec=codec, profile=profile)
        self.file = file
        self.language = language

    def _update_indices(self, index: int, pertype_index: int=None):
        """ InputStreams should not have their indices changed. """
        if index != self.index:
            raise ValueError("Cannot update indices on InputStreams! (This might mean there are bogus ids in the input")
        # pertype_index gets updated by File._add_stream() so we don't throw up if it gets updated


class OutputStream(Stream, ObjectWithOptions, ObjectWithMetadata):
    """
    Holds information about a mapped output stream
    """
    __slots__ = "source", "options", "metadata"

    # TODO: support other parameters like frame resolution

    # Override polymorphic types
    #file = None
    """ :type: OutputFile """

    def __init__(self, file: "OutputFile", source: InputStream, stream_id: int, stream_pertype_id: int=None,
                 codec: str=None, options: Mapping=None, metadata: MutableMapping=None):
        super().__init__(file=file, type=source.type, index=stream_id, pertype_index=stream_pertype_id,
            codec=codec, options=options, metadata=metadata)
        self.source = source


class OutputVideoStream(OutputStream):
    def downscale(self, width, height):
        # Scale while keeping aspect ratio; never upscale.
        self.options["filter_complex"] = "scale=iw*min(1\,min(%i/iw\,%i/ih)):-1" % (width, height)
        return self


def output_stream_factory(file, source, *args, **more):
    return (OutputVideoStream if source.type == S_VIDEO else OutputStream)(file, source, *args, **more)


# === File Classes ===
class File(ObjectWithOptions):
    """
    ABC for Input- and Output-Files
    """
    __slots__ = "name", "_streams", "_streams_by_type", "options"

    def __init__(self, name: str, options: dict=None, **more):
        super().__init__(options=options, **more)

        self.name = name

        self.options = options if options is not None else {}
        """ :type: dict[str, str] """

        self._streams = []
        """ :type: list[Stream] """

        self._streams_by_type = collections.defaultdict(list)
        """ :type: dict[str, list[Stream]] """

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

    @property
    def filename(self) -> str:
        """ Alias for .name """
        return self.name

    def __str__(self):
        return "<%s %s>" % (type(self).__name__, self.name)


class InputFile(File):
    """
    Holds information about an input file

    :note: Modifying the options after accessing the streams results in undefined
            behaviour! (Currently: Changes will only apply to conv call)
    """
    __slots__ = "pp", "_streams_initialized"

    stream_factory = InputStream

    def __init__(self, pp: "AdvancedAV", filename: str, options: Mapping=None):
        super().__init__(name=filename, options=dict(options.items()) if options else None)

        self.pp = pp

        self._streams_initialized = False

    # -- Probe streams
    _reg_probe_streams = re.compile(
        r"Stream #0:(?P<id>\d+)(?:\((?P<lang>[^\)]+)\))?:\s+(?P<type>\w+):\s+(?P<codec>[\w_\d]+)"
        r"(?:\s+\((?P<profile>[^\)]+)\))?(?:\s+(?P<extra>.+))?"
    )

    @staticmethod
    def _stream_type(type_: str) -> str:
        """ Convert the ff-/avprobe type output to the notation used on the ffmpeg/avconv commandline """
        lookup = {
            "Audio": S_AUDIO,
            "Video": S_VIDEO,
            "Subtitle": S_SUBTITLE,
            "Attachment": S_ATTACHMENT,
            "Data": S_DATA
        }

        return lookup.get(type_, S_UNKNOWN)

    def _initialize_streams(self, probe: str=None) -> Iterator:
        """ Parse the ffprobe output

        The locale of the probe output in \param probe should be C!

        :rtype: Iterator[InputStream]
        """
        if probe is None:
            if self.options:
                probe = self.pp.call_probe(itertools.chain(Task.argv_options(self.options), ("-i", self.name)))
            else:
                probe = self.pp.call_probe(("-i", self.name))

        for match in self._reg_probe_streams.finditer(probe):
            self._add_stream(self.stream_factory(self,
                                                 self._stream_type(match.group("type")),
                                                 int(match.group("id")),
                                                 match.group("lang"),
                                                 match.group("codec"),
                                                 match.group("profile")))
        self._streams_initialized = True

    @property
    def streams(self) -> Sequence:
        """ Collect the available streams

        :rtype: Sequence[InputStream]
        """
        if not self._streams_initialized:
            self._initialize_streams()
        return self._streams

    @property
    def video_streams(self) -> Sequence:
        """ All video streams

        :rtype: Sequence[InputStream]
        """
        if not self._streams_initialized:
            self._initialize_streams()
        return self._streams_by_type[S_VIDEO]

    @property
    def audio_streams(self) -> Sequence:
        """ All audio streams

        :rtype: Sequence[InputStream]
        """
        if not self._streams_initialized:
            self._initialize_streams()
        return self._streams_by_type[S_AUDIO]

    @property
    def subtitle_streams(self) -> Sequence:
        """ All subtitle streams

        :rtype: Sequence[InputStream]
        """
        if not self._streams_initialized:
            self._initialize_streams()
        return self._streams_by_type[S_SUBTITLE]

    @property
    def attachment_streams(self) -> Sequence:
        """ All attachment streams (i.e. Fonts)

        :rtype: Sequence[InputStream]
        """
        if not self._streams_initialized:
            self._initialize_streams()
        return self._streams_by_type[S_ATTACHMENT]

    @property
    def data_streams(self) -> Sequence:
        """ All data streams

        :rtype: Sequence[InputStream]
        """
        if not self._streams_initialized:
            self._initialize_streams()
        return self._streams_by_type[S_DATA]


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
        if  isinstance(file, str):
            if file in self.inputs_by_name:
                return self.inputs_by_name[file]

            file = self.pp.create_input(file)

        if file not in self.inputs:
            self.pp.to_debug("Adding input file #%i: %s", len(self.inputs), file.name)
            self.inputs.append(file)
            self.inputs_by_name[file.name] = file

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
            if outfile.name == filename:
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
                yield value[0]
                for x in value[1:]:
                    yield opt_fmt % option
                    yield x
            elif value is not None:
                yield value

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
            filename = input_.name
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
            out_fn = output.name
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
    name = _redir("output", "name")

    del _redir


# === Interface Class ===
class AdvancedAV(metaclass=ABCMeta):
    input_factory = InputFile

    # ---- Output ----
    @abstractmethod
    def to_screen(self, text: str, *fmt):
        """ Log messages to the user """
        pass

    @abstractmethod
    def to_debug(self, text: str, *fmt):
        """ Process verbose messages """
        pass

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
        return self.input_factory(pp=self, filename=filename, options=options)


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
            import logging
            self.logger = logging.getLogger("advancedav.SimpleAV")
        else:
            self.logger = logger
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self.ffmpeg_output = ffmpeg_output
        self.logger.debug("SimpleAV initialized.")

    def to_screen(self, text, *fmt):
        self.logger.log(text % fmt)

    def to_debug(self, text, *fmt):
        self.logger.debug(text % fmt)

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

        return err.decode("utf-8", "replace")
