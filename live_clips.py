"""LIVE CLIPS. Backend for the Live dots drawer. Not the screen.

Builds a per-player collection of clips while the match is on:

1. Captured live: the auto-clipper (sarang/pipeline/live.py) appends one JSON line per analyzed clip to
   <root>/runs/live_*.jsonl and leaves the mp4 (plus a .json sidecar with wall-clock and match offsets)
   in <root>/clips/. This module tails those files, so a clip shows on the desk seconds after TwelveLabs
   names the players in it.
2. Phone and camera uploads: <root>/scoreplay_uploads.jsonl, one ScorePlay media record per line
   (ID, name, compressed_url, tc_in, tc_out, date, player_ids). The demo writes it. A live poll of
   ScorePlay's /media/search would feed the same shape.
3. Fallback: the pre-loaded ScorePlay library (data/library.json) for players with nothing captured yet.

Then every clip is grouped into moments: one play, several angles. Two clips are the same play when
their match time overlaps, their capture clock overlaps, one is the broadcast replay of the other, or
(weakest) they are the same goal by the same player and no clock says otherwise.

Pure functions (normalize_record, resolve_players, group_moments) are unit-tested in tests/.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Events that are one-off enough to match a live clip to a library clip on content alone.
UNIQUE_EVENTS = {"goal", "penalty", "save", "big_chance", "card", "shot_on_target"}
LIBRARY_EVENT = {
    "GOAL": "goal",
    "CHANCE": "big_chance",
    "TACKLE": "tackle",
    "CELE": "celebration",
    "SUB": "substitution",
    "PLAY": "play",
}
EVENT_PLAIN = {
    "goal": "Goal",
    "shot_on_target": "Shot on target",
    "shot_off_target": "Shot off target",
    "save": "Save",
    "big_chance": "Big chance",
    "skill": "Skill",
    "tackle": "Tackle",
    "foul": "Foul",
    "free_kick": "Free kick",
    "corner": "Corner",
    "penalty": "Penalty",
    "card": "Card",
    "substitution": "Substitution",
    "celebration": "Celebration",
    "injury": "Injury",
    "build_up": "Build-up",
    "play": "Play",
}
SKIP_EVENTS = {"none"}
OVERLAP_SLACK = 4.0  # seconds of slack when two clocks say "same moment"
REPLAY_WINDOW = 45.0  # a broadcast replay lands within this many seconds after the play
CONFLICT_GAP = 60.0  # two live clips this far apart on one clock are different plays
KEY_SPAN = 3.0  # clips are matched on their key moment, +- this many seconds (not the whole clip)
MOMENT_RE = re.compile(r"^m(\d+)_(quick|full)_")


# ---------- normalizing ----------


@dataclass
class Clip:
    id: str
    source: str  # live | upload | scoreplay
    label: str  # how the angle reads in the drawer: Broadcast, Broadcast replay, Phone, Camera A...
    event: str
    team: str
    caption: str
    video: str
    thumb: str = ""
    duration: float = 0.0
    key_seconds: float = 0.0  # where the action is inside this file
    player_ids: list[int] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    match: tuple[int, float, float] | None = None  # (media_id, key - KEY_SPAN, key + KEY_SPAN), seconds into that media
    tod: tuple[float, float] | None = None  # capture clock around the action: seconds since midnight UTC
    day: str = ""  # capture date, YYYY-MM-DD: the clock only matches clips from the same day
    is_replay: bool = False
    captured_at: float = 0.0  # unix time the clip became available
    confidence: float | None = None
    found_by: str = ""
    group_hint: str = ""  # clips sharing a hint are one play already (catalog file groups, quick/full)
    superseded: bool = False
    importance: float = 0.0
    extra: dict = field(default_factory=dict)

    def public(self) -> dict:
        out = {
            "id": self.id,
            "source": self.source,
            "label": self.label,
            "event": self.event,
            "event_plain": EVENT_PLAIN.get(self.event, self.event.replace("_", " ").capitalize()),
            "team": self.team,
            "caption": self.caption,
            "video": self.video,
            "thumb": self.thumb,
            "duration": round(self.duration, 1),
            "key_seconds": round(self.key_seconds, 1),
            "player_ids": self.player_ids,
            "names": self.names,
            "is_replay": self.is_replay,
            "captured_at": self.captured_at or None,
            "confidence": self.confidence,
            "found_by": self.found_by,
        }
        if self.match:
            out["match"] = {"media_id": self.match[0], "start": round(self.match[1], 1), "end": round(self.match[2], 1)}
        out.update(self.extra)
        return out


def _tod(unix: float) -> float:
    d = datetime.fromtimestamp(unix, timezone.utc)
    return d.hour * 3600 + d.minute * 60 + d.second + d.microsecond / 1e6


def _day(value) -> str:
    """YYYY-MM-DD from a unix time or an ISO-ish date string; "" when unknown."""
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d")
    text = str(value or "")
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else ""


def normalize_record(rec: dict, sidecar: dict | None, clip_key: str, run_name: str, seen_at: float) -> Clip | None:
    """One line of the auto-clipper's runs/live_*.jsonl -> Clip. None when there is nothing to show."""
    a = rec.get("analysis") or {}
    event = a.get("event_type") or "none"
    if event in SKIP_EVENTS:
        return None
    wb = rec.get("writeback") or {}
    side = sidecar or {}
    stem = Path(rec.get("clip") or clip_key).stem
    key_in_clip = float(a.get("key_moment_seconds") or 0)
    duration = float(side.get("duration") or 0)

    # Match on the key moment, not the whole log window: the clipper logs key-8..key+12, so two
    # different plays 18s apart would otherwise overlap.
    match = None
    media_id = wb.get("media_id") or rec.get("media_id")
    key = None
    if wb.get("log_at") is not None:
        key = float(wb["log_at"])
    elif side.get("source_start_offset") is not None:
        key = float(side["source_start_offset"]) + key_in_clip
    if key is not None and media_id:
        match = (int(media_id), key - KEY_SPAN, key + KEY_SPAN)

    # A replay's wall clock is when the broadcast showed it, not when the play happened: no capture time.
    tod, day = None, ""
    if side.get("start_unix"):
        key_unix = float(side["start_unix"]) + key_in_clip
        day = _day(key_unix)
        if not a.get("is_replay"):
            tod = (_tod(key_unix - KEY_SPAN), _tod(key_unix + KEY_SPAN))

    cut = rec.get("cut") or "full"
    found_by = rec.get("found_by") or "rules"
    is_replay = bool(a.get("is_replay"))
    if is_replay:
        label = "Broadcast replay"
    elif cut == "quick":
        label = "Quick cut"
    elif found_by == "sweep":
        label = "Broadcast (safety net)"
    else:
        label = "Broadcast"

    hint = ""
    m = MOMENT_RE.match(stem)
    if m:
        hint = f"{run_name}:m{m.group(1)}"

    extra = {"cut": cut, "clip_key": stem}
    upload = wb.get("upload") or {}
    if upload.get("media_id"):
        extra["scoreplay_media_id"] = upload["media_id"]
    if wb.get("log_at") is not None:
        extra["log_at"] = wb.get("log_at")
    if wb.get("log_range"):
        extra["log_range"] = wb["log_range"]
    if a.get("commentary_quote"):  # football-v3
        extra["quote"] = a["commentary_quote"]
    extra["in_scoreplay"] = "written" if upload.get("media_id") else ("dry run" if upload.get("dry_run") else ("logged" if wb.get("tags") else ""))

    return Clip(
        id=f"live:{clip_key}",
        source="live",
        label=label,
        event=event,
        team=a.get("team") or "",
        caption=a.get("caption") or "",
        video="",  # filled by the index (needs the serving route)
        duration=duration,
        key_seconds=key_in_clip,
        player_ids=[int(p) for p in wb.get("players") or []],
        names=list(a.get("tottenham_players") or []),
        match=match,
        tod=tod,
        day=day,
        is_replay=is_replay,
        captured_at=min(float(side.get("end_unix") or seen_at), seen_at),
        confidence=a.get("confidence"),
        found_by=found_by,
        group_hint=hint,
        importance=1.0 if a.get("is_highlight") else 0.5,
        extra=extra,
    )


