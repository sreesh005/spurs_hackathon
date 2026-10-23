"""Safety net: every few minutes, ask TwelveLabs to list every clip-worthy moment in the last
few minutes, so anything the rules engine missed still gets clipped.

The window is re-encoded to a small 360p copy (~6 MB for 5 minutes) so it fits the 30 MB
inline limit of a sync analyze call. No upload, so it also works with DRY_RUN on.
"""

import subprocess
from pathlib import Path

from . import analyze

SCHEMA = {
    "type": "object",
    "properties": {
        "events": {"type": "array", "items": {"type": "object", "properties": {
            "seconds": {"type": "number"},
            "event_type": {"type": "string", "enum": [
                "goal", "shot_on_target", "shot_off_target", "save", "big_chance", "skill", "tackle",
                "foul", "free_kick", "corner", "penalty", "card", "celebration", "other"]},
            "team": {"type": "string", "enum": ["tottenham", "manchester_united", "both", "none"]},
            "caption": {"type": "string"},
        }, "required": ["seconds", "event_type", "team", "caption"]}},
    },
    "required": ["events"],
}

PROMPT = """You are scanning a Premier League broadcast, Manchester United (red) vs Tottenham Hotspur
(dark navy and purple away kit), for moments a social media team would clip.
List every goal, shot, save, big chance, notable skill, tackle, set piece (free kick, corner, penalty),
card and celebration. For each, give the seconds from the start of this video when the key action
happens, the event type, the team, and one factual sentence. Skip routine passing, stoppages,
substitutions and replays of a moment you have already listed. Return an empty list if nothing happens."""


def small_copy(mp4: Path) -> Path:
    out = mp4.with_name(mp4.stem + "_360.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-vf", "scale=-2:360", "-c:v", "libx264",
                    "-preset", "veryfast", "-b:v", "120k", "-c:a", "aac", "-b:a", "48k", "-ac", "1", str(out)],
                   check=True)
    return out


def scan(mp4: Path) -> list[dict]:
    """[{seconds, event_type, team, caption}] for a window, seconds relative to its start."""
    import json

    small = small_copy(mp4)
    try:
        res = analyze.call(small, PROMPT, SCHEMA, max_tokens=2048)
    finally:
        small.unlink(missing_ok=True)
    return json.loads(res["data"]).get("events", [])


def missed(events: list[dict], window_start: float, clipped_times: list[float], within: float) -> list[dict]:
    """Events the rules engine didn't already clip. `seconds` becomes absolute (`at`)."""
    out = []
    for e in events:
        at = window_start + float(e["seconds"])
        if not any(abs(at - t) <= within for t in clipped_times):
            out.append({**e, "at": at})
    return out
