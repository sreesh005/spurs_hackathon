# Next Post

Producer desk for the Spurs² hackathon. The lineup stays on screen. Click a shirt for that player's reel, or search a highlight such as `goal 13`.

## What is the front end

The UI is the `static/` folder. Open these three files if you are changing what people see.

| File | What it is |
| --- | --- |
| `static/index.html` | The page. Header, search box, and the empty shell the desk draws into. |
| `static/app.js` | The UI behavior. Lineup, tabs, search, player reels, and the buttons that call the API. |
| `static/live.js` | The Live dots tab. The tracker's dots, and the drawer of live clips a Spurs dot opens. |
| `static/styles.css` | The look. Colors, the court, the shirts, and the reel beside the lineup. |

The browser loads the page from `http://127.0.0.1:8765`. That address is served by the backend, but the screen itself is those three files.

## What is not the front end

| File | What it is |
| --- | --- |
| `server.py` | Backend. Starts the site and the API: `/api/library`, `/api/rebuild`, `/api/decide`, `/api/read`. |
| `catalog.py` | Builds the clip library from ScorePlay. No screen in this file. |
| `live_clips.py` | Each player's clips as the auto-clipper captures them, with every angle of a play grouped. Serves `/api/live/*`. |
| `demo/` | Fake tracker, fake auto-clipper, and a demo library, so Live dots runs without keys. |
| `tests/` | Tests for `live_clips.py`: `python -m pytest tests -q`. |
| `sarang/` | The live auto-clipper. It writes the clips the Live dots drawer shows. See `sarang/README.md`. |
| `.env` | Your ScorePlay and TwelveLabs keys. Never commit this. |
| `data/` | Saved library, clip reads, and approvals. Created when you run the app. Never commit this. |
| `requirements.txt` | Python packages the backend needs. |
| The two PDFs | Hackathon reference docs from ScorePlay and TwelveLabs. |

## How to run

From this folder, in PowerShell:

```powershell
python -m pip install -r requirements.txt
```

Create a `.env` file next to `server.py`:

```
SCOREPLAY_API_KEY=your_scoreplay_key
TWELVELABS_API_KEY=your_twelvelabs_key
SCOREPLAY_BASE_URL=https://media.scoreplay.io/v1
TWELVELABS_BASE_URL=https://api.twelvelabs.io/v1.3
```

Start the desk:

```powershell
python -m uvicorn server:app --host 127.0.0.1 --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

The first start pulls the ScorePlay library and writes `data/library.json`. Later starts reuse that file. Leave the terminal open while you use the desk.

## Refresh the clips

When ScorePlay has new media, rebuild and restart:

```powershell
python -c "from catalog import build_library; build_library()"
```

Stop the server with Ctrl+C, then start it again with the uvicorn command above. A change to `catalog.py` needs that restart. A change to `static/` shows up on a hard refresh of the browser.

## Live dots: each player's clips as they happen

The **Live dots** tab shows the tracker's dots on a pitch. Click a Spurs dot and the drawer opens that player's live collection:

- **Captured live tonight.** Every play the auto-clipper (`sarang/`) cut and TwelveLabs tagged him in, newest first. A clip lands seconds after it is analyzed. The dot shows a count and pulses when a new one arrives, and a "Just captured" row under the pitch lists the latest.
- **From ScorePlay.** Until he has a live clip, the drawer falls back to his pre-loaded ScorePlay clips. Once he has one, those stay below as "Also in ScorePlay".
- **Every angle of a play together.** Each play shows one button per angle: the broadcast, its replay, phone uploads, and ScorePlay edits (16:9, 9:16). The line under them says why they were grouped.

How angles are matched (`live_clips.py`, strongest first):

| Match | When |
| --- | --- |
| Same moment | The quick cut and the full cut of one rules-engine moment. The full cut replaces the quick one. |
| Same match time | Two clips from the same video with key moments within a few seconds. |
| Same capture time | A clip whose capture clock (`tc_in`/`tc_out`, same day) overlaps the live clip's wall-clock time. This brings in phone uploads nobody has tagged yet. |
| Broadcast replay | A replay of the same event up to 45 s after the play. |
| Same goal, same player | A ScorePlay library clip of the same goal, save, chance or card with the same player. Weakest match: only used when no clock says the two are different plays, and a library clip joins at most one live play. |

Where the clips come from: the desk reads `sarang/runs/live_*.jsonl` and `sarang/clips/` (what `uv run pipeline live` writes), plus an optional `scoreplay_uploads.jsonl` of ScorePlay media records for phone uploads. To read other folders, set `CLIPPER_DIRS` (separated by `;` on Windows, `:` elsewhere).

### Try it without keys

```powershell
python -m pip install -r requirements.txt
python -m pip install pillow   # optional: draws the moving broadcast picture
python -m demo
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). This starts a fake tracker on 8766, a fake auto-clipper that writes the same files `sarang/` writes, and the desk on a small demo library. You need ffmpeg on PATH for the clips to play. The first play lands about 14 seconds in, and Solanke's goal then collects five angles: broadcast, replay, an untagged phone upload, and two ScorePlay edits. `python -m demo --speed 2` runs the scripted match faster.

### Run it for real

1. Start the tracker: `hack_live_dots.py --serve 8766` on the tracker laptop. If it runs on another machine, open the desk with `?live=http://<that machine>:8766`.
2. Start the auto-clipper from `sarang/`: `uv run pipeline live` (see `sarang/README.md`).
3. Start the desk as above and open the **Live dots** tab. Check the shirt numbers on the dots before kick-off.

Not built yet: polling ScorePlay for new phone uploads during the match. The desk reads them from `scoreplay_uploads.jsonl` (the demo writes it). A poll of ScorePlay's `/media/search` would write the same records.