def _tags(log: dict) -> list[str]:
    """raw_tags as plain strings, whether ScorePlay returns strings or {name|value|label} objects."""
    out = []
    for t in log.get("raw_tags") or log.get("tags") or []:
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, dict):
            v = t.get("name") or t.get("value") or t.get("label") or t.get("raw_tag") or ""
            if v:
                out.append(str(v))
    return out


def _tag(tags: list[str], key: str) -> str:
    return next((t.split(":", 1)[1] for t in tags if t.startswith(key + ":")), "")


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _when(value) -> float | None:
    """A unix time from seconds, milliseconds, or an ISO date."""
    n = _num(value)
    if n is not None:
        return n / 1000.0 if n > 1e11 else n
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def normalize_log(log: dict, media_id: int, seen_at: float, relay=None) -> Clip | None:
    """One ScorePlay video log the auto-clipper wrote back (sarang/pipeline/writeback.py) -> Clip.

    Only logs tagged source:twelvelabs count. ScorePlay makes each log on a live recording into a clip
    with its own playback URL, which is what the drawer plays. `relay` turns that URL into one the desk serves.
    """
    tags = _tags(log)
    if "source:twelvelabs" not in tags:
        return None
    event = _tag(tags, "event") or "play"
    if event in SKIP_EVENTS:
        return None
    start = _num(log.get("start_offset"))
    end = _num(log.get("end_offset"))
    if start is None:
        start = _num(log.get("offset"))
    match = None
    if start is not None:
        # the clipper logs key-8 .. key+12, kept inside its clip: the key moment is 8s in when there is room
        key = start + 8 if end is None or end - start >= 16 else (start + (end if end is not None else start)) / 2
        match = (int(media_id), key - KEY_SPAN, key + KEY_SPAN)
    players = log.get("players") or []
    ids = [int(p["id"]) for p in players if isinstance(p, dict) and p.get("id") is not None]
    ids += [int(x) for x in log.get("player_ids") or [] if int(x) not in ids]
    names = [p.get("name") for p in players if isinstance(p, dict) and p.get("name")]
    comment = (log.get("comment") or log.get("description") or "").strip()
    caption, _, rest = comment.partition("\n")
    quote = rest.split("Commentary:", 1)[1].strip().strip('"') if "Commentary:" in rest else ""
    video = log.get("playback_url") or log.get("clip_url") or log.get("video_url") or ""
    if not video:
        return None  # ScorePlay hasn't made the clip yet: the next poll picks it up
    clip_id = _tag(tags, "clip")
    is_replay = "replay" in tags
    cut = _tag(tags, "cut") or "full"
    hint = ""
    m = MOMENT_RE.match(clip_id)
    if m:
        hint = f"sp{media_id}:{clip_id.rsplit('_', 1)[0].replace('_quick', '').replace('_full', '')}:{clip_id.rsplit('_', 1)[-1]}"
    found_by = _tag(tags, "found_by") or "rules"
    label = "Broadcast replay" if is_replay else ("Quick cut" if cut == "quick" else ("Broadcast (safety net)" if found_by == "sweep" else "Broadcast"))
    created = _when(log.get("created_at") or log.get("createdAt"))
    log_id = log.get("ID") or log.get("id")
    return Clip(
        id=f"log:{log_id}",
        source="live",
        label=label,
        event=event,
        team=_tag(tags, "team"),
        caption=caption or clip_id,
        video=relay(video) if relay else video,
        thumb=log.get("thumbnail_url") or log.get("thumbnail") or "",
        duration=(end - start) if (start is not None and end is not None) else 0.0,
        player_ids=ids,
        names=names,
        match=match,
        is_replay=is_replay,
        captured_at=min(created or seen_at, seen_at),
        confidence=_num(_tag(tags, "confidence")),
        found_by=found_by,
        group_hint=hint,
        importance=1.0 if event in UNIQUE_EVENTS or event == "skill" else 0.5,
        extra={"cut": cut, "clip_key": clip_id, "in_scoreplay": "in ScorePlay", "scoreplay_log_id": log_id,
               "scoreplay_media_id": media_id, "quote": quote, "from": "scoreplay"},
    )


