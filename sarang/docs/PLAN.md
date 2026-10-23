# Build plan

Rewritten Oct 22 2026 (evening). The team-facing version, with owners and status, is the "Spurs Enrichment Build Plan" doc: https://claude.ai/artifact/BS5uk8QipM6QnWZSRZfbxK. Task IDs (W1, A1, ...) match it.

## The scenario

A live broadcast feed comes into ScorePlay. Our service watches it, sends it to TwelveLabs in short windows, and writes every highlight back to ScorePlay as a captioned, player-tagged clip, so a content creator only has to pick and publish. Target: under 2 minutes from a play to a clip in Highlights, with no person in the loop until the creator.

```
Live feed (HLS, 2s segments)
   │  buffer: last 90s on disk                         [M1, built]
   ▼
Window loop: every 20s, the newest 30s window          [M4]
   │  analyzed in the background; recording never waits
   ▼
TwelveLabs Pegasus: event, team, players, caption,     [M2, built]
   │  key moment, is_highlight
   ▼
Highlight? re-cut centred on the key moment, dedupe    [M4]
   ▼
ScorePlay write-back: clip into Highlights + caption   [M3]
   + player tags, and a log on the match
   ▼
Creator picks and publishes from Highlights
```

## Decisions

- **Sport and game:** Tottenham Hotspur football. The live feed is a 720p replay, on a loop, of Man Utd vs Tottenham. Our copy is media 130851979 in company 5370. Segment `video_N.ts` starts N x 2s into the match, so any feed moment maps to an offset on our media.
- **TwelveLabs decides, no separate detector.** The 2s HLS segments are only how the feed arrives. We group them into windows and let Pegasus judge each window.
- **Windows:** 30s long, a new one every 20s (10s overlap), so any play shorter than 10s sits wholly inside at least one window. Overlap is a setting; with it off, a window starts every 30s (~210 calls per match instead of ~315).
- **Plays split across windows:** TwelveLabs has no memory between calls. Three fixes: the overlap above; the previous window's caption goes into the next prompt as context; and highlights are re-cut from the buffer centred on `key_moment_seconds`, so the delivered clip is whole even when the window wasn't. Two windows reporting the same event within ~10s of match time are one highlight (dedupe).
- **Write-back:** highlights are uploaded into the Highlights event (1536128) with the caption as description, the event type and team as tags, and players as `player_ids`. Every window that isn't `none` also gets a log on media 130851979 (offset range), so the whole game becomes a searchable timeline. Everything we write carries `source:twelvelabs`.
- **Players by name, not number.** Names come from the commentary and are matched to the Tottenham squad (team season 72217). Shirt numbers proved unreliable. Only tag when `team` is tottenham and the surname appears in `commentary_names`.
- **No compute on ScorePlay.** ScorePlay's ingest workflows are fixed for the hackathon (its `http_call` step would be the production route to TwelveLabs). We cut, transcode and call TwelveLabs on our machine, as the ScorePlay deck asks.
- **Analysis stays simple until the loop works:** one Pegasus call per window with the `football-v2` schema. Smarter analysis is a stretch goal.
- **Hands off the pre-loaded TwelveLabs assets** unless we decide we need them.
- **Adopted (Oct 22, late): a local rules engine decides when to clip**, from crowd noise (loud and sudden quiet), commentary energy, camera shots and people counts (ffmpeg + MediaPipe). TwelveLabs decides what happened. This replaces the fixed 20s window step in M4; a 5-minute TwelveLabs sweep is the safety net. Spec, thresholds and results: `docs/rules-engine.md`.
- **TwelveLabs roles:** Pegasus sync analyze per clip (seconds); Pegasus on a 360p copy of the last 5 minutes for the sweep; our own knowledge store "spurs-highlights" for every delivered highlight, with Jockey grouping angles of the same play.

## Scaffold status (Oct 22, late)

`uv run pipeline live` runs the whole chain on the live feed. With `DRY_RUN=true`, ScorePlay and TwelveLabs writes are printed, not sent.

