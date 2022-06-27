"""
AdvancedAV FFmpeg commandline generator v3.0 [Library Edition]
-----------------------------------------------------------
    AdvancedAV helps with constructing FFmpeg commandline arguments.

    It can automatically parse input files with the help of FFmpeg's ffprobe tool (WiP)
    and allows programatically mapping streams to output files and setting metadata on them.
-----------------------------------------------------------
    Copyright 2014-2022 Taeyeon Mori

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

from __future__ import annotations

import itertools
import json
import logging
import os
import subprocess
import sys
from abc import ABCMeta, abstractmethod
from collections import defaultdict, deque
from pathlib import Path, PurePath
from typing import (Any, Callable, ClassVar, Dict, Generic, Iterable, Iterator,
                    List, Literal, Mapping, MutableMapping, MutableSequence,
                    MutableSet, Optional, Protocol, Sequence, Tuple, TypeVar,
                    Union)

try:
    from typing import Self  # type:ignore
except ImportError:
    try:
        from typing_extensions import Self
    except ImportError:
        from typing import _SpecialForm
        @_SpecialForm #type:ignore
        def Self(self, params):
            raise TypeError(f"{self} is not subscriptable")


__all__ = "AdvancedAVError", "AdvancedAV", "SimpleAV", "MultiAV"

version_info = 2, 99, 9

# Constants
StreamType = Union[Literal["a"], Literal["v"], Literal["s"], Literal["t"], Literal["d"], Literal["u"]]
S_AUDIO: StreamType = "a"
S_VIDEO: StreamType = "v"
S_SUBTITLE: StreamType = "s"
S_ATTACHMENT: StreamType = "t"
S_DATA: StreamType = "d"
S_UNKNOWN: StreamType = "u"


# == Exceptions ==
class AdvancedAVError(Exception):
    pass


# == Helpers ==
T = TypeVar("T")
U = TypeVar("U")
V = TypeVar("V")

OptionsValue = Union[str, int, Literal[True], List[str], List[int], List[Literal[True]]]
OptionsDict = Dict[str, OptionsValue]
InformationDict = Dict[str, Any]

class FFmpeg:
    @staticmethod
    def int(no: str) -> int:
        """
        Parse a ffmpeg number.
        See https://ffmpeg.org/ffmpeg.html#Options
        """
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

    # Commandline generation
    @staticmethod
    def argv_options(options: OptionsDict, qualifier: Optional[str]=None) -> Iterator[str]:
        """ Yield arbitrary options """
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
    def argv_metadata(metadata: Mapping[str, str], qualifier: Optional[str]=None) -> Iterator[str]:
        """ Yield arbitrary metadata options """
        if qualifier is None:
            opt = "-metadata"
        else:
            opt = "-metadata:%s" % qualifier
        for meta in metadata.items():
            yield opt
            yield "%s=%s" % meta

    # Stream types
    stype_by_ctype = {
        "audio": S_AUDIO,
        "video": S_VIDEO,
        "subtitle": S_SUBTITLE,
        "attachment": S_ATTACHMENT,
        "data": S_DATA,
    }

    @classmethod
    def stype_from_ctype(ffmpeg, ctype: str) -> StreamType:
        return ffmpeg.stype_by_ctype.get(ctype, S_UNKNOWN)


class Future(Generic[T]):
    finished: bool
    result: Optional[T]
    exception: Optional[BaseException]
    _then: List[Callable[[T], None]]
    _catch: List[Callable[[BaseException], None]]

    def __init__(self):
        self.result = None
        self.finished = False
        self.exception = None

        self._then = []
        self._catch = []

    # Consumer
    def then(self, fn: Callable[[T], None]) -> Self:
        if self.finished:
            if self.exception is None:
                fn(self.result) #type:ignore
        else:
            self._then.append(fn)
        return self

    def catch(self, fn: Callable[[BaseException], None]) -> Self:
        if self.finished:
            if self.exception is not None:
                fn(self.exception)
        else:
            self._catch.append(fn)
        return self

    # Provider
    def complete(self, result: T=None) -> Self:
        self.result = result
        self.finished = True
        for c in self._then:
            c(result) #type:ignore
        return self

    def fail(self, exception: BaseException) -> Self:
        self.exception = exception
        self.finished = True
        for c in self._catch:
            c(exception)
        return self

    def __enter__(self) -> Callable[[T], Self]:
        return self.complete

    def __exit__(self, tp, exc, tb):
        if not self.finished:
            if exc:
                self.fail(exc)
            else:
                self.fail(RuntimeError("Future not completed in context"))


# == Base Classes ==
class ObjectWithOptions(metaclass=ABCMeta):
    """
    Options refer to ffmpeg commandline arguments, referring to a specific Task, File or Stream.

    Option values can be:
        - str: pass value
        - int: convert to string, pass value
        - list, tuple: pass option multiple times, with different values
        - True: pass option without value
        - None: pass option without value (deprecated)

    For option names, refer to the FFmpeg documentation.

    Subclasses must define 'options' slot/property as inheriting multiple __slots__ bases is forbidden.
    """
    __slots__ = ()
    local_option_names: ClassVar[Sequence[str]] = ()

    options: OptionsDict

    def __init__(self, *, options: OptionsDict=None, **more):
        super().__init__(**more)
        self.options = options or {} #type:ignore

    def apply(self, source: OptionsDict, *names: str, **omap: str) -> Self:
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

    def set(self, **options: OptionsValue) -> Self:
        """
        Set options on this object

        Applies all keyword arguments as options

        :return: self, for method chaining
        """
        self.options.update(options)
        return self
    
    @property
    def ffmpeg_options(self) -> OptionsDict:
        if self.local_option_names:
            return {k: v for k, v in self.options.items() if k not in self.local_option_names}
        else:
            return self.options


class ObjectWithMetadata:
    """
    (writable) Stream or File metadata. Always strings.

    Subclasses must define 'metadata' slot/property as inheriting multiple __slots__ bases is forbidden.
    """
    __slots__ = ()

    metadata: Dict[str, str]

    def __init__(self, *, metadata: Dict[str, str]=None, **more):
        super().__init__(**more)
        self.metadata = metadata or {} #type:ignore

    def apply_meta(self, source: Dict[str, str], *names: str, **mmap: str) -> Self:
        for name in names:
            if name in source:
                self.metadata[name] = source[name]
        if mmap:
            for name, key in mmap.items():
                if name in source:
                    self.metadata[key] = source[name]
        return self

    def meta(self, **metadata: str) -> Self:
        self.metadata.update(metadata)
        return self


class ObjectWithInformation:
    """
    Stream or file information from FFprobe. Nested json data.

    Subclasses must define 'information' slot/property as inheriting multiple __slots__ bases is forbidden.
    """
    __slots__ = ()

    information: InformationDict

    def __init__(self, info: InformationDict, **more):
        super().__init__(**more)
        self.information = info #type:ignore


# == Descriptors ==
TOptions = TypeVar("TOptions", bound=OptionsValue)


class DescriptorBase(Generic[T, U]):
    __slots__ = "owner", "name"
    owner: U
    name: str

    def __init__(self, default_name="(Name Unknown)"):
        self.owner = None
        self.name = default_name

    def __set_name__(self, owner: U, name: str):
        self.owner = owner
        self.name = name

    @property
    def repr_info(self) -> str:
        return ""

    def __repr__(self):
        return "<%s %s of %s%s>" % (type(self).__name__, self.name, self.owner, self.repr_info)


class InformationProperty(DescriptorBase[T, ObjectWithInformation]):
    """
    A read-only property referring ffprobe information
    """
    __slots__ = "path", "type"
    path: Sequence[str]
    #_ type: Optional[Callable[[Any], T]]

    def __init__(self, *path: str, type: Optional[Callable[[Any], T]]=None):
        super().__init__()
        self.path = path
        self.type = type

    @property
    def repr_info(self) -> str:
        return " referring to %s" % self.path

    def __get__(self, object: ObjectWithInformation, obj_type=None) -> Optional[T]:
        info = object.information
        try:
            for seg in self.path:
                info = info[seg]
        except (KeyError, IndexError):
            return None
        else:
            return self.type(info) if self.type is not None else info #type:ignore


class OptionProperty(DescriptorBase[TOptions, ObjectWithOptions]):
    """
    A read-write descriptor referring to ffmpeg options

    Unset options will return None,
    setting an option to None will unset it.

    Note: This differs from deprecated behaviour when setting options directly,
          which will cause the option to be passed without arguments.
    """
    __slots__ = "candidates", "type"
    candidates: Sequence[str]
    #_ type: Optional[Callable[[Any], TOptions]]

    def __init__(self, *candidates: str, type: Optional[Callable[[Any], TOptions]]=None):
        super().__init__()
        self.candidates = candidates
        self.type = type

    @property
    def repr_info(self) -> str:
        return " referencing option %s" % self.candidates[0]

    def __get__(self, object: ObjectWithOptions, obj_type=None) -> Optional[TOptions]:
        for candidate in self.candidates:
            try:
                value = object.options[candidate]
            except KeyError:
                pass
            else:
                return self.type(value) if self.type is not None else value #type:ignore
        else:
            return None

    def __set__(self, object: ObjectWithOptions, value: Optional[TOptions]=None):
        for candidate in self.candidates:
            if candidate in object.options:
                del object.options[candidate]
        if value is not None:
            object.options[self.candidates[0]] = value
    
    __delete__ = __set__


# === Stream Classes ===
class Stream:
    """
    Abstract stream base class

    One continuous stream of data muxed into a container format
    """
    __slots__ = 'file', 'pertype_index'

    file: File
    pertype_index: Optional[int]

    def __init__(self, file: File, pertype_index: int=None, **more):
        super().__init__(**more)
        self.file = file
        self.pertype_index = pertype_index

    @property
    def index(self):
        return 0

    @property
    def type(self) -> StreamType:
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
class InputStream(Stream, ObjectWithInformation):
    """
    Holds information about an input stream
    """
    __slots__ = 'information',

    file: InputFile

    def __init__(self, file: InputFile, **more):
        super().__init__(file, **more)

    @property
    def type(self) -> StreamType:
        return FFmpeg.stype_from_ctype(self.codec_type) if self.codec_type is not None else S_UNKNOWN

    index       = InformationProperty("index", type=int)

    codec       = InformationProperty[str]("codec_name")
    codec_name  = InformationProperty[str]("codec_long_name")
    codec_type  = InformationProperty[str]("codec_type")
    profile     = InformationProperty[str]("profile")

    duration    = InformationProperty("duration", type=float)
    duration_ts = InformationProperty("duration_ts", type=int)

    start_time  = InformationProperty[str]("start_time")

    bitrate     = InformationProperty("bit_rate", type=int)
    max_bitrate = InformationProperty("max_bit_rate", type=int)
    nb_frames   = InformationProperty("nb_frames", type=int)

    @property
    def disposition(self):
        try:
            return tuple(k for k, v in self.information["disposition"].items() if v)
        except KeyError:
            return ()

    language    = InformationProperty[str]("tags", "language")


class InputAudioStream(InputStream):
    __slots__ = ()

    def  __init__(self, file: InputFile, **more):
        super().__init__(file, **more)

        if self.codec_type != "audio":
            raise ValueError("Cannot create %s from stream info of type %s" % (type(self).__name__, self.codec_type))

    @property
    def type(self):
        return S_AUDIO

    sample_format   = InformationProperty[str]("sample_format")
    sample_rate     = InformationProperty("sample_rate", type=int)

    channels        = InformationProperty("channels", type=int)
    channel_layout  = InformationProperty[str]("channel_layout")


class InputAttachmentStream(InputStream):
    __slots__ = ()

    @property
    def type(self):
        return S_ATTACHMENT

    og_filename = InformationProperty[str]("tags", "filename")
    mimetype    = InformationProperty[str]("tags", "mimetype")


def input_stream_factory(file: InputFile, info: InformationDict, pertype_index: int=None) -> InputStream:
    return {
        "audio": InputAudioStream,
        "attachment": InputAttachmentStream,
    }.get(info["codec_type"], InputStream)(file, info=info, pertype_index=pertype_index)


# Output Streams
class OutputStream(Stream, ObjectWithOptions, ObjectWithMetadata):
    """
    Holds information about a mapped output stream
    """
    __slots__ = 'source', 'index', 'options', 'metadata'

    file: OutputFile
    source: InputStream
    index: int

    # TODO: support other parameters like frame resolution
    def __init__(self, file: OutputFile, source: InputStream, stream_id: int, stream_pertype_id: int=None,
                 options: OptionsDict=None, metadata: MutableMapping=None):
        super().__init__(file=file, options=options, metadata=metadata, pertype_index=stream_pertype_id)
        self.index = stream_id
        self.source = source

    @property
    def type(self) -> StreamType:
        return self.source.type

    def _update_indices(self, index: int, pertype_index: int=None):
        """ Update the Stream indices """
        self.index = index
        if pertype_index is not None:
            self.pertype_index = pertype_index

    codec = OptionProperty[str]("codec", "c")

    bitrate = OptionProperty("b", type=FFmpeg.int)


class OutputAudioStream(OutputStream):
    __slots__ = ()

    channels = OptionProperty("ac", type=int)


class OutputVideoStream(OutputStream):
    __slots__ = ()

    def downscale(self, width: int, height: int) -> Self:
        # Scale while keeping aspect ratio; never upscale.
        self.options["filter_complex"] = "scale=iw*min(1\,min(%i/iw\,%i/ih)):-1" % (width, height)
        return self


def output_stream_factory(file: OutputFile, source: InputStream, *args, **more) -> OutputStream:
    return {
        S_AUDIO: OutputAudioStream,
        S_VIDEO: OutputVideoStream,
    }.get(source.type, OutputStream)(file, source, *args, **more)


# === File Classes ===
TStream = TypeVar("TStream", bound=Stream)


class BaseFile(metaclass=ABCMeta):
    __slots__ = 'path',

    path: Path

    def __init__(self, path: Path, **more):
        super().__init__(**more)
        self.path = Path(path)

    @abstractmethod
    def generate_args(self) -> Iterator[str]: ...

    # Filename
    @property
    def name(self) -> str:
        """
        The file's name
        Changed in 3.0: previously, full path
        """
        return self.path.name

    @name.setter
    def name(self, value: str):
        self.path = self.path.with_name(value)

    @property
    def filename(self) -> str:
        """
        The file's full path as string
        """
        return str(self.path)

    @filename.setter
    def filename(self, value: str):
        self.path = Path(value)


class File(BaseFile, ObjectWithOptions, Generic[TStream]):
    """
    ABC for Input- and Output-Files
    """
    __slots__ = '_streams', '_streams_by_type', 'options'

    _streams: Sequence[TStream]
    _streams_by_type: Mapping[StreamType, Sequence[TStream]]

    def __init__(self, path: Path, **more):
        super().__init__(path=path, **more)
        self._streams = []
        self._streams_by_type = defaultdict(list)

    # Streams
    @property
    def streams(self) -> Sequence[TStream]:
        """ The streams contained in this file """
        return self._streams

    @property
    def video_streams(self) -> Sequence[TStream]:
        """ All video streams """
        return self._streams_by_type[S_VIDEO]

    @property
    def audio_streams(self) -> Sequence[TStream]:
        """ All audio streams """
        return self._streams_by_type[S_AUDIO]

    @property
    def subtitle_streams(self) -> Sequence[TStream]:
        """ All subtitle streams """
        return self._streams_by_type[S_SUBTITLE]

    @property
    def attachment_streams(self) -> Sequence[TStream]:
        """ All attachment streams (i.e. Fonts) """
        return self._streams_by_type[S_ATTACHMENT]

    @property
    def data_streams(self) -> Sequence[TStream]:
        """ All data streams """
        return self._streams_by_type[S_DATA]

    def __repr__(self) -> str:
        return "<%s \"%s\">" % (type(self).__name__, self.name)


class InputFileChapter(ObjectWithInformation):
    __slots__ = 'file', 'information'

    file: InputFile

    def __init__(self, file: InputFile, info: InformationDict):
        super().__init__(info=info)
        self.file = file

    def __repr__(self) -> str:
        return "<InputFileChapter #%i of %s from %.0fs to %.0fs (%s)>" \
                % (self.index or 0, self.file, self.start_time or 0, self.end_time or 0, self.title)

    start_time  = InformationProperty("start_time", type=float)
    end_time    = InformationProperty("end_time", type=float)

    index       = InformationProperty("id", type=int)
    title       = InformationProperty[str]("tags", "title")


class InputFile(File[InputStream], ObjectWithInformation):
    """
    Holds information about an input file

    :note: Modifying the options after accessing the streams results in undefined
            behaviour! (Currently: Changes will only apply to conv call)
    """
    __slots__ = 'pp', '_information'
    stream_factory = staticmethod(input_stream_factory)

    pp: AdvancedAV
    _information: Optional[InformationDict]

    def __init__(self, pp: AdvancedAV, path: Path, options: OptionsDict=None, info=None):
        super().__init__(path, options=dict(options.items()) if options else None, info=info)
        self.pp = pp

    @property #type:ignore # Mypy doesn't support overriding with properties
    def information(self) -> InformationDict: #type:ignore
        return self._information if self._information is not None else self._initialize_info()
    
    @information.setter
    def information(self, info: InformationDict):
        self._information = info
    
    @information.deleter
    def information(self):
        pass

    def generate_args(self) -> Iterator:
        # Input options
        yield from FFmpeg.argv_options(self.ffmpeg_options)

        # Add Input
        yield "-i"
        yield self.filename if self.filename[0] != "-" else "./" + self.filename

    # -- Initialize
    ffprobe_args = "-show_format", "-show_streams", "-show_chapters", "-print_format", "json"

    def _initialize_info(self) -> InformationDict:
        self._information = info = self.pp.probe_file(self, ffprobe_args_hint=self.ffprobe_args)
        return info

    def _initialize_streams(self):
        """ Parse the ffprobe output

        The locale of the probe output in \param probe should be C!
        """
        for sinfo in self.information["streams"]:
            stype = FFmpeg.stype_from_ctype(sinfo["codec_type"])
            stream = self.stream_factory(self, sinfo, len(self._streams_by_type[stype]))
            self._streams.append(stream)
            self._streams_by_type[stype].append(stream)

    # -- Streams
    @property
    def streams(self) -> Sequence[InputStream]:
        """ Collect the available streams """
        if not self._streams:
            self._initialize_streams()
        return self._streams

    @property
    def video_streams(self) -> Sequence[InputStream]:
        """ All video streams """
        if not self._streams:
            self._initialize_streams()
        return self._streams_by_type[S_VIDEO]

    @property
    def audio_streams(self) -> Sequence[InputStream]:
        """ All audio streams """
        if not self._streams:
            self._initialize_streams()
        return self._streams_by_type[S_AUDIO]

    @property
    def subtitle_streams(self) -> Sequence[InputStream]:
        """ All subtitle streams """
        if not self._streams:
            self._initialize_streams()
        return self._streams_by_type[S_SUBTITLE]

    @property
    def attachment_streams(self) -> Sequence[InputStream]:
        """ All attachment streams (i.e. Fonts) """
        if not self._streams:
            self._initialize_streams()
        return self._streams_by_type[S_ATTACHMENT]

    @property
    def data_streams(self) -> Sequence[InputStream]:
        """ All data streams """
        if not self._streams:
            self._initialize_streams()
        return self._streams_by_type[S_DATA]

    # Information
    nb_streams  = InformationProperty("format", "nb_streams", type=int)

    duration    = InformationProperty("format", "duration", type=float)

    size        = InformationProperty("format", "size", type=int)
    bitrate     = InformationProperty("format", "bit_rate", type=int)

    # Metadata
    metadata    = InformationProperty[Dict[str, str]]("format", "tags")

    title       = InformationProperty[str]("format", "tags", "title")
    artist      = InformationProperty[str]("format", "tags", "artist")
    album       = InformationProperty[str]("format", "tags", "album")

    # Chapters
    @property
    def chapters(self) -> Sequence[InputFileChapter]:
        return list(InputFileChapter(self, i) for i in self.information["chapters"])


InputFileRef = Union[InputFile, Path, str]


class OutputFile(File[OutputStream], ObjectWithMetadata):
    """
    Holds information about an output file
    """
    __slots__ = 'task', 'container', '_mapped_sources', 'metadata'
    local_option_names = ("reorder_streams", *File.local_option_names)
    stream_factory = staticmethod(output_stream_factory)

    task: Task
    name: str
    container: Optional[str]
    _streams: MutableSequence[OutputStream]
    _streams_by_type: Mapping[StreamType, MutableSequence[OutputStream]]
    _mapped_sources: MutableSet[InputStream]

    def __init__(self, task: "Task", path: Path, container=None,
            options: Mapping=None, metadata: Mapping=None):
        super().__init__(path, options=options, metadata=metadata)

        #self.options.setdefault("c", "copy")
        self.options.setdefault("reorder_streams", True)

        self.task = task
        self.container = container
        self._mapped_sources = set()

    def generate_args(self) -> Iterator[str]:
        # Global Metadata & Additional Options
        yield from FFmpeg.argv_metadata(self.metadata)
        yield from FFmpeg.argv_options(self.ffmpeg_options)

        # Map Streams, sorted by type
        if self.options["reorder_streams"]:
            self.reorder_streams()

        for stream in self.streams:
            yield "-map"
            id = self.task.qualified_input_stream_spec(stream.source)
            if id is None:
                raise AdvancedAVError("Could not determine id for stream %r" % stream)
            yield id

            if stream.codec is not None:
                yield "-c:%s" % stream.stream_spec
                yield stream.codec

            yield from FFmpeg.argv_metadata(stream.metadata, stream.stream_spec)
            yield from FFmpeg.argv_options(stream.ffmpeg_options, stream.stream_spec)

        # Container
        if self.container is not None:
            yield "-f"
            yield self.container

        # Output Filename, prevent it from being interpreted as option
        yield self.filename if self.filename[0] != "-" else "./" + self.filename

    # -- Map Streams
    def _add_stream(self, stream: OutputStream):
        """ Add a stream """
        stream._update_indices(len(self._streams), len(self._streams_by_type[stream.type]))
        self._streams.append(stream)
        self._streams_by_type[stream.type].append(stream)

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
        raise KeyError()

    # -- Map multiple Streams
    def map_all_streams(self, file: InputFileRef, return_existing: bool=False) -> Sequence[OutputStream]:
        """ Map all streams in \param file

        Note that this will only map streams that are not already mapped.
        """
        out_streams: List[OutputStream] = []
        for stream in self.task.add_input(file).streams:
            if stream in self._mapped_sources:
                if return_existing:
                    out_streams.append(self.get_mapped_stream(stream)) #
            else:
                out_streams.append(self.map_stream_(stream))

        return out_streams

    def merge_all_files(self, files: Iterable[InputFileRef], return_existing: bool=False) -> Sequence[OutputStream]:
        """ Map all streams from multiple files

        Like map_all_streams(), this will only map streams that are not already mapped.
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


