from ..profile import *


@profile
@description("Copy all streams to a new container")
@defines(format="Container format",
    fext="File extension")
@features(argshax=None)
def remux(task, defines, args):
    task.change_format(
        defines["format"] if "format" in defines else None,
        defines["fext"] if "fext" in defines and args.genout else None)
    return all(task.map_stream(s) for s in task.iter_streams())
