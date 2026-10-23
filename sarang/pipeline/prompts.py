"""M2 prompt and response schema for TwelveLabs analyze. Bump VERSION when you change either."""

VERSION = "football-v2"

EVENT_TYPES = [
    "goal", "shot_on_target", "shot_off_target", "save", "big_chance", "skill",
    "tackle", "foul", "free_kick", "corner", "penalty", "card", "substitution",
    "celebration", "injury", "build_up", "none",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "is_highlight": {"type": "boolean"},
        "event_type": {"type": "string", "enum": EVENT_TYPES},
        "team": {"type": "string", "enum": ["tottenham", "manchester_united", "both", "none"]},
        "key_moment_seconds": {"type": "number"},
        "commentary_names": {"type": "array", "items": {"type": "string"}},
        "tottenham_players": {"type": "array", "items": {"type": "string"}},
        "tottenham_jersey_numbers": {"type": "array", "items": {"type": "string"}},
        "is_replay": {"type": "boolean"},
        "caption": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": [
        "is_highlight", "event_type", "team", "key_moment_seconds", "commentary_names", "tottenham_players",
        "tottenham_jersey_numbers", "is_replay", "caption", "confidence",
    ],
}


def build(squad_names: list[str]) -> str:
    names = ", ".join(squad_names)
    return f"""You are logging a Premier League broadcast for Tottenham Hotspur's content team.
The match is Manchester United (red shirts, home) vs Tottenham Hotspur (dark navy and purple away shirts, AIA sponsor).
The scoreboard is in the top-left corner: MNU score, TOT score, match clock.

Watch the whole clip and listen to the commentary, then fill in the JSON.

- event_type: the single most important thing that happens. Use "build_up" for ordinary passing play and "none" for crowd, bench or stoppage shots where nothing happens.
- is_highlight: true only for a goal, a shot on target, a save, a big chance, a notable piece of skill, a penalty, a card, or a goal celebration. Routine play, throw-ins and stoppages are false.
- team: which team made the key action. A save by Tottenham's goalkeeper counts as tottenham.
- key_moment_seconds: seconds from the start of this clip when the key action happens (the shot, the save, the foul). Use 0 if nothing happens.
- commentary_names: every player name the commentators say out loud during the clip, in the order spoken, as heard. Empty if they name nobody.
- tottenham_players: at most 3 Tottenham players who make the key action: the scorer and assister, the shooter, the goalkeeper making the save, the player fouled or booked, the players coming on and off. Not everyone who touches the ball or is on screen. Name someone only if the commentator says the name, a graphic shows it, or you can read the shirt number. Do not guess. Spell names as in this squad list: {names}.
- tottenham_jersey_numbers: the readable shirt numbers of the players in tottenham_players only. Empty if none are readable.
- is_replay: true if the key action is shown as a slow-motion or broadcast replay.
- caption: one factual sentence a social media editor could use, naming players only if you are sure.
- confidence: 0 to 1, how sure you are about event_type and the players."""