def normalize_upload(rec: dict, seen_at: float) -> Clip | None:
    """One ScorePlay media record (a phone or camera upload during the match) -> Clip."""
    if rec.get("type", "video") != "video" or not rec.get("compressed_url"):
        return None
    name = rec.get("name") or ""
    tod = None
    if rec.get("tc_in") is not None and rec.get("tc_out") is not None:
        tod = (float(rec["tc_in"]) / 1000.0, float(rec["tc_out"]) / 1000.0)
    low = name.lower()
    shape = "Vertical 9:16" if "9x16" in low else ""
    who = rec.get("source_label") or ("Phone" if "phone" in low or "iphone" in low else "Camera upload")
    label = f"{who} · {shape}" if shape else who
    event = rec.get("event") or LIBRARY_EVENT.get(_library_action(name), "play")
    return Clip(
        id=f"upload:{rec.get('ID')}",
        source="upload",
        label=label,
        event=event,
        team=rec.get("team") or "",
        caption=rec.get("description") or re.sub(r"\.[a-z0-9]+$", "", name, flags=re.I),
        video=rec["compressed_url"],
        thumb=rec.get("thumbnail_url") or "",
        duration=float(rec.get("duration") or 0),
        key_seconds=float(rec.get("key_seconds") or 0),
        player_ids=[int(p) for p in rec.get("player_ids") or []],
        tod=tod,
        day=_day(rec.get("date")),
        captured_at=float(rec.get("uploaded_at") or seen_at),
        found_by="upload",
        importance=0.8,
        extra={"scoreplay_media_id": rec.get("ID")},
    )


