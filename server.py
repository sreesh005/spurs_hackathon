"""BACKEND. Not the screen.

Serves the Next Post desk and the /api routes.
The front end is static/index.html, static/app.js, and static/styles.css.
This file loads data/library.json, merges TwelveLabs reads, and stores approvals.
"""

from __future__ import annotations

import json
from pathlib import Path

import urllib.error
import urllib.request

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from catalog import DATA, LIBRARY_PATH, build_library, load_env, load_library

ROOT = Path(__file__).resolve().parent
READS_PATH = DATA / "reads.json"
DECISIONS_PATH = DATA / "decisions.json"
LIBRARY: dict = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global LIBRARY
    DATA.mkdir(exist_ok=True)
    LIBRARY = load_library() if LIBRARY_PATH.exists() else build_library()
    yield


app = FastAPI(title="Next Post", lifespan=lifespan)


class Decision(BaseModel):
    play_id: str
    audience: str
    status: str


class ReadRequest(BaseModel):
    media_id: int


def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    DATA.mkdir(exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _apply_read(play: dict, read: dict) -> None:
    watch = float(read.get("watchability") or 0)
    if read.get("camera_on_action") is False:
        watch *= 0.45
    play["picture"] = round(max(0.05, min(0.99, watch)), 3)
    play["tl"] = {
        "description": read.get("description") or "",
        "words_heard": read.get("words_heard") or "",
        "sponsor_mark_visible": bool(read.get("sponsor_mark_visible")),
        "camera_on_action": bool(read.get("camera_on_action")),
    }
    if play["tl"]["words_heard"]:
        play["quote"] = play["tl"]["words_heard"]
        play["quote_source"] = "Heard in the clip"
    else:
        play["quote_source"] = "Desk line"
    story = play["story"]
    room = play["room"]
    fit = {
        "matchday": play["importance"],
        "hardcore": 0.25 + 0.75 * story,
        "player": 0.25 + 0.75 * room,
    }
    room_for = {"matchday": max(0.15, 1 - room), "hardcore": 0.55, "player": room}
    # Matchday room stays anchored to how common the finish is: picture carries the TwelveLabs update.
    room_for["matchday"] = 0.7
    for audience in fit:
        play["scores"][audience] = round(
            play["picture"] * (0.45 + 0.55 * story) * (0.4 + 0.6 * room_for[audience]) * fit[audience],
            3,
        )


def _with_reads(library: dict) -> dict:
    reads = _read_json(READS_PATH, {})
    plays = []
    for play in library["plays"]:
        copy = json.loads(json.dumps(play))
        copy["quote_source"] = "Desk line"
        copy["tl"] = None
        for angle in copy["angles"]:
            read = reads.get(str(angle["id"]))
            if read and "error" not in read:
                _apply_read(copy, read)
                break
        plays.append(copy)
    merged = dict(library)
    merged["plays"] = plays
    merged["decisions"] = _read_json(DECISIONS_PATH, {})
    return merged


def _find_play(play_id: str) -> dict:
    for play in LIBRARY.get("plays") or []:
        if play["id"] == play_id:
            return play
    raise HTTPException(status_code=404, detail="Play not found")


def _angle(play: dict, media_id: int | None = None) -> dict:
    if media_id is not None:
        for angle in play["angles"]:
            if angle["id"] == media_id:
                return angle
    return play["angles"][0]


def _analyze(video_url: str, duration: float) -> dict:
    env = load_env()
    key = env.get("TWELVELABS_API_KEY") or ""
    if not key:
        raise HTTPException(status_code=400, detail="TWELVELABS_API_KEY is empty in .env")
    end = max(2.0, min(float(duration or 12), 12.0))
    body = {
        "model_name": "pegasus1.5",
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 400,
        "start_time": 0,
        "end_time": end,
        "video": {"type": "url", "url": video_url},
        "prompt": (
            "This is a sports highlight. watchability is 0 to 1 for a social post. "
            "camera_on_action is true only when the athletic play is in frame. "
            "description is one sentence of what happens. "
            "words_heard is commentary you can actually hear, or an empty string. "
            "sponsor_mark_visible is true only if a jersey patch or chest logo is readable."
        ),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "type": "object",
                "properties": {
                    "watchability": {"type": "number"},
                    "camera_on_action": {"type": "boolean"},
                    "description": {"type": "string"},
                    "words_heard": {"type": "string"},
                    "sponsor_mark_visible": {"type": "boolean"},
                },
                "required": [
                    "watchability",
                    "camera_on_action",
                    "description",
                    "words_heard",
                    "sponsor_mark_visible",
                ],
            },
        },
    }
    req = urllib.request.Request(
        env["TWELVELABS_BASE_URL"].rstrip("/") + "/analyze",
        data=json.dumps(body).encode(),
        headers={"x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise HTTPException(status_code=502, detail=detail) from exc
    data = payload.get("data", payload)
    if isinstance(data, str):
        data = json.loads(data)
    return data


def _write_scoreplay(media_id: int, caption: str) -> str:
    env = load_env()
    key = env.get("SCOREPLAY_API_KEY") or ""
    if not key:
        return "saved on the desk"
    url = env["SCOREPLAY_BASE_URL"].rstrip("/") + f"/media/{media_id}"
    req = urllib.request.Request(
        url,
        data=json.dumps({"description": caption}).encode(),
        headers={"X-ScorePlay-Api-Key": key, "Content-Type": "application/json", "Accept": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if 200 <= resp.status < 300:
                return "written back to ScorePlay"
    except urllib.error.HTTPError as exc:
        return f"saved on the desk (ScorePlay {exc.code})"
    except urllib.error.URLError:
        return "saved on the desk"
    return "saved on the desk"


@app.get("/api/library")
def library() -> dict:
    return _with_reads(LIBRARY)


@app.post("/api/rebuild")
def rebuild() -> dict:
    global LIBRARY
    LIBRARY = build_library()
    return {"plays": len(LIBRARY["plays"]), "photos": len(LIBRARY["photos"])}


@app.post("/api/decide")
def decide(body: Decision) -> dict:
    if body.status not in {"approved", "rejected", "pending"}:
        raise HTTPException(status_code=400, detail="status must be approved, rejected, or pending")
    play = _find_play(body.play_id)
    audience = body.audience if body.audience in {"matchday", "hardcore", "player"} else "matchday"
    decisions = _read_json(DECISIONS_PATH, {})
    note = "saved on the desk"
    if body.status == "approved":
        merged = _with_reads({"plays": [play]})["plays"][0]
        note = _write_scoreplay(_angle(play)["id"], merged["captions"][audience])
    decisions[body.play_id] = {"status": body.status, "audience": audience, "note": note}
    _write_json(DECISIONS_PATH, decisions)
    return decisions[body.play_id]


@app.post("/api/read")
def read_clip(body: ReadRequest) -> dict:
    play = next((p for p in LIBRARY["plays"] if any(a["id"] == body.media_id for a in p["angles"])), None)
    if not play:
        raise HTTPException(status_code=404, detail="Clip not found")
    angle = _angle(play, body.media_id)
    if not angle.get("video"):
        raise HTTPException(status_code=400, detail="No proxy video on this clip")
    result = _analyze(angle["video"], float(angle.get("duration") or 12))
    reads = _read_json(READS_PATH, {})
    reads[str(body.media_id)] = result
    _write_json(READS_PATH, reads)
    return result


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


# the recorded demo clip and its transcript, for the Demo clip tab
app.mount("/clips", StaticFiles(directory=ROOT / "live" / "clips"), name="clips")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
