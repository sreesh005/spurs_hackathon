"""M3: write a TwelveLabs result back to ScorePlay.

- A log (note) at the key moment, for every result that isn't skipped, on the target media: the
  live recording when the loop watches it, or the full match 130851979. On the live recording
  ScorePlay makes a clip from the log right away, so the note is the creator's clip.
- For highlights only: the full-quality clip uploaded into the Highlights event, with caption,
  tags and players, ready to post.
Every write carries `source:twelvelabs` and respects DRY_RUN (printed, not sent).
Body building is pure (`build_log_body`, `build_upload_body`, `upload_name`) so it is unit-tested.
"""

import json
import re
from pathlib import Path

import httpx

from . import clients, config, scoreplay_data


def player_ids(analysis: dict) -> list[int]:
    """Squad IDs for the Tottenham players named, only when the commentary backs the name up."""
    heard = " ".join(analysis.get("commentary_names") or []).lower()
    by_name = {p["name"].lower(): p["id"] for p in scoreplay_data.squad()}
    out = []
    for name in analysis.get("tottenham_players") or []:
        pid = by_name.get(name.lower())
        parts = [p for p in re.split(r"[\s-]+", name.lower()) if len(p) > 3]  # "Solanke-Mitchell" -> solanke, mitchell
        if pid and any(part in heard for part in parts):
            out.append(pid)
    return out


def raw_tags(analysis: dict, cut: str, excitement: float | None, found_by: str) -> list[str]:
    tags = ["source:twelvelabs", f"event:{analysis['event_type']}", f"team:{analysis['team']}",
            f"cut:{cut}", f"confidence:{analysis.get('confidence', 0):.2f}", f"found_by:{found_by}"]
    if excitement is not None:
        tags.append(f"excitement:{excitement:.2f}")
    if analysis.get("is_replay"):
        tags.append("replay")
    return tags


def log_range(run: dict) -> tuple[float, float, float]:
    """(key, start, end) in seconds into the source: key-8 .. key+12, kept inside the clip."""
    clip = run.get("clip") or {}
    base = float(clip.get("source_start_offset") or 0.0)
    key = base + float(run["analysis"].get("key_moment_seconds") or 0)
    end_of_clip = clip.get("source_end_offset")
    end_of_clip = float(end_of_clip) if end_of_clip is not None else key + 12
    key = min(max(key, base), end_of_clip)
    return key, max(base, key - 8), min(end_of_clip, key + 12)


def build_log_body(run: dict, media_id: int, company_id: int, players: list[int], tags: list[str]) -> dict:
    """`POST /video/logs` body. Offset range mode only, and no `external_id`: on a video log that
    means "find the media by this external match ID" (it gave RECORD_NOT_FOUND), so our clip ID
    rides along as a `clip:<id>` tag instead."""
    _, start, end = log_range(run)
    tags = list(tags)
    if "source:twelvelabs" not in tags:
        tags.insert(0, "source:twelvelabs")
    return {"company_id": company_id, "video_logs": [{
        "media_id": media_id,
        "log": {"start_offset": start, "end_offset": end, "comment": run["analysis"]["caption"],
                "raw_tags": tags + [f"clip:{run['clip_id']}"], "player_ids": players}}]}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "x"


def upload_name(run: dict) -> str:
    """File name a creator can scan in Highlights, e.g. `goal_tottenham_t2_goal_tot.mp4`."""
    a = run["analysis"]
    return f"{_slug(a['event_type'])}_{_slug(a['team'])}_{run['clip_id']}.mp4"


def build_upload_body(name: str, caption: str, tags: list[str]) -> dict:
    """`POST /upload/event/{id}` body."""
    tags = list(tags)
    if "source:twelvelabs" not in tags:
        tags.insert(0, "source:twelvelabs")
    return {"name": name, "description": caption, "raw_tags": tags, "player_accessible": True}


def deliver(run: dict, mp4: Path, cut: str = "full", excitement: float | None = None,
            found_by: str = "rules", skip: tuple[str, ...] = ("substitution", "none"),
            media_id: int | None = None) -> dict:
    """Write one analyzed clip back. `media_id` is the media the log goes on (default: the match
    from config). Returns a summary of what was (or would be) written."""
    a = run["analysis"]
    if a["event_type"] in skip:
        return {"skipped": a["event_type"]}
    s = config.load()
    sp = clients.scoreplay(s)
    media_id = media_id if media_id is not None else s.scoreplay_media_id
    players, tags = player_ids(a), raw_tags(a, cut, excitement, found_by)
    key, start, end = log_range(run)

    sp.write("POST", "/video/logs", build_log_body(run, media_id, s.scoreplay_company_id, players, tags))
    summary = {"media_id": media_id, "log_at": key, "log_range": [start, end], "players": players, "tags": tags}

    if a.get("is_highlight"):
        summary["upload"] = upload(sp, s, mp4, upload_name(run), a["caption"], tags, players)
    return summary


def upload(sp: clients.Api, s: config.Settings, mp4: Path, name: str, caption: str,
           tags: list[str], players: list[int]) -> dict:
    """Upload a clip into the Highlights event: create -> PUT bytes -> complete -> tag players.
    `name` is only the name ScorePlay shows; the local file is read as is."""
    body = build_upload_body(name, caption, tags)
    r = sp.write("POST", f"/upload/event/{s.scoreplay_event_id}", body, params={"parts": 1})
    if r is None:  # dry run: the next three calls depend on this response
        size = f"{mp4.stat().st_size / 1e6:.1f} MB" if mp4.exists() else "file missing"
        print(f"[DRY_RUN scoreplay] then PUT {mp4.name} ({size}) to the returned URL, "
              f"POST /upload/complete/<media_id>, POST /media/<media_id>/tags {json.dumps({'player_ids': players})}")
        return {"dry_run": True, "name": name}
    up = r.json()
    put = httpx.put(up["urls"][0]["url"], content=mp4.read_bytes(), timeout=300)  # presigned: no API key
    put.raise_for_status()
    etag = put.headers.get("ETag", "").strip('"')
    sp.write("POST", f"/upload/complete/{up['media_id']}",
             {"key": up["key"], "upload_id": up["upload_id"], "parts_number": 1,
              "parts": [{"parts_number": 1, "etag": etag}]})
    if players:
        sp.write("POST", f"/media/{up['media_id']}/tags", {"player_ids": players})
    return {"media_id": up["media_id"], "name": name}