def _library_action(name: str) -> str:
    try:
        from catalog import infer_action

        return infer_action(name)
    except Exception:  # catalog is optional for the pure functions
        return "PLAY"


ANGLE_LABEL = {"9x16": "Vertical 9:16", "16x9": "Edit 16:9", "4x5": "Edit 4:5", "1x1": "Square edit", "cut": "Edit", "noaudio": "Edit, no audio", "clip": "Edit"}


def library_clips(library: dict, club: str = "thfc") -> list[Clip]:
    """Pre-loaded ScorePlay plays -> one Clip per angle. Angles of one play share a group hint."""
    out = []
    for play in library.get("plays") or []:
        if play.get("club") != club or play.get("mode") in ("broadcast", "context"):
            continue
        if play.get("action") in ("HIGHLIGHTS", "FULL"):
            continue
        ids = [p["id"] for p in play.get("players") or []]
        for angle in play.get("angles") or []:
            if not angle.get("video"):
                continue
            label = angle.get("label") or ""
            nice = ANGLE_LABEL.get(label.lower()) or (f"Camera {label}" if len(label) == 1 else label or "Clip")
            tod = None
            if angle.get("tc_in") is not None and angle.get("tc_out") is not None:
                tod = (float(angle["tc_in"]) / 1000.0, float(angle["tc_out"]) / 1000.0)
            out.append(
                Clip(
                    id=f"sp:{angle['id']}",
                    source="scoreplay",
                    label=nice,
                    event=LIBRARY_EVENT.get(play.get("action") or "", (play.get("action") or "play").lower()),
                    team="tottenham",
                    # the catalog's caption ends "2 versions." / "3 angles.": the drawer counts angles itself
                    caption=re.sub(r"\s*\d+ (versions|angles)\.$", "", (play.get("captions") or {}).get("matchday") or play.get("title") or ""),
                    video=angle["video"],
                    thumb=angle.get("thumb") or "",
                    duration=float(angle.get("duration") or 0),
                    player_ids=ids,
                    tod=tod,
                    day=_day(angle.get("date")),
                    found_by="library",
                    group_hint=f"play:{play['id']}",
                    importance=float(play.get("importance") or 0.5),
                    extra={
                        "scoreplay_media_id": angle["id"],
                        "play_id": play["id"],
                        "title": re.sub(r"\.[a-z0-9]+$", "", play.get("title") or "", flags=re.I),
                        "named_id": play.get("named_id"),
                        "crowd": len(ids),
                    },
                )
            )
    return out


