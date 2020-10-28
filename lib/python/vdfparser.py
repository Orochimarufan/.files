#!/usr/bin/env python3
# Parse Steam/Source VDF Files
# Reference: https://developer.valvesoftware.com/wiki/KeyValues#File_Format
# (c) 2015-2020 Taeyeon Mori; CC-BY-SA

from __future__ import unicode_literals

import io
import struct
import collections
import datetime

from typing import Dict, Union, Mapping, Tuple

DeepDict = Mapping[str, Union[str, "DeepDict"]]


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
                    if len(tokens) / 2 == len(tokens) // 2 and (self.strict or self.factory == dict):
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


class BinaryVdfParser:
    # Type codes
    T_SKEY = b'\x00'    # Subkey
    T_CSTR = b'\x01'    # 0-delimited string
    T_INT4 = b'\x02'    # 32-bit int
    T_FLT4 = b'\x03'    # 32-bit float
    T_PNTR = b'\x04'    # 32-bit pointer
    T_WSTR = b'\x05'    # 0-delimited wide string
    T_COLR = b'\x06'    # 32-bit color
    T_UNT8 = b'\x07'    # 64-bit unsigned int
    T_END  = b'\x08'    # End of subkey
    T_INT8 = b'\x0A'    # 64-bit signed int
    T_END2 = b'\x0B'    # Alternative end of subkey tag

    # Unpack binary types
    S_INT4 = struct.Struct("<i")
    S_FLT4 = struct.Struct("<f")
    S_INT8 = struct.Struct("<q")
    S_UNT8 = struct.Struct("<Q")

    def __init__(self, factory=dict):
        self.factory = factory
    
    @staticmethod
    def _read_until(fd: io.BufferedIOBase, delim: bytes) -> bytes:
        pieces = []
        buf = bytearray(64)
        end = -1

        while end == -1:
            read = fd.readinto(buf)

            if not read:
                raise EOFError()

            end = buf.find(delim, 0, read)
            pieces.append(bytes(buf[:read if end < 0 else end]))
        
        fd.seek(end - read + len(delim), io.SEEK_CUR)

        return b"".join(pieces)

    @staticmethod
    def _read_struct(fd: io.BufferedIOBase, s: struct.Struct):
        return s.unpack(fd.read(s.size))

    def _read_cstring(self, fd: io.BufferedIOBase) -> str:
        return self._read_until(fd, b'\0').decode("utf-8", "replace")
    
    def _read_wstring(self, fd: io.BufferedIOBase) -> str:
        return self._read_until(fd, b'\0\0').decode("utf-16")
    
    def _read_map(self, fd: io.BufferedIOBase) -> DeepDict:
        map = self.factory()

        while True:
            t = fd.read(1)

            if not len(t):
                raise EOFError()

            if t in (self.T_END, self.T_END2):
                return map
            
            key, value = self._read_item(fd, t)
            map[key] = value
    
    def _read_item(self, fd: io.BufferedIOBase, t: int) -> (str, DeepDict):
            key = self._read_cstring(fd)

            if t == self.T_SKEY:
                return key, self._read_map(fd)
            elif t == self.T_CSTR:
                return key, self._read_cstring(fd)
            elif t == self.T_WSTR:
                return key, self._read_wstring(fd)
            elif t in (self.T_INT4, self.T_PNTR, self.T_COLR):
                return key, self._read_struct(fd, self.S_INT4)[0]
            elif t == self.T_UNT8:
                return key, self._read_struct(fd, self.S_UNT8)[0]
            elif t == self.T_INT8:
                return key, self._read_struct(fd, self.S_INT8)[0]
            elif t == self.T_FLT4:
                return key, self._read_struct(fd, self.S_FLT4)[0]
            else:
                raise ValueError("Unknown data type", fd.tell(), t)
    
    def parse(self, fd: io.BufferedIOBase) -> DeepDict:
        return self._read_map(fd)

    def parse_bytes(self, data: bytes) -> DeepDict:
        with io.BytesIO(data) as fd:
            return self.parse(fd)


class AppInfoFile:
    S_APP_HEADER = struct.Struct("<IIIIQ20sI")
    S_INT4 = struct.Struct("<I")

    @classmethod
    def open(cls, filename) -> "AppInfoFile":
        return cls(open(filename, "br"), close=True)

    def __init__(self, file, bvdf_parser=None, close=True):
        self.file = file
        self.parser = bvdf_parser if bvdf_parser is not None else BinaryVdfParser()
        self._close_file = close
        self._universe = None
        self._apps = None
    
    def _load_map(self, offset: int) -> DeepDict:
        self.file.seek(offset, io.SEEK_SET)
        return self.parser.parse(self.file)

    class App:
        __slots__ = "appinfo", "offset", "id", "size", "state", "last_update", "token", "hash", "changeset", "_data"

        def __init__(self, appinfo,  offset, struct):
            self.id = struct[0]
            self.size = struct[1]
            self.state = struct[2]
            self.last_update = datetime.datetime.fromtimestamp(struct[3])
            self.token = struct[4]
            self.hash = struct[5]
            self.changeset = struct[6]
            self.appinfo = appinfo
            self.offset = offset
            self._data = None
        
        def __getitem__(self, key):
            if self._data is None:
                self._data = self.appinfo._load_map(self.offset)
            return self._data[key]
        
        def __getattr__(self, attr):
            if attr in dir(dict):
                if self._data is None:
                    self._data = self.appinfo._load_map(self.offset)
                return getattr(self._data, attr)
            raise AttributeError(attr)
        
        @property
        def dict(self):
            if self._data is None:
                self._data = self.appinfo._load_map(self.offset)
            return self._data

    def _read_exactly(self, s: int) -> bytes:
        cs = self.file.read(s)
        if len(cs) < s:
            raise EOFError()
        return cs
    
    def _read_int(self) -> int:
        return self.S_INT4.unpack(self._read_exactly(self.S_INT4.size))[0]

    def _load(self):
        magic = self._read_exactly(4)
        if magic != b"\x27\x44\x56\x07":
            raise ValueError("Wrong appinfo.vdf magic")
        
        self._universe = self._read_int()
        self._apps = {}

        buffer = bytearray(self.S_APP_HEADER.size)

        while True:
            read = self.file.readinto(buffer)

            if read < 4:
                raise EOFError()
            
            struct = self.S_APP_HEADER.unpack(buffer)
            appid, size, *_ = struct

            if appid == 0:
                return # Done
            elif read < self.S_APP_HEADER.size:
                raise EOFError()

            self._apps[appid] = self.App(self, self.file.tell(), struct)

            self.file.seek(size - (self.S_APP_HEADER.size - 8), io.SEEK_CUR)

    @property
    def universe(self):
        if self._universe is None:
            self._load()
        return self._universe

    def __getattr__(self, attr):
        if attr in dir(dict):
            if self._apps is None:
                self._load()
            return getattr(self._apps, attr)
        raise AttributeError(attr)

    def __getitem__(self, key):
        if self._apps is None:
            self._load()
        return self._apps[key]
    
    def __iter__(self):
        if self._apps is None:
            self._load()
        return iter(self._apps)

    @property
    def dict(self):
        if self._apps is None:
            self._load()
        return self._apps

    # Cleanup
    def __enter__(self):
        return self
    
    def __exit__(self, exc, tp, tb):
        self.close()

    def close(self):
        if self._close_file:
            self.file.close()

