# Auto-clipper for the live match

Sarang's part of the Spurs² hackathon project.

**In one line:** it watches the live match in ScorePlay, spots the big moments by itself, asks TwelveLabs what happened and who was involved, and puts a captioned, player-tagged clip back into ScorePlay. A content creator only has to pick and post.

**The problem it solves:** clipping by hand takes hours, so coverage goes to the stars. This finds every big moment automatically, including the ones bench and role players are in.

## How it works

1. **ScorePlay records the match.** The live feed is scheduled in ScorePlay (Live › Schedule). That's the only place the broadcast comes in.
2. **The clipper watches ScorePlay's recording.** It finds the recording by itself and follows it about 8 seconds behind live.
3. **It listens and looks, every 2 seconds.** Crowd and commentary noise, cheering and whistles, wide shots vs close-ups, how many people are in frame, and raised arms in celebrations. This runs on the laptop (ffmpeg and Google's MediaPipe), so it costs nothing.
4. **A rules engine decides when to clip.** A roar that stays up, a home crowd suddenly going quiet (an away goal), and a switch from wide play to close-ups all count. It marks where the play started and sends a quick clip right away, then a fuller one once the celebration is over.
5. **TwelveLabs decides what happened.** It names the event (goal, save, chance...), the team, the Tottenham players involved, and writes a one-line caption.
6. **The result goes back into ScorePlay:**
   - a **note on the live recording** at that exact moment, with the caption, tags and players. ScorePlay turns it into a clip on the timeline straight away.
   - for real highlights, the **clip in the match's Highlights folder**, ready to post, tagged with the players.
7. **A safety net:** every 5 minutes TwelveLabs also checks the last 5 minutes for anything the rules missed.

## What works today

| | |
| --- | --- |
| Both goals in the recorded match are caught | Man Utd 1-0 and Spurs' 1-1 equalizer. The equalizer scored highest: Old Trafford went quiet, then the away end erupted. |
| A real clip is in ScorePlay | The Spurs equalizer is in Highlights, captioned, with Solanke and Simons tagged. ScorePlay's own face recognition added three more players. |
| Watching ScorePlay's live recording | Tested on a live recording: it found it by itself and ran about 7-9 seconds behind live. |
| Notes turn into ScorePlay clips | A note on the live recording became a playable clip in ScorePlay immediately, frame-accurate. |
| Cost | About 150 TwelveLabs calls per match (versus about 315 if every 30 seconds were checked). |

**Not done yet:** grouping several camera angles of one play in ScorePlay or TwelveLabs (TwelveLabs Jockey, built but not tried for real), replacing the quick clip once the full clip arrives, and vertical 9:16 crops for social.

**On the desk:** the Next Post desk's Live dots tab (`live_clips.py` at the repo root) reads `runs/live_*.jsonl` and `clips/` as this pipeline writes them. It shows each player's clips as they land, shows the full clip in place of the quick one, and groups angles of one play by match time, capture time and replays. It doesn't write anything back to ScorePlay.

## Running it (for whoever has the laptop set up)

It's safe by default: nothing is written to ScorePlay or TwelveLabs until you turn dry run off.

On Windows, install with `winget install Gyan.FFmpeg astral-sh.uv` instead of `brew`. Run everything from inside this `sarang` folder.

```bash
brew install ffmpeg uv
uv sync
cp .env.example .env        # then paste the ScorePlay and TwelveLabs keys (from the team chat, never commit them)
uv run pipeline smoke       # checks both accounts work: should end with SMOKE OK
```

Download the three small MediaPipe models into `models/` once (see the `models/` note below), then:

```bash
uv run pipeline live --minutes 10 --no-analyze   # watch the live recording, no TwelveLabs calls
uv run pipeline live --minutes 10                # with TwelveLabs; ScorePlay writes are only printed
DRY_RUN=false uv run pipeline live --minutes 10  # the real thing: writes to ScorePlay
uv run pipeline replay --start 4500 --end 6000   # replay both goals from the recorded match: should print CAUGHT twice
uv run pytest -q                                 # 39 quick tests
```

`models/` (not in git): `yamnet.tflite`, `efficientdet_lite0.tflite`, `blaze_face_short_range.tflite`, `pose_landmarker_lite.task`, all from `https://storage.googleapis.com/mediapipe-models/` (audio_classifier/yamnet/float32/1, object_detector/efficientdet_lite0/int8/1, face_detector/blaze_face_short_range/float16/1, pose_landmarker/pose_landmarker_lite/float16/1).

## Where things are

| | |
| --- | --- |
| `rules.yaml` | Every threshold the rules engine uses. Tune here, then re-run `replay`. |
| `pipeline/` | The code, one file per step (feed, signals, rules, analyze, writeback, live...). |
| `docs/PLAN.md` | The plan and what's built. |
| `docs/rules-engine.md` | How the rules engine decides, and what tuning showed. |
| `docs/api-notes.md` | Everything we learned about the ScorePlay and TwelveLabs APIs. |
| `tests/` | The unit tests. |