# ---------- players ----------


def _parts(name: str) -> list[str]:
    return [p for p in re.split(r"[\s'\-]+", (name or "").lower()) if len(p) > 3]


def resolve_players(clip: Clip, people: list[dict]) -> list[int]:
    """Player IDs for a clip: the IDs the clipper tagged in ScorePlay, else the names TwelveLabs gave,
    matched to the roster by full name, then by a distinctive part of it (Solanke, Kudus...)."""
    known = {int(p["id"]) for p in people}
    ids = [pid for pid in clip.player_ids if pid in known]
    if ids:
        return ids
    out: list[int] = []
    for name in clip.names:
        low = name.lower().strip()
        hit = next((p for p in people if (p.get("name") or "").lower() == low), None)
        if not hit:
            wanted = set(_parts(name))
            hits = [p for p in people if wanted & (set(_parts(p.get("name") or "")) | set(_parts(p.get("short") or "")))]
            hit = hits[0] if len(hits) == 1 else None  # two Johnsons: don't guess
        if hit and int(hit["id"]) not in out:
            out.append(int(hit["id"]))
    return out


# ---------- grouping angles into moments ----------


def _overlap(a: tuple[float, float], b: tuple[float, float], slack: float) -> bool:
    return a[0] - slack <= b[1] and b[0] - slack <= a[1]




def _gap(a: tuple[int, float, float], b: tuple[int, float, float]) -> float | None:
    if a[0] != b[0]:
        return None
    return max(0.0, max(a[1], b[1]) - min(a[2], b[2]))


def link_reason(a: Clip, b: Clip) -> tuple[int, str] | None:
    """Why two clips show the same play, strongest first (lower = stronger). None if no reason."""
    if a.group_hint and a.group_hint == b.group_hint:
        return 0, "same file group" if a.source == "scoreplay" else "quick and full cut of one moment"
    same_media = bool(a.match and b.match and a.match[0] == b.match[0])
    if same_media:
        gap = _gap(a.match, b.match)
        if gap is not None and gap <= OVERLAP_SLACK and not (a.is_replay or b.is_replay):
            return 1, "same match time"
    # Two clips cut from one video are placed by the match clock alone; capture time is for the rest.
    if not same_media and a.tod and b.tod and a.day and a.day == b.day and _overlap(a.tod, b.tod, OVERLAP_SLACK):
        return 1, "same capture time"
    if a.match and b.match and (a.is_replay != b.is_replay) and a.event == b.event:
        play, replay = (a, b) if b.is_replay else (b, a)
        if play.match[0] == replay.match[0] and 0 <= replay.match[1] - play.match[1] <= REPLAY_WINDOW:
            return 2, "broadcast replay of the play"
    if (
        a.event == b.event
        and a.event in UNIQUE_EVENTS
        and set(a.player_ids) & set(b.player_ids)
        and "live" in (a.source, b.source)
        and "scoreplay" in (a.source, b.source)
    ):
        return 3, f"same {EVENT_PLAIN.get(a.event, a.event).lower()}, same player"
    return None


