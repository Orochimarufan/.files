from ..profile import *


@profile
@description("Save the first audio track as FLAC.")
@output(ext="flac")
@singleaudio
def flac(task, stream):
    if stream.codec == "ape":
        stream.file.set(max_samples="all") # Monkey's insane preset is insane.
    (task.map_stream(stream)
        .set(codec="flac",
            compression_level="10"))
    return True
