from ..profile import *


@profile
@description("Encode Opus Audio")
@output(ext="mka", container="matroska")
@defines(ogg="Use Ogg/Opus output container",
    bitrate="Target bitrate (Default 96k)")
@features(argshax=None)
@singleaudio
def opus(task, stream, defines, args):
    os = (task.map_stream(stream)
        .set(codec="libopus",
            vbr="on")
    # Defines
        .apply(defines, bitrate="b"))
    # Output format
    if "ogg" in defines:
        task.change_format("ogg", "opus" if args.genout else None)
    return True
