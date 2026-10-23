"""LIBRARY BUILDER. Not the UI.

Pulls players and media from ScorePlay and writes data/library.json.
server.py reads that file and serves it. The front end is the static/ folder.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
ENV_PATH = ROOT / ".env"
LIBRARY_PATH = DATA / "library.json"

NAME_RE = re.compile(r"S(\d+)\s+(.+)-(\d+)([A-Z])-\.", re.IGNORECASE)

ACTION_PLAIN = {
    "DUNK!": "dunk",
    "STL JAM!": "steal and jam",
    "WINDMILL": "windmill",
    "BLOCK": "block",
    "BLK": "block",
    "3PT": "three",
    "LAY": "layup",
    "GLASS": "glass finish",
    "DRIVE": "drive",
    "PULL J": "pull-up",
    "TAKE": "take",
    "J": "jumper",
    "AND 1": "and-one",
    "PLAY": "play",
    "CONTEXT": "off the ball",
    "GOAL": "goal",
    "HIGHLIGHTS": "highlights",
    "CHANCE": "chance",
    "TACKLE": "tackle",
    "CELE": "celebration",
    "SUB": "substitutions",
    "FULL": "full match",
}

IMPORTANCE = {
    "DUNK!": 0.96,
    "STL JAM!": 0.94,
    "WINDMILL": 0.9,
    "BLOCK": 0.84,
    "BLK": 0.84,
    "3PT": 0.8,
    "LAY": 0.64,
    "GLASS": 0.66,
    "DRIVE": 0.62,
    "PULL J": 0.58,
    "TAKE": 0.55,
    "J": 0.57,
    "AND 1": 0.88,
    "PLAY": 0.52,
    "CONTEXT": 0.34,
    "GOAL": 0.97,
    "HIGHLIGHTS": 0.92,
    "CHANCE": 0.74,
    "TACKLE": 0.76,
    "CELE": 0.62,
    "SUB": 0.42,
    "FULL": 0.2,
}

# Longer needles win. number/pos/spot filled for the lineup only.
ROSTER = [
    ("victor wembanyama", "sas", "1", "C"),
    ("de'aaron fox", "sas", "4", "G"),
    ("stephon castle", "sas", "5", "G"),
    ("dylan harper", "sas", "2", "G"),
    ("devin vassell", "sas", "24", "F"),
    ("keldon johnson", "sas", "3", "F"),
    ("julian champagnie", "sas", "30", "F"),
    ("luke kornet", "sas", "7", "C"),
    ("carter bryant", "sas", "25", "F"),
    ("harrison barnes", "sas", "40", "F"),
    ("ja'kobi gillespie", "sas", "", "G"),
    ("maliq brown", "sas", "", "F"),
    ("tobias harris", "sas", "", "F"),
    ("kendall brown", "sas", "", "F"),
    ("guglielmo vicario", "thfc", "1", "GK"),
    ("pedro antonio porro", "thfc", "23", "RB"),
    ("micky van de ven", "thfc", "37", "CB"),
    ("kevin danso", "thfc", "4", "CB"),
    ("iyenoma destiny udogie", "thfc", "13", "RB"),
    ("radu dragusin", "thfc", "3", "CB"),
    ("joão palhinha", "thfc", "6", "CM"),
    ("joao palhinha", "thfc", "6", "CM"),
    ("james daniel maddison", "thfc", "10", "AM"),
    ("dejan kulusevski", "thfc", "21", "AM"),
    ("brennan johnson", "thfc", "22", "RW"),
    ("dominic ayodele solanke", "thfc", "19", "ST"),
    ("mohammed kudus", "thfc", "20", "LW"),
    ("pape matar sarr", "thfc", "29", "CM"),
    ("rodrigo bentancur", "thfc", "30", "CM"),
    ("mathys henri tel", "thfc", "11", "FW"),
    ("lucas erik holger bergvall", "thfc", "15", "CM"),
    ("djed spence", "thfc", "24", "RB"),
    ("antonín kinsk", "thfc", "31", "GK"),
    ("marcos nicolás senesi", "thfc", "5", "CB"),
    ("sandro tonali", "thfc", "16", "CM"),
    ("archie james francis gray", "thfc", "14", "LB"),
    ("conor john gallagher", "thfc", "8", "CM"),
    ("sávio moreira", "thfc", "17", "RW"),
    ("jan paul van hecke", "thfc", "6", "CB"),
    ("martin dúbravka", "thfc", "39", "GK"),
    ("abdul-nasir oluwatosin oluwadoyinsolami adarabioyo", "thfc", "4", "CB"),
    ("mateus gonçalo espanha fernandes", "thfc", "18", "CM"),
    ("omar khaled mohamed abdelsalam marmoush", "thfc", "22", "FW"),
    ("richarlison", "thfc", "9", "ST"),
    ("wilson serge eric odobert", "thfc", "28", "FW"),
    ("yves bissouma", "thfc", "8", "CM"),
    ("manor solomon", "thfc", "27", "FW"),
    ("benjamin thomas davies", "thfc", "33", "CB"),
]

SAS_LINEUP = ["victor wembanyama", "de'aaron fox", "stephon castle", "dylan harper", "devin vassell"]
SAS_BENCH = ["keldon johnson", "julian champagnie", "luke kornet", "carter bryant", "harrison barnes"]
SAS_SPOTS = [(50, 18), (24, 40), (76, 40), (36, 68), (64, 70)]

# Shirts and spots follow the broadcast lineup graphic: Kinsky at the back,
# Solanke nearest the camera, left to right as drawn.
THFC_LINEUP = [
    "antonín kinsk",
    "archie james francis gray",
    "jan paul van hecke",
    "marcos nicolás senesi",
    "iyenoma destiny udogie",
    "mohammed kudus",
    "lucas erik holger bergvall",
    "conor john gallagher",
    "sandro tonali",
    "sávio moreira",
    "dominic ayodele solanke",
]
THFC_BENCH = [
    "martin dúbravka",
    "benjamin thomas davies",
    "micky van de ven",
    "abdul-nasir oluwatosin oluwadoyinsolami adarabioyo",
    "james daniel maddison",
    "mateus gonçalo espanha fernandes",
    "rodrigo bentancur",
    "mathys henri tel",
    "omar khaled mohamed abdelsalam marmoush",
]
THFC_SPOTS = [
    (50, 14),
    (16, 32),
    (38, 30),
    (62, 30),
    (84, 32),
    (14, 64),
    (36, 50),
    (50, 66),
    (68, 58),
    (86, 66),
    (50, 86),
]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    for key in ("SCOREPLAY_API_KEY", "TWELVELABS_API_KEY", "SCOREPLAY_BASE_URL", "TWELVELABS_BASE_URL"):
        if os.environ.get(key):
            env[key] = os.environ[key].strip()
    env.setdefault("SCOREPLAY_BASE_URL", "https://media.scoreplay.io/v1")
    env.setdefault("TWELVELABS_BASE_URL", "https://api.twelvelabs.io/v1.3")
    return env


def _request(url: str, key: str, body: dict | None = None) -> dict | list:
    data = None
    headers = {"X-ScorePlay-Api-Key": key, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def fetch_scoreplay(env: dict[str, str]) -> tuple[list, list]:
    base = env["SCOREPLAY_BASE_URL"].rstrip("/")
    key = env["SCOREPLAY_API_KEY"]
    players = _request(f"{base}/players", key)
    media: list = []
    seen: set = set()
    # Page lives on the query string. The JSON body ignores it and repeats page 1.
    for page in range(1, 30):
        payload = _request(f"{base}/media/search?page={page}&per_page=100", key, {})
        batch = payload.get("media") or []
        fresh = [item for item in batch if item.get("ID") not in seen]
        if not fresh:
            break
        seen.update(item.get("ID") for item in fresh)
        media.extend(fresh)
    return players, media


def match_roster(full_name: str) -> dict | None:
    name = (full_name or "").lower()
    best = None
    best_len = 0
    for needle, club, number, pos in ROSTER:
        if needle in name and len(needle) > best_len:
            best = {"club": club, "number": number, "pos": pos, "needle": needle}
            best_len = len(needle)
    return best


def shop_url(club: str, full_name: str) -> str:
    if club == "thfc":
        query = urllib.parse.quote(f"{full_name} shirt")
        return f"https://shop.tottenhamhotspur.com/search?q={query}"
    query = urllib.parse.quote(f"{full_name} jersey")
    return f"https://store.nba.com/search?query={query}"


SHORT = {
    "victor wembanyama": "Wembanyama",
    "de'aaron fox": "Fox",
    "stephon castle": "Castle",
    "dylan harper": "Harper",
    "devin vassell": "Vassell",
    "keldon johnson": "Johnson",
    "julian champagnie": "Champagnie",
    "luke kornet": "Kornet",
    "carter bryant": "Bryant",
    "harrison barnes": "Barnes",
    "ja'kobi gillespie": "Gillespie",
    "maliq brown": "Brown",
    "guglielmo vicario": "Vicario",
    "pedro antonio porro": "Porro",
    "micky van de ven": "Van de Ven",
    "kevin danso": "Danso",
    "iyenoma destiny udogie": "Udogie",
    "radu dragusin": "Dragusin",
    "joão palhinha": "Palhinha",
    "joao palhinha": "Palhinha",
    "james daniel maddison": "Maddison",
    "dejan kulusevski": "Kulusevski",
    "brennan johnson": "Johnson",
    "dominic ayodele solanke": "Solanke",
    "mohammed kudus": "Kudus",
    "pape matar sarr": "Sarr",
    "rodrigo bentancur": "Bentancur",
    "mathys henri tel": "Tel",
    "lucas erik holger bergvall": "Bergvall",
    "djed spence": "Spence",
    "antonín kinsk": "Kinsky",
    "marcos nicolás senesi": "Senesi",
    "sandro tonali": "Tonali",
    "archie james francis gray": "Gray",
    "conor john gallagher": "Gallagher",
    "sávio moreira": "Savio",
    "richarlison": "Richarlison",
    "wilson serge eric odobert": "Odobert",
    "yves bissouma": "Bissouma",
    "benjamin thomas davies": "Davies",
    "jan paul van hecke": "Van Hecke",
    "martin dúbravka": "Dubravka",
    "abdul-nasir oluwatosin oluwadoyinsolami adarabioyo": "Adarabioyo",
    "mateus gonçalo espanha fernandes": "Fernandes",
    "omar khaled mohamed abdelsalam marmoush": "Marmoush",
}


def short_name(full_name: str, needle: str = "") -> str:
    if needle and needle in SHORT:
        return SHORT[needle]
    parts = [p for p in (full_name or "").split() if p]
    if not parts:
        return "Player"
    token = parts[-1]
    return token[:1].upper() + token[1:] if token[:1].islower() else token


ASPECT_RE = re.compile(r"(9x16|16x9|4x5|1x1|noaudio|clip)", re.IGNORECASE)
HINTS = [
    (r"wembanyama|\bvic\b", "victor wembanyama"),
    (r"\bsteph\b|castle", "stephon castle"),
    (r"harper|\bdylan\b", "dylan harper"),
    (r"\bfox\b", "de'aaron fox"),
    (r"\bkj\b|keldon", "keldon johnson"),
    (r"\bluke\b|kornet", "luke kornet"),
    (r"champagnie|juthree|\bju\b", "julian champagnie"),
    (r"ja'?kobi|gillespie", "ja'kobi gillespie"),
    (r"\bdev\b|vassell", "devin vassell"),
    (r"kudus", "mohammed kudus"),
    (r"\btel\b|mathys", "mathys henri tel"),
    (r"solanke|\bdom\b", "dominic ayodele solanke"),
    (r"savio|sávio", "sávio moreira"),
    (r"gallagher", "conor john gallagher"),
    (r"archie", "archie james francis gray"),
    (r"kinsk", "antonín kinsk"),
    (r"senesi", "marcos nicolás senesi"),
    (r"tonali", "sandro tonali"),
    (r"solanke", "dominic ayodele solanke"),
    (r"maddison", "james daniel maddison"),
    (r"van hecke", "jan paul van hecke"),
    (r"adarabioyo", "abdul-nasir oluwatosin oluwadoyinsolami adarabioyo"),
    (r"dubravka|dúbravka", "martin dúbravka"),
    (r"fernandes", "mateus gonçalo espanha fernandes"),
    (r"marmoush", "omar khaled mohamed abdelsalam marmoush"),
    (r"bergvall", "lucas erik holger bergvall"),
    (r"barnes", "harrison barnes"),
    (r"tarris", "tarris jr."),
]


def is_thfc(name: str) -> bool:
    low = (name or "").lower()
    markers = (
        "man utd",
        "man united",
        "manchester",
        "mnu",
        "tottenham",
        "de zerbi",
        "pre match",
        "previously against",
        "full match",
        "solanke",
        "kudus",
        "savio",
        "gallagher",
        "archie",
        "kinsk",
        "senesi",
        "tonali",
        "bergvall",
        "van hecke",
        "adarabioyo",
        "dubravka",
        "dúbravka",
        "fernandes",
        "marmoush",
        "vicario",
        "key highlights",
        "def actions",
    )
    if any(word in low for word in markers):
        return True
    return bool(re.search(r"(^|[^a-z])tot([^a-z]|$)", low))


def infer_action(stem: str) -> str:
    text = stem.lower()
    if any(word in text for word in ("postgame", "pre match", "prematch", "line up", "lineup", "podcast", "previously", "press conference", "team news", "fpl")):
        return "CONTEXT"
    if "full match" in text:
        return "FULL"
    if "highlight" in text:
        return "HIGHLIGHTS"
    if "goal" in text or "equaliser" in text or "equalizer" in text:
        return "GOAL"
    if "chance" in text or "over the bar" in text:
        return "CHANCE"
    if "tackle" in text or "def action" in text:
        return "TACKLE"
    if any(word in text for word in ("cele", "limbs", "fans clap")):
        return "CELE"
    if "sub" in text:
        return "SUB"
    if "windmill" in text:
        return "WINDMILL"
    if any(word in text for word in ("dunk", "jam", "oop")):
        return "DUNK!"
    if "block" in text or "blk" in text:
        return "BLOCK"
    if re.search(r"\bthree\b|\b3pt\b", text):
        return "3PT"
    if re.search(r"\blay\b|\blayup\b", text):
        return "LAY"
    if "drive" in text or "dribble" in text:
        return "DRIVE"
    if "and 1" in text or "and1" in text:
        return "AND 1"
    return "PLAY"


def describe_video(name: str) -> dict:
    found = NAME_RE.search(name)
    produced = bool(ASPECT_RE.search(name))
    if found and not produced:
        quarter, action, number, angle = found.groups()
        action = action.strip().upper()
        return {
            "key": f"raw-S{quarter}-{int(number)}-{re.sub(r'[^A-Z0-9]+', '', action)}",
            "action": action if action in IMPORTANCE else infer_action(action),
            "quarter": quarter,
            "number": int(number),
            "kind": "angle",
            "mode": "action",
            "label": angle.upper(),
            "assist": "assist" in name.lower(),
            "club": "thfc" if is_thfc(name) else "sas",
        }
    stem = re.sub(r"\.[^.]+$", "", name)
    aspect = "cut"
    match = ASPECT_RE.search(stem)
    if match:
        aspect = match.group(1).lower()
        stem = ASPECT_RE.sub(" ", stem)
    stem = re.sub(r"[_\s]+", " ", stem).strip(" _-")
    action = infer_action(stem)
    quarter_match = re.search(r"\bQ(\d)\b", stem, re.I)
    number_match = re.search(r"#(\d+)", stem)
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "clip"
    mode = "broadcast" if action == "FULL" else ("context" if action == "CONTEXT" else "action")
    return {
        "key": f"cut-{slug}",
        "action": action,
        "quarter": quarter_match.group(1) if quarter_match else ("0" if action in {"CONTEXT", "FULL"} else "1"),
        "number": int(number_match.group(1)) if number_match else sum(ord(char) for char in slug) % 400 + 1,
        "kind": "cut",
        "mode": mode,
        "label": aspect,
        "assist": "assist" in name.lower(),
        "club": "thfc" if is_thfc(name) else "sas",
    }


def hint_player(name: str, by_id: dict) -> dict | None:
    low = name.lower()
    by_needle = {person["needle"]: person for person in by_id.values() if person.get("needle")}
    for pattern, needle in HINTS:
        if re.search(pattern, low) and needle in by_needle:
            return by_needle[needle]
    return None


def build_library(env: dict[str, str] | None = None) -> dict:
    env = env or load_env()
    if not env.get("SCOREPLAY_API_KEY"):
        raise RuntimeError("SCOREPLAY_API_KEY is empty in .env")
    raw_players, raw_media = fetch_scoreplay(env)
    by_id = {}
    for raw in raw_players:
        full = raw.get("full_name") or ""
        info = match_roster(full)
        by_id[raw["ID"]] = {
            "id": raw["ID"],
            "name": full,
            "short": short_name(full, info["needle"] if info else ""),
            "thumb": raw.get("profile_picture_thumb") or raw.get("profile_picture") or "",
            "club": info["club"] if info else "",
            "number": info["number"] if info else "",
            "pos": info["pos"] if info else "",
            "needle": info["needle"] if info else "",
            "shop": shop_url(info["club"], full) if info else "",
        }

    videos = []
    photos = []
    for raw in raw_media:
        pids = raw.get("player_ids") or []
        players = [by_id[pid] for pid in pids if pid in by_id]
        roster_players = [p for p in players if p["club"]]
        item = {
            "id": raw.get("ID"),
            "name": raw.get("name") or "",
            "thumb": raw.get("thumbnail_url") or "",
            "video": raw.get("compressed_url") or "",
            "duration": (raw.get("video") or {}).get("duration") or raw.get("duration") or 0,
            "players": roster_players or players,
        }
        if raw.get("type") == "video":
            videos.append(item)
        else:
            photos.append(item)

    groups: dict[str, dict] = {}
    for video in videos:
        info = describe_video(video["name"])
        players = list(video["players"])
        if not players:
            hinted = hint_player(video["name"], by_id)
            if hinted:
                players = [hinted]
        group = groups.setdefault(
            info["key"],
            {
                "quarter": info["quarter"],
                "action": info["action"],
                "number": info["number"],
                "kind": info["kind"],
                "mode": info["mode"],
                "assist": info["assist"],
                "angles": [],
                "player_map": {},
                "club": info["club"],
                "named_id": None,
                "title": video["name"],
            },
        )
        hinted = hint_player(video["name"], by_id)
        if hinted:
            group["named_id"] = hinted["id"]
            group["player_map"][hinted["id"]] = hinted
        group["angles"].append(
            {
                "id": video["id"],
                "label": info["label"],
                "thumb": video["thumb"],
                "video": video["video"],
                "duration": video["duration"],
            }
        )
        for player in players:
            group["player_map"][player["id"]] = player
        if info["club"] == "thfc":
            group["club"] = "thfc"

    plays = []
    for key, group in groups.items():
        angles = sorted(group["angles"], key=lambda a: a["label"])
        players = list(group["player_map"].values())
        if any(p.get("club") == "thfc" for p in players) and not any(p.get("club") == "sas" for p in players):
            group["club"] = "thfc"
        action = group["action"]
        plays.append(
            {
                "id": key,
                "quarter": group["quarter"],
                "number": group["number"],
                "action": action,
                "action_plain": ACTION_PLAIN.get(action, action.lower()),
                "importance": IMPORTANCE.get(action, 0.5) + (0.08 if group["kind"] == "cut" else 0),
                "kind": group["kind"],
                "mode": group["mode"],
                "assist": group["assist"],
                "named_id": group["named_id"],
                "title": group.get("title") or key,
                "angles": angles,
                "players": [{k: p[k] for k in ("id", "name", "short", "thumb", "club", "number", "pos", "shop") if k in p} for p in players],
                "club": group["club"],
            }
        )
    plays.sort(key=lambda p: (p["club"], int(p["quarter"] or 0), p["number"], p["action"]))

    counts: dict[tuple, int] = defaultdict(int)
    for play in plays:
        for player in play["players"]:
            if player.get("club") == play["club"]:
                counts[(play["club"], player["id"])] += 1
    max_count = max(counts.values()) if counts else 1

    by_quarter: dict[str, list] = defaultdict(list)
    for play in plays:
        if play["kind"] != "angle":
            play["setup_id"] = None
            continue
        by_quarter[f"{play['club']}-{play['quarter']}"].append(play)

    for quarter, bucket in by_quarter.items():
        bucket.sort(key=lambda p: p["number"])
        for index, play in enumerate(bucket):
            play["setup_id"] = bucket[index - 1]["id"] if index else None

    play_index = {p["id"]: p for p in plays}
    for play in plays:
        setup = play_index.get(play["setup_id"]) if play["setup_id"] else None
        their_ids = {p["id"] for p in play["players"]}
        setup_ids = {p["id"] for p in setup["players"]} if setup else set()
        story = 0.2
        if play.get("assist"):
            story = 1.0
        elif setup and their_ids and setup_ids and their_ids != setup_ids:
            story = 1.0
        elif setup:
            story = 0.45
        play["story"] = story
        club_id = play["club"]
        club_players = [p for p in play["players"] if p.get("club") == club_id] or play["players"]
        play_total = max(sum(1 for item in plays if item["club"] == club_id), 1)
        ubiquitous = {pid for (club_key, pid), count in counts.items() if club_key == club_id and count >= 0.85 * play_total}
        if club_players and counts:
            candidates = [p for p in club_players if p["id"] not in ubiquitous] or club_players
            quiet = min(candidates, key=lambda p: counts.get((club_id, p["id"]), 1))
            named = next((p for p in club_players if p["id"] == play.get("named_id")), None)
            star = named or max(club_players, key=lambda p: counts.get((club_id, p["id"]), 1))
            star_room = 1 - (counts.get((club_id, star["id"]), 1) / max_count)
            quiet_room = 1 - (counts.get((club_id, quiet["id"]), 1) / max_count)
        else:
            quiet = star = (club_players or [{"id": 0, "name": "Open", "short": "Open", "shop": ""}])[0]
            star_room = quiet_room = 0.5
        room = round(quiet_room, 3)
        setup_players = setup["players"] if setup else []
        hardcore_hero = next((p for p in setup_players if p["id"] != star["id"]), star)
        picture = round(min(0.98, 0.42 + 0.4 * play["importance"] + 0.08 * min(len(play["angles"]), 4)), 3)
        heroes = {"matchday": star, "hardcore": hardcore_hero, "player": quiet}
        fit = {"matchday": play["importance"], "hardcore": 0.25 + 0.75 * story, "player": 0.25 + 0.75 * quiet_room}
        room_for = {"matchday": star_room, "hardcore": 0.55, "player": quiet_room}
        scores = {}
        reasons = {}
        captions = {}
        for audience, hero in heroes.items():
            audience_room = room_for[audience]
            scores[audience] = round(
                picture * (0.45 + 0.55 * story) * (0.4 + 0.6 * audience_room) * fit[audience], 3
            )
            captions[audience] = _caption(audience, hero, play, setup, hardcore_hero)
        unit = "versions" if play.get("kind") == "cut" else "angles"
        reasons["matchday"] = f"{play['action_plain'].capitalize()} with {len(play['angles'])} {unit}. {_who(star)} is the finish."
        if play.get("assist"):
            reasons["hardcore"] = "The pass is named on the file. That is the clip to post for the hardcore account."
        elif setup and story > 0.8:
            reasons["hardcore"] = f"The clip before it is a {setup['action_plain']} from {_who(hardcore_hero)}."
        elif setup:
            reasons["hardcore"] = f"Same stretch of the quarter. The previous file is a {setup['action_plain']}."
        else:
            reasons["hardcore"] = "No earlier clip in this quarter to join."
        reasons["player"] = f"{_who(quiet)} is on fewer plays than the rest of this file."
        hero_photo = _still_for(photos, heroes["matchday"]["id"]) or _still_for(photos, heroes["player"]["id"])
        play.update(
            {
                "picture": picture,
                "story": round(play["story"], 3),
                "room": room,
                "scores": scores,
                "reasons": reasons,
                "captions": captions,
                "heroes": {k: {"id": v["id"], "name": v["name"], "short": v["short"], "shop": v.get("shop", "")} for k, v in heroes.items()},
                "still": hero_photo,
                "quote": _quote(play, heroes["matchday"]),
                "saturated": star_room < 0.22,
            }
        )

    slim_photos = []
    kept = {"sas": 0, "thfc": 0}
    for photo in photos:
        named_club = "thfc" if is_thfc(photo["name"]) else ""
        if not photo["players"] and named_club != "thfc":
            continue
        lead = photo["players"][0] if photo["players"] else None
        club_id = named_club or (lead or {}).get("club") or "sas"
        if kept.get(club_id, 0) >= 200:
            continue
        kept[club_id] = kept.get(club_id, 0) + 1
        slim_photos.append(
            {
                "id": photo["id"],
                "thumb": photo["thumb"],
                "image": photo["video"] or photo["thumb"],
                "player_id": lead["id"] if lead else 0,
                "player": lead["short"] if lead else "Tottenham",
                "name": photo["name"],
                "club": club_id,
            }
        )

    clubs = [_club("sas", plays, by_id), _club("thfc", plays, by_id)]
    library = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "game": {
            "sas": {"label": "Spurs vs Kings", "when": "Oct 16, 2026", "assets": len(videos) + len(photos)},
            "thfc": {"label": "Tottenham", "when": "Match file not in this library", "assets": 0},
        },
        "audiences": [
            {"id": "matchday", "label": "Matchday"},
            {"id": "hardcore", "label": "Hardcore"},
            {"id": "player", "label": "Player channels"},
        ],
        "clubs": clubs,
        "plays": plays,
        "photos": slim_photos[:480],
    }
    DATA.mkdir(exist_ok=True)
    LIBRARY_PATH.write_text(json.dumps(library), encoding="utf-8")
    return library


def _who(player: dict) -> str:
    return player.get("short") or player.get("name") or "the player"


def _caption(audience: str, hero: dict, play: dict, setup: dict | None, hardcore_hero: dict) -> str:
    name = _who(hero)
    action = play["action_plain"]
    unit = "versions" if play.get("kind") == "cut" else "angles"
    if play.get("action") == "FULL":
        return "Full match. Manchester United 1–1 Tottenham."
    if play.get("action") == "HIGHLIGHTS":
        return f"Match highlights. {len(play['angles'])} {unit}."
    if audience == "matchday":
        return f"{name}, {action}. {len(play['angles'])} {unit}."
    if audience == "hardcore" and play.get("assist"):
        return f"{name}'s {action}. Keep the pass in the post."
    if audience == "hardcore" and setup and play["story"] > 0.8:
        return f"Before {name}'s {action}: {_who(hardcore_hero)}, {setup['action_plain']}."
    if audience == "hardcore" and setup:
        return f"{name}'s {action}, with the previous clip still in."
    return f"{name} is quiet everywhere else. This {action} is the post."


def _quote(play: dict, hero: dict) -> str:
    loud = {
        "DUNK!": "That is a poster.",
        "STL JAM!": "Stolen, and put through.",
        "WINDMILL": "He brought the windmill out.",
        "BLOCK": "Sent it back.",
        "BLK": "Sent it back.",
        "3PT": "From the logo, no hesitation.",
        "LAY": "He finishes through contact.",
        "GLASS": "Off the glass, and it drops.",
        "DRIVE": "He turns the corner.",
        "PULL J": "Pulls up in the gap.",
        "TAKE": "He takes the contact.",
        "J": "Rises over the closeout.",
        "GOAL": "The net moves.",
        "CHANCE": "He should score that.",
        "TACKLE": "He wins it clean.",
        "HIGHLIGHTS": "The match, cut short.",
        "FULL": "The whole night is in this file.",
        "CELE": "The away end goes.",
    }
    line = loud.get(play["action"], "The camera stays with him.")
    return f"{_who(hero)}. {line}"


def _still_for(photos: list, player_id: int) -> dict | None:
    for photo in photos:
        if len(photo["players"]) == 1 and photo["players"][0]["id"] == player_id and photo["thumb"]:
            return {"id": photo["id"], "thumb": photo["thumb"], "image": photo["video"] or photo["thumb"]}
    return None


def _club(club_id: str, plays: list, by_id: dict) -> dict:
    if club_id == "sas":
        meta = {
            "id": "sas",
            "name": "San Antonio Spurs",
            "short": "Spurs",
            "kind": "basketball",
            "opponent": "Sacramento Kings",
            "when": "Oct 16, 2026",
            "sponsor": {
                "name": "Ledger",
                "place": "Jersey patch",
                "url": "https://www.ledger.com",
                "blurb": "The patch on the Spurs jersey. A clip only counts as sponsor-visible after TwelveLabs can read the mark in frame.",
            },
            "kit": "Nike",
            "lineup_needles": SAS_LINEUP,
            "bench_needles": SAS_BENCH,
            "spots": SAS_SPOTS,
        }
    else:
        meta = {
            "id": "thfc",
            "name": "Tottenham Hotspur",
            "short": "Tottenham",
            "kind": "football",
            "opponent": "Manchester United",
            "when": "2026/27",
            "score": "1–1",
            "sponsor": {
                "name": "AIA",
                "place": "Front of shirt",
                "url": "https://www.aia.com",
                "blurb": "Front of shirt through the 2026/27 season. Nike makes the kit. Kraken sits on the sleeve.",
            },
            "kit": "Nike",
            "lineup_needles": THFC_LINEUP,
            "bench_needles": THFC_BENCH,
            "spots": THFC_SPOTS,
        }
    people = [p for p in by_id.values() if p["needle"]]
    by_needle = {}
    for person in people:
        by_needle.setdefault(person["needle"], person)

    def place(needles, spots=None):
        placed = []
        for index, needle in enumerate(needles):
            person = by_needle.get(needle)
            if not person:
                continue
            row = {
                "id": person["id"],
                "name": person["name"],
                "short": person["short"],
                "thumb": person["thumb"],
                "number": person["number"],
                "pos": person["pos"],
                "shop": person["shop"],
            }
            if spots and index < len(spots):
                row["x"], row["y"] = spots[index]
            placed.append(row)
        return placed

    meta["lineup"] = place(meta.pop("lineup_needles"), meta.pop("spots"))
    meta["bench"] = place(meta.pop("bench_needles"))
    meta["play_count"] = sum(1 for p in plays if p["club"] == club_id)
    return meta


def load_library() -> dict:
    if LIBRARY_PATH.exists():
        return json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    return build_library()