# === Dump Attachments ===
# see also Task.generate_args()
class AttachmentOutputStream(Stream):
    __slots__ = ()

    def __init__(self, file):
        super().__init__(file=file)

    @property
    def source(self):
        return self.file.source

    @property
    def type(self):
        return S_ATTACHMENT


class AttachmentOutputFile(BaseFile):
    __slots__ = 'source',

    def __init__(self, source: InputAttachmentStream, path: Path=None):
        if path is None:
            if source.og_filename is not None:
                path = Path(source.og_filename.lstrip('/'))
            else:
                raise RuntimeError("Couldn't detect attachment filename")

        super().__init__(path=path)

        self.source = source

    def generate_args(self):
        yield "-dump_attachment:%s" % self.source.stream_spec
        yield self.filename if self.filename[0] != "-" else "./" + self.filename

    @property
    def attachment_streams(self):
        return (AttachmentOutputStream(self),)

    streams = attachment_streams


# === Task Classes ===
class BaseTask(metaclass=ABCMeta):
    """
    Task base class
    """
    pp: AdvancedAV

    @property
    @abstractmethod
    def inputs(self) -> Sequence[InputFile]: ...

    @property
    @abstractmethod
    def outputs(self) -> Sequence[OutputFile]: ...


    def __init__(self, pp: AdvancedAV):
        super().__init__()

        self.pp = pp

    # -- Inputs
    @property
    def inputs_by_name(self) -> Mapping[str, InputFile]:
        return {i.name: i for i in self.inputs}

    def qualified_input_stream_spec(self, stream: InputStream) -> Optional[str]:
        """ Construct the qualified input stream spec (combination of input file number and stream spec)

        None will be returned if stream's file isn't registered as an input to this Task
        """
        file_index = self.inputs.index(stream.file)
        if file_index >= 0:
            return "{}:{}".format(file_index, stream.stream_spec)
        return None

    # -- Input Streams
    def iter_video_streams(self) -> Iterator[InputStream]:
        for input_ in self.inputs:
            yield from input_.video_streams

    def iter_audio_streams(self) -> Iterator[InputStream]:
        for input_ in self.inputs:
            yield from input_.audio_streams

    def iter_subtitle_streams(self) -> Iterator[InputStream]:
        for input_ in self.inputs:
            yield from input_.subtitle_streams

    def iter_attachment_streams(self) -> Iterator[InputStream]:
        for input_ in self.inputs:
            yield from input_.attachment_streams

    def iter_data_streams(self) -> Iterator[InputStream]:
        for input_ in self.inputs:
            yield from input_.data_streams

    def iter_streams(self) -> Iterator[InputStream]:
        for input_ in self.inputs:
            yield from input_.streams

    def iter_chapters(self) -> Iterator[InputFileChapter]:
        for input_ in self.inputs:
            yield from input_.chapters

    # -- FFmpeg
    def generate_args(self) -> Iterator[str]:
        """ Generate the ffmpeg commandline for this task

        :rtype: Iterator[str]
        """
        # Dump attachments. this is stupid, ffmpeg!
        # dumping attachments is inherently creating output files
        # and shouldn't be done by an input option
        # This HACK may or may not stay in final v3....
        attachment_dumps: Sequence[AttachmentOutputFile] = [o for o in self.outputs if isinstance(o, AttachmentOutputFile)] #type:ignore

        # Inputs
        for input_ in self.inputs:
            for att in attachment_dumps:
                if att.source.file is input_:
                    yield from att.generate_args()

            yield from input_.generate_args()

        # Outputs
        for output in self.outputs:
            if output not in attachment_dumps:
                yield from output.generate_args()

    def commit(self, additional_args: Sequence[str]=(), immediate=True, **args):
        """
        Commit the changes.

        additional_args is used to pass global arguments to ffmpeg. (like -y)

        :type additional_args: Iterable[str]
        :raises: AdvancedAVError when FFmpeg fails
        """
        f = self.pp.commit_task(self, add_ffmpeg_args=additional_args, immediate=immediate, **args)
        if f.finished:
            if f.exception:
                raise f.exception
        elif immediate:
            raise RuntimeError("Requested immediate commit but result was deferred")

    def commit2(self, **args) -> Future:
        """
        Commit the changes.

        add_ffmpeg_args can be used to pass global arguments to ffmpeg. (like -y)

        :type additional_args: Iterable[str]
        :returns: a Future
        """
        return self.pp.commit_task(self, **args)

    # -- Managing the task
    def split(self, pieces=0) -> Sequence[PartialTask]:
        """
        Split a task into min(pieces, len(outputs)) partial tasks
        """
        parts: List[List[OutputFile]] = []

        if pieces > 0:
            for i in range(min(len(self.outputs), pieces)):
                parts.append([])

            for i, output in enumerate(self.outputs):
                parts[i % pieces].append(output)

        else:
            parts = [[output] for output in self.outputs]

        return [PartialTask(self, outset) for outset in parts]


