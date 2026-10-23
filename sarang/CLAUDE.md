# Spurs Highlight Enrichment (hackathon prototype)

Spurs² Hackathon, UT Austin, Oct 22–23 2026. Team problem: the manual content workflow takes hours, so coverage defaults to stars. This prototype auto-enriches live game video so moments from bench and role players get tagged and surfaced too.

## Architecture (target)

```
Live feed (HLS) ──► Enrichment service (this repo)
                      buffer the feed, every 20s send the newest 30s window
                      ─► TwelveLabs analyze ─► structured JSON
                      highlight? re-cut around the key moment, dedupe
                          │
                          ▼ write back: clip into Highlights, caption, player tags, log on the match
                    ScorePlay (collections, search, distribution) ─► content creator picks and publishes
```

TwelveLabs decides what is a highlight; there is no separate detector. ScorePlay is the destination (and the live recording, once scheduled). This repo is the glue and does all cutting locally: ScorePlay runs no compute for us this week.

## Stack and conventions

- Python 3.11+, managed with `uv`. HTTP with `httpx`. Webhook server with FastAPI + uvicorn. Video with `ffmpeg` (CLI, via subprocess). State in SQLite (`state.db`).
- Single package `pipeline/` with a Typer CLI: `uv run pipeline <command>`.
- Config from `.env` (see `.env.example`). Never print, log or commit API keys. `.env` is gitignored.
- `DRY_RUN=true` by default: every write to ScorePlay or TwelveLabs prints the request (method, URL, JSON body) instead of sending it. Reads are always allowed.
- Every log or tag this service writes to ScorePlay carries the raw tag `source:twelvelabs`. The webhook handler must skip events for logs with that tag (loop guard).
- Webhook handling is idempotent: key jobs on `video_log_id`, treat each event as "re-read current state".
- Keep it small. Prefer one readable module per stage over abstractions.

## Milestones

Work one milestone at a time. Stop after each and show me how to verify it before starting the next. Details and acceptance criteria are in `docs/PLAN.md`; API facts are in `docs/api-notes.md`.

- M0 Smoke test both APIs (done)
- M1 Cut a clip from the live HLS feed (done)
- M2 Analyze a clip with TwelveLabs, get structured JSON (built)
- M3 Write back to ScorePlay: clip into Highlights, player tags, log on the match
- M4 Live window loop: `pipeline live` sends overlapping 30s windows to TwelveLabs and writes highlights back
- M5 End to end on the live feed, demo-ready

The ScorePlay webhook (manual moments), multi-angle grouping and MediaPipe reframing are stretch goals in `docs/PLAN.md`.

## Known facts vs assumptions

Confirmed in M0: our company is 5370 and our copy of the game is media 130851979 (Man Utd vs Tottenham, football). The live feed replays it. Media 8632559 / company 5167 belong to the organizers and are not reachable with our key. See "Confirmed in M0" in `docs/api-notes.md` and the decisions at the top of `docs/PLAN.md`.
