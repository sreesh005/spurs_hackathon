"""The scripted match both fakes share: the tracker moves the dots for it, the clipper cuts clips of it.

A cycle of plays repeats every CYCLE seconds. Each play names a Tottenham player by short name and
lists the angles that turn up after it, with how many seconds later each one lands on the desk:
  quick   the auto-clipper's quick cut, right after the peak
  full    the full cut once the reaction is over (replaces the quick cut)
  replay  the broadcast's slow-motion replay, clipped as its own moment a little later
  phone   a social team phone video uploaded to ScorePlay, matched by capture time
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

CYCLE = 110.0
DELAYS = {"quick": 4.0, "full": 10.0, "replay": 17.0, "phone": 24.0}
MATCH_MEDIA_ID = 130851979  # our copy of Man Utd vs Tottenham in ScorePlay
FIRST_OFFSET = 3900.0  # where in the match the demo starts, seconds


@dataclass
class Play:
    at: float  # seconds into the cycle
    who: str  # short name, as the desk shows it
    slot: int  # lineup index to fall back on when the short name is not in this library
    event: str  # football-v2 event type
    caption: str
    angles: list[str] = field(default_factory=lambda: ["full"])
    toward: str = "attack"  # where the ball goes: attack (their goal), defend (our goal)
    names_heard: bool = True


PLAYS = [
    Play(10, "Kudus", 5, "skill", "{name} skips past two on the left and wins a corner.", ["full"]),
    Play(26, "Solanke", 10, "goal", "{name} turns in the equaliser for Tottenham at Old Trafford.", ["quick", "full", "replay", "phone"]),
    Play(52, "Kinsky", 0, "save", "{name} gets down low to keep out a Man United header.", ["full", "replay"], toward="defend"),
    Play(70, "Gallagher", 7, "tackle", "{name} slides in to win it back on the edge of the box.", ["full", "phone"], toward="defend"),
    Play(88, "Savio", 9, "big_chance", "{name} cuts inside and curls one just wide.", ["quick", "full"]),
]


class Clock:
    def __init__(self, speed: float = 1.0):
        self.t0 = time.time()
        self.speed = speed

    def sim(self) -> float:
        return (time.time() - self.t0) * self.speed

    def unix_at(self, sim_t: float) -> float:
        """Wall clock the feed would show for a sim time. Runs at match speed whatever --speed is,
        so clips are stamped as if the match played in real time (capture-time matching stays honest)."""
        return self.t0 + sim_t


def play_time(loop: int, play: Play) -> float:
    """Sim seconds when this play's key moment happens."""
    return loop * CYCLE + play.at


def match_offset(sim_t: float) -> float:
    """Seconds into the match video for a sim time: the demo plays the match forward from FIRST_OFFSET."""
    return FIRST_OFFSET + sim_t


def match_clock(offset: float) -> str:
    """Rough broadcast clock for an offset (the real match kicked off ~70s into the file)."""
    minutes = max(0, int((offset - 70) // 60))
    return f"{minutes}:{int((offset - 70) % 60):02d}"


def lineup_slot(library: dict, play: Play) -> int:
    club = next((c for c in library.get("clubs") or [] if c.get("id") == "thfc"), None)
    if club:
        for index, person in enumerate(club["lineup"]):
            if person.get("short") == play.who:
                return index
    return play.slot


def person_for(library: dict, play: Play) -> dict | None:
    club = next((c for c in library.get("clubs") or [] if c.get("id") == "thfc"), None)
    if not club or not club["lineup"]:
        return None
    slot = lineup_slot(library, play)
    return club["lineup"][slot] if slot < len(club["lineup"]) else None