class PartialTask(BaseTask):
    parent: BaseTask
    outputs: Sequence[OutputFile] = []

    def __init__(self, parent: BaseTask, outs: Sequence[OutputFile]):
        super().__init__(parent.pp)

        self.parent = parent
        self.outputs = outs

    @property
    def inputs(self) -> Sequence[InputFile]:
        return self.parent.inputs

    @property
    def inputs_by_name(self) -> Mapping[str, InputFile]:
        return self.parent.inputs_by_name


class Task(BaseTask):
    """
    Holds information about an AV-processing Task.

    A Task is a collection of Input- and Output-Files and related options.
    While OutputFiles are bound to one task at a time, InputFiles can be reused across Tasks.
    """

    output_factory: ClassVar[Callable] = OutputFile

    # XXX: must have assignments here to clear class-level abstractmethods
    inputs: MutableSequence[InputFile] = []
    inputs_by_name: MutableMapping[str, InputFile] = {}
    outputs: MutableSequence[OutputFile] = []

    def __init__(self, pp: "AdvancedAV"):
        super().__init__(pp)

        self.inputs = []
        self.inputs_by_name = {}
        self.outputs = []

    # -- Manage Inputs
    def add_input(self, file: InputFileRef) -> InputFile:
        """ Register an input file

        When \param file is already registered as input file to this Task, do nothing.

        :param file: Can be either the filename of an input file or an InputFile object.
                        The latter will be created if the former is passed.
        """
        if  isinstance(file, PurePath): # Pathlib support
            file = str(file)
        if isinstance(file, InputFile):
            input_ = file
        else:
            if file in self.inputs_by_name:
                return self.inputs_by_name[file]
            input_ = self.pp.create_input(file)

        if input_ not in self.inputs:
            self.pp.to_debug("Adding input file #%i: %s", len(self.inputs), input_.name)
            self.inputs.append(input_)
            self.inputs_by_name[input_.filename] = input_

        return input_

    # -- Manage Outputs
    def add_output(self, filename: str, container: str=None, options: Mapping=None) -> OutputFile:
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

    # -- Attachment Shenanigans
    def dump_attachment(self, attachment: InputAttachmentStream, filename: Union[str, Path]=None) -> AttachmentOutputFile:
        for outfile in self.outputs:
            if outfile.filename == filename:
                raise AdvancedAVError("Output file '%s' already added." % filename)
        else:
            if attachment.type != S_ATTACHMENT:
                raise AdvancedAVError("Stream %r not an attachment!" % attachment)
            aoutfile = AttachmentOutputFile(attachment, Path(filename)if filename is not None else None)
            self.outputs.append(aoutfile) #type: ignore #FIXME
            return aoutfile


