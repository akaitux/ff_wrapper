#! /usr/bin/env python3

import sys
import time
from ffmpeg import FFMpegProc
from config import Config
from ffmpeg_manager import FFMpegManager


if __name__ == "__main__":
    args = ' '.join(sys.argv[1:])
    cfg = Config()
    ffmpeg = FFMpegProc(args)
    process = ffmpeg.run()
    if process is None:
        ffmpeg.stop()
        sys.exit(1)
    cfg.FFMPEG_PID = str(process.pid)
    cfg.save_status_to_files()
    ffmpeg_manager = FFMpegManager(ffmpeg)
    ffmpeg_manager.run()
    while True:
        try:
            time.sleep(0.5)
            if ffmpeg.finish:
                break
        except KeyboardInterrupt:
            break
    ffmpeg.stop()
    ffmpeg_manager.stop()
    time.sleep(1)
    sys.exit(1)
