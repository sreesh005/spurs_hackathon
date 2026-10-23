"""Fake ScorePlay live recording: what Live > Schedule makes of the feed, for the demo.

ffmpeg records the fake tracker's broadcast (video.mjpg) into an HLS EVENT playlist laid out like
ScorePlay's: original.m3u8 plus original_N.ts, 2s each, so segment N starts N x 2s into the recording.
The fake tracker serves the folder at /hls/, and the desk plays it through the same relay it uses for
the real recording (SCOREPLAY_LIVE_PLAYLIST points at it).
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from catalog import DATA

from . import footage

HLS_DIR = DATA / "demo" / "hls"
RECORDING_ID = 990000001  # stands in for the media ID ScorePlay gives the recording


class Recording:
    def __init__(self, tracker_url: str):
        self.tracker_url = tracker_url
        self.proc: subprocess.Popen | None = None
        self.started_at = 0.0
        self.media_id = RECORDING_ID

    def start(self) -> bool:
        if not footage.available():
            return False
        shutil.rmtree(HLS_DIR, ignore_errors=True)
        HLS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            import PIL  # noqa: F401  the tracker only draws its broadcast with Pillow

            source = ["-f", "mpjpeg", "-i", f"{self.tracker_url}/video.mjpg"]
            vf = "fps=10,format=yuv420p"
        except ImportError:
            source = ["-re", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=10"]
            vf = "format=yuv420p"
        cmd = ["ffmpeg", "-v", "error", "-y", *source, "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast",
               "-tune", "zerolatency", "-g", "20", "-keyint_min", "20", "-sc_threshold", "0", "-an",
               "-f", "hls", "-hls_time", "2", "-hls_playlist_type", "event",
               "-hls_segment_filename", "original_%d.ts", "original.m3u8"]
        self.proc = subprocess.Popen(cmd, cwd=HLS_DIR, stdin=subprocess.DEVNULL)
        self.started_at = time.time()
        return True

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
