"""Fake ScorePlay live recording: what Live > Schedule makes of the feed, for the demo.

ffmpeg records the fake tracker's broadcast into an HLS EVENT playlist laid out like
ScorePlay's: original.m3u8 plus original_N.ts, 2s each, so segment N starts N x 2s into the recording.
The fake tracker serves the folder at /hls/, and the desk plays it through the same relay it uses for
the real recording (SCOREPLAY_LIVE_PLAYLIST points at it).
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

from catalog import DATA

from . import footage

HLS_DIR = DATA / "demo" / "hls"
RECORDING_ID = 990000001  # stands in for the media ID ScorePlay gives the recording


class Recording:
    """Draws the fake tracker's broadcast at FPS frames a second and pipes it into ffmpeg, so the recording
    keeps real time (reading the MJPEG over HTTP, ffmpeg only got ~3 frames a second)."""

    FPS = 10

    def __init__(self, tracker):
        self.tracker = tracker
        self.proc: subprocess.Popen | None = None
        self.started_at = 0.0
        self.media_id = RECORDING_ID
        self.stop_flag = threading.Event()

    def start(self) -> bool:
        if not footage.available():
            return False
        shutil.rmtree(HLS_DIR, ignore_errors=True)
        HLS_DIR.mkdir(parents=True, exist_ok=True)
        piped = self.tracker.frame() is not None  # None without Pillow
        source = (["-f", "image2pipe", "-framerate", str(self.FPS), "-c:v", "mjpeg", "-i", "-"] if piped
                  else ["-re", "-f", "lavfi", "-i", f"testsrc2=s=640x360:r={self.FPS}"])
        cmd = ["ffmpeg", "-v", "error", "-y", *source, "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
               "-tune", "zerolatency", "-g", str(2 * self.FPS), "-keyint_min", str(2 * self.FPS), "-sc_threshold", "0", "-an",
               "-f", "hls", "-hls_time", "2", "-hls_playlist_type", "event",
               "-hls_segment_filename", "original_%d.ts", "original.m3u8"]
        self.proc = subprocess.Popen(cmd, cwd=HLS_DIR, stdin=subprocess.PIPE if piped else subprocess.DEVNULL)
        self.started_at = time.time()
        if piped:
            threading.Thread(target=self._feed, name="demo-recording", daemon=True).start()
        # don't point the desk at it until the first segment exists (like a ScorePlay schedule reaching LIVE)
        give_up = time.time() + 15
        while time.time() < give_up and not (HLS_DIR / "original.m3u8").exists():
            if self.proc.poll() is not None:
                print("demo: the stand-in ScorePlay recording could not start (ffmpeg exited)")
                return False
            time.sleep(0.25)
        return (HLS_DIR / "original.m3u8").exists()

    def _feed(self) -> None:
        tick = self.started_at
        while not self.stop_flag.is_set() and self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(self.tracker.frame())
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                return
            tick += 1 / self.FPS
            time.sleep(max(0.0, tick - time.time()))

    def stop(self) -> None:
        self.stop_flag.set()
        if self.proc and self.proc.poll() is None:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()  # lets ffmpeg finish the playlist
                self.proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.terminate()
