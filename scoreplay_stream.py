"""SCOREPLAY LIVE VIDEO. Backend for the video on the Live dots tab. Not the screen.

Finds the recording ScorePlay is making of the live feed (Live > Schedule, status LIVE) and relays its
HLS through the desk, so the browser only ever talks to the desk:
  /api/live/stream                  which recording, and the playlist URL to play
  /api/live/stream/playlist.m3u8    ScorePlay's playlist, its segment lines pointed back at the desk
  /api/live/stream/seg/<name>       one segment, fetched from the recording's folder

How the recording is found (the same calls sarang/pipeline/scoreplay_live.py makes):
  POST /media/search {"is_growing_media": true}  -> recordings in progress, newest first
  GET  /media/{id}                                -> video.live_master_url; original.m3u8 sits next to it
Overrides in .env or the environment:
  SCOREPLAY_LIVE_MEDIA_ID   play this media instead of searching
  SCOREPLAY_LIVE_PLAYLIST   play this HLS URL directly (the organizer feed URL works too; the demo uses it)
Segment N of a ScorePlay recording starts N x 2s into it, which is the offset the auto-clipper logs clips
at, so the desk can seek this player to any clip's moment.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from catalog import load_env

FOUND_TTL = 30.0  # seconds to trust a found recording before asking ScorePlay again
MISSING_TTL = 10.0
SAFE_PART = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")
TYPES = {".ts": "video/mp2t", ".m4s": "video/iso.segment", ".mp4": "video/mp4", ".aac": "audio/aac", ".m3u8": "application/vnd.apple.mpegurl"}


def playlist_url(media: dict) -> str | None:
    """original.m3u8 of a `GET /media/{id}` response, or None if the recording isn't LIVE yet."""
    master = (media.get("video") or {}).get("live_master_url") or ""
    if master:
        return master.rsplit("/", 1)[0] + "/original.m3u8"
    for f in media.get("files") or []:
        if (f.get("url") or "").endswith("original.m3u8"):
            return f["url"]
    return None


