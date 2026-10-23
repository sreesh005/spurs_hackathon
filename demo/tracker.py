"""Fake live tracker: stands in for hack_live_dots.py (--serve 8766) when that laptop isn't here.

Same contract the Live dots tab reads (static/live.js):
  GET  /state.json   {ready, cutaway, players:[{id, team: tot|mnu|ref, x, y}], ball:{x,y}|null, alerts:[{title, detail, ids}]}
                     x runs along the pitch (0 = left goal line), y across it, both 0..1
  GET  /video.mjpg   the broadcast with labels on the players (MJPEG; drawn with Pillow when it is installed)
  POST /assign       {labels: {dot_id: "#19"}}: shirt numbers to draw on the video
  GET  /hls/...      the demo's stand-in for ScorePlay's live recording (demo/recording.py)
Dots 1-11 are Tottenham in lineup order, 12-22 Man United, 23 the referee.
"""

from __future__ import annotations

import io
import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from catalog import THFC_SPOTS

from .scenario import CYCLE, PLAYS, Clock, lineup_slot, match_clock, match_offset

PLAY_LEAD = 7.0  # seconds of build-up before a play's key moment
PLAY_HOLD = 4.0  # seconds the ball stays in the net / with the keeper after it


def _spot(index: int) -> tuple[float, float]:
    x, y = THFC_SPOTS[index % len(THFC_SPOTS)]
    return (y - 14) / 72, x / 100  # along the pitch (0 = own goal), across it


def _lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def _ease(k: float) -> float:
    k = min(1.0, max(0.0, k))
    return k * k * (3 - 2 * k)


class Match:
    """Positions of everything at a given sim time. Pure function of time, so every request agrees."""

    def __init__(self, clock: Clock, library: dict):
        self.clock = clock
        self.slots = [lineup_slot(library, p) for p in PLAYS]

    def wander(self, t: float) -> tuple[float, float]:
        return 0.5 + 0.22 * math.sin(0.11 * t) + 0.06 * math.sin(0.5 * t), 0.5 + 0.3 * math.sin(0.17 * t + 1)

    def base(self, team: str, i: int, ball: tuple[float, float], t: float) -> tuple[float, float]:
        along, across = _spot(i)
        x = 0.06 + 0.8 * along
        if team == "mnu":
            x, across = 1 - x, 1 - across
        shift = 0.14 * (ball[0] - 0.5)
        jx = 0.012 * math.sin(0.7 * t + i * 1.7 + (5 if team == "mnu" else 0))
        jy = 0.02 * math.sin(0.5 * t + i * 2.3 + (3 if team == "mnu" else 0))
        if i == 0:  # keepers stay home
            shift *= 0.15
        return min(0.99, max(0.01, x + shift + jx)), min(0.98, max(0.02, across + 0.1 * (ball[1] - 0.5) + jy))

    def current_play(self, t: float):
        cycle_t = t % CYCLE
        for index, play in enumerate(PLAYS):
            if play.at - PLAY_LEAD <= cycle_t <= play.at + PLAY_HOLD:
                return index, play, cycle_t - play.at
        return None

    def state(self) -> dict:
        t = self.clock.sim()
        ball = self.wander(t)
        hot = None
        now_play = self.current_play(t)
        if now_play:
            index, play, rel = now_play
            slot = self.slots[index]
            start = self.wander(t - (rel + PLAY_LEAD))
            carrier = self.base("tot", slot, start, t)
            goal = (0.985, 0.5) if play.toward == "attack" else (0.03, 0.48)
            if play.toward == "defend":
                carrier = (min(carrier[0], 0.2), carrier[1]) if slot == 0 else carrier
            k = (rel + PLAY_LEAD) / PLAY_LEAD
            if k < 0.65:
                ball = (_lerp(start[0], carrier[0], _ease(k / 0.65)), _lerp(start[1], carrier[1], _ease(k / 0.65)))
            elif rel <= 0:
                ball = (_lerp(carrier[0], goal[0], _ease((k - 0.65) / 0.35)), _lerp(carrier[1], goal[1], _ease((k - 0.65) / 0.35)))
            else:
                ball = goal
            hot = (slot, ball, rel)

        players = []
        for i in range(11):
            x, y = self.base("tot", i, ball, t)
            if hot and hot[0] == i:
                pull = 0.85 if hot[2] <= 0 else 0.6
                x, y = _lerp(x, hot[1][0], pull), _lerp(y, hot[1][1] + 0.025, pull)
            players.append({"id": i + 1, "team": "tot", "x": round(x, 4), "y": round(y, 4)})
        for i in range(11):
            x, y = self.base("mnu", i, ball, t)
            players.append({"id": 12 + i, "team": "mnu", "x": round(x, 4), "y": round(y, 4)})
        players.append({"id": 23, "team": "ref", "x": round(min(0.95, max(0.05, ball[0] - 0.08)), 4), "y": round(min(0.95, max(0.05, ball[1] + 0.15)), 4)})

        alerts = []
        cutaway = False
        if now_play:
            index, play, rel = now_play
            if 0 <= rel <= PLAY_HOLD:
                alerts.append({"title": play.event.replace("_", " ").upper(), "detail": f"{play.who} · clip on its way to the desk", "ids": [self.slots[index] + 1]})
        cycle_t = t % CYCLE
        for play in PLAYS:
            if "replay" in play.angles and play.at + 11 <= cycle_t <= play.at + 13.5:
                cutaway = True  # the broadcast cuts to its replay
        return {
            "ready": t > 2.0,
            "cutaway": cutaway,
            "players": players,
            "ball": {"x": round(ball[0], 4), "y": round(ball[1], 4)},
            "alerts": alerts,
            "clock": match_clock(match_offset(t)),
            "sim": round(t, 2),
            "source": "demo tracker",
        }


