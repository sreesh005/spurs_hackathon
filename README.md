# Next Post

Producer desk for the Spurs² hackathon. The lineup stays on screen. Click a shirt for that player's reel, or search a highlight such as `goal 13`.

## What is the front end

The UI is the `static/` folder. Open these three files if you are changing what people see.

| File | What it is |
| --- | --- |
| `static/index.html` | The page. Header, search box, and the empty shell the desk draws into. |
| `static/app.js` | The UI behavior. Lineup, tabs, search, player reels, and the buttons that call the API. |
| `static/styles.css` | The look. Colors, the court, the shirts, and the reel beside the lineup. |

The browser loads the page from `http://127.0.0.1:8765`. That address is served by the backend, but the screen itself is those three files.

## What is not the front end

| File | What it is |
| --- | --- |
| `server.py` | Backend. Starts the site and the API: `/api/library`, `/api/rebuild`, `/api/decide`, `/api/read`. |
| `catalog.py` | Builds the clip library from ScorePlay. No screen in this file. |
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
