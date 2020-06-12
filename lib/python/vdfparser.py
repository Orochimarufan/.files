#!/usr/bin/env python3
# Parse Steam/Source VDF Files
# Reference: https://developer.valvesoftware.com/wiki/KeyValues#File_Format
# (c) 2015-2020 Taeyeon Mori; CC-BY-SA

from __future__ import unicode_literals

import io

from typing import Dict, Union

DeepDict = Dict[str, Union[str, "DeepDict"]]


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
