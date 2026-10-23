"""M2: send a clip to TwelveLabs Pegasus and get structured JSON back.

Analyze creates nothing in either account, so it runs even with DRY_RUN on
(it does spend TwelveLabs credits).
"""

import base64
import json
import time
from pathlib import Path

from . import clients, config, prompts, scoreplay_data

RUNS_DIR = config.ROOT / "runs"
MAX_BASE64_BYTES = 30 * 1024 * 1024
MODEL = "pegasus1.6"


def call(mp4: Path, prompt: str, schema: dict, max_tokens: int = 1024) -> dict:
    """One sync Pegasus call on a local clip, sent inline. Returns the raw response."""
    b64 = base64.b64encode(mp4.read_bytes()).decode()
    if len(b64) > MAX_BASE64_BYTES:
        raise ValueError(f"{mp4.name} is {len(b64) / 1e6:.1f} MB as base64, over the 30 MB limit; cut a shorter clip")
    body = {
        "model_name": MODEL,
        "stream": False,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "video": {"type": "base64_string", "base64_string": b64},
        "prompt": prompt,
        "response_format": {"type": "json_schema", "json_schema": schema},
    }
    r = clients.twelvelabs(config.load()).http.post("/analyze", json=body, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"analyze -> HTTP {r.status_code}: {r.text[:500]}")
    res = r.json()
    if res.get("finish_reason") != "stop":
        raise RuntimeError(f"analyze stopped early ({res.get('finish_reason')}): {str(res.get('data'))[:300]}")
    return res


def analyze(mp4: Path, context: str | None = None) -> dict:
    """Analyze one clip with the football prompt; save and return runs/<id>.analysis.json.
    `context`: what happened just before (e.g. the previous clip's caption)."""
    squad = [p["name"] for p in scoreplay_data.squad()]
    prompt = prompts.build(squad)
    if context:
        prompt += f"\n\nFor context, just before this clip: {context}"
    t0 = time.time()
    res = call(mp4, prompt, prompts.SCHEMA)

    clip_meta_path = mp4.with_suffix(".json")
    run = {
        "clip_id": mp4.stem,
        "clip_file": str(mp4.relative_to(config.ROOT)) if mp4.is_relative_to(config.ROOT) else str(mp4),
        "clip": json.loads(clip_meta_path.read_text()) if clip_meta_path.exists() else None,
        "model": MODEL,
        "prompt_version": prompts.VERSION,
        "analysis_id": res.get("id"),
        "seconds": round(time.time() - t0, 1),
        "usage": res.get("usage"),
        "analysis": json.loads(res["data"]),
    }
    RUNS_DIR.mkdir(exist_ok=True)
    (RUNS_DIR / f"{mp4.stem}.analysis.json").write_text(json.dumps(run, indent=2, ensure_ascii=False))
    return run
