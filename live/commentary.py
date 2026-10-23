#!/usr/bin/env python3
"""Live announcer transcript for the Next Post UI.
   python3 commentary.py --src "<hls url>" --serve 8767
   Reads the audio of the same stream, transcribes it every few seconds (faster-whisper, on this computer),
   and serves /transcript.json for the Live dots tab.  --demo makes fake commentary so you can test the page."""
import argparse, json, subprocess, threading, time, sys, re, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ap = argparse.ArgumentParser()
ap.add_argument("--src", default=""); ap.add_argument("--serve", type=int, default=8767)
ap.add_argument("--model", default="small.en"); ap.add_argument("--chunk", type=float, default=6.0)
ap.add_argument("--lib", default="http://127.0.0.1:8765/api/library"); ap.add_argument("--demo", action="store_true")
ap.add_argument("--realtime", action="store_true", help="pass -re to ffmpeg (use for a file or a replay that would otherwise run fast)")
a = ap.parse_args()
SEG = []; LOCK = threading.Lock()

def add(text, t=None):
    text = re.sub(r"\s+", " ", text).strip()
    if not text: return
    with LOCK: SEG.append({"id": len(SEG) + 1, "t": t or time.time(), "text": text})
    print("  >", text, flush=True)

class Hd(BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def do_OPTIONS(self): self.send_response(204); self._c(); self.end_headers()
    def _c(self): self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "Content-Type"); self.send_header("Cache-Control", "no-store")
    def do_GET(self):
        if self.path.startswith("/transcript.json"):
            m = re.search(r"after=(\d+)", self.path); after = int(m.group(1)) if m else 0
            with LOCK: out = [s for s in SEG if s["id"] > after][-60:]
            b = json.dumps({"now": time.time(), "segments": out, "ready": READY[0]}).encode()
            self.send_response(200); self._c(); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
        else: self.send_response(404); self.end_headers()
READY = [False]
srv = ThreadingHTTPServer(("127.0.0.1", a.serve), Hd); threading.Thread(target=srv.serve_forever, daemon=True).start()
print(f"transcript on http://127.0.0.1:{a.serve}/transcript.json", flush=True)

if a.demo:
    READY[0] = True
    L = ["Tonali picks it up in the middle of the park, looks for the run.", "Gallagher on the left, he's been busy tonight.", "Oh, that is a lovely ball over the top for Son.",
         "Romero steps in, a big clearance, Spurs under pressure here.", "Van de Ven wins the header and it falls to Maddison.", "Johnson drives at the full back, cuts inside, shot, saved!"]
    i = 0
    while True:
        add(L[i % len(L)]); i += 1; time.sleep(7)

# names to bias the recogniser toward
names = []
try:
    lib = json.load(urllib.request.urlopen(a.lib, timeout=5))
    for c in lib.get("clubs", []):
        if c.get("id") == "thfc":
            for p in (c.get("lineup") or []) + (c.get("bench") or []): names.append(p.get("name") or p.get("short"))
except Exception as e: print("could not read the roster from", a.lib, "-", e)
prompt = "Football commentary, Manchester United against Tottenham Hotspur. Players: " + ", ".join(n for n in names if n) + "."
print("prompt:", prompt[:200], flush=True)
from faster_whisper import WhisperModel
model = WhisperModel(a.model, device="cpu", compute_type="int8")
cmd = ["ffmpeg", "-loglevel", "error"] + (["-re"] if a.realtime else []) + ["-i", a.src, "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
import numpy as np
n = int(16000 * 2 * a.chunk); READY[0] = True; print("listening…", flush=True)
while True:
    buf = p.stdout.read(n)
    if not buf or len(buf) < 3200: print("audio ended"); break
    t_end = time.time(); x = np.frombuffer(buf, np.int16).astype(np.float32) / 32768
    segs, _ = model.transcribe(x, language="en", initial_prompt=prompt, vad_filter=True, condition_on_previous_text=False, beam_size=1)
    add(" ".join(s.text for s in segs), t_end)
