"""Local signals for the rules engine, one set per 2s feed segment.

- Loudness of the full mix and of the speech band (commentary energy): ffmpeg's EBU R128
  meter. MediaPipe classifies sounds but doesn't measure volume, so this part is ffmpeg.
- Crowd roar, whistle, people, shot type, camera cuts, stillness, raised arms (pose, close-ups only):
  MediaPipe (mp_signals.py).
"""

import re
import statistics
import subprocess
from collections import deque
from dataclasses import dataclass

LINE_RE = re.compile(r"Parsed_ebur128_(\d+) .*?t:\s*([\d.]+)\s+TARGET:.*?M:\s*(-?[\d.]+)")
FLOOR_LUFS = -70.0  # silence reads as -120.7; clamp so it doesn't wreck the baseline


@dataclass
class Signals:
    t: float  # segment start: unix seconds (live) or match offset (replay)
    duration: float
    loudness: float  # mean momentary loudness of the full mix, LUFS
    voice: float  # same for the 300-3000 Hz band
    loud_z: float = 0.0
    voice_z: float = 0.0
    drop: float = 0.0  # highest loud_z in the previous 6s minus now
    # MediaPipe (mp_signals.py)
    roar: float = 0.0  # raw max score of cheering/crowd/noise classes
    cheer: float = 0.0  # roar against the recent baseline, 0 to 1 (set by Tracker)
    whistle: float = 0.0
    shot: str = "unknown"  # wide | medium | closeup | crowd | unknown
    people: int = 0
    still: float = 0.0
    cut: bool = False
    arms_up: bool = False  # MediaPipe pose, close-ups only

    def apply(self, v, shot_cfg: dict) -> "Signals":
        from .mp_signals import shot_type

        self.roar, self.whistle, self.people = v.cheer, v.whistle, v.people
        self.still, self.cut, self.shot = v.still, v.cut, shot_type(v, shot_cfg)
        self.arms_up = v.arms_up
        return self


def loudness_series(src: str, start: float | None = None, duration: float | None = None) -> list[tuple[float, float, float]]:
    """[(t, mix_lufs, voice_lufs)] every 0.1s, t relative to `start`. One ffmpeg pass, audio only."""
    cmd = ["ffmpeg", "-nostats", "-hide_banner"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += [
        "-i", src, "-vn", "-filter_complex",
        "[0:a]asplit=2[a][b];[a]ebur128=framelog=info[oa];"
        "[b]highpass=f=300,lowpass=f=3000,ebur128=framelog=info[ob]",
        "-map", "[oa]", "-f", "null", "-", "-map", "[ob]", "-f", "null", "-",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True).stderr
    mix, voice = {}, {}
    filters = sorted({int(m.group(1)) for m in LINE_RE.finditer(out)})
    if len(filters) != 2:
        return []
    for m in LINE_RE.finditer(out):
        which, t, lufs = int(m.group(1)), round(float(m.group(2)), 1), max(float(m.group(3)), FLOOR_LUFS)
        (mix if which == filters[0] else voice)[t] = lufs
    return [(t, mix[t], voice.get(t, mix[t])) for t in sorted(mix)]


def measure(path: str, t: float, duration: float, shot_cfg: dict, use_mediapipe: bool = True) -> Signals:
    """Signals for one segment file (live mode). Tracker adds the z-scores afterwards."""
    series = loudness_series(path)
    mix = [x[1] for x in series] or [FLOOR_LUFS]
    voice = [x[2] for x in series] or [FLOOR_LUFS]
    s = Signals(t=t, duration=duration, loudness=statistics.fmean(mix), voice=statistics.fmean(voice))
    if use_mediapipe:
        from .mp_signals import views

        v = views(path, seg=duration)
        if v:
            s.apply(v[0], shot_cfg)
    return s


def measure_range(src: str, start: float, duration: float, shot_cfg: dict, use_mediapipe: bool = True,
                  seg: float = 2.0) -> list[Signals]:
    """Signals for every `seg` seconds of a longer video (replay mode). `t` is the match offset.

    A remote source is first saved as a small local 360p copy of just this range (one download),
    because reading a remote 1080p file several times is slow and dies if the connection drops."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        local = str(Path(tmp) / "range.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(duration), "-i", src,
                        "-vf", "scale=-2:360", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                        "-c:a", "aac", "-b:a", "128k", local], check=True, timeout=max(120, duration * 2))
        out = bucket(loudness_series(local), offset=start, seg=seg)
        if use_mediapipe:
            from .mp_signals import views

            for s, v in zip(out, views(local, seg=seg)):
                s.apply(v, shot_cfg)
    return out


def bucket(series: list[tuple[float, float, float]], offset: float, seg: float = 2.0) -> list[Signals]:
    """Group a 0.1s loudness series into segment-sized Signals (replay mode). `offset` = match time of t=0."""
    groups: dict[int, list[tuple[float, float]]] = {}
    for t, mix, voice in series:
        groups.setdefault(int(t // seg), []).append((mix, voice))
    return [
        Signals(t=offset + k * seg, duration=seg,
                loudness=statistics.fmean(v[0] for v in vals), voice=statistics.fmean(v[1] for v in vals))
        for k, vals in sorted(groups.items())
    ]


class Tracker:
    """Turns raw loudness into z-scores against a rolling baseline, and the 'went quiet' drop."""

    def __init__(self, baseline_seconds: float = 60, seg: float = 2.0):
        n = max(5, int(baseline_seconds / seg))
        self.mix: deque[float] = deque(maxlen=n)
        self.voice: deque[float] = deque(maxlen=n)
        self.recent_z: deque[float] = deque(maxlen=3)  # previous 6s
        self.roar: deque[float] = deque(maxlen=n)

    @staticmethod
    def _z(x: float, hist: deque[float]) -> float:
        if len(hist) < 5:
            return 0.0
        sd = max(statistics.pstdev(hist), 1.5)  # floor: 1.5 LU, so a flat baseline doesn't explode
        return (x - statistics.fmean(hist)) / sd

    def update(self, s: Signals) -> Signals:
        s.loud_z = self._z(s.loudness, self.mix)
        s.voice_z = self._z(s.voice, self.voice)
        s.drop = (max(self.recent_z) - s.loud_z) if self.recent_z else 0.0
        base = statistics.fmean(self.roar) if self.roar else s.roar
        s.cheer = min(1.0, max(0.0, (s.roar - base) / 0.1))  # +0.1 over baseline reads as a full cheer
        self.mix.append(s.loudness)
        self.voice.append(s.voice)
        self.recent_z.append(s.loud_z)
        self.roar.append(s.roar)
        return s