class SimpleTask(Task):
    """
    A simple task with only one output file

    All members of the OutputFile can be accessed on the SimpleTask directly, as well as the usual Task methods.
    Usage of add_output should be avoided however, because it would lead to confusion.
    """
    def __init__(self, pp: "AdvancedAV", filename: str, container: str=None, options: Mapping=None):
        super().__init__(pp)

        self.output = self.add_output(filename, container, options)

    def __getattr__(self, attr: str):
        """ You can directly access the OutputFile from the SimpleTask instance """
        return getattr(self.output, attr)

    # Allow assignment to these OutputFile members
    @staticmethod # XXX: requires python 3.10+. Remove for earlier, but breaks typecheck
    def _redir(attr: str, name: str):
        def redir_get(self):
            return getattr(getattr(self, attr), name)
        def redir_set(self, value):
            setattr(getattr(self, attr), name, value)
        return property(redir_get, redir_set)

    container = _redir("output", "container")
    metadata = _redir("output", "metadata")
    options = _redir("output", "options")
    name = _redir("output", "name")
    path = _redir("output", "path")
    filename = _redir("output", "filename")

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

    # ---- Create Tasks ----
    def create_task(self) -> Task:
        """
        Create a AdvancedAV Task.
        """
        return Task(self)

    def create_job(self, filename: str, container: str=None, options: Mapping=None) -> SimpleTask:
        """
        Create a simple AdvandecAV task
        :param filename: str The resulting filename
        :param container: str The output container format
        :param options: Additional Options for the output file
        :return: SimpleTask An AdvancedAV Task
        """
        return SimpleTask(self, filename, container, options)

    # ---- Process Tasks ----
    @abstractmethod
    def commit_task(self, task: BaseTask, *, add_ffmpeg_args: Sequence[str]=None, immediate: bool=False) -> Future:
        """
        Execute a task

        :param add_ffmpeg_args: List[str] arguments to add to ffmpeg call, if ffmpeg is used
        :param immediate: Request that the task is executed synchronously
        :return: A simple (possibly finished) future object describing the result
        """

    # ---- Analyze Files ----
    @abstractmethod
    def probe_file(self, path, *, ffprobe_args_hint: Sequence[str]=None) -> InformationDict:
        """
        Analyze a media file

        :param path: The file path
        :param ffprobe_args_hint: A hint as to which arguments would need to be passed to ffprobe to
                                supply all needed information
        :return: The media information, in parsed ffmpeg JSON format
        """

    # ---- Create InputFiles ----
    def create_input(self, path: Union[Path, str], options=None):
        """
        Create a InputFile instance
        :param path: str The filename
        :param options: Mapping Additional Options
        :return: A InputFile instance
        NOTE that Task.add_input is usually the preferred way to create inputs
        """
        return self.input_factory(self, Path(path), options=options)


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

    def make_conv_argv(self, task, add_ffmpeg_args):
        return tuple(itertools.chain((self._ffmpeg,), self.global_args, self.global_conv_args,
                                                    add_ffmpeg_args, task.generate_args()))

    def commit_task(self, task, *, add_ffmpeg_args=(), immediate=True):
        with Future() as f:
            argv = self.make_conv_argv(task, add_ffmpeg_args)

            self.to_debug("Running Command: %s", argv)

            output = None if self.ffmpeg_output else subprocess.DEVNULL

            subprocess.call(argv, stdout=output, stderr=output)

            return f()

    def call_probe(self, args: Iterable):
        """
        Call ffprobe.
        :param args: Iterable[str] The ffprobe arguments
        :return: str the standard output
        It should throw an AdvancedAVError if the call fails
        NOTE: Make sure the locale is set to C so the regexes match
        """
        argv = tuple(itertools.chain((self._ffprobe,), self.global_args, self.global_probe_args, args))

        self.to_debug("Running Command: %s", argv)

        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self._posix_env)

        out, err = proc.communicate()

        if proc.returncode != 0:
            msg = err.decode("utf-8", "replace").strip().split('\n')[-1]
            raise AdvancedAVError(msg)

        return out.decode("utf-8", "replace")

    def probe_file(self, file, *, ffprobe_args_hint=None):
        probe = self.call_probe(ffprobe_args_hint
                                + tuple(FFmpeg.argv_options(file.options))
                                + ("-i", file.filename))
        return json.loads(probe)


