#!/usr/bin/env python3
# Parse Steam/Source VDF Files
# Reference: https://developer.valvesoftware.com/wiki/KeyValues#File_Format
# (c) 2015-2024 Taeyeon Mori; CC-BY-SA

from __future__ import unicode_literals

import datetime
import io
import struct
from typing import (Any, BinaryIO, Dict, Iterator, List, Mapping, NewType, Optional, Sequence,
                    Tuple, Type, TypeVar, Union, overload)

try:
    from functools import cached_property
except ImportError:
    from propex import cached_property
try:
    from typing import Self
except ImportError:
    try:
        from typing_extensions import Self
    except ImportError:
        Self = Any

#### Nested dictionary support
# Mypy doesn't support recursive types :(
DeepDict = Mapping[str, Union['DeepDict', str]]
DeepDictPath = Sequence[Union[str, Sequence[str]]]

_NoDefault = NewType('_NoDefault', object)
_nodefault = _NoDefault(object())
_DefaultT = TypeVar('_DefaultT', DeepDict, str, None)
_DDCastT = TypeVar('_DDCastT', DeepDict, str, Dict[str, str])

@overload
def dd_getpath(dct: DeepDict, path: DeepDictPath, default: _NoDefault=_nodefault, *, t: None=None) -> Union[DeepDict, str]: ...
@overload
def dd_getpath(dct: DeepDict, path: DeepDictPath, default: _DefaultT, *, t: None=None) -> Union[DeepDict, str, _DefaultT]: ...
@overload
def dd_getpath(dct: DeepDict, path: DeepDictPath, default: _NoDefault=_nodefault, *, t: Type[_DDCastT]) -> _DDCastT: ...
@overload
def dd_getpath(dct: DeepDict, path: DeepDictPath, default: _DefaultT, *, t: Type[_DDCastT]) -> Union[_DDCastT, _DefaultT]: ...

def dd_getpath(dct: DeepDict, path: DeepDictPath, default: Union[_DefaultT, _NoDefault]=_nodefault, *, t: Optional[Type[_DDCastT]]=None) -> Any: # type: ignore[misc]
    """
    Retrieve a value from inside a nested dictionary.
    @param dct The nested mapping
    @param path The path to retrieve. Represented by a tuple of strings.
    @param default A default value. Raises KeyError if omitted.
    @param t Result type for built-in typing.cast(), specify 'str' or 'dict'
    """
    d: Any = dct
    try:
        for pc in path:
            if isinstance(pc, str):
                d = d[pc]
            else:
                for candidate in pc:
                    try:
                        d = d[candidate]
                    except KeyError:
                        continue
                    else:
                        break
                else:
                    raise KeyError("Dictionary has none of key candidates %s" % pc)
        # XXX: runtime type check
        assert (t is None or isinstance(d, t)), f"Expected value at path {path} to be {t}, not {type(d)}"
        return d
    except KeyError:
        if default is not _nodefault:
            return default
        raise


#### Case-Insensitive dictionary.
# Unfortunately, Valve seems to play it a little loose with casing in their .vdf files
class LowerCaseNormalizingDict(dict):
    def __init__(self, *args, **kwds):
        super().__init__()
        # XXX: is there a better way to do this?
        for k,v in dict(*args,**kwds).items():
            k_ = k.lower()
            if k_ in self:
                raise KeyError("Duplicate key in LowerCaseNormalizingDict arguments: %s" % k_)
            self[k_] = v

    def __setitem__(self, key, value):
        return super().__setitem__(key.lower(), value)

    def __getitem__(self, key):
        return super().__getitem__(key.lower())

    def get(self, key, default=None):
        return super().get(key.lower(), default=default)


