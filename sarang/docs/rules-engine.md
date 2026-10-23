# Clip rules engine (draft)

Drafted Oct 22 2026 from the team's answers. Status: built and running (scaffold), see "Results so far".

Code: `pipeline/signals.py` (loudness, z-scores), `pipeline/mp_signals.py` (MediaPipe), `pipeline/rules.py` (state machine), `pipeline/replay.py`, `pipeline/live.py`, thresholds in `rules.yaml`.

## Results so far (Oct 22, late)

- Both known goals are caught on replay: Man Utd 1-0 (clip 4654-4694, score 0.65) and Spurs 1-1 (clip 5814-5854, score 0.94, the only one where the silence rule fired: Old Trafford went quiet as Spurs attacked, then the away end and commentators erupted).
- First half, offsets 600-1800: 12 clips in 20 minutes, about one every 1.7 minutes. Not yet checked by eye.
- Live on the feed: keeps pace (95 segments in 3 minutes, MediaPipe on).
- What the data showed while tuning:
  - Broadcast audio is compressed. A goal only reaches loud_z ~1.5-2, but stays up for 10s or more, so a "sustained" signal (share of the last 8s with loud_z ≥ 1) carries most of the weight.
  - YAMNet hears the commentary as "Speech" ~0.9 almost all the time and a crowd roar mostly as noise classes, so the cheer score is weak and is read against its own baseline.
  - Silence counts whenever it happens, not only while watching: the Spurs build-up had expired 10s before the hush.
  - The wide-to-close-up switch is reliable on both goals.
- Raised arms (MediaPipe pose, close-ups only, Oct 23): fires in 2 of 8 celebration close-ups on the Spurs equalizer, never in wide play. Pose finds nobody in wide shots, so it is a confirming signal, not a trigger.
- Watching ScorePlay's own live recording (Oct 23): works, about 7-9s behind the organizer feed; a 6-minute run cut 2 moments and the safety net found 9 events (most fouls and tackles, hence `clip_event_types`).
- Not built: re-tagging a quick clip as superseded, SQLite state.

## Job

Decide, from cheap local signals, **when** a moment starts and ends and **when** to send it on. TwelveLabs then says **what** happened and **who** was involved (the sport-specific, probabilistic part). The engine knows nothing about football. It reads sound, camera shots and people.

The team's choices:

| Question | Answer |
| --- | --- |
| Bias when unsure | Catch more; the creator filters. TwelveLabs marks weak clips. |
| Moments that clip | Goals and big chances, set pieces, emotion and reactions |
| Bench and substitutions | Left out entirely |
| Home crowd goes quiet after a build-up | A trigger (likely an away goal or a home miss) |
| Clip shape | Play + reaction, 20 to 40s |
| Timing | Both: a quick tight clip at the peak, then a full clip when the reaction ends |
| Tuning | Thresholds in an editable file (`rules.yaml`) plus a replay command |
| Safety net | Yes: every 5 minutes, TwelveLabs checks the last 5 minutes for anything the rules missed (can be switched off) |

## Signals, per 2s feed segment

All local, all faster than real time on a laptop. Video is sampled at 4 frames per second.

| Signal | What it measures | Tool |
| --- | --- | --- |
| `loud_z` | Loudness vs the last 60s (how many standard deviations above normal) | ffmpeg `ebur128` |
| `cheer` | Probability of cheering, crowd, applause, shouting | MediaPipe audio classifier (YAMNet classes) |
| `whistle` | Probability of a referee's whistle | MediaPipe audio classifier |
| `voice_z` | Commentary energy: loudness in the speech band (300-3000 Hz) vs the last 60s | ffmpeg band-pass + `ebur128` |
| `drop` | How far loudness fell: highest `loud_z` in the previous 6s minus now | derived |
| `shot` | `wide`, `medium`, `closeup` or `crowd` | MediaPipe person + face detectors, plus share of green pitch pixels |
| `people` | Number of people in frame, and their median size | MediaPipe object detector (person) |
| `cut` | A camera cut happened in this segment; `cuts_10s` = cuts in the last 10s | frame difference (or ffmpeg scene score) |
| `still` | How little the people in a wide shot are moving (0 to 1) | frame difference inside person boxes |
| `arms_up` | Someone in a close-up has their wrists above their shoulders | MediaPipe pose |

How `shot` is decided: `wide` = at least 8 people, all small, mostly green; `closeup` = one large face or at most 2 large people; `crowd` = many small faces and little green; anything else is `medium`.

Rough edges: `voice_z` can't fully separate the commentators from the crowd, and small players in wide shots are hard to detect. Both are why the rules combine several signals rather than trusting one.

## States

```
CALM ──arm──► WATCHING ──trigger──► TRIGGERED ──► CLOSING ──end──► COOLDOWN ──20s──► CALM
  ▲               │ no trigger in 15s                 │
  └───────────────┘                                   └─ quick clip sent at the trigger
CALM ──trigger──► TRIGGERED   (a moment can trigger without a build-up)
```

### Arm (CALM → WATCHING): something may be about to happen

Any one of:

