#!/usr/bin/env python3
"""Twelve Labs transcript of the demo clip, served to the Next Post UI (port 8767, same place commentary.py used).
   python3 tl_transcript.py --upload demo90.mp4 --serve 8767          # upload the clip, wait for its transcription
   python3 tl_transcript.py --asset <asset_id> --offset 1234 --len 90  # or cut the clip's span out of an existing asset (offset = where the clip starts, seconds)
   Reads TWELVELABS_API_KEY from ~/Downloads/spurs_hackathon/.env (or the environment). The key is never printed."""
import argparse, json, os, re, ssl, sys, time, threading, urllib.request, urllib.error, uuid, mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ap = argparse.ArgumentParser(); ap.add_argument("--upload"); ap.add_argument("--asset"); ap.add_argument("--offset", type=float, default=0.0); ap.add_argument("--len", type=float, default=0.0)
ap.add_argument("--serve", type=int, default=8767); ap.add_argument("--env", default=os.path.expanduser("~/Downloads/spurs_hackathon/.env")); ap.add_argument("--cache", default="clip_transcript.json")
a = ap.parse_args()
KEY = os.environ.get("TWELVELABS_API_KEY", "")
BASE = os.environ.get("TWELVELABS_BASE_URL", "https://api.twelvelabs.io/v1.3").rstrip("/")
if os.path.exists(a.env):
    for line in open(a.env):
        m = re.match(r"\s*(TWELVELABS_API_KEY|TWELVELABS_BASE_URL)\s*=\s*(.*)", line)
        if m:
            v = m.group(2).strip().strip('"\'')
            if m.group(1) == "TWELVELABS_API_KEY" and v: KEY = v
            if m.group(1) == "TWELVELABS_BASE_URL" and v: BASE = v.rstrip("/")
try:
    import certifi; CTX = ssl.create_default_context(cafile=certifi.where())
except Exception: CTX = ssl.create_default_context()

def call(method, path, body=None, headers=None, timeout=120):
    h = {"x-api-key": KEY, "Accept": "application/json"}; h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r: return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8", "replace")[:500]

def upload(path):
    b = uuid.uuid4().hex; name = os.path.basename(path); data = open(path, "rb").read()
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="method"\r\n\r\ndirect\r\n'.encode(),
             f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: {mimetypes.guess_type(name)[0] or "video/mp4"}\r\n\r\n'.encode(), data, f"\r\n--{b}--\r\n".encode()]
    return call("POST", "/assets", b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={b}"}, timeout=600)

SENT = []; STATE = {"ready": False, "note": "starting"}
def load():
    if a.upload:
        print("uploading", a.upload, "…", flush=True); code, r = upload(a.upload)
        if code not in (200, 201): sys.exit(f"upload failed {code}: {r}")
        aid = r.get("_id") or r.get("id"); print("asset", aid, flush=True)
        for _ in range(120):
            code, r = call("GET", f"/assets/{aid}")
            st = (r or {}).get("status") if isinstance(r, dict) else None
            print("  asset status:", st, flush=True)
            if st in ("ready", "failed") or code == 404: break
            time.sleep(4)
    else: aid = a.asset
    for k in range(150):
        code, r = call("GET", f"/assets/{aid}/transcription?include=sentences&include=utterances")
        if code == 200 and isinstance(r, dict):
            st = r.get("status"); print("  transcription:", st, flush=True)
            if st == "ready":
                sents = r.get("sentences") or [{"start": u["start"], "end": u["end"], "value": u["value"]} for u in r.get("utterances", [])]
                out = []
                for s in sents:
                    t0 = float(s["start"]) - a.offset
                    if t0 < -0.5 or (a.len and t0 > a.len): continue
                    out.append({"start": round(max(t0, 0), 2), "end": round(float(s["end"]) - a.offset, 2), "text": str(s["value"]).strip()})
                SENT[:] = out; json.dump(out, open(a.cache, "w")); STATE.update(ready=True, note="ready")
                print(f"{len(out)} sentences. First: {out[0]['text'] if out else '(none)'}", flush=True); return
            if st == "failed": sys.exit(f"transcription failed: {r.get('error')}")
        elif code != 404 or k > 20: print("  transcription:", code, str(r)[:200], flush=True)
        time.sleep(4)
    sys.exit("gave up waiting for the transcription")

class Hd(BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def do_OPTIONS(self): self.send_response(204); self._c(); self.end_headers()
    def _c(self): self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "Content-Type"); self.send_header("Cache-Control", "no-store")
    def do_GET(self):
        if self.path.startswith("/clip_transcript.json"): out = {"ready": STATE["ready"], "sentences": SENT}
        elif self.path.startswith("/transcript.json"): out = {"now": time.time(), "segments": [], "ready": STATE["ready"], "clip": True}
        else: self.send_response(404); self.end_headers(); return
        b = json.dumps(out).encode(); self.send_response(200); self._c(); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
if not KEY: sys.exit("No TWELVELABS_API_KEY found (checked the environment and " + a.env + ")")
if not (a.upload or a.asset):
    if os.path.exists(a.cache): SENT[:] = json.load(open(a.cache)); STATE.update(ready=True)
    else: sys.exit("Give --upload clip.mp4 or --asset ID")
srv = ThreadingHTTPServer(("127.0.0.1", a.serve), Hd); threading.Thread(target=srv.serve_forever, daemon=True).start(); print(f"serving on http://127.0.0.1:{a.serve}/clip_transcript.json", flush=True)
if a.upload or a.asset: load()
while True: time.sleep(3600)
