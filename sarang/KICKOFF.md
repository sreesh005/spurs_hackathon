# First prompt for Claude Code

Paste this after running `claude` inside this folder:

```
Read CLAUDE.md, docs/PLAN.md and docs/api-notes.md.

Then set up the project (uv, the pipeline package, a Typer CLI) and build M0 only.
I will put my keys in .env myself; do not ask me to paste them into chat and never print them.
When M0 is ready, tell me the one command to run and what output means it worked. Stop there.
```

After each milestone is verified, say "M0 verified, go to M1" and so on.

## Before you start

- ffmpeg installed: `brew install ffmpeg`
- uv installed: `brew install uv`
- A tunnel for M4: `brew install cloudflared` (or ngrok)
- Keys: ScorePlay (Settings → API Key), TwelveLabs (dashboard → API Keys)
