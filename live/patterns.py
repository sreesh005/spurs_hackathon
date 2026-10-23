"""Formation / pattern triggers on tracked dots. Pure python, no dependencies.
Engine.step(t, players, ball) -> list of alerts fired at this instant.
players: [{"id", "team": "mnu"|"tot"|"ref", "x", "y"}] in metres (pitch 105 x 68); ball: (x, y) or None.
Everything is expressed in the attacking team's frame: it attacks toward ax = 105."""
import math, collections

L, W = 105.0, 68.0
COOLDOWN = {"overload": 8, "overlap": 8, "linebreak": 8, "counter": 10, "switch": 8, "press": 8}
NAMES = {"overload": "OVERLOAD IN THE BOX", "overlap": "WING OVERLAP", "linebreak": "LINE BREAK", "counter": "COUNTER-ATTACK", "switch": "SWITCH OF PLAY", "press": "PRESSING TRAP"}

class Engine:
    def __init__(self):
        self.hist = collections.defaultdict(lambda: collections.deque(maxlen=60))   # id -> (t, x, y)
        self.ballh = collections.deque(maxlen=120)                                  # (t, x, y)
        self.holder = None; self.holder_t = -9; self.last = {}; self.linehist = collections.deque(maxlen=60)

    def vel(self, pid, t, win=0.8):
        h = self.hist[pid]
        old = next((q for q in h if t - q[0] <= win), None)
        if not old or t - old[0] < 0.3: return 0.0, 0.0
        return (h[-1][1] - old[1]) / (h[-1][0] - old[0]), (h[-1][2] - old[2]) / (h[-1][0] - old[0])

    def step(self, t, players, ball):
        out = []
        for p in players: self.hist[p["id"]].append((t, p["x"], p["y"]))
        if ball: self.ballh.append((t, ball[0], ball[1]))
        field = [p for p in players if p["team"] in ("mnu", "tot")]
        if len(field) < 12: return out
        # possession: nearest player to the ball, held for a moment after the ball leaves them
        if ball:
            near = min(field, key=lambda p: math.hypot(p["x"] - ball[0], p["y"] - ball[1]))
            if math.hypot(near["x"] - ball[0], near["y"] - ball[1]) < 3.5: self.holder, self.holder_t = near, t
        if not self.holder or t - self.holder_t > 1.5 or not ball: return out
        team = self.holder["team"]; att = [p for p in field if p["team"] == team]; dfn = [p for p in field if p["team"] != team]
        if len(att) < 5 or len(dfn) < 5: return out
        d = 1 if sum(p["x"] for p in dfn) / len(dfn) > sum(p["x"] for p in att) / len(att) else -1   # they defend the end their players crowd toward
        A = lambda x: x if d > 0 else L - x; Y = lambda y: y
        bx, by = A(ball[0]), ball[1]
        hx, hy = A(self.holder["x"]), self.holder["y"]
        def fire(name, score, detail, ids, region=None):
            if t - self.last.get(name, -99) < COOLDOWN[name]: return
            self.last[name] = t
            out.append({"pattern": name, "title": NAMES[name], "score": round(score, 2), "detail": detail, "ids": ids, "team": team, "t": round(t, 2), "region": region, "dir": d})
        # 1 overload in / near the box
        if bx > 68:
            inbox = lambda p: A(p["x"]) > 82 and 13.8 < p["y"] < 54.2
            na = [p for p in att if inbox(p)]; nd = [p for p in dfn if inbox(p)]
            if len(na) >= 3 and len(na) - len(nd) >= 2:
                reg = [min(105, 82) if d > 0 else 0, 13.8, 105 if d > 0 else 23, 54.2]
                fire("overload", min(1.0, 0.5 + 0.15 * (len(na) - len(nd))), f"{len(na)} v {len(nd)} in the box", [p["id"] for p in na + nd], reg)
        # 2 wing overlap: carrier wide and closely marked, team-mate running past on the outside
        if (hy < 17 or hy > 51) and hx > 35:
            marked = [p for p in dfn if math.hypot(p["x"] - self.holder["x"], p["y"] - self.holder["y"]) < 3.5]
            if marked:
                for m in att:
                    if m["id"] == self.holder["id"]: continue
                    mx = A(m["x"])
                    vx, vy = self.vel(m["id"], t); vx = vx * d
                    wide = (m["y"] < hy - 1.5) if hy < 17 else (m["y"] > hy + 1.5)
                    if 0 < mx - hx < 14 and vx > 3.0 and abs(m["y"] - hy) < 12 and (wide or abs(m["y"] - hy) < 3):
                        fire("overlap", 0.7, "runner on the outside, carrier marked", [self.holder["id"], m["id"]] + [p["id"] for p in marked]); break
        # 3 line break: ball goes through the defensive line
        outf = sorted([A(p["x"]) for p in dfn])[:-1]               # drop the deepest (keeper)
        if len(outf) >= 5:
            line = sum(sorted(outf, reverse=True)[:4]) / 4; self.linehist.append((t, line))
            past = [q for q in self.linehist if 1.0 <= t - q[0] <= 2.5]
            old = [b for b in self.ballh if 1.0 <= t - b[0] <= 2.5]
            if past and old and A(old[0][1]) < past[0][1] - 1.0 and bx > line + 1.0 and bx > 50:
                behind = len([x for x in outf if x < bx])
                fire("linebreak", min(1.0, 0.5 + 0.1 * behind), f"{behind} defenders now behind the ball", [self.holder["id"]])
        # 4 counter-attack: ball crosses halfway quickly, defenders outnumbered behind it
        old = [b for b in self.ballh if 1.5 <= t - b[0] <= 3.5]
        if old and A(old[0][1]) < 52.5 < bx and (bx - A(old[0][1])) / (t - old[0][0]) > 6.0:
            ahead = [p for p in att if A(p["x"]) > bx - 6]; back = [p for p in dfn if A(p["x"]) > bx and p is not None]
            if len(ahead) >= 3 and len(back) <= 5:
                fire("counter", min(1.0, 0.5 + 0.1 * (len(ahead) - len(back) + 3)), f"{len(ahead)} attackers up, {len(back)} defenders between ball and goal", [p["id"] for p in ahead])
        # 5 switch of play: ball crosses the width quickly
        old = [b for b in self.ballh if 1.0 <= t - b[0] <= 3.2]
        if old:
            o = old[0]
            if abs(by - o[2]) > 30 and ((o[2] < 22 and by > 46) or (o[2] > 46 and by < 22)):
                fire("switch", 0.8, "ball swung from one wing to the other", [self.holder["id"]])
        # 6 pressing trap: carrier surrounded
        close = [p for p in dfn if math.hypot(p["x"] - self.holder["x"], p["y"] - self.holder["y"]) < 6.0]
        vc = [p for p in dfn if math.hypot(p["x"] - self.holder["x"], p["y"] - self.holder["y"]) < 3.5]
        if len(close) >= 3 and len(vc) >= 2:
            fire("press", min(1.0, 0.4 + 0.15 * len(close)), f"{len(close)} defenders closing on the ball carrier", [self.holder["id"]] + [p["id"] for p in close])
        return out