| Stage | Module | State |
| --- | --- | --- |
| Feed buffer (6 min) | `feed.py` | Built |
| Loudness, commentary energy | `signals.py` (ffmpeg) | Built |
| Roar, whistle, people, shot type, cuts, raised arms | `mp_signals.py` (MediaPipe) | Built |
| Watch ScorePlay's live recording (finds it by itself) | `scoreplay_live.py`, `live.py --source scoreplay` | Built; ~7-9s behind the feed; default source |
| Rules engine | `rules.py`, `rules.yaml` | Built; both goals caught on replay |
| Replay for tuning | `replay.py` | Built, with a signals cache |
| Pegasus per clip, with previous caption as context | `analyze.py` | Built |
| Safety-net sweep | `sweep.py` | Works against TwelveLabs (9 events in 5 min); clips only `clip_event_types` |
| ScorePlay log + upload + player tags | `writeback.py` | Works for real: Spurs equalizer logged (17897968) and uploaded (130968755) |
| Knowledge store + Jockey angles | `tl_store.py` | Dry run only; REST shapes unverified |
| Quick clip superseded by full clip | `live.py` | TODO |
| SQLite state | | TODO (results go to `runs/live_*.jsonl`) |
| Unit tests | `tests/` | 39 tests, `uv run pytest -q`, about 1s |

## Verify each milestone

Each milestone ends with a command a human runs to verify it. Don't start the next one until the current one is verified.

## M0 · Smoke test both APIs (done)

`uv run pipeline smoke`

Checks ScorePlay (`whoami`, company ID, media 130851979, its logs, the upload event), the live feed (and that it replays our media), and TwelveLabs (indexes). Ends with `SMOKE OK`.

## M1 · Cut a clip from the live feed (done)

`uv run pipeline clip --seconds 15`

- `feed.Buffer` polls the playlist every 2s and keeps the last N segments on disk, each with its wall-clock time (`EXT-X-PROGRAM-DATE-TIME`) and its offset in the match.
- `feed.cut` joins segments into `clips/<id>.mp4` with ffmpeg's `concat:` protocol (the concat demuxer gave duplicate DTS) and writes `clips/<id>.json` with wall-clock and match-offset times. Checked frame for frame against media 130851979.
- A clip runs about 0.42 MB/s, so the 30 MB base64 limit caps inline clips at about 50s.

## M2 · Analyze a clip with TwelveLabs (built; names need a human check, task D1)

`uv run pipeline analyze clips/<id>.mp4`

- `POST /analyze`, `pegasus1.6`, clip inline as base64, `response_format` JSON schema from `pipeline/prompts.py` (`football-v2`). Saves `runs/<id>.analysis.json`.
- Test set: `uv run pipeline clip-source --start S --end E --name ID` cuts 720p clips from media 130851979. Five clips: Man Utd goal (4645-4690), Spurs equalizer (5800-5845), Man Utd free kick (3975-4005), Spurs substitution (4278-4300), build-up (4600-4625). Goals: 1-0 at 72:05 match clock (offset ~4671), 1-1 at 91:15 (offset ~5824).
- Event type and team right on 5/5; `key_moment_seconds` within a second or two on both goals. Cost about 24k input tokens and 11s per 30s clip, 35k and 15s per 45s clip.

## M3 · Write back to ScorePlay

`uv run pipeline writeback runs/<id>.analysis.json`

- **Players (A2):** map `tottenham_players` to ScorePlay player IDs from the squad, cached in SQLite (`state.db`, table `players`). Apply the tottenham + `commentary_names` rule above.
- **Log (A1):** `POST /video/logs` on media 130851979 with `start_offset` / `end_offset` around the key moment (match offset = clip `source_start_offset` + `key_moment_seconds`), `comment` = caption, `raw_tags` = `source:twelvelabs`, event type, team, player names; `player_ids`. Then `GET /media/{id}/logs` to confirm.
- **Clip (A3):** `POST /upload/event/1536128?parts=1` with name, description (caption) and `raw_tags` → PUT the bytes, keep the ETag → `POST /upload/complete/{media_id}`. Poll until status is DONE (about 40s).
- **Tags (A4):** `POST /media/{id}/tags` with `player_ids` on the uploaded clip.
- Respect `DRY_RUN`: with it on, print every request instead of sending it.