#### Text VDF parser.
class VdfParser:
    """
    Simple Steam/Source VDF parser
    """
    # Special Characters
    quote_char = "\""
    escape_char = "\\"
    begin_char = "{"
    end_char = "}"
    whitespace_chars = " \t\n"
    comment_char = "/"
    newline_char = "\n"

    def __init__(self, *, encoding=False, factory=dict, strict=True):
        """
        @brief Construct a VdfParser instance
        @param encoding Encoding for bytes operations. Pass None to use unicode strings
        @param factory A factory function creating a mapping type from an iterable of key/value tuples.
        """
        self.encoding = encoding
        if encoding:
            self.empty_string   = self.empty_string.encode(encoding)
            self.quote_char     = self.quote_char.encode(encoding)
            self.escape_char    = self.escape_char.encode(encoding)
            self.begin_char     = self.begin_char.encode(encoding)
            self.end_char       = self.end_char.encode(encoding)
            self.whitespace_chars = self.whitespace_chars.encode(encoding)
            self.comment_char   = self.comment_char.encode(encoding)
            self.newline_char   = self.newline_char.encode(encoding)
        self.factory = factory
        self.strict = strict

    def _make_map(self, tokens):
        return self.factory(zip(tokens[::2], tokens[1::2]))

    def _parse_map(self, fd, inner=False):
        tokens = []
        current = []
        escape = False
        quoted = False
        comment = False

        if self.encoding:
            make_string = b"".join
        else:
            make_string = "".join

        def finish(override=False):
            if current or override:
                tokens.append(make_string(current))
                current.clear()

        while True:
            c = fd.read(1)

            if not c:
                finish()
                if len(tokens) / 2 != len(tokens) // 2:
                    raise ValueError("Unexpected EOF: Last pair incomplete")
                elif self.strict and (escape or quoted or inner):
                    raise ValueError("Unexpected EOF: EOF encountered while not processing outermost mapping")
                return self._make_map(tokens)

            if escape:
                current.append(c)
                escape = False

            elif quoted:
                if c == self.escape_char:
                    escape = True
                elif c == self.quote_char:
                    quoted = False
                    finish(override=True)
                else:
                    current.append(c)

            elif comment:
                if c == self.newline_char:
                    comment = False

            else:
                if c == self.escape_char:
                    escape = True
                elif c == self.begin_char:
                    finish()
                    if len(tokens) / 2 == len(tokens) // 2 and (self.strict or self.factory is dict):
                        raise ValueError("Sub-dictionary cannot be a key")
                    tokens.append(self._parse_map(fd, True))
                elif c == self.end_char:
                    finish()
                    if len(tokens) / 2 != len(tokens) // 2:
                        raise ValueError("Unexpected close: Missing last value (Unbalanced tokens)")
                    return self._make_map(tokens)
                elif c in self.whitespace_chars:
                    finish()
                elif c == self.quote_char:
                    finish()
                    quoted = True
                elif c == self.comment_char and current and current[-1] == self.comment_char:
                    del current[-1]
                    finish()
                    comment = True
                else:
                    current.append(c)

    def parse(self, fd) -> DeepDict:
        """
        Parse a VDF file into a python dictionary
        """
        return self._parse_map(fd)

    def parse_string(self, content) -> DeepDict:
        """
        Parse the content of a VDF file
        """
        if self.encoding:
            return self.parse(io.BytesIO(content))
        else:
            return self.parse(io.StringIO(content))

    def _make_literal(self, lit):
        # TODO
        return "\"%s\"" % (str(lit).replace("\\", "\\\\").replace("\"", "\\\""))

    def _write_map(self, fd, dictionary, indent):
        if indent is None:
            def write(str=None, i=False, d=False, nl=False):
                if str:
                    fd.write(str)
                if d:
                    fd.write(" ")

        else:
            def write(str=None, i=False, d=False, nl=False):
                if not str and nl:
                    fd.write("\n")
                else:
                    if i:
                        fd.write("\t" * indent)
                    if str:
                        fd.write(str)
                    if nl:
                        fd.write("\n")
                    elif d:
                        fd.write("\t\t")

        for k, v in dictionary.items():
            if isinstance(v, dict):
                write(self._make_literal(k), i=1, d=1, nl=1)
                write("{", i=1, nl=1)
                self._write_map(fd, v, indent + 1 if indent is not None else None)
                write("}", i=1)
            else:
                write(self._make_literal(k), i=1, d=1)
                write(self._make_literal(v))
            write(d=1, nl=1)

    def write(self, fd, dictionary: DeepDict, *, pretty=True):
        """
        Write a dictionary to a file in VDF format
        """
        if self.encoding:
            raise NotImplementedError("Writing in binary mode is not implemented yet.") # TODO (maybe)
        self._write_map(fd, dictionary, 0 if pretty else None)


