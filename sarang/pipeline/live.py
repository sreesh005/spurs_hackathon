"""The live loop: feed -> local signals -> rules engine -> clip -> TwelveLabs -> ScorePlay + knowledge store.

Runs end to end today. With DRY_RUN on (the default), every write to ScorePlay and TwelveLabs is
printed instead of sent. Pegasus analyze calls do run (they spend credits); use --no-analyze for a
free run of the local half only.

Not built yet (marked TODO): retagging a quick clip as superseded once its full clip lands,
raised-arms pose detection, SQLite state (results go to runs/live_<time>.jsonl for now).

Two sources. "scoreplay" (default) watches ScorePlay's own live recording (scoreplay_live.py) and logs
highlights on that media: segment offsets are seconds into the recording. "feed" watches the organizer
feed and logs on our copy of the full match (SCOREPLAY_MEDIA_ID): the feed replays it, so offsets line up.
"""

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import analyze, config, feed, rules, scoreplay_live, signals, sweep, tl_store, writeback

RUNS = config.ROOT / "runs"


def _hms(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M:%SZ")


class Live:
    def __init__(self, analyze_on: bool, mediapipe: bool, max_calls: int | None,
                 source: str = "scoreplay", wait: bool = True):
        self.s, self.cfg = config.load(), rules.load()
        self.source = source
        if source == "scoreplay":
            found = scoreplay_live.wait_for_recording() if wait else scoreplay_live.find_recording()
            if not found:
                raise SystemExit("no ScorePlay recording is live (use --wait, or --source feed)")
            self.target_media_id, url = found
        elif source == "feed":
            self.target_media_id, url = self.s.scoreplay_media_id, self.s.live_feed_url
        else:
            raise ValueError(f"unknown source {source!r}: use scoreplay or feed")
        keep = int(self.cfg["buffer_seconds"] / self.cfg["segment_seconds"])
        self.buf = feed.Buffer(url, keep=keep)
        self.tracker = signals.Tracker(self.cfg["baseline_seconds"], self.cfg["segment_seconds"])
        self.engine = rules.Engine(self.cfg)
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.analyze_on, self.mediapipe, self.max_calls = analyze_on, mediapipe, max_calls
        self.stats: Counter = Counter()
        self.clipped_at: list[float] = []  # peak times of everything the engine clipped
        self.last_caption: str | None = None
        RUNS.mkdir(exist_ok=True)
        self.log = (RUNS / f"live_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl").open("a")

    # ---- main loop ----

    def run(self, minutes: float) -> None:
        net = self.cfg["safety_net"]
        stop, next_sweep = time.time() + minutes * 60, time.time() + net["every_seconds"]
        print(f"live: watching {self.source} {self.buf.feed_url.rsplit('/', 1)[-1]}, "
              f"logs go on media {self.target_media_id}")
        print(f"live: {minutes:.0f} min, analyze={'on' if self.analyze_on else 'off'}, "
              f"mediapipe={'on' if self.mediapipe else 'off'}, DRY_RUN={'on' if self.s.dry_run else 'OFF'}")
        idle_since = time.time()
        try:
            while time.time() < stop:
                new = self.buf.poll()
                if new:
                    idle_since = time.time()
                elif self.finished(time.time() - idle_since):
                    print("recording finished")
                    break
                for seg in new:
                    if seg.discontinuity:
                        self.engine = rules.Engine(self.cfg)  # the replay looped back to kick-off: start fresh
                    sig = self.tracker.update(signals.measure(seg.path, seg.start_unix, seg.duration,
                                                              self.cfg["shot"], self.mediapipe))
                    self.stats["segments"] += 1
                    print(f"  {_hms(sig.t)} {seg.name} at {seg.source_offset:5.0f}s "
                          f"lag {time.time() - seg.end_unix:4.0f}s  loud_z={sig.loud_z:+.1f} "
                          f"cheer={sig.cheer:.2f} shot={sig.shot:7} [{self.engine.state}]")
                    for kind, m in self.engine.step(sig):
                        self.on_event(kind, m)
                if net["enabled"] and time.time() >= next_sweep:
                    next_sweep += net["every_seconds"]
                    self.start_sweep()
                time.sleep(2)
        except KeyboardInterrupt:
            print("stopping")
        print("waiting for analysis still running...")
        self.pool.shutdown(wait=True)
        print(f"done: {dict(self.stats)}")

    def finished(self, idle: float) -> bool:
        """Has the ScorePlay recording ended? Checked only while no new segments arrive."""
        if self.source != "scoreplay":
            return False  # the organizer feed loops forever
        if scoreplay_live.is_finished(self.buf.http.get(self.buf.feed_url).text):
            return True
        return idle > 60 and not scoreplay_live.still_growing(self.target_media_id)

    # ---- moments from the rules engine ----

    def on_event(self, kind: str, m: rules.Moment) -> None:
        if kind == "arm":
            print(f"  ARM    moment {m.id}: {', '.join(m.reasons)}, clip starts {_hms(m.start)}")
            return
        if kind == "quick":
            a, b = self.engine.quick_window(m)
            self.clipped_at.append(m.peak)
        else:
            a, b = m.start, m.end
        print(f"  {kind.upper():6} moment {m.id}: {_hms(a)}-{_hms(b)}, score {m.score:.2f} ({', '.join(m.reasons)})")
        mp4 = self.cut(self.buf.window(a, b), f"m{m.id}_{kind}_{int(m.peak)}")
        if mp4:
            self.pool.submit(self.process, mp4, kind, m.score, "rules")

    def cut(self, segs: list[feed.Segment], clip_id: str) -> Path | None:
        if not segs:
            return None
        if any(s.discontinuity for s in segs[1:]):
            print(f"  skip {clip_id}: spans the replay looping back to kick-off")
            return None
        self.stats["clips"] += 1
        return feed.cut(segs, clip_id)  # cut now, on this thread, before the buffer drops the segments

    def process(self, mp4: Path, cut: str, excitement: float | None, found_by: str) -> None:
        try:
            if not self.analyze_on:
                print(f"  (no-analyze) would send {mp4.name} to TwelveLabs")
                return
            if self.max_calls is not None and self.stats["tl_calls"] >= self.max_calls:
                print(f"  skip {mp4.name}: --max-calls {self.max_calls} reached")
                return
            self.stats["tl_calls"] += 1
            run = analyze.analyze(mp4, context=self.last_caption)
            a = run["analysis"]
            print(f"  TL     {mp4.stem}: {a['event_type']} ({a['team']}) highlight={a['is_highlight']} "
                  f"conf={a['confidence']:.2f}: {a['caption']}")
            if cut == "full":
                self.last_caption = a["caption"]
            result = writeback.deliver(run, mp4, cut, excitement, found_by, tuple(self.cfg["skip_event_types"]),
                                       media_id=self.target_media_id)
            if a["is_highlight"] and "skipped" not in result:
                self.stats["highlights"] += 1
                self.add_to_store(mp4, run, a)
            self.log.write(json.dumps({"clip": mp4.name, "media_id": self.target_media_id, "cut": cut,
                                       "found_by": found_by, "analysis": a, "writeback": result}) + "\n")
            self.log.flush()
        except Exception as e:  # one bad clip shouldn't stop the loop
            self.stats["errors"] += 1
            print(f"  ERROR  {mp4.name}: {e}")

    def add_to_store(self, mp4: Path, run: dict, a: dict) -> None:
        """Copy the clip into our TwelveLabs knowledge store (for Jockey's multi-angle grouping). Optional:
        a key that may not write knowledge stores (HTTP 403) turns it off for the run instead of losing the clip."""
        if getattr(self, "store_off", False):
            return
        try:
            tl_store.add_clip(mp4, {"media_id": self.target_media_id, "event": a["event_type"], "team": a["team"],
                                    "caption": a["caption"], "offset": (run.get("clip") or {}).get("source_start_offset")})
        except Exception as e:
            self.store_off = True
            print(f"  NOTE   knowledge store off for this run ({str(e)[:120]})")

    # ---- safety net ----

    def start_sweep(self) -> None:
        net, now = self.cfg["safety_net"], time.time()
        segs = self.buf.window(now - net["window_seconds"], now)
        mp4 = self.cut(segs, f"sweep_{int(now)}")
        if mp4:
            print(f"  SWEEP  {len(segs) * 2}s window from {_hms(segs[0].start_unix)}")
            self.pool.submit(self.sweep_job, mp4, segs[0].start_unix)

    def sweep_job(self, mp4: Path, start: float) -> None:
        try:
            if not self.analyze_on:
                print(f"  (no-analyze) would scan {mp4.name}")
                return
            self.stats["tl_calls"] += 1
            events = sweep.scan(mp4)
            net = self.cfg["safety_net"]
            worth = [e for e in events if e["event_type"] in net.get("clip_event_types", [e["event_type"]])]
            new = sweep.missed(worth, start, self.clipped_at, net["match_within_seconds"])
            print(f"  SWEEP  {len(events)} events, {len(worth)} worth clipping, {len(new)} missed by the rules")
            for e in new:
                self.stats["sweep_finds"] += 1
                clip = self.cut(self.buf.window(e["at"] - 10, e["at"] + 15), f"sw_{int(e['at'])}_{e['event_type']}")
                if clip:
                    self.process(clip, "full", None, "sweep")
        except Exception as e:
            self.stats["errors"] += 1
            print(f"  ERROR  sweep {mp4.name}: {e}")
