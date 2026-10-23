# API notes

Gathered Oct 22 2026 from ScorePlay's OpenAPI spec and docs and from the TwelveLabs v1.3 docs. Full specs:

- ScorePlay OpenAPI: https://developer.scoreplay.io/downloads/scoreplay.yaml (Postman: https://developer.scoreplay.io/downloads/scoreplay.postman_collection.json)
- ScorePlay webhooks: https://developer.scoreplay.io/webhooks/overview/ and https://developer.scoreplay.io/webhooks/events/
- TwelveLabs docs index: https://docs.twelvelabs.io/v1.3/llms.txt (append `.md` to any page URL for markdown)

When something below conflicts with the live spec, the spec wins. Update this file.

## Live feed

- `LIVE_FEED_URL` returns an HLS playlist: `#EXT-X-TARGETDURATION:2`, about 6 segments (12s), each preceded by `#EXT-X-PROGRAM-DATE-TIME`.
- Segment URLs: `https://cdn.scoreplay.io/<bucket>/5167/8632559/<uuid>/hls/video_NNNNNN.ts`
- Has `#EXT-X-DISCONTINUITY-SEQUENCE` and segment numbers far below `MEDIA-SEQUENCE`: likely a recorded game replayed in a loop.

## Confirmed in M0 (Oct 22)

- Our API key belongs to company **5370** (`spurs2-hack-16`), a clone of the organizers' company 5167. Media 8632559 belongs to 5167 and returns `MEDIA_NOT_FOUND` for us.
- Our copy of the game is media **130851979**, "Manchester United vs Spurs | Full Match | 2026-27.mp4" (6335s, event 1536135). Its file URLs point at the same source as the feed (`5167/8632559/1e89c326-...`).
- The feed replays that match (Man Utd vs Tottenham, football, not basketball). Checked by comparing frames: feed segment `video_001991.ts` and our media at 3982s both show match clock 60:35. Feed is 720p, our media 1080p.
- Segment `video_N.ts` starts at `N * 2` seconds in the source. Its PTS `start_time` is that plus the 1.4s mpegts muxer delay (3983.41s for N=1991). So offset-mode video logs on 130851979 work.

## Live feed, from the organizers (ScorePlay info page 2760)

- It is a replay of the full match on a loop, around the clock, starting again at kick-off. You join mid-match.
- `EXT-X-PROGRAM-DATE-TIME` is today's wall-clock time, not the match clock.
- To record it in ScorePlay, use the UI: Live > Schedule > New schedule > Pull tab > Manual URL > paste the feed URL. The start time must be in the future. Turn on "Save to media library" and pick a collection.
- `POST /streams/schedules` has no manual-URL source (only `stream_id`, `stream_group_id`, `pull_receiver_id` or an SRT caller), so the schedule is created in the UI. Once a recording exists it is a live media in our company, and logs can use unix timestamps (`start_timestamp` / `end_timestamp`) from the PDT.
- Upload target for enriched clips: event **1536128** "Highlights" under Premier League / Manchester United vs Tottenham Hotspur - Week 6 (1536124).
- The company also holds San Antonio Spurs content (event tree "NBA", pre-cut clips named like `S7 BLOCK-252A`), Spurs vs Kings photos, and 92 players covering both Tottenham and San Antonio.

## ScorePlay quirks found in M0

- `GET /whoami` has no company ID. Read `company_id` off any media from `POST /media/search`.
- `POST /event/search` with `event_id` or `event_ids` returns `[]`. `parent_id` and `query` work. Walk the tree from the top-level events to find one by ID.
- `GET /media/{id}` returns `duration: 0` for the full match. Use `(tc_out - tc_in) / 1000`, or `duration` from `/media/search`.
- `GET /media/{id}/logs` returns `{items, page, limit}`.

## ScorePlay live recording (tested Oct 23, schedule 54745)