def _conflict(xs: list[Clip], ys: list[Clip]) -> bool:
    """Would joining these two groups put two different plays together?"""
    for x in xs:
        for y in ys:
            if x.match and y.match:
                gap = _gap(x.match, y.match)
                if gap is not None and gap > (REPLAY_WINDOW if (x.is_replay or y.is_replay) else CONFLICT_GAP):
                    return True
            if x.tod and y.tod and x.day and x.day == y.day:
                if max(x.tod[0], y.tod[0]) - min(x.tod[1], y.tod[1]) > CONFLICT_GAP:
                    return True
            if x.source == y.source == "scoreplay" and x.group_hint != y.group_hint:
                return True  # the catalog already decided these are different plays
    return False


def group_moments(clips: list[Clip]) -> list[dict]:
    """Union clips into moments. Strong links first; a weak link never joins groups a clock keeps apart."""
    parent = list(range(len(clips)))
    members = {i: [i] for i in range(len(clips))}
    reasons: dict[int, set[str]] = {i: set() for i in range(len(clips))}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    links = []
    for i in range(len(clips)):
        for j in range(i + 1, len(clips)):
            why = link_reason(clips[i], clips[j])
            if why:
                links.append((why[0], i, j, why[1]))
    links.sort()
    for _, i, j, why in links:
        ri, rj = find(i), find(j)
        if ri == rj:
            if why != "same file group":
                reasons[ri].add(why)
            continue
        if _conflict([clips[k] for k in members[ri]], [clips[k] for k in members[rj]]):
            continue
        parent[rj] = ri
        members[ri].extend(members.pop(rj))
        reasons[ri] |= reasons.pop(rj)
        if why != "same file group":
            reasons[ri].add(why)

    moments = []
    for root, idx in members.items():
        group = [clips[k] for k in idx]
        moments.append(_moment(group, sorted(reasons.get(root) or [])))
    return moments


SOURCE_RANK = {"live": 0, "upload": 1, "scoreplay": 2}


def _angle_rank(c: Clip) -> tuple:
    return (SOURCE_RANK.get(c.source, 3), c.is_replay, c.label == "Quick cut", -c.importance, c.id)


def _moment(group: list[Clip], reasons: list[str]) -> dict:
    group = sorted(group, key=_angle_rank)
    lead = group[0]
    players: list[int] = []
    for c in group:
        for pid in c.player_ids:
            if pid not in players:
                players.append(pid)
    live = [c for c in group if c.source in ("live", "upload")]
    at = max((c.captured_at for c in live), default=0.0)
    match = next((c.match for c in group if c.match and not c.is_replay), None)
    return {
        "id": "mo:" + lead.id,
        "event": lead.event,
        "event_plain": EVENT_PLAIN.get(lead.event, lead.event.replace("_", " ").capitalize()),
        "team": lead.team,
        "caption": lead.caption,
        "player_ids": players,
        "live": bool(live),
        "captured_at": at or None,
        "first_seen": min((c.captured_at for c in live), default=0.0) or None,
        "match": {"media_id": match[0], "start": round(match[1], 1), "end": round(match[2], 1)} if match else None,
        "importance": max(c.importance for c in group),
        "angle_count": len(group),
        "views": len({c.label for c in group}),
        "grouped_by": reasons,
        "angles": [c.public() for c in group],
    }


# ---------- the index the server keeps ----------