#### Binary parsing utils
def _read_exactly(fd: BinaryIO, s: int) -> bytes:
    cs = fd.read(s)
    if len(cs) < s:
        raise EOFError()
    return cs

def _read_int(fd: BinaryIO, size: int=4, signed=False) -> int:
    return int.from_bytes(_read_exactly(fd, size), 'little', signed=signed)

def _read_struct(fd: BinaryIO, s: struct.Struct):
    return s.unpack(fd.read(s.size))

def _read_until(fd: BinaryIO, delim: bytes, bufsize: int=64) -> bytes:
    pieces = []
    piece: bytes
    end = -1

    while end == -1:
        piece = fd.read(bufsize)
        if not piece:
            raise EOFError()

        end = piece.find(delim)
        pieces.append(piece[:end])

    fd.seek(end - len(piece) + len(delim), io.SEEK_CUR)

    return b"".join(pieces)

def _read_cstring(fd: BinaryIO) -> str:
    return _read_until(fd, b'\0').decode("utf-8", "replace")


#### Binary VDF parser
class BinaryVdfParser:
    # Type codes
    T_SKEY = b'\x00'    # Subkey
    T_CSTR = b'\x01'    # 0-delimited string
    T_INT4 = b'\x02'    # 32-bit int
    T_FLT4 = b'\x03'    # 32-bit float
    T_PNTR = b'\x04'    # 32-bit pointer
    T_WSTR = b'\x05'    # 0-delimited wide string
    T_COLR = b'\x06'    # 32-bit color
    T_INT8 = b'\x07'    # 64-bit int
    T_END  = b'\x08'    # End of subkey
    T_SIN8 = b'\x0A'    # 64-bit signed int
    T_END2 = b'\x0B'    # Alternative end of subkey tag

    # Unpack binary types
    S_FLT4 = struct.Struct("<f")

    def __init__(self, factory=dict):
        self.factory = factory

    def _read_map(self, fd: BinaryIO, key_table: Optional[List[str]]=None) -> DeepDict:
        map = self.factory()

        while True:
            t = fd.read(1)

            if not t:
                raise EOFError()

            if t in (self.T_END, self.T_END2):
                return map

            if key_table is not None:
                key = key_table[_read_int(fd, 4)]
            else:
                key = _read_cstring(fd)

            value = self._read_value(fd, t, key_table=key_table)

            map[key] = value

    def _read_value(self, fd: BinaryIO, t: bytes, key_table: Optional[List[str]]=None) -> Union[str, int, float, DeepDict]:
            if t == self.T_SKEY:
                return self._read_map(fd, key_table=key_table)
            elif t == self.T_CSTR:
                return _read_cstring(fd)
            elif t == self.T_WSTR:
                length = _read_int(fd, 2)
                return _read_exactly(fd, length).decode("utf-16")
            elif t in (self.T_INT4, self.T_PNTR, self.T_COLR):
                return _read_int(fd, 4)
            elif t == self.T_INT8:
                return _read_int(fd, 8)
            elif t == self.T_SIN8:
                return _read_int(fd, 8, True)
            elif t == self.T_FLT4:
                return _read_struct(fd, self.S_FLT4)[0]
            else:
                raise ValueError("Unknown data type", fd.tell(), t)

    def parse(self, fd: BinaryIO, key_table: Optional[List[str]]=None) -> DeepDict:
        return self._read_map(fd, key_table=key_table)

    def parse_bytes(self, data: bytes, key_table: Optional[List[str]]=None) -> DeepDict:
        with io.BytesIO(data) as fd:
            return self.parse(fd, key_table=key_table)


