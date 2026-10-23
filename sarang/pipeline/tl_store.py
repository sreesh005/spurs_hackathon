"""TwelveLabs knowledge store of our delivered clips, and Jockey questions over it.

- add_clip(): upload a clip as an asset and add it to our store ("spurs-highlights"), so Jockey
  can reason across every clip. Indexing runs in the background on TwelveLabs' side.
- group_angles(): ask Jockey which clips and uploads show the same play (multi-angle stretch goal).

Our own store only: the pre-loaded hackathon assets are left alone.
Writes respect DRY_RUN. The REST shapes follow the Agents API docs and slides but haven't been
called for real yet: check them on the first DRY_RUN=false run.
"""

import json
from pathlib import Path

from . import clients, config

STORE_NAME = "spurs-highlights"

ANGLES_SCHEMA = {
    "type": "object",
    "properties": {
        "plays": {"type": "array", "items": {"type": "object", "properties": {
            "play": {"type": "string"},
            "match_time": {"type": "string"},
            "angles": {"type": "array", "items": {"type": "object", "properties": {
                "item": {"type": "string"},
                "start_sec": {"type": "number"},
                "end_sec": {"type": "number"},
                "view": {"type": "string"},
            }}},
        }}},
    },
}


def store_id() -> str | None:
    s = config.load()
    if s.twelvelabs_store_id:
        return s.twelvelabs_store_id
    tl = clients.twelvelabs(s)
    r = tl.get("/knowledge-stores")
    if r.status_code == 200:
        for st in r.json().get("data", []):
            if st.get("name") == STORE_NAME:
                return st.get("id") or st.get("_id")
    created = tl.write("POST", "/knowledge-stores", {"name": STORE_NAME})
    if created is None:
        return None  # dry run
    sid = created.json().get("id") or created.json().get("_id")
    print(f"created knowledge store {STORE_NAME}: put TWELVELABS_STORE_ID={sid} in .env")
    return sid


def add_clip(mp4: Path, metadata: dict) -> str | None:
    """Upload the clip and add it to the store. Returns the store item ID (None in dry run)."""
    tl = clients.twelvelabs(config.load())
    sid = store_id() or "<store id>"
    with mp4.open("rb") as f:
        r = tl.write("POST", "/assets", data={"method": "direct", "user_metadata": json.dumps(metadata)},
                     files={"file": (mp4.name, f, "video/mp4")})
    asset = (r.json().get("_id") or r.json().get("id")) if r is not None else "<asset id>"
    item = tl.write("POST", f"/knowledge-stores/{sid}/items", {"asset_id": asset})
    return (item.json().get("id") or item.json().get("_id")) if item is not None else None


def group_angles(play: str, match_time: str) -> dict | None:
    """Ask Jockey which videos in the store show the same play. Read-only, but spends credits."""
    s = config.load()
    sid = store_id()
    if not sid:
        print("no knowledge store yet (dry run, or none created): nothing to ask")
        return None
    body = {
        "knowledge_store_id": sid,
        "instructions": "You are a video editor for Tottenham Hotspur's social team. Group footage by play, "
                        "matching the same moment filmed from different cameras or phones.",
        "input": [{"type": "message", "role": "user", "content":
                   f"Find every video in the store that shows this play: {play} (around {match_time}). "
                   "Include broadcast clips and phone footage from other angles, with the seconds where the play is."}],
        "text": {"format": {"type": "json_schema", "name": "angles", "schema": ANGLES_SCHEMA}},
    }
    r = clients.twelvelabs(s).http.post("/responses", json=body, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"responses -> HTTP {r.status_code}: {r.text[:300]}")
    for out in r.json().get("output", []):
        if out.get("type") == "message":
            return json.loads(out["content"][0]["text"])
    return None