- Schedule status went SCHEDULED → FEED_DETECTED (20s) → LIVE (about 4 min after start). The recording exists as a media from the start: find it with `POST /media/search {"is_growing_media": true}` (ours: 131029031, in event 1536124).
- Once LIVE, `GET /media/{id}` → `video` carries HLS playlists: `original.m3u8` (the feed's own 720p), `1080p.m3u8` (an upscale, no extra detail), `720p.m3u8`, `stream_playlist.m3u8`, `master.m3u8`. Same list in `GET /media/{id}/formats/clip`. The playlists are public S3 URLs.
- Playlists are `PLAYLIST-TYPE:EVENT`: they grow and list every segment since the start, 2s each, named `original_N.ts`, with `PROGRAM-DATE-TIME`. Segment N starts N x 2s into the recording, so offset-mode logs on the live media need no clock matching. `video.timecode` was 13:18:47 UTC, about 2s before the first PDT, so prefer offsets over unix times.
- Delay: the recording's newest segment is about 9s behind the organizer feed.
- `feed.Buffer` reads it as is (relative segment URLs, `_N.ts` names; the first poll starts from the newest segments).
- A log on the live media gets a ScorePlay-made clip immediately: `playback_url` (HLS, 640x360 preview) and a thumbnail were present at the first read after `POST /video/logs`, frame-accurate (checked against the recording at 36s), exact length. Test log: 17905257 (tags `source:twelvelabs`, `test`).

## First real write-back (Oct 22, late): what we learned

- `POST /video/logs`: `external_id` on a `video_logs` entry means "find the media by this external match ID", not a label for the log. Our own ID there gave `404 RECORD_NOT_FOUND`. Put our clip ID in `raw_tags` (`clip:<id>`) instead.
- Use one timing mode per log. Offset range (`start_offset` + `end_offset`) works on media 130851979. Read back, `start_timestamp` / `end_timestamp` are in milliseconds and `timestamp` in seconds.
- The log inherits the match's own tags (Premier League, Week 6, ...) next to our raw tags, and shows `players` as `{id, name}`.
- Upload into Highlights (`/upload/event/1536128?parts=1` → PUT → `/upload/complete`) went PROCESSING → TRANSFORMED → DONE in about 60s for a 45s, 17 MB clip.
- On a media, players and tag options both live in `tags[]` (`player_id` + `player`, or `tag_option_id` + `tag_option`). There is no `players` field.
- ScorePlay's own face recognition runs on upload and adds players of its own: our clip got Simons and Solanke from us, plus Sávio, De Zerbi and Marmoush from ScorePlay.
- First real results: log 17897968 on media 130851979 at 5816-5836s; clip media 130968755 in Highlights.

## ScorePlay

Base URL `https://media.scoreplay.io/v1`. Header `X-ScorePlay-Api-Key`. Key from Settings → API Key in the ScorePlay app (needs the "Can view api key" permission).

| Purpose | Call |
|---|---|
| Key scope | `GET /whoami` |
| Media record | `GET /media/{id}` |
| Clippable files (incl. HLS, presigned 24h `file_url`) | `GET /media/{id}/formats/clip` |
| Downloadable files | `GET /media/{id}/formats/download` |
| Logs on a media | `GET /media/{id}/logs` |
| One log | `GET /video/logs/{id}` |
| Search logs | `POST /video/logs/search` |
| Create logs | `POST /video/logs` (returns boolean) |
| Tag a media | `POST /media/{id}/tags` body `{tag_option_ids, player_ids, sponsor_ids, external_player_ids}` |
| Players, tags | `GET /players`, `GET /tag/search`, `/tag/options` |
| Find the game event | `POST /event/search` |
| Upload into event | `POST /upload/event/{id}?parts=N` body `{name*, description, date, player_accessible, raw_tags, available_user_type_ids}` → `{upload_id, key, urls[{url, parts_number}], media_id, media_version_id}` |
| Finish upload | `POST /upload/complete/{media_id}` body `{key*, upload_id*, parts*[{parts_number, etag}]}` |
| Live recording | `POST /streams/schedules` body `{name*, start*, end, collection_id, stream_id, stream_group_id, pull_receiver_id, use_caller, srt_destination, preset_id, is_private, tag_option_ids}`; status SCHEDULED → PROBING → FEED_DETECTED → LIVE → RECORDED |
| Distribution destinations | `/storages` (S3, GCS, SMB) |

`POST /video/logs` body:

```json
{
  "company_id": 5370,
  "video_logs": [{
    "media_id": 130851979,
    "external_id": "optional-your-id",
    "log": {
      "start_offset": 5094, "end_offset": 5106, "offset": 5100,
      "comment": "Block by #14 at the rim",
      "raw_tags": ["source:twelvelabs", "block", "jersey:14"],
      "player_ids": [],
      "raw_player_external_ids": []
    }
  }]
}
```

Time modes inside `log`: offset single (`offset`), offset range (`start_offset` + `end_offset`), unix single (`action_timestamp`), unix range (`start_timestamp` + `end_timestamp`), all in seconds.

No update endpoint for an existing video log was found (create, read, delete only). Enrichment therefore adds new logs.

### Webhooks

- Configured in the ScorePlay platform UI. One event type per webhook.
- Events: `media.create`, `media.proxy.create`, `media.update`, `media.delete`, `media.transcript.create|update|delete`, `video_log.created`, `video_log.updated`, `video_log.deleted`, `manual.trigger` (test).
- Body is minimal: `{event, company_id, media_id, video_log_id?, timestamp}`. Fetch details with the API.
- Must answer 2xx within 10s. Duplicates and out-of-order delivery happen. Requests are not signed, so configure an auth header on the webhook and check it.
- Destination must be public. Localhost is rejected, so use a tunnel.
- `video_log.updated` often follows `video_log.created`, including when tags are auto-added.

## TwelveLabs

Base URL `https://api.twelvelabs.io/v1.3`. Header `x-api-key`.

### Analyze (sync), the core call

`POST /analyze`

```json
{
  "model_name": "pegasus1.6",
  "stream": false,
  "temperature": 0.1,
  "video": { "type": "base64_string", "base64_string": "<mp4 base64>" },
  "prompt_v2": { "input_text": "Clip from a San Antonio Spurs game. Decide if it contains a highlight-worthy Spurs play. Name the play, list jersey numbers of Spurs players involved, write a one-sentence caption." },
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "type": "object",
      "properties": {
        "is_highlight": { "type": "boolean" },
        "play_type": { "type": "string", "enum": ["dunk", "three", "block", "steal-break", "and-one", "alley-oop", "other", "none"] },
        "jersey_numbers": { "type": "array", "items": { "type": "string" } },
        "description": { "type": "string" },
        "confidence": { "type": "number" }
      },
      "required": ["is_highlight", "play_type", "jersey_numbers", "description", "confidence"]
    }
  }
}
```

- `video.type` can be `url`, `asset_id`, or `base64_string` (30 MB max).
- `start_time` / `end_time` (seconds, window at least 1s) analyze part of a longer video.
- `stream` defaults to true (NDJSON). Set false for one JSON response: `{id, data, finish_reason, usage}`. `data` is a JSON string.
- Schema must be JSON Schema 2020-12; `minLength` / `maxLength` are rejected.
- No live or HLS stream ingest found in the TwelveLabs API. Partner VideoDB offers live analysis with Pegasus.

### Other features

- Assets: `POST /assets` (multipart: `method=direct|url`, `file` ≤200 MB or `url`, `user_metadata` JSON string). Poll `GET /assets/{id}` until `ready`.
- Index: `POST /indexes/{index_id}/indexed-assets` body `{asset_id}` (202, async).
- Segmentation: async analyze with `analysis_mode: "time_based_metadata"` and `response_format.type: "segment_definitions"` (up to 10 definitions, 20 fields each). Returns segments with `start_time`, `end_time`, `metadata`. SDK: `client.analyze_async.tasks.create(...)`. Check the API reference for the raw REST path.
- Entities (beta): entity collections of people with reference images; search with `<@entity_id>` in `query_text`. Free plan: 1 collection, 15 entities. Index needs Marengo.
- Webhooks: fire when indexing or async analysis tasks finish. Set up in the TwelveLabs dashboard.
- Existing index in the account: `premiere-league`.
