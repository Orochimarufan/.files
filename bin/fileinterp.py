#!/usr/bin/env python3
# (c) 2015 Taeyeon Mori
# execute a python file as if the lines were entered into an interactive prompt

import sys
import io
import code

try:
    import pygments, pygments.lexers, pygments.formatters
except:
    hl = None
else:
    pyg_lex = pygments.lexers.PythonLexer()
    pyg_fmt = pygments.formatters.Terminal256Formatter()
    def hl(code):
        return pygments.highlight(code, pyg_lex, pyg_fmt)


class IOIPythonPrefix:
    def __init__(self, init=1):
        self.count = init
        self.ctx = ""
        self.__enter__()

    def inc(self, by=1):
        self.count += by

    def __call__(self, ctx):
        self.ctx = ctx
        return self

    def __enter__(self):
        self.prefix = "%s\033[0m[\033[31m%2d\033[0m] " % (self.ctx, self.count)

    def __exit__(self, *a):
        pass


class IOPrefixWrapper:
    def __init__(self, parent, pfx):
        self.parent = parent
        self.prefix = pfx
        self.nl = True

    def write(self, text):
        lines = text.splitlines(True)
        if lines:
            if self.nl:
                self.parent.write(self.prefix.prefix)
            self.parent.write(lines[0])
            for line in lines[1:]:
                self.parent.write(self.prefix.prefix)
                self.parent.write(line)
            self.nl = lines[-1].endswith("\n")

    def flush(self):
        return self.parent.flush()


xcount = IOIPythonPrefix()
sys.stdout = IOPrefixWrapper(sys.stdout, xcount)
interp = code.InteractiveInterpreter()


def print_in_x(cmd_lines):
    with xcount("\033[34mIn "):
        print(">>>", cmd_lines[0], end="")
        for line in cmd_lines[1:]:
            print("...", line, end="")

def print_in_hl(cmd_lines):
        print_in_x(hl("".join(cmd_lines)).splitlines(True))

if hl:
    print_in = print_in_hl
else:
    print_in = print_in_x
        


def compile_lines(lines):
    return code.compile_command("".join(lines))

def isindent(c):
    return c in " \t"


with open(sys.argv[1]) as f:
    ln = 0
    peekbuf = []

    def readline():
        global ln, peekbuf
        ln += 1
        if peekbuf:
            l = peekbuf.pop(0)
        else:
            l = f.readline()
        if not l:
            raise SystemExit()
        return l
    
    def peekline(n=0):
        global peekbuf
        while len(peekbuf) <= n:
            peekbuf.append(f.readline())
        return peekbuf[n]
    
    def peekindent():
        i = 0
        while not peekline(i).strip():
            i += 1
        return isindent(peekline(i)[0])

    while True:
        cmd_lines = [readline()]

        c = compile_lines(cmd_lines)
        if not c:
            while not c:
                cmd_lines.append(readline())
                while peekindent():
                    cmd_lines.append(readline())
                c = compile_lines(cmd_lines)

        print_in(cmd_lines)

        with xcount("\033[33mOut"):
            interp.runcode(c)
        #sys.stdout.parent.write("\n")
        xcount.inc()