Done when: the log shows on the match in the ScorePlay UI, and the clip plays in Highlights with its caption and player tags. Run it on t2 (the Spurs equalizer) first.

## M4 · Live window loop

`uv run pipeline live` (flags: `--window 30 --step 20`, `--no-overlap`, `--max-calls N`)

- **W1:** keep `feed.Buffer` running (keep 90s). Every `step` seconds, cut the newest `window` seconds and hand it to a background worker, so polling never stops. Pass the previous window's caption into the prompt as context.
- **W2:** speed test before settling the defaults: analyze-call time at 30s vs 20s windows and 720p vs 480p. Pick the fastest that still names players right.
- **L1:** for each result:
  - `none` → nothing written.
  - anything else → a log on the match (M3 A1).
  - `is_highlight` → dedupe against recent highlights (same event type within ~10s of match time), then re-cut from the buffer centred on the key moment (about 10s before, 15s after), then M3 A2-A4.
- SQLite table `windows(start_offset, end_offset, status, event_type, is_highlight, analysis_id, error)` for visibility and restarts. Print a running count of TwelveLabs calls and highlights.
- The feed loops back to kick-off. Skip or split a window whose segments carry a discontinuity.

Done when: 10 minutes of live feed produce one analysis per window with none skipped, and every highlight in that time lands in Highlights, tagged, under 2 minutes after it happens, with no manual steps.

## M5 · End to end and demo-ready (X1)

- Run `pipeline live` across both goals (start the feed loop near offsets ~4600 and ~5780, or wait for them to come round) and confirm each lands once in Highlights.
- Record the numbers for the pitch: seconds from play to clip, TwelveLabs calls and tokens per match, highlights found vs windows analyzed.
- Record a backup video of the demo.

Done when: the demo runs twice in a row without anyone touching it.

## ScorePlay setup (no code)

- **C1:** schedule the live feed into ScorePlay (Live > Schedule > Pull > Manual URL, Save to media library). Gives a live media of our own; logs on it can use unix times from the feed.
- **Taxonomy:** agree our tag names (event types, `source:twelvelabs`) with the ScorePlay engineers before writing, as their deck asks.

## Stretch

- **Multi-angle plays:** social media managers film the same play on their phones and upload to ScorePlay. ScorePlay puts every photo and video on one clock (`tc_in` / `tc_out`, ms since midnight, from capture time). For each highlight, find uploads whose time range overlaps the play and group them with the feed clip (a sub-collection per play, or logs sharing an `external_id`), so an editor gets every angle in one place. For the demo the feed carries today's clock while the library's phone footage is from match day: set a test upload's timecode (`PUT /media/{id}/details`) or match by content. Allow a few seconds of slack for camera clocks.
- **Smarter analysis:** one call per longer window with segmentation (`time_based_metadata`), which returns every timed event in it; players recognised by face from ScorePlay headshots (TwelveLabs entity collections), for bench players nobody names; search the match in words with Marengo and turn hits into logs; more fields per clip (excitement score, thumbnail moment, caption styles).
- **MediaPipe on the delivered clip:** 9:16 reframing that follows the action, and picking the best thumbnail frame. Runs locally after a highlight is found; it doesn't decide what is a highlight.
- **Manual moments:** a ScorePlay webhook (`video_log.created`, tunnel, loop guard on `source:twelvelabs`, jobs keyed on `video_log_id`) so the creator can add a moment by hand. This was the original M4.
- **Live-recording logs:** once C1 exists, also write logs on the live media, timed from the feed's wall-clock times.
