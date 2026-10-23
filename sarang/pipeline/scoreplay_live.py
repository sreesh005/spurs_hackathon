"""Find ScorePlay's own live recording and the HLS playlist to watch.

ScorePlay records the broadcast as a "growing" media from the moment the schedule starts. Before the
schedule reaches LIVE the media exists but has no `video` (status WAITING): not ready yet. Once LIVE,
`video.live_master_url` points into a public S3 folder that also holds `original.m3u8`, the feed's own
720p. Segment `original_N.ts` starts N x 2s into the recording, which is the offset a log on that media
needs. When the recording ends the playlist gets #EXT-X-ENDLIST and the media stops growing.
"""

import time
from datetime import datetime, timezone

from . import clients, config


def playlist_url(media: dict) -> str | None:
    """The original.m3u8 URL of a `GET /media/{id}` response, or None if the recording isn't ready."""
    master = (media.get("video") or {}).get("live_master_url") or ""
    if master:
        return master.rsplit("/", 1)[0] + "/original.m3u8"
    for f in media.get("files") or []:
        if (f.get("url") or "").endswith("original.m3u8"):
            return f["url"]
    return None


def is_finished(playlist_text: str) -> bool:
    return "#EXT-X-ENDLIST" in playlist_text


def _scan() -> tuple[tuple[int, str] | None, str]:
    """(recording, note): the newest growing media in our company that has a playlist, and a status line."""
    s = config.load()
    sp = clients.scoreplay(s)
    r = sp.search("/media/search", {"is_growing_media": True})
    r.raise_for_status()
    media = [m for m in r.json().get("media") or []
             if s.scoreplay_company_id is None or m.get("company_id") == s.scoreplay_company_id]
    if not media:
        return None, "no recording in progress"
    notes = []
    for m in sorted(media, key=lambda m: m["ID"], reverse=True):
        full = sp.get(f"/media/{m['ID']}").json()
        url = playlist_url(full)
        if url:
            return (m["ID"], url), f"recording {m['ID']} is live"
        notes.append(f"{m['ID']} not ready (status {full.get('status') or '?'})")
    return None, "recording " + ", ".join(notes)


def find_recording() -> tuple[int, str] | None:
    """(media_id, original.m3u8 URL) of the newest live recording in our company, or None."""
    return _scan()[0]


def still_growing(media_id: int) -> bool:
    r = clients.scoreplay(config.load()).get(f"/media/{media_id}")
    r.raise_for_status()
    return bool(r.json().get("is_growing_media"))


def wait_for_recording(poll_seconds: float = 60, timeout: float | None = None) -> tuple[int, str] | None:
    """Poll ScorePlay until a recording is live. Returns None if `timeout` seconds pass first."""
    give_up = time.time() + timeout if timeout is not None else float("inf")
    while True:
        found, note = _scan()
        print(f"  {datetime.now(timezone.utc):%H:%M:%SZ} {note}")
        if found or time.time() + poll_seconds > give_up:
            return found
        time.sleep(poll_seconds)
