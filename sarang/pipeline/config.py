"""Settings from .env. Keys are never printed."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _int(name: str) -> int | None:
    v = os.getenv(name, "").strip()
    return int(v) if v else None


@dataclass(frozen=True)
class Settings:
    scoreplay_api_key: str
    scoreplay_base_url: str
    scoreplay_company_id: int | None
    scoreplay_media_id: int | None
    scoreplay_event_id: int | None
    scoreplay_webhook_secret: str
    team_season_id: int | None
    twelvelabs_api_key: str
    twelvelabs_base_url: str
    twelvelabs_index_id: str
    twelvelabs_store_id: str
    live_feed_url: str
    dry_run: bool


def load() -> Settings:
    return Settings(
        scoreplay_api_key=os.getenv("SCOREPLAY_API_KEY", ""),
        scoreplay_base_url=os.getenv("SCOREPLAY_BASE_URL", "https://media.scoreplay.io/v1").rstrip("/"),
        scoreplay_company_id=_int("SCOREPLAY_COMPANY_ID"),
        scoreplay_media_id=_int("SCOREPLAY_MEDIA_ID"),
        scoreplay_event_id=_int("SCOREPLAY_EVENT_ID"),
        scoreplay_webhook_secret=os.getenv("SCOREPLAY_WEBHOOK_SECRET", ""),
        team_season_id=_int("SCOREPLAY_TEAM_SEASON_ID"),
        twelvelabs_api_key=os.getenv("TWELVELABS_API_KEY", ""),
        twelvelabs_base_url=os.getenv("TWELVELABS_BASE_URL", "https://api.twelvelabs.io/v1.3").rstrip("/"),
        twelvelabs_index_id=os.getenv("TWELVELABS_INDEX_ID", ""),
        twelvelabs_store_id=os.getenv("TWELVELABS_STORE_ID", ""),
        live_feed_url=os.getenv("LIVE_FEED_URL", ""),
        dry_run=os.getenv("DRY_RUN", "true").strip().lower() not in ("false", "0", "no"),
    )
