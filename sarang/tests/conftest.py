import pytest

from pipeline import rules
from pipeline.signals import Signals

SEG = 2.0


@pytest.fixture
def cfg() -> dict:
    """The real thresholds from rules.yaml."""
    return rules.load()


def sig(t: float, loud_z: float = 0.0, voice_z: float = 0.0, drop: float = 0.0, cheer: float = 0.0,
        shot: str = "wide", cut: bool = False) -> Signals:
    """A hand-built 2s Signals with the z-scores set directly (no Tracker)."""
    return Signals(t=t, duration=SEG, loudness=-23.0, voice=-26.0, loud_z=loud_z, voice_z=voice_z,
                   drop=drop, cheer=cheer, shot=shot, cut=cut)


def run(engine: rules.Engine, signals: list[Signals]) -> list[tuple[float, str, rules.Moment]]:
    """Step through `signals`, returning (t, kind, moment) for every event."""
    out = []
    for s in signals:
        out += [(s.t, kind, m) for kind, m in engine.step(s)]
    return out


def calm(start: float, end: float, loud_z: float = 0.0) -> list[Signals]:
    """Flat wide play from `start` up to (not including) `end`."""
    return [sig(t, loud_z=loud_z) for t in _range(start, end)]


def _range(start: float, end: float):
    t = start
    while t < end:
        yield t
        t += SEG
