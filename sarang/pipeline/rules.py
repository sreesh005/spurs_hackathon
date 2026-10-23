"""Clip rules engine: decides when a moment starts, peaks and ends, from local signals.

Feed it one Signals per segment with `step()`; it returns events:
  ("arm", m)    something may be about to happen; m.start is the clip start mark
  ("quick", m)  a moment peaked; cut m.peak - quick_before .. m.peak + quick_after now
  ("full", m)   the reaction is over; cut m.start .. m.end now
TwelveLabs decides what happened. This only decides when. Design: docs/rules-engine.md
"""

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import ROOT
from .signals import Signals


def load(path: Path = ROOT / "rules.yaml") -> dict:
    return yaml.safe_load(path.read_text())


def _norm(x: float, lo: float, hi: float) -> float:
    return min(1.0, max(0.0, (x - lo) / (hi - lo)))


@dataclass
class Moment:
    id: int
    start: float
    peak: float = 0.0
    score: float = 0.0
    end: float | None = None
    reasons: list[str] = field(default_factory=list)
    quick_sent: bool = False

    def summary(self) -> str:
        end = f"{self.end:.0f}" if self.end is not None else "?"
        return f"moment {self.id}: {self.start:.0f}-{end}, peak {self.peak:.0f} score {self.score:.2f} ({', '.join(self.reasons)})"


class Engine:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.hist: deque[Signals] = deque(maxlen=30)
        self.state = "calm"  # calm | watching | triggered | cooldown
        self.moment: Moment | None = None
        self.next_id = 1
        self.armed_at: float | None = None
        self.arm_reason = ""
        self.above = 0  # consecutive segments over the trigger threshold
        self.calm_since: float | None = None
        self.cooldown_until = 0.0
        self.last_wide_cut: float | None = None
        self.last_whistle: float | None = None
        self.still_since: float | None = None
        self.last_silence: float | None = None

    # ---- signals ----

    def _arm_reason(self, s: Signals) -> str | None:
        a = self.cfg["arm"]
        prev = self.hist[-2] if len(self.hist) >= 2 else None
        if prev and s.shot in ("wide", "unknown") and s.loud_z - prev.loud_z >= a["buildup_loud_rise"]:
            return "build-up"
        if s.whistle >= a["setpiece_whistle"]:
            self.last_whistle = s.t
        if s.shot == "wide" and s.people >= a["setpiece_min_people"] and s.still >= a["setpiece_still"]:
            self.still_since = self.still_since if self.still_since is not None else s.t
        else:
            self.still_since = None
        if (self.last_whistle is not None and s.t - self.last_whistle <= 10 and self.still_since is not None
                and s.t + s.duration - self.still_since >= a["setpiece_hold_seconds"]):
            return "set piece"
        if s.voice_z >= a["voice_rise"]:
            return "commentary rise"
        return None

    def _score(self, s: Signals) -> tuple[float, list[str]]:
        t, w = self.cfg["trigger"], self.cfg["trigger"]["weights"]
        if s.drop >= t["silence_drop"]:
            self.last_silence = s.t
        quiet_then_loud = self.last_silence is not None and s.t - self.last_silence <= t["silence_memory_seconds"]
        silence = 1.0 if quiet_then_loud and s.loud_z >= t["sustained_loud_z"] else 0.0
        recent = [h for h in self.hist if s.t - h.t <= t["reaction_window_seconds"]]
        went_close = any(h.shot == "wide" for h in recent) and s.shot == "closeup"
        reaction = 1.0 if went_close and (s.arms_up or s.cheer >= 0.4 or s.loud_z >= 1.0) else 0.0
        window = [h for h in self.hist if s.t - h.t < t["sustained_seconds"]]
        sustained = sum(h.loud_z >= t["sustained_loud_z"] for h in window) / max(1, len(window))
        parts = {
            "loud": w["loud"] * _norm(s.loud_z, *t["loud_range"]),
            "sustained": w["sustained"] * sustained,
            "cheer": w["cheer"] * s.cheer,
            "voice": w["voice"] * _norm(s.voice_z, *t["voice_range"]),
            "silence": w["silence"] * silence,
            "reaction": w["reaction"] * reaction,
            "armed": w["armed"] * (1.0 if self.state == "watching" else 0.0),
        }
        return sum(parts.values()), [k for k, v in parts.items() if v > 0 and k != "armed"]

    # ---- state machine ----

    def step(self, s: Signals) -> list[tuple[str, Moment]]:
        c, out = self.cfg, []
        if s.cut and s.shot == "wide":
            self.last_wide_cut = s.t
        self.hist.append(s)
        score, why = self._score(s)

        if self.state == "cooldown" and s.t >= self.cooldown_until:
            self.state = "calm"

        if self.state in ("calm", "watching"):
            reason = self._arm_reason(s)
            if self.state == "calm" and reason:
                self.state, self.armed_at, self.arm_reason = "watching", s.t, reason
                start = self._start_mark(s.t)
                self.moment = Moment(self.next_id, start=start, reasons=[reason])
                out.append(("arm", self.moment))
            elif self.state == "watching" and s.t - self.armed_at > c["arm"]["expire_seconds"]:
                self.state, self.moment = "calm", None

            self.above = self.above + 1 if score >= c["trigger"]["threshold"] else 0
            if self.above >= c["trigger"]["consecutive_segments"]:
                if self.moment is None:  # triggered without a build-up
                    self.moment = Moment(self.next_id, start=self._start_mark(s.t))
                self.next_id += 1
                self.state = "triggered"
                self.moment.peak, self.moment.score = s.t, score
                self.moment.reasons += [r for r in why if r not in self.moment.reasons]
                self.calm_since = None

        elif self.state == "triggered":
            m, cl = self.moment, c["clip"]
            if score > m.score:
                m.peak, m.score = s.t, score
                m.reasons += [r for r in why if r not in m.reasons]
            now = s.t + s.duration
            if not m.quick_sent and now >= m.peak + cl["quick_after"]:
                m.quick_sent = True
                out.append(("quick", m))
            calm = s.loud_z < c["close"]["calm_loud_z"] and s.shot in ("wide", "unknown")
            self.calm_since = (self.calm_since if self.calm_since is not None else s.t) if calm else None
            long_enough = now - m.start >= cl["full_min"]
            settled = self.calm_since is not None and now - self.calm_since >= c["close"]["calm_seconds"]
            if (settled and long_enough) or now - m.start >= cl["full_max"]:
                m.end = min(now, m.start + cl["full_max"])
                out.append(("full", m))
                self.state, self.cooldown_until, self.moment, self.above = "cooldown", now + cl["cooldown_seconds"], None, 0
        return out

    def _start_mark(self, t: float) -> float:
        back = self.cfg["arm"]["max_lookback_seconds"]
        if self.last_wide_cut is not None and t - self.last_wide_cut <= back:
            return self.last_wide_cut
        return t - min(back, 10)  # no cut seen: 10s of lead-in

    def quick_window(self, m: Moment) -> tuple[float, float]:
        cl = self.cfg["clip"]
        return m.peak - cl["quick_before"], m.peak + cl["quick_after"]
