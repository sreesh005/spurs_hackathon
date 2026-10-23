"""Run the rules engine over the recorded match, faster than real time, without calling TwelveLabs.

Signals are measured once per range and cached in runs/signals/, so re-tuning rules.yaml
and replaying takes seconds.
"""

import json
from dataclasses import asdict
from pathlib import Path

from . import config, rules, scoreplay_data, signals

CACHE = config.ROOT / "runs" / "signals"
KNOWN_GOALS = {4671: "Man Utd 1-0", 5824: "Spurs 1-1"}  # match offsets, from the scoreboard


def measured(start: float, end: float, cfg: dict, refresh: bool = False) -> list[signals.Signals]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{int(start)}_{int(end)}.json"
    if path.exists() and not refresh:
        return [signals.Signals(**d) for d in json.loads(path.read_text())]
    s = config.load()
    out = signals.measure_range(scoreplay_data.source_file_url(s.scoreplay_media_id), start, end - start, cfg["shot"])
    path.write_text(json.dumps([asdict(x) for x in out]))
    return out


def run(start: float, end: float, refresh: bool = False, verbose: bool = False) -> list[tuple[str, rules.Moment]]:
    cfg = rules.load()
    sig = measured(start, end, cfg, refresh)
    tracker, engine = signals.Tracker(cfg["baseline_seconds"]), rules.Engine(cfg)
    events, fulls = [], []
    for x in sig:
        tracker.update(x)
        if verbose:
            print(f"    {x.t:6.0f} loud_z={x.loud_z:+.1f} voice_z={x.voice_z:+.1f} drop={x.drop:+.1f} "
                  f"cheer={x.cheer:.2f} shot={x.shot:7} people={x.people:2d} cut={int(x.cut)}  [{engine.state}]")
        for kind, m in engine.step(x):
            events.append((kind, m))
            label = m.summary() if kind != "quick" else f"moment {m.id}: quick clip {engine.quick_window(m)[0]:.0f}-{engine.quick_window(m)[1]:.0f}"
            print(f"{x.t:6.0f}  {kind:5}  {label}")
            if kind == "full":
                fulls.append((m.start, m.end))
    print()
    for goal, name in KNOWN_GOALS.items():
        if start <= goal <= end:
            hit = any(a <= goal <= b for a, b in fulls)
            print(f"{'CAUGHT' if hit else 'MISSED'}  {name} at {goal}")
    print(f"{len(fulls)} clips over {(end - start) / 60:.0f} minutes of match")
    return events