class Tracker:
    def __init__(self, clock: Clock, library: dict):
        self.match = Match(clock, library)
        self.labels: dict[str, str] = {}
        self.lock = threading.Lock()

    def frame(self) -> bytes | None:
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return None
        st = self.match.state()
        w, h = 640, 360
        img = Image.new("RGB", (w, h), (28, 74, 44))
        draw = ImageDraw.Draw(img)
        ball = st["ball"]
        span = 0.5  # the camera shows half the pitch length and follows the ball
        left = min(1 - span, max(0.0, ball["x"] - span / 2))

        def to_px(x: float, y: float) -> tuple[float, float]:
            # a little perspective: the far touchline is narrower than the near one
            v = 0.12 + 0.82 * y
            scale = 0.78 + 0.22 * y
            u = 0.5 + ((x - left) / span - 0.5) * scale
            return u * w, v * h

        for k in range(10):  # mowing stripes
            x0, x1 = k / 10, (k + 1) / 10
            if k % 2:
                poly = [to_px(x0, 0), to_px(x1, 0), to_px(x1, 1), to_px(x0, 1)]
                draw.polygon(poly, fill=(32, 82, 49))
        line = (205, 222, 205)
        for a, b in [((0, 0), (1, 0)), ((0, 1), (1, 1)), ((0.5, 0), (0.5, 1)), ((0, 0), (0, 1)), ((1, 0), (1, 1)),
                     ((0, 0.2), (0.157, 0.2)), ((0.157, 0.2), (0.157, 0.8)), ((0, 0.8), (0.157, 0.8)),
                     ((1, 0.2), (0.843, 0.2)), ((0.843, 0.2), (0.843, 0.8)), ((1, 0.8), (0.843, 0.8))]:
            draw.line([to_px(*a), to_px(*b)], fill=line, width=2)
        with self.lock:
            labels = dict(self.labels)
        for p in sorted(st["players"], key=lambda q: q["y"]):
            px, py = to_px(p["x"], p["y"])
            r = 5 + 5 * p["y"]
            color = {"tot": (238, 238, 245), "mnu": (215, 45, 45), "ref": (230, 205, 50)}[p["team"]]
            draw.ellipse([px - r, py - 2.2 * r, px + r, py], fill=color, outline=(15, 15, 15))
            if p["team"] == "tot" and labels.get(str(p["id"])):
                text = labels[str(p["id"])]
                draw.rectangle([px - 14, py - 2.2 * r - 16, px + 14, py - 2.2 * r - 2], fill=(40, 120, 215))
                draw.text((px - 11, py - 2.2 * r - 15), text, fill=(255, 255, 255))
        bx, by = to_px(ball["x"], ball["y"])
        draw.ellipse([bx - 4, by - 4, bx + 4, by + 4], fill=(255, 255, 255), outline=(255, 120, 0))
        draw.rectangle([12, 12, 196, 38], fill=(10, 10, 10))
        draw.text((20, 18), f"MNU 1 - 1 TOT   {st['clock']}", fill=(255, 255, 255))
        draw.rectangle([w - 132, 12, w - 12, 34], fill=(255, 159, 28))
        draw.text((w - 124, 17), "SIMULATED FEED", fill=(20, 20, 8))
        if st["cutaway"]:
            draw.rectangle([0, 0, w, h], fill=(20, 22, 38))
            draw.text((w / 2 - 70, h / 2 - 8), "BROADCAST REPLAY", fill=(255, 209, 102))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return buf.getvalue()


PLACEHOLDER_SVG = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 640 360'><rect width='640' height='360' fill='#1c4a2c'/>
<text x='320' y='170' fill='#f4f1e8' font-family='sans-serif' font-size='26' text-anchor='middle'>Simulated broadcast</text>
<text x='320' y='205' fill='#9dbe86' font-family='sans-serif' font-size='15' text-anchor='middle'>pip install pillow to draw the moving feed</text></svg>"""


def make_handler(tracker: Tracker):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_POST(self):
            if self.path.split("?")[0] != "/assign":
                self.send_error(404)
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                with tracker.lock:
                    tracker.labels = {str(k): str(v)[:6] for k, v in (body.get("labels") or {}).items()}
            except ValueError:
                self.send_error(400)
                return
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/state.json":
                data = json.dumps(tracker.match.state()).encode()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path.startswith("/hls/"):
                from .recording import HLS_DIR

                name = path[len("/hls/"):]
                target = HLS_DIR / name
                if "/" in name or not name or not target.is_file():
                    self.send_error(404)
                    return
                data = target.read_bytes()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp2t")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/video.mjpg":
                first = tracker.frame()
                if first is None:
                    self.send_response(200)
                    self._cors()
                    self.send_header("Content-Type", "image/svg+xml")
                    self.end_headers()
                    self.wfile.write(PLACEHOLDER_SVG)
                    return
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    jpg = first
                    while True:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                        time.sleep(1 / 8)
                        jpg = tracker.frame()
                except (BrokenPipeError, ConnectionResetError):
                    return
            self.send_error(404)

    return Handler


def serve(tracker: Tracker, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(tracker))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="demo-tracker", daemon=True).start()
    return server