class ClipIndex:
    """Tails the clipper's run files and keeps every live clip, upload and library clip, grouped."""

    def __init__(self, roots: list[Path], library: dict | None = None, min_refresh: float = 0.5):
        self.roots = [Path(r) for r in roots]
        self.library = library or {}
        self.min_refresh = min_refresh
        self.lock = threading.Lock()
        self.offsets: dict[Path, int] = {}
        self.live: dict[str, Clip] = {}
        self.paths: dict[str, Path] = {}  # clip key -> mp4 on disk, so /api/live/media can serve it
        self.uploads: dict[str, Clip] = {}
        self.version = 0
        self.last_refresh = 0.0
        self.scoreplay_seen = 0.0  # last time a clip came in from ScorePlay
        self._lib_clips: list[Clip] | None = None
        self._moments: list[dict] | None = None
        self._moments_version = -1
        self._lib_version = 0

    def set_library(self, library: dict) -> None:
        with self.lock:
            self.library = library
            self._lib_clips = None
            self._lib_version += 1
            self._moments = None

    def people(self) -> list[dict]:
        club = next((c for c in self.library.get("clubs") or [] if c.get("id") == "thfc"), None)
        return [*club["lineup"], *club["bench"]] if club else []

    # -- tailing --

    def refresh(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self.last_refresh < self.min_refresh:
            return
        with self.lock:
            self.last_refresh = now
            changed = False
            for root in self.roots:
                runs = root / "runs"
                if runs.is_dir():
                    for path in sorted(runs.glob("live_*.jsonl")):
                        changed |= self._tail(path, lambda line, p=path, r=root: self._add_live(line, p, r))
                ups = root / "scoreplay_uploads.jsonl"
                if ups.is_file():
                    changed |= self._tail(ups, self._add_upload)
            if changed:
                self._supersede()
                self.version += 1

    def _tail(self, path: Path, handle) -> bool:
        start = self.offsets.get(path, 0)
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size < start:
            start = 0  # file was replaced
        if size == start:
            return False
        with path.open("rb") as f:
            f.seek(start)
            chunk = f.read(size - start)
        end = chunk.rfind(b"\n")
        if end < 0:
            return False  # half-written line: wait for the rest
        self.offsets[path] = start + end + 1
        changed = False
        for line in chunk[: end + 1].decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                changed |= bool(handle(json.loads(line)))
            except (ValueError, KeyError, TypeError) as exc:
                print(f"live_clips: skipped a line in {path.name}: {exc}")
        return changed

    def _add_live(self, rec: dict, run_path: Path, root: Path) -> bool:
        name = rec.get("clip") or ""
        if not name:
            return False
        mp4 = root / "clips" / name
        side_path = mp4.with_suffix(".json")
        sidecar = None
        if side_path.is_file():
            try:
                sidecar = json.loads(side_path.read_text(encoding="utf-8"))
            except ValueError:
                sidecar = None
        key = f"{root.name}-{Path(name).stem}"
        clip = normalize_record(rec, sidecar, key, f"{root.name}/{run_path.stem}", time.time())
        if not clip:
            return False
        clip.video = f"/api/live/media/{key}.mp4"
        if clip.key_seconds > 1.5:
            clip.video += f"#t={max(0.0, clip.key_seconds - 3):.1f}"
        self.paths[key] = mp4
        self.live[clip.id] = clip
        return True

    def _add_upload(self, rec: dict) -> bool:
        clip = normalize_upload(rec, time.time())
        if not clip:
            return False
        self.uploads[clip.id] = clip
        return True

    def add_scoreplay_logs(self, media_id: int, logs: list[dict], relay=None) -> int:
        """Clips the auto-clipper wrote back to ScorePlay, as read from GET /media/{id}/logs. Returns how many are new."""
        new = changed = 0
        with self.lock:
            for log in logs:
                clip = normalize_log(log, media_id, time.time(), relay)
                if not clip:
                    continue
                old = self.live.get(clip.id)
                if old:
                    clip.captured_at = old.captured_at
                    if (old.video, old.player_ids, old.names, old.caption) == (clip.video, clip.player_ids, clip.names, clip.caption):
                        continue  # nothing new; also keeps resolved player IDs
                else:
                    new += 1
                changed += 1
                self.live[clip.id] = clip
                self.scoreplay_seen = time.time()
            if changed:
                self._supersede()
                self.version += 1
        return new

    def _supersede(self) -> None:
        """A full cut replaces the quick cut of the same rules-engine moment (sarang README: not done yet),
        and a clip ScorePlay already has replaces the local file of the same clip."""
        full = {c.group_hint for c in self.live.values() if c.group_hint and c.extra.get("cut") == "full"}
        in_scoreplay = {c.extra.get("clip_key") for c in self.live.values() if c.extra.get("from") == "scoreplay" and c.extra.get("clip_key")}
        for c in self.live.values():
            quick = bool(c.group_hint and c.extra.get("cut") == "quick" and c.group_hint in full)
            dup = c.extra.get("from") != "scoreplay" and c.extra.get("clip_key") in in_scoreplay
            c.superseded = quick or dup

    # -- reading --

    def media_path(self, key: str) -> Path | None:
        self.refresh()
        return self.paths.get(key)

    def _library_clips(self) -> list[Clip]:
        if self._lib_clips is None:
            self._lib_clips = library_clips(self.library)
        return self._lib_clips

    def moments(self) -> list[dict]:
        self.refresh()
        with self.lock:
            stamp = self.version * 100000 + self._lib_version
            if self._moments is not None and self._moments_version == stamp:
                return self._moments
            people = self.people()
            clips = []
            for c in [*self.live.values(), *self.uploads.values()]:
                if c.superseded:
                    continue
                c.player_ids = resolve_players(c, people)
                clips.append(c)
            clips.extend(self._library_clips())
            self._moments = group_moments(clips)
            self._moments_version = stamp
            return self._moments

    def feed(self) -> dict:
        """What the dots need every second or two: clip counts per player and the newest captures."""
        moments = self.moments()
        live = [m for m in moments if m["live"]]
        counts: dict[str, int] = {}
        for m in live:
            for pid in m["player_ids"]:
                counts[str(pid)] = counts.get(str(pid), 0) + 1
        newest = sorted(live, key=lambda m: m["captured_at"] or 0, reverse=True)[:6]
        return {
            "version": self.version,
            "counts": counts,
            "latest": [
                {
                    "id": m["id"],
                    "event_plain": m["event_plain"],
                    "caption": m["caption"],
                    "player_ids": m["player_ids"],
                    "captured_at": m["captured_at"],
                    "angle_count": m["angle_count"],
                }
                for m in newest
            ],
            "live_clips": sum(1 for c in self.live.values() if not c.superseded),
            "from_scoreplay": sum(1 for c in self.live.values() if not c.superseded and c.extra.get("from") == "scoreplay"),
            "watching": [str(r) for r in self.roots],
            "now": time.time(),
        }

    def for_player(self, pid: int) -> dict:
        moments = self.moments()
        person = next((p for p in self.people() if int(p["id"]) == pid), None)
        mine = [m for m in moments if pid in m["player_ids"]]
        live = sorted([m for m in mine if m["live"]], key=lambda m: m["captured_at"] or 0, reverse=True)
        library = [m for m in mine if not m["live"] and _personal(m, pid, person)]
        library.sort(key=lambda m: (-m["importance"], -m["angle_count"]))
        if live:
            note = f"{len(live)} {'play' if len(live) == 1 else 'plays'} captured live"
        elif library:
            note = "Nothing captured live yet. Showing ScorePlay's library."
        else:
            note = "Nothing captured live yet, and no ScorePlay clip is his alone."
        return {
            "player": person,
            "showing": "live" if live else ("scoreplay" if library else "none"),
            "note": note,
            "live": live,
            "library": library[:8],
            "version": self.version,
        }


def _personal(moment: dict, pid: int, person: dict | None) -> bool:
    """Library clips tag whole squads. Keep the ones that are his: named on the file, or a small crowd."""
    short = ((person or {}).get("short") or "").lower()
    for a in moment["angles"]:
        if a.get("named_id") == pid:
            return True
        title = (a.get("title") or "").lower()
        if len(short) > 2 and short in title:
            return True
        if 0 < (a.get("crowd") or 0) <= 2:
            return True
    return False
