"""Draws stand-in footage with ffmpeg, so every angle in the demo is a real, playable, labelled mp4.

Text goes through textfile= and the font is copied next to the clips, so no path or caption ever has
to be escaped inside an ffmpeg filter (Windows drive letters included).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

STYLES = {
    # background, accent: a wide broadcast, its replay, a phone in the stand, a ScorePlay library edit
    "broadcast": ("0x1d4a2c", "white"),
    "replay": ("0x2b2f4a", "0xffd166"),
    "quick": ("0x1d4a2c", "0x9dbe86"),
    "phone": ("0x3a2a1a", "0xff9f1c"),
    "library": ("0x13233d", "0x7fb2ff"),
}


def available() -> bool:
    return shutil.which("ffmpeg") is not None


def _font(work: Path) -> str | None:
    target = work / "font.ttf"
    if target.exists():
        return "font.ttf"
    for path in FONTS:
        if Path(path).exists():
            shutil.copyfile(path, target)
            return "font.ttf"
    return None


def render(out: Path, title: str, subtitle: str, badge: str, seconds: float = 8.0,
           vertical: bool = False, style: str = "broadcast") -> bool:
    """Write a labelled clip to `out`. Returns False (and writes nothing) when ffmpeg is missing."""
    if not available():
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent
    bg, accent = STYLES.get(style, STYLES["broadcast"])
    w, h = (360, 640) if vertical else (640, 360)
    stem = out.stem
    files = {"t": title, "s": subtitle, "b": badge}
    for k, text in files.items():
        (work / f".{stem}.{k}.txt").write_text(text, encoding="utf-8")
    font = _font(work)
    fontopt = f"fontfile={font}:" if font else ""
    big, small = (30, 18) if vertical else (38, 20)
    speed = "160" if style != "replay" else "60"  # the replay runs slow
    vf = ",".join([
        # pitch: halfway line, centre circle hint, a touchline
        f"drawbox=x={w // 2}:y=0:w=3:h={h}:color=white@0.25:t=fill",
        f"drawbox=x=0:y={h - 40}:w={w}:h=3:color=white@0.25:t=fill",
        f"drawbox=x={w // 2 - 60}:y={h // 2 - 60}:w=120:h=120:color=white@0.18:t=3",
        # the ball crossing the frame
        f"drawtext={fontopt}text='o':fontsize=34:fontcolor=white:x='mod(40+{speed}*t\\,{w})':y='{h // 2}+30*sin(2*t)'",
        f"drawtext={fontopt}textfile=.{stem}.b.txt:fontsize={small}:fontcolor=black:box=1:boxcolor={accent}@0.95:boxborderw=8:x=16:y=16",
        f"drawtext={fontopt}textfile=.{stem}.t.txt:fontsize={big}:fontcolor=white:x=(w-text_w)/2:y=h*0.30",
        f"drawtext={fontopt}textfile=.{stem}.s.txt:fontsize={small}:fontcolor={accent}:x=(w-text_w)/2:y=h*0.30+{big + 14}",
        f"drawtext={fontopt}text='%{{pts\\:hms}}':fontsize=16:fontcolor=white@0.8:x=w-tw-14:y=h-th-12",
    ])
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={bg}:s={w}x{h}:d={seconds}:r=25",
        "-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:a=0.04",
        "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "64k", "-shortest", "-movflags", "+faststart", out.name,
    ]
    try:
        subprocess.run(cmd, cwd=work, check=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"demo footage: ffmpeg failed for {out.name}: {exc}")
        return False
    finally:
        for k in files:
            (work / f".{stem}.{k}.txt").unlink(missing_ok=True)
    return True
