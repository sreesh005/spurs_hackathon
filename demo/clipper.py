"""Fake auto-clipper: writes exactly what sarang/pipeline/live.py writes, on the scripted match's clock.

For every clip: the mp4 and its .json sidecar in <root>/clips/ (same fields as feed.cut), then one line
in <root>/runs/live_<time>.jsonl (same fields as Live.process: clip, media_id, cut, found_by, analysis,
writeback). Phone angles go to <root>/scoreplay_uploads.jsonl as ScorePlay media records, untagged,
the way a social team's upload arrives before anyone tags it.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from catalog import DATA

from . import footage
from .scenario import CYCLE, DELAYS, MATCH_MEDIA_ID, PLAYS, Clock, Play, match_clock, match_offset, person_for, play_time

ROOT = DATA / "demo-clipper"
PHONE_MEDIA = DATA / "demo" / "media" / "live"
HIGHLIGHTS = {"goal", "save", "big_chance", "skill", "shot_on_target"}
WINDOWS = {"quick": (5.0, 5.0), "full": (8.0, 8.0), "replay": (4.0, 8.0), "phone": (5.0, 5.0)}
REPLAY_LAG = 12.0  # the broadcast shows its replay this many seconds after the play


def reset() -> None:
    """Start each demo from an empty desk: only our own demo folders are touched."""
    shutil.rmtree(ROOT, ignore_errors=True)
    shutil.rmtree(PHONE_MEDIA, ignore_errors=True)


class FakeClipper(threading.Thread):
    def __init__(self, clock: Clock, library: dict, verbose: bool = True):
        super().__init__(name="demo-clipper", daemon=True)
        self.clock, self.library, self.verbose = clock, library, verbose
        self.done: set[tuple] = set()
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.write_lock = threading.Lock()
        (ROOT / "runs").mkdir(parents=True, exist_ok=True)
        (ROOT / "clips").mkdir(parents=True, exist_ok=True)
        PHONE_MEDIA.mkdir(parents=True, exist_ok=True)
        self.run_file = ROOT / "runs" / f"live_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            sim = self.clock.sim()
            loop_now = int(sim // CYCLE)
            for loop in (loop_now - 1, loop_now):
                if loop < 0:
                    continue
                for index, play in enumerate(PLAYS):
                    for kind in play.angles:
                        key = (loop, index, kind)
                        if key in self.done or play_time(loop, play) + DELAYS[kind] > sim:
                            continue
                        self.done.add(key)
                        self.pool.submit(self._safe, loop, index, play, kind)
            time.sleep(0.25)

    def _safe(self, loop: int, index: int, play: Play, kind: str) -> None:
        try:
            self.emit(loop, index, play, kind)
        except Exception as exc:  # one bad clip shouldn't stop the demo
            print(f"demo clipper: {kind} for {play.who} failed: {exc}")

    def emit(self, loop: int, index: int, play: Play, kind: str) -> None:
        person = person_for(self.library, play) or {"id": 0, "name": play.who, "short": play.who, "number": ""}
        name = person["short"]
        moment = loop * 10 + index + 1
        peak_sim = play_time(loop, play)
        peak_unix = self.clock.unix_at(peak_sim)
        offset = match_offset(peak_sim)
        before, after = WINDOWS[kind]
        if kind == "replay":
            peak_unix += REPLAY_LAG
            offset += REPLAY_LAG
        start_unix, end_unix = peak_unix - before, peak_unix + after
        event_plain = play.event.replace("_", " ").upper()
        caption = play.caption.format(name=name)

        if kind == "phone":
            out = PHONE_MEDIA / f"phone_{moment}_{int(peak_unix)}.mp4"
            footage.render(out, f"{name.upper()}", "Phone, north stand", "PHONE ANGLE", seconds=before + after, vertical=True, style="phone")
            day = datetime.fromtimestamp(peak_unix, timezone.utc)
            midnight = day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            rec = {
                "ID": 990000 + moment,
                "name": f"IMG_{4100 + moment} 9x16.mov",
                "type": "video",
                "compressed_url": f"/demo-media/live/{out.name}",
                "thumbnail_url": "",
                "duration": before + after,
                "key_seconds": before,
                "tc_in": round((start_unix - midnight) * 1000),
                "tc_out": round((end_unix - midnight) * 1000),
                "date": day.strftime("%Y-%m-%d"),
                "player_ids": [],
                "source_label": "Phone · north stand",
                "uploaded_at": time.time(),
            }
            self._append(ROOT / "scoreplay_uploads.jsonl", rec)
            self._say(f"phone upload  {name:10} {event_plain} (untagged, matched by capture time)")
            return

        engine_moment = moment + 1000 if kind == "replay" else moment  # the rules engine sees the replay as its own moment
        cut = "quick" if kind == "quick" else "full"
        clip_id = f"m{engine_moment}_{cut}_{int(peak_unix)}"
        mp4 = ROOT / "clips" / f"{clip_id}.mp4"
        title = f"{name.upper()}  {event_plain}"
        if kind == "replay":
            footage.render(mp4, title, "Broadcast replay, slow motion", "REPLAY", seconds=before + after, style="replay")
        else:
            footage.render(mp4, title, f"Main camera  {match_clock(offset)}", "QUICK CUT" if kind == "quick" else "LIVE CAPTURE",
                           seconds=before + after, style="quick" if kind == "quick" else "broadcast")
        sidecar = {
            "id": clip_id,
            "file": f"clips/{mp4.name}",
            "start_pdt": datetime.fromtimestamp(start_unix, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "end_pdt": datetime.fromtimestamp(end_unix, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "start_unix": start_unix,
            "end_unix": end_unix,
            "duration": before + after,
            "source_start_offset": offset - before,
            "source_end_offset": offset + after,
            "discontinuity": False,
        }
        mp4.with_suffix(".json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        highlight = play.event in HIGHLIGHTS
        analysis = {
            "is_highlight": highlight,
            "event_type": play.event,
            "team": "tottenham",
            "key_moment_seconds": before,
            "commentary_names": [name] if play.names_heard else [],
            "tottenham_players": [person["name"]],
            "tottenham_jersey_numbers": [str(person.get("number") or "")] if person.get("number") else [],
            "is_replay": kind == "replay",
            "caption": caption if kind != "replay" else f"Replay: {caption}",
            "confidence": 0.88 if kind != "quick" else 0.74,
        }
        tags = ["source:twelvelabs", f"event:{play.event}", "team:tottenham", f"cut:{cut}",
                f"confidence:{analysis['confidence']:.2f}", "found_by:rules"] + (["replay"] if kind == "replay" else [])
        writeback = {
            "media_id": MATCH_MEDIA_ID,
            "log_at": offset,
            "log_range": [offset - 8, offset + 12],
            "players": [int(person["id"])] if person.get("id") else [],
            "tags": tags,
        }
        if highlight:
            writeback["upload"] = {"dry_run": True, "name": f"{play.event}_tottenham_{clip_id}.mp4"}
        line = {"clip": mp4.name, "media_id": MATCH_MEDIA_ID, "cut": cut, "found_by": "rules", "analysis": analysis, "writeback": writeback}
        self._append(self.run_file, line)  # the line goes last, so the desk never sees a clip before its file
        self._say(f"{kind:13} {name:10} {event_plain}  -> {mp4.name}")

    def _append(self, path: Path, rec: dict) -> None:
        with self.write_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")

    def _say(self, text: str) -> None:
        if self.verbose:
            print(f"  [clipper {datetime.now():%H:%M:%S}] {text}")
