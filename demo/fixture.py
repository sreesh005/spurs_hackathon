"""Demo library: a small, real-shaped ScorePlay library for when there is no API key.

Fake raw ScorePlay records (players and media, same fields as /players and /media/search) go through
catalog.assemble_library, so the desk sees exactly the shape a real build gives it. Footage is drawn
by demo/footage.py into data/demo/media and served at /demo-media.
"""

from __future__ import annotations

import json
from pathlib import Path

from catalog import DATA, LIBRARY_PATH, SAS_BENCH, SAS_LINEUP, THFC_BENCH, THFC_LINEUP, assemble_library, load_library

from . import footage

DEMO_DIR = DATA / "demo"
MEDIA = DEMO_DIR / "media"
LIBRARY = DEMO_DIR / "library.json"
VERSION = 2  # bump to rebuild data/demo/library.json after changing this file
MATCH_DAY = "2026-09-28"

FULL_NAMES = {"antonín kinsk": "Antonín Kinský"}

# (file name, players by short name, seconds into the clip of the action, capture time on match day)
LIBRARY_MEDIA = [
    ("Solanke goal 16x9.mp4", ["Solanke"], "17:46:02"),
    ("Solanke goal 9x16.mp4", ["Solanke"], "17:46:02"),
    ("Kudus chance.mp4", ["Kudus"], "16:31:40"),
    ("Gallagher tackle.mp4", ["Gallagher"], "17:12:15"),
    ("Kinsky save 16x9.mp4", ["Kinsky"], "17:20:51"),
    ("Savio chance 9x16.mp4", ["Savio"], "17:28:09"),
    ("Van Hecke def actions.mp4", ["Van Hecke"], "16:58:30"),
    ("Tonali tackle 16x9.mp4", ["Tonali"], "17:05:44"),
    ("Bergvall cele.mp4", ["Bergvall"], "16:44:12"),
    ("Udogie chance.mp4", ["Udogie"], "16:50:03"),
]


def raw_players() -> list[dict]:
    out = []
    for index, needle in enumerate([*THFC_LINEUP, *THFC_BENCH, *SAS_LINEUP, *SAS_BENCH]):
        name = FULL_NAMES.get(needle) or " ".join(part[:1].upper() + part[1:] for part in needle.split())
        thumb = MEDIA / f"p_{50000 + index}.png"
        out.append({"ID": 50000 + index, "full_name": name, "profile_picture_thumb": f"/demo-media/{thumb.name}" if thumb.exists() else ""})
    return out


def _ms(clock: str) -> int:
    h, m, s = (int(x) for x in clock.split(":"))
    return ((h * 60 + m) * 60 + s) * 1000


def raw_media(players: list[dict]) -> list[dict]:
    from catalog import match_roster, short_name

    by_short = {}
    for p in players:
        info = match_roster(p["full_name"])
        by_short[short_name(p["full_name"], info["needle"] if info else "")] = p["ID"]
    out = []
    for index, (name, who, clock) in enumerate(LIBRARY_MEDIA):
        stem = Path(name).stem.lower().replace(" ", "_")
        out.append(
            {
                "ID": 900000 + index,
                "name": name,
                "type": "video",
                "compressed_url": f"/demo-media/lib_{stem}.mp4",
                "thumbnail_url": "",
                "duration": 8,
                "player_ids": [by_short[w] for w in who if w in by_short],
                "tc_in": _ms(clock) - 4000,
                "tc_out": _ms(clock) + 4000,
                "date": MATCH_DAY,
            }
        )
    return out


def _avatars(players: list[dict]) -> None:
    """Initials on a navy disc, so the dots show a face-sized marker like the real headshots."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return
    font_path = MEDIA / "font.ttf"
    for p in players:
        out = MEDIA / f"p_{p['ID']}.png"
        if out.exists():
            continue
        img = Image.new("RGB", (96, 96), (19, 35, 61))
        draw = ImageDraw.Draw(img)
        letters = "".join(part[0] for part in p["full_name"].split()[-2:]).upper()
        try:
            font = ImageFont.truetype(str(font_path), 36) if font_path.exists() else ImageFont.load_default()
        except OSError:
            font = ImageFont.load_default()
        box = draw.textbbox((0, 0), letters, font=font)
        draw.text(((96 - (box[2] - box[0])) / 2 - box[0], (96 - (box[3] - box[1])) / 2 - box[1]), letters, fill=(244, 241, 232), font=font)
        img.save(out)


def _render_library(media: list[dict]) -> None:
    for item in media:
        out = MEDIA / Path(item["compressed_url"]).name
        if out.exists():
            continue
        stem = Path(item["name"]).stem
        vertical = "9x16" in stem
        title = stem.replace(" 16x9", "").replace(" 9x16", "").upper()
        footage.render(out, title, f"Match day  {MATCH_DAY}", "SCOREPLAY LIBRARY", vertical=vertical, style="library")


def build_demo_library() -> dict:
    MEDIA.mkdir(parents=True, exist_ok=True)
    if not footage.available():
        print("demo: ffmpeg not found, so the demo clips will not play. Install ffmpeg and delete data/demo/.")
    else:
        footage.render(MEDIA / "_warmup.mp4", "warm up", "", "", seconds=1)  # copies the font next to the clips
        (MEDIA / "_warmup.mp4").unlink(missing_ok=True)
    _avatars(raw_players())
    players = raw_players()
    media = raw_media(players)
    _render_library(media)
    library = assemble_library(players, media)
    library["demo"] = VERSION
    library["game"]["thfc"] = {"label": "Man United vs Tottenham", "when": "Demo replay", "assets": len(media)}
    for club in library["clubs"]:
        if club["id"] == "thfc":
            club["when"] = "Demo replay"
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    LIBRARY.write_text(json.dumps(library), encoding="utf-8")
    return library


def load_demo_library() -> dict:
    if LIBRARY.exists():
        library = json.loads(LIBRARY.read_text(encoding="utf-8"))
        if library.get("demo") == VERSION:
            return library
    return build_demo_library()


def library_for_sim(demo: bool) -> dict:
    """The library the desk is showing: the demo one, or the real data/library.json."""
    if not demo and LIBRARY_PATH.exists():
        return load_library()
    return load_demo_library()