class AppInfoFile:
    S_APP_HEADER    = struct.Struct("<IIIIQ20sI")
    S_APP_HEADER_V2 = struct.Struct("<IIIIQ20sI20s")

    file: BinaryIO
    parser: BinaryVdfParser
    key_table: Optional[List[str]]

    @classmethod
    def open(cls, filename) -> Self:
        return cls(open(filename, "br"), close=True)

    def __init__(self, file: BinaryIO, bvdf_parser=None, close=True):
        self.file = file
        self.parser = bvdf_parser if bvdf_parser is not None else BinaryVdfParser()
        self.key_table = None
        self._close_file = close

    def _load_offset(self, offset: int) -> DeepDict:
        self.file.seek(offset, io.SEEK_SET)
        return self.parser.parse(self.file, key_table=self.key_table)

    class App:
        __slots__ = "appinfo", "offset", "id", "size", "state", "last_update", "token", "hash", "changeset", "hash_bin", "_data"

        def __init__(self, appinfo,  offset, struct):
            self.id = struct[0]
            self.size = struct[1]
            self.state = struct[2]
            self.last_update = datetime.datetime.fromtimestamp(struct[3])
            self.token = struct[4]
            self.hash = struct[5]
            self.changeset = struct[6]
            self.hash_bin = struct[7] if len(struct) > 7 else None
            self.appinfo = appinfo
            self.offset = offset
            self._data = None

        def __repr__(self) -> str:
            return f"<{self.__class__.__qualname__}@{id(self):08x}: {self.id} @{self.offset:08x}>"

        def __getitem__(self, key):
            if self._data is None:
                self._data = self.appinfo._load_offset(self.offset)
            return self._data[key]

        @property
        def data(self):
            if self._data is None:
                self._data = self.appinfo._load_offset(self.offset)
            return self._data

    def _read_string_table_from(self, offset: int) -> List[str]:
        # preserve offset
        _offset = self.file.tell()
        self.file.seek(offset)
        count = _read_int(self.file, 4)

        stable: List[str] = []
        rest: List[bytes] = []
        buf = b''
        for _ in range(count):
            while (end := buf.find(b'\0')) < 0:
                rest.append(buf)
                buf = self.file.read(4096)
                if not buf:
                    raise EOFError()
            if rest:
                cs = b''.join((*rest, buf[:end]))
                rest.clear()
            else:
                cs = buf[:end]
            stable.append(cs.decode("utf-8"))
            buf = buf[end+1:]

        self.file.seek(_offset)
        return stable

    def _load_index(self) -> Tuple[int, Dict[int, App]]:
        magic = _read_exactly(self.file, 4)
        universe = _read_int(self.file, 4)

        if magic == b"\x29\x44\x56\x07":
            header_struct = self.S_APP_HEADER_V2
            # read key table
            kto = _read_int(self.file, 8)
            self.key_table = self._read_string_table_from(kto)
        elif magic == b"\x28\x44\x56\x07":
            header_struct = self.S_APP_HEADER_V2
        elif magic == b"\x27\x44\x56\x07":
            header_struct = self.S_APP_HEADER
        else:
            raise ValueError(f"Unknown appinfo.vdf magic {magic.hex()}")

        apps = {}

        while True:
            buf = self.file.read(header_struct.size)
            if buf.startswith(b"\0\0\0\0"):
                break # Done
            if len(buf) < header_struct.size:
                raise EOFError()

            struct = header_struct.unpack(buf)
            appid, size, *_ = struct

            apps[appid] = self.App(self, self.file.tell(), struct)

            self.file.seek(size - (header_struct.size - 8), io.SEEK_CUR)

        return universe, apps

    @cached_property
    def universe(self) -> int:
        universe, self.apps = self._load_index()
        return universe

    @cached_property
    def apps(self) -> Dict[int, App]:
        self.universe, apps = self._load_index()
        return apps

    def __getitem__(self, key: int) -> App:
        return self.apps[key]

    def __iter__(self) -> Iterator[App]:
        return iter(self.apps.values())

    # Cleanup
    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc, tp, tb):
        self.close()

    def close(self):
        if self._close_file:
            self.file.close()