def rewrite(text: str, playlist: str, base_dir: str) -> str:
    """Point every URI in a playlist at the desk. URIs outside the recording's folder are left alone."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            out.append(_local(urllib.parse.urljoin(playlist, stripped), base_dir) or stripped)
        elif 'URI="' in line:
            out.append(re.sub(r'URI="([^"]+)"', lambda m: f'URI="{_local(urllib.parse.urljoin(playlist, m.group(1)), base_dir) or m.group(1)}"', line))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def _local(absolute: str, base_dir: str) -> str | None:
    clean = absolute.split("#", 1)[0]
    if not clean.startswith(base_dir):
        return None
    rel = clean[len(base_dir):]
    path, _, query = rel.partition("?")
    if not SAFE_PART.match(path) or ".." in path.split("/"):
        return None
    if path.endswith(".m3u8"):
        return "/api/live/stream/playlist.m3u8?v=" + urllib.parse.quote(rel, safe="")
    return "/api/live/stream/seg/" + urllib.parse.quote(path) + ("?q=" + urllib.parse.quote(query, safe="") if query else "")


class LiveStream:
    def __init__(self):
        self.lock = threading.Lock()
        self.found: dict | None = None
        self.checked = 0.0
        self.note = "not checked yet"

    # ---- finding the recording ----

    def _env(self) -> dict:
        env = load_env()
        for key in ("SCOREPLAY_LIVE_MEDIA_ID", "SCOREPLAY_LIVE_PLAYLIST", "SCOREPLAY_LIVE_NAME", "SCOREPLAY_COMPANY_ID"):
            if os.environ.get(key):
                env[key] = os.environ[key].strip()
        return env

    def _api(self, env: dict, path: str, body: dict | None = None):
        headers = {"X-ScorePlay-Api-Key": env["SCOREPLAY_API_KEY"], "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(env["SCOREPLAY_BASE_URL"].rstrip("/") + path, data=data, headers=headers, method="POST" if body is not None else "GET")
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())

    def _find(self) -> tuple[dict | None, str]:
        env = self._env()
        if env.get("SCOREPLAY_LIVE_PLAYLIST"):
            mid = env.get("SCOREPLAY_LIVE_MEDIA_ID")
            return {"media_id": int(mid) if mid and mid.isdigit() else None, "name": env.get("SCOREPLAY_LIVE_NAME") or "Live feed", "upstream": env["SCOREPLAY_LIVE_PLAYLIST"]}, "playing SCOREPLAY_LIVE_PLAYLIST"
        if not env.get("SCOREPLAY_API_KEY"):
            return None, "SCOREPLAY_API_KEY is empty in .env"
        if env.get("SCOREPLAY_LIVE_MEDIA_ID"):
            ids = [int(env["SCOREPLAY_LIVE_MEDIA_ID"])]
        else:
            media = self._api(env, "/media/search", {"is_growing_media": True}).get("media") or []
            company = env.get("SCOREPLAY_COMPANY_ID")
            media = [m for m in media if not company or str(m.get("company_id")) == str(company)]
            if not media:
                return None, "no recording in progress in ScorePlay (Live > Schedule)"
            ids = [m["ID"] for m in sorted(media, key=lambda m: m["ID"], reverse=True)]
        notes = []
        for mid in ids[:5]:
            full = self._api(env, f"/media/{mid}")
            url = playlist_url(full)
            if url:
                return {"media_id": mid, "name": full.get("name") or f"media {mid}", "upstream": url}, f"recording {mid} is live"
            notes.append(f"{mid} is {full.get('status') or 'not ready'}")
        return None, "recording found but not live yet: " + ", ".join(notes)

    def current(self, force: bool = False) -> dict | None:
        with self.lock:
            ttl = FOUND_TTL if self.found else MISSING_TTL
            if force or time.time() - self.checked > ttl:
                try:
                    self.found, self.note = self._find()
                except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
                    self.found, self.note = None, f"could not reach ScorePlay: {exc}"
                self.checked = time.time()
            return self.found

    def status(self) -> dict:
        found = self.current()
        if not found:
            return {"ok": False, "note": self.note}
        return {"ok": True, "media_id": found["media_id"], "name": found["name"], "playlist": "/api/live/stream/playlist.m3u8", "note": self.note}

    # ---- relaying ----

    def _base(self) -> tuple[str, str]:
        found = self.current()
        if not found:
            raise LookupError(self.note)
        upstream = found["upstream"]
        return upstream, upstream.rsplit("/", 1)[0] + "/"

    def playlist(self, variant: str | None = None) -> str:
        upstream, base = self._base()
        url = upstream
        if variant:
            path = variant.partition("?")[0]
            if not SAFE_PART.match(path) or ".." in path.split("/"):
                raise LookupError("bad playlist name")
            url = base + variant
        with urllib.request.urlopen(url, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        return rewrite(text, url, base)

    def segment(self, path: str, query: str = "") -> tuple[bytes, str]:
        if not SAFE_PART.match(path) or ".." in path.split("/"):
            raise LookupError("bad segment name")
        _, base = self._base()
        url = base + path + (f"?{query}" if query else "")
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = resp.read()
        ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
        return data, TYPES.get(ext, "application/octet-stream")


# ---- relaying ScorePlay's clip videos (the playback URL of each log) ----

RELAY_HOSTS = ("scoreplay.io", "amazonaws.com", "cloudfront.net")


def relay_allowed(url: str, extra_hosts: tuple[str, ...] = ()) -> bool:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("https", "http"):
        return False
    return any(host == h or host.endswith("." + h) for h in (*RELAY_HOSTS, *extra_hosts))


def relay_url(url: str) -> str:
    """Where the desk serves a ScorePlay media URL. Playlists and their parts all go through the relay."""
    path = urllib.parse.urlsplit(url).path
    route = "/api/live/relay.m3u8" if path.endswith(".m3u8") else "/api/live/relay"
    return f"{route}?u={urllib.parse.quote(url, safe='')}"


def relay_rewrite(text: str, playlist: str) -> str:
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            target = urllib.parse.urljoin(playlist, stripped)
            out.append(relay_url(target) if relay_allowed(target) else stripped)
        elif 'URI="' in line:
            out.append(re.sub(r'URI="([^"]+)"', lambda m: f'URI="{relay_url(urllib.parse.urljoin(playlist, m.group(1)))}"' if relay_allowed(urllib.parse.urljoin(playlist, m.group(1))) else m.group(0), line))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def relay_fetch(url: str) -> tuple[bytes, str]:
    """Fetch a ScorePlay media URL for the desk. Only ScorePlay and its storage hosts, never anything else."""
    if not relay_allowed(url):
        raise LookupError("not a ScorePlay media URL")
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = resp.read()
        kind = resp.headers.get_content_type()
    path = urllib.parse.urlsplit(url).path
    if path.endswith(".m3u8"):
        return relay_rewrite(data.decode("utf-8", errors="replace"), url).encode(), TYPES[".m3u8"]
    ext = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    return data, TYPES.get(ext, kind or "application/octet-stream")


# ---- polling the clips the auto-clipper wrote back ----


class LogPoller(threading.Thread):
    """Every few seconds, reads the logs on the live recording (and any SCOREPLAY_CLIP_MEDIA_IDS) and hands
    the auto-clipper's ones to the clip index. The desk then needs nothing from the clipper's machine."""

    def __init__(self, stream: LiveStream, index, every: float = 8.0):
        super().__init__(name="scoreplay-logs", daemon=True)
        self.stream, self.index, self.every = stream, index, every
        self.note = "starting"
        self.last_ok = 0.0
        self.counts: dict[int, int] = {}

    def media_ids(self, env: dict) -> list[int]:
        ids = []
        found = self.stream.current()
        if found and found.get("media_id"):
            ids.append(int(found["media_id"]))
        for part in (os.environ.get("SCOREPLAY_CLIP_MEDIA_IDS") or env.get("SCOREPLAY_CLIP_MEDIA_IDS") or "").split(","):
            if part.strip().isdigit() and int(part) not in ids:
                ids.append(int(part))
        return ids

    def logs(self, env: dict, media_id: int) -> list[dict]:
        items: list[dict] = []
        for page in range(1, 21):
            payload = self.stream._api(env, f"/media/{media_id}/logs?page={page}&limit=100")
            batch = payload.get("items") if isinstance(payload, dict) else payload
            batch = batch or []
            items.extend(batch)
            if len(batch) < 100:
                break
        return items

    def poll(self) -> None:
        env = self.stream._env()
        if not env.get("SCOREPLAY_API_KEY"):
            self.note = "SCOREPLAY_API_KEY is empty in .env"
            return
        ids = self.media_ids(env)
        if not ids:
            self.note = "waiting for a live recording in ScorePlay"
            return
        notes = []
        for mid in ids:
            items = self.logs(env, mid)
            self.index.add_scoreplay_logs(mid, items, relay_url)
            ours = sum(1 for log in items if "source:twelvelabs" in str(log.get("raw_tags") or log.get("tags") or ""))
            self.counts[mid] = ours
            notes.append(f"media {mid}: {ours} clips from the auto-clipper")
        self.last_ok = time.time()
        self.note = "; ".join(notes)

    def run(self) -> None:
        while True:
            try:
                self.poll()
            except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
                self.note = f"could not read ScorePlay logs: {exc}"
            time.sleep(self.every)

    def status(self) -> dict:
        return {"note": self.note, "last_ok": self.last_ok or None, "counts": self.counts}