- **A1 Build-up:** `loud_z` rises by at least 1.0 from one 2s segment to the next while `shot` is `wide` (or unknown). Tuned this way on replay.
- **A2 Set piece:** a `whistle` above 0.5, then within 10s a `wide` shot with `people` ≥ 10 and `still` ≥ 0.7 for at least 4s (a wall or players gathered in the box).
- **A3 Commentary rise:** `voice_z` ≥ 1.5 for 2s.

On arm: mark the clip start at the last camera cut into the current wide shot, at most 20s back. If nothing triggers within 15s, drop the mark and return to CALM.

### Trigger (→ TRIGGERED): something happened

A weighted score, so several weak signals can add up. The bias is catch-more, so the bar is low:

```
score = 0.35·norm(loud_z, 1→3) + 0.25·cheer + 0.20·norm(voice_z, 1→3)
      + 0.20·silence + 0.15·reaction + 0.10·armed
trigger when score ≥ 0.45 for 2 segments in a row
```

- `silence` = 1 when WATCHING and `drop` ≥ 2.0 within 4s (the home crowd falling quiet after a build-up), otherwise 0.
- `reaction` = 1 when the picture switches from `wide` to `closeup` within 6s and either `arms_up`, `cheer` ≥ 0.4 or `loud_z` ≥ 1.0. A large "face" only counts as a close-up off the pitch (green < 0.45): the face detector finds false faces on grass.
- `armed` = 1 when already WATCHING.

On trigger:

1. Note the peak time (the segment with the highest score).
2. **Quick clip:** peak − 8s to peak + 4s (about 12s). Send it to TwelveLabs and then to ScorePlay tagged `cut:quick`.

### Close (CLOSING → done): the reaction is over

The first of these:

- The picture is back on a `wide` shot for 4s with `loud_z` below 0.5 (play has restarted).
- `cuts_10s` falls back to normal after the replays.
- 40s have passed since the clip start (hard cap).

Then the **full clip** runs from the start mark to the close, kept between 20s and 40s. Send it to TwelveLabs and then to ScorePlay tagged `cut:full`. It replaces the quick clip: the quick one is retagged `superseded`.

### Cooldown and dedupe

For 20s after a close, new triggers are ignored, so one play never makes two clips. Football plays run longer than the 2s dedupe window in the TwelveLabs post.

## What TwelveLabs decides

For each clip the engine sends, Pegasus returns the event type, team, players, caption, key moment and `is_highlight` (the `football-v2` schema).

- `substitution` or `none` → nothing written. Bench moments are out of scope.
- Everything else is written, including weak results, because the bias is catch-more. The clip carries `confidence:<0-1>` and `excitement:<engine score>` tags so the creator can sort by them and skip the weak ones.
- The engine's own score never overrides TwelveLabs on what happened.

## The rules file

Every threshold lives in `rules.yaml` so the team can tune without touching code. Draft:

```yaml
baseline_seconds: 60
frames_per_second: 4

shot:
  wide_min_people: 8
  closeup_face_share: 0.05      # face covers 5% of the frame
  crowd_max_green: 0.15

arm:
  buildup_loud_rise: 1.0        # loud_z rise over 4s, wide shot
  setpiece_whistle: 0.5
  setpiece_min_people: 10
  setpiece_still: 0.7
  setpiece_hold_seconds: 4
  voice_rise: 1.5
  max_lookback_seconds: 20
  expire_seconds: 15

trigger:
  threshold: 0.45
  consecutive_segments: 2
  weights: {loud: 0.35, cheer: 0.25, voice: 0.20, silence: 0.20, reaction: 0.15, armed: 0.10}
  silence_drop: 2.0
  reaction_window_seconds: 6

clip:
  quick_before: 8
  quick_after: 4
  full_min: 20
  full_max: 40
  cooldown_seconds: 20

skip_event_types: [substitution, none]
```

## Checking a change

`uv run pipeline rules replay --from 4500 --to 6000` runs the engine over the recorded match faster than real time and prints every arm, trigger and close with its signals, without calling TwelveLabs. The two known goals (offsets ~4671 and ~5824) must trigger. Every other trigger gets a quick look by eye, and the count goes in the commit message so threshold changes stay honest.

## Safety net (decided: include, switchable)

The engine only sends what it notices, so a quiet moment that trips no rule would never reach TwelveLabs. As a backup:

- Every 5 minutes, send the last 5 minutes of feed to TwelveLabs in one call that lists every clip-worthy event with its time (the approach in the TwelveLabs sports post).
- For each event, check whether the engine already made a clip within 20s of that time. If it did, skip it. If not, cut a full clip (20 to 40s around the event) from the recording and send it on like any other, tagged `found_by:sweep`.
- The recording has to keep the last 6 minutes for this (the engine alone needs 90s).
- Cost: about 21 extra calls per match. Moments found this way arrive a few minutes late, not within 2 minutes.
- A count of sweep finds vs engine finds shows where the rules are weak and need tuning.

In `rules.yaml`:

```yaml
safety_net:
  enabled: true
  every_seconds: 300
  window_seconds: 300
  match_within_seconds: 20
```