class MultiAV(SimpleAV):
    def __init__(self, workers=1, ffmpeg=None, ffprobe=None):
        super().__init__(ffmpeg=ffmpeg, ffprobe=ffprobe)

        self.concurrent = workers

        self.workers = {}
        self.queue = deque()

    # Enqueue
    def commit_task(self, task, *, add_ffmpeg_args=(), immediate=False):
        if immediate:
            return super().commit_task(task, add_ffmpeg_args=add_ffmpeg_args)
        else:
            f = Future()
            self.queue.append((f, task, add_ffmpeg_args))
            return f

    # Process
    def process_queue(self):
        """
        Process tasks until queue is empty.
        Note that the last few tasks may still be running in the background when this returns
        """
        from time import sleep
        while self.queue:
            self.manage_workers()
            sleep(.250)

    def manage_workers(self):
        """
        Make a single run over available workers and see to it that they have work if available
        """
        for id in range(self.concurrent):
            if not self.poll_worker(id) and self.queue:
                self.workers[id] = self._spawn_next()

    def wait(self):
        """ Wait for processing to finish up """
        while self.workers:
            for id, (worker, f) in list(self.workers.items()):
                worker.wait()
                self.poll_worker(id)

    def process_serial(self):
        """ Process the queue one task at a time """
        while self.queue:
            p, f = self.spawn_next()
            with f:
                p.wait()
                p.complete()

    def poll_worker(self, id):
        """ See if a worker is still running and clean it up otherwise """
        if id in self.workers:
            worker, future = self.workers[id]

            if worker.poll() is not None:
                if worker.returncode != 0:
                    future.fail(AdvancedAVError("ffmpeg returned %d" % worker.returncode))
                else:
                    future.complete()
                del self.workers[id]
            else:
                return True
        return False

    def _spawn_next(self, **b):
        """ Spawn next worker """
        f, task, add_ffmpeg_args = self.queue.popleft()

        argv = self.make_conv_argv(task, add_ffmpeg_args)
        self.to_debug("Running: %s" % (argv,))

        return subprocess.Popen(self.make_conv_argv(task, add_ffmpeg_args), **b), f
