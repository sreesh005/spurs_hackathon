"""M0: read-only smoke test of ScorePlay, the live feed and TwelveLabs."""

import re

import httpx

from . import clients
from .config import Settings

SEGMENT_RE = re.compile(r"/(\d+)/(\d+)/([0-9a-f-]{36})/hls/video_(\d+)\.ts")


def _ok(msg: str) -> None:
    print(f"  ok   {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL {msg}")


def scoreplay(s: Settings) -> bool:
    print("ScorePlay")
    sp = clients.scoreplay(s)
    good = True

    r = sp.get("/whoami")
    if r.status_code != 200:
        _fail(f"whoami -> HTTP {r.status_code}")
        return False
    who = r.json()
    _ok(f"whoami: company '{(who.get('company') or {}).get('name')}', user type {who.get('user_type')}")

    # whoami has no company ID, so read it off any media in the company.
    r = sp.search("/media/search", {}, params={"per_page": 1})
    media = r.json().get("media") or []
    real_company = media[0]["company_id"] if media else None
    if real_company == s.scoreplay_company_id:
        _ok(f"company ID {real_company} matches .env ({r.json().get('count')} media in company)")
    else:
        _fail(f"company ID is {real_company}, .env has {s.scoreplay_company_id}")
        good = False

    mid = s.scoreplay_media_id
    r = sp.get(f"/media/{mid}")
    if r.status_code != 200 or not r.json().get("ID"):
        _fail(f"media {mid} -> HTTP {r.status_code} {r.text[:80]}")
        return False
    m = r.json()
    duration = m.get("duration") or round((m.get("tc_out", 0) - m.get("tc_in", 0)) / 1000)
    _ok(f"media {mid}: '{m.get('name')}', status {m.get('status')}, is_live {m.get('is_live')}, "
        f"duration {duration}s, event {m.get('event_id')}")

    logs = sp.get(f"/media/{mid}/logs").json().get("items") or []
    _ok(f"media {mid} has {len(logs)} video logs (first page)")

    if s.scoreplay_event_id:
        path = _find_event(sp, s.scoreplay_event_id)
        if path:
            _ok(f"upload event {s.scoreplay_event_id}: {path}")
        else:
            _fail(f"upload event {s.scoreplay_event_id} not found")
            good = False

    # Is this media the game behind the live feed? Compare the source path in its files.
    files = [f.get("url", "") for f in (m.get("files") or [])]
    source_paths = {f"{a}/{b}/{c}" for u in files for a, b, c in re.findall(r"/(\d+)/(\d+)/([0-9a-f-]{36})/", u)}
    feed = _feed_source(s)
    if feed:
        path, seg = feed
        if path in source_paths:
            _ok(f"live feed replays this media (source {path}), now at segment {seg} ~ offset {seg * 2}s")
        else:
            _fail(f"live feed source {path} not found in media {mid} files")
            good = False
    return good


def _find_event(sp: clients.Api, event_id: int) -> str | None:
    """Walk the event tree from the top. The `event_id` filter on /event/search returns []."""
    queue = [(e, e["name"]) for e in sp.search("/event/search", {}).json()]
    while queue:
        e, path = queue.pop(0)
        if e["ID"] == event_id:
            return path
        if e.get("child_count"):
            children = sp.search("/event/search", {"parent_id": e["ID"]}).json()
            queue += [(c, f"{path} / {c['name']}") for c in children]
    return None


def _feed_source(s: Settings) -> tuple[str, int] | None:
    print("Live feed")
    try:
        text = httpx.get(s.live_feed_url, timeout=20).text
    except httpx.HTTPError as e:
        _fail(f"playlist: {e}")
        return None
    hits = SEGMENT_RE.findall(text)
    if not hits:
        _fail("playlist has no segments")
        return None
    a, b, c, n = hits[-1]
    pdt = re.findall(r"#EXT-X-PROGRAM-DATE-TIME:(\S+)", text)
    _ok(f"{len(hits)} segments, latest video_{n}.ts at {pdt[-1] if pdt else '?'}")
    return f"{a}/{b}/{c}", int(n)


def twelvelabs(s: Settings) -> bool:
    print("TwelveLabs")
    r = clients.twelvelabs(s).get("/indexes")
    if r.status_code != 200:
        _fail(f"indexes -> HTTP {r.status_code}")
        return False
    data = r.json().get("data") or []
    _ok(f"{len(data)} index(es)")
    for i in data:
        models = ", ".join(m.get("model_name", "") for m in i.get("models", []))
        print(f"       {i.get('index_name')}  {i.get('_id')}  [{models}]")
    return True


def run(s: Settings) -> bool:
    results = [scoreplay(s), twelvelabs(s)]
    ok = all(results)
    print("\nSMOKE OK" if ok else "\nSMOKE FAILED")
    return ok
