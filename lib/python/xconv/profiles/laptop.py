from ..profile import *


@profile
@description("First Video H.264 Main fastdecode animation, max 1280x800; Audio AAC; Keep subtitles")
@output(container="matroska", ext="mkv")
def laptop(task):
    # add first video stream
    for s in task.iter_video_streams():
        (task.map_stream(s)
            .set(codec="libx264",
                tune=("fastdecode", "animation"),
                profile="main",
                preset="fast")
            .downscale(1280, 800))
        break
    # Add all audio streams (reencode to aac if necessary)
    for s in task.iter_audio_streams():
        os = task.map_stream(s)
        if s.codec != "aac":
            os.set(codec="aac")
    # add all subtitle and attachment streams
    for s in chain(task.iter_subtitle_streams(), task.iter_attachment_streams()):
        task.map_stream(s)
    # go
    return True
