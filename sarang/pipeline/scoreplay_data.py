"""Read-only lookups in ScorePlay that the other stages share."""

from functools import lru_cache

from . import clients, config


@lru_cache
def squad() -> list[dict]:
    """Tottenham 2026-27 squad (players and staff) as [{id, name}]."""
    s = config.load()
    r = clients.scoreplay(s).get("/players", params={"team_season_id": s.team_season_id, "per_page": 200})
    r.raise_for_status()
    return [{"id": p["ID"], "name": p["full_name"]} for p in r.json()]


def source_file_url(media_id: int) -> str:
    """URL of the full-quality mp4 behind a media."""
    r = clients.scoreplay(config.load()).get(f"/media/{media_id}")
    r.raise_for_status()
    files = [f for f in r.json().get("files") or [] if f.get("url", "").endswith(".mp4")]
    best = next((f for f in files if f.get("details") == "photographer_quality"), files[0] if files else None)
    if not best:
        raise RuntimeError(f"media {media_id} has no mp4 file")
    return best["url"]
