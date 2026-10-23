#!/usr/bin/env python3
"""LIVE DOT MAP (Kits & Cartoons overlay on cutaways). Run on your Mac.

    cd ~/Downloads/hack_data/kids && source ../venv/bin/activate
    python3 hack_live_kids.py --src ../live_rec.mp4 --model yolov8s.pt --imgsz 960          # recorded feed played in real time
    python3 hack_live_kids.py --model yolov8s.pt --imgsz 960                                  # the live HLS feed

What you see (everything about 3 seconds behind the feed, so passes can be drawn with a proper arc):
  left  : the broadcast with player boxes          right : the same moment as a cartoon pitch (kit colours come from the real shirts)
  When the broadcast leaves the main camera (close-ups, replays, crowd shots) the cartoon pauses and a "Kits & Cartoons"
  card asks the kids and their dads a question about what just happened.  No clicking: the pitch is calibrated automatically.
Keys: q quit   n next question   d debug line
"""
import json, os, sys, time, argparse, threading, subprocess, collections, math
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autocalib as A
import patterns as PT

FEED = "https://aoitcvzxerocd4mckn7hcis7eu0iivfh.lambda-url.us-east-1.on.aws/live.m3u8"
W, H = 1280, 720
ap = argparse.ArgumentParser()
ap.add_argument("--src", default=FEED); ap.add_argument("--model", default="yolov8s.pt"); ap.add_argument("--imgsz", type=int, default=960)
ap.add_argument("--device", default=""); ap.add_argument("--delay", type=float, default=5.0)
ap.add_argument("--serve", type=int, default=0); ap.add_argument("--testalert", action="store_true"); ap.add_argument("--loop", action="store_true"); ap.add_argument("--hgate", type=float, default=0.3); ap.add_argument("--noshow", action="store_true"); ap.add_argument("--out", default=""); ap.add_argument("--seconds", type=float, default=0)
a = ap.parse_args()
from ultralytics import YOLO
import torch
dev = a.device or ("mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu"))
model = YOLO(a.model); MODEL_LOCK = threading.Lock(); print("device:", dev)
T0 = time.time(); STOP = False
now = lambda: time.time() - T0
clamp = lambda v, lo, hi: max(lo, min(hi, v))
lerp = lambda p, q, t: p + (q - p) * t

# ============================ video source ============================
def frames():
    if not a.src.startswith("http"):                      # saved file: real-time pacing
        cap = cv2.VideoCapture(a.src); dt = 1.0 / (cap.get(cv2.CAP_PROP_FPS) or 25); tn = time.time(); i = 0
        while not STOP:
            ok, f = cap.read()
            if not ok:
                if a.loop: cap.set(cv2.CAP_PROP_POS_FRAMES, 0); ok, f = cap.read()
                if not ok: return
            n = time.time()
            if n < tn: time.sleep(tn - n)
            tn = max(tn, n) + dt; yield i, cv2.resize(f, (W, H)) if f.shape[1] != W else f; i += 1
        return
    box = {"i": -1, "f": None, "dead": False}; Q = collections.deque(maxlen=300)
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", a.src, "-vf", f"fps=25,scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, bufsize=W * H * 3 * 4)
    def rd():
        n = W * H * 3
        while True:
            b = p.stdout.read(n)
            if len(b) < n: box["dead"] = True; return
            box["i"] += 1; Q.append((box["i"], np.frombuffer(b, np.uint8).reshape(H, W, 3).copy()))      # every frame, in order: nothing is dropped before display
    threading.Thread(target=rd, daemon=True).start()
    while not STOP and not (box["dead"] and not Q):
        if Q: yield Q.popleft()
        else: time.sleep(0.003)

# ============================ camera: automatic calibration + per-frame tracking ============================
LOCK = threading.Lock()
CAM = {"Hp": None, "state": "NONE", "inl": 0, "refs": [], "since_key": 0, "hist": collections.OrderedDict(), "cal_tries": 0, "cal_ok": 0}
PREV = {"g": None}; INC = collections.OrderedDict(); sift = cv2.SIFT_create(nfeatures=900); bf = cv2.BFMatcher(cv2.NORM_L2)
small_gray = lambda f: cv2.cvtColor(cv2.resize(f, (640, 360)), cv2.COLOR_BGR2GRAY)

def to_pitch(Hp, x, y):
    v = Hp @ np.array([x, y, 1.0]); return v[0] / v[2], v[1] / v[2]
def plausible(Hp):
    try: cx, cy = to_pitch(Hp, 640, 500); return -25 < cx < 130 and -20 < cy < 90
    except Exception: return False
def feats(f, boxes):
    g = small_gray(f); m = np.full((360, 640), 255, np.uint8); m[0:52, 0:220] = 0
    for x1, y1, x2, y2 in boxes: m[max(0, y1 // 2 - 4):max(0, y2 // 2 + 4), max(0, x1 // 2 - 4):max(0, x2 // 2 + 4)] = 0
    kp, des = sift.detectAndCompute(g, m)
    return (np.float32([k.pt for k in kp]) * 2 if kp else np.zeros((0, 2), np.float32)), des
def match(A_, B_):
    if A_[1] is None or B_[1] is None or len(A_[0]) < 20 or len(B_[0]) < 20: return None, 0
    good = [p[0] for p in bf.knnMatch(A_[1], B_[1], k=2) if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < 20: return None, 0
    src = A_[0][[g.queryIdx for g in good]]; dst = B_[0][[g.trainIdx for g in good]]
    Hm, mk = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    return (None, 0) if Hm is None else (Hm, int(mk.sum()))
def chain(pg, g, boxes):
    h0 = cv2.calcHist([pg], [0], None, [32], [0, 256]); h1 = cv2.calcHist([g], [0], None, [32], [0, 256])
    if cv2.compareHist(h0, h1, cv2.HISTCMP_CORREL) < 0.7: return None, 0
    m = np.full((360, 640), 255, np.uint8); m[0:52, 0:220] = 0
    for x1, y1, x2, y2 in boxes: m[max(0, y1 // 2 - 4):max(0, y2 // 2 + 4), max(0, x1 // 2 - 4):max(0, x2 // 2 + 4)] = 0
    p0 = cv2.goodFeaturesToTrack(pg, 300, 0.01, 8, mask=m)
    if p0 is None or len(p0) < 25: return None, 0
    p1, st, _ = cv2.calcOpticalFlowPyrLK(pg, g, p0, None, winSize=(21, 21), maxLevel=3); st = st.ravel() == 1
    if st.sum() < 25: return None, 0
    Hm, mk = cv2.findHomography(p0[st] * 2, p1[st] * 2, cv2.RANSAC, 3.0)
    if Hm is None or mk.sum() < 25 or mk.sum() < 0.5 * st.sum(): return None, 0
    return Hm, int(mk.sum())
def track_step(f, i, boxes):
    g = small_gray(f); pg = PREV["g"]; PREV["g"] = g
    if pg is None: return
    Hm, n = chain(pg, g, boxes); INC[i] = Hm if n >= 25 else None
    while len(INC) > 1500: INC.popitem(last=False)
    if CAM["Hp"] is None or CAM["state"] != "OK": return
    with LOCK:
        new = CAM["Hp"] @ np.linalg.inv(Hm) if Hm is not None else None
        if new is not None and plausible(new):
            CAM["Hp"] = new; CAM["inl"] = n; CAM["hist"][i] = new
            while len(CAM["hist"]) > 400: CAM["hist"].popitem(last=False)
        else: CAM["state"] = "LOST"; CAM["inl"] = 0
def refine_cam(f, boxes, i):
    if CAM["Hp"] is None: return
    cur = feats(f, boxes); was_ok = CAM["state"] == "OK"; best = None
    for rf, Hr in (CAM["refs"][-6:] if was_ok else CAM["refs"][::-1]):
        H2, n2 = match(rf, cur)
        if H2 is not None and n2 >= (60 if was_ok else 40) and (best is None or n2 > best[0]): best = (n2, Hr @ np.linalg.inv(H2))
    with LOCK:
        if best and plausible(best[1]):
            if was_ok and CAM["state"] == "OK" and i in CAM["hist"]:
                p, q = to_pitch(CAM["hist"][i], 640, 500), to_pitch(best[1], 640, 500)
                if np.hypot(p[0] - q[0], p[1] - q[1]) < 8: CAM["Hp"] = best[1] @ np.linalg.inv(CAM["hist"][i]) @ CAM["Hp"]; CAM["hist"][i] = best[1]; CAM["inl"] = best[0]
            elif not was_ok: CAM["Hp"] = best[1]; CAM["state"] = "OK"; CAM["hist"][i] = best[1]; CAM["inl"] = best[0]; PREV["g"] = small_gray(f)
        if CAM["state"] == "OK":
            CAM["since_key"] += 1
            if CAM["since_key"] >= 8: CAM["refs"].append((cur, CAM["hist"].get(i, CAM["Hp"]))); CAM["refs"] = CAM["refs"][:1] + CAM["refs"][-23:]; CAM["since_key"] = 0
def grass_share(f):
    hsv = cv2.cvtColor(f[int(H * 0.35):], cv2.COLOR_BGR2HSV); return float(((hsv[..., 0] > 30) & (hsv[..., 0] < 85) & (hsv[..., 1] > 55) & (hsv[..., 2] > 40)).mean())
def height_ok(frame, P, params, boxes):
    th, ph, ro, fx = params; Pm = np.array([[fx, 0, 960], [0, fx, 540], [0, 0, 1.0]]) @ A.rot(th, ph, ro) @ np.c_[np.eye(3), -A.C]; errs = []
    for x1, y1, x2, y2 in boxes:
        h = y2 - y1
        if h < 14 or h > 260: continue
        pp = P @ np.array([(x1 + x2) / 2, y2, 1.0]); x, y = pp[0] / pp[2], pp[1] / pp[2]
        if not (-5 < x < 110 and -5 < y < 75): errs.append(1.0); continue
        a_ = Pm @ np.array([x, y, 0, 1.0]); b_ = Pm @ np.array([x, y, -1.8, 1.0])
        if a_[2] <= 0 or b_[2] <= 0: continue
        errs.append(abs(math.log(max(h, 1) / max(abs(a_[1] / a_[2] - b_[1] / b_[2]) * (frame.shape[0] / 1080), 1))))
    return float(np.median(errs)) if len(errs) >= 6 else None
FAILS = [0]
SHARED = {"f": None, "i": -1, "t": 0.0}

def calib_worker():
    """no clicking: whenever there is no calibration, look at the newest frame, find pan/tilt/zoom, and sanity-check with player heights"""
    last_try = 0
    while not STOP:
        time.sleep(0.2)
        if CAM["state"] == "OK" or SHARED["f"] is None or time.time() - last_try < 2.0: continue
        def attempt():
            f = SHARED["f"].copy(); i = SHARED["i"]
            if grass_share(f) < 0.45: return
            last_try = time.time(); CAM["cal_tries"] += 1
            _t=time.time(); res = A.calibrate(f); print('calib', round(time.time()-_t,1),'s', None if res is None else round(res[2]['score'],2), flush=True)
            if res is None: return
            P, params, q = res
            if q["score"] > 12: return
            with MODEL_LOCK: r = model.predict(f, imgsz=a.imgsz, conf=0.3, classes=[0], device=dev, verbose=False)[0]
            boxes = [tuple(map(int, b)) for b in r.boxes.xyxy.cpu().numpy()] if r.boxes is not None else []
            med = height_ok(f, P, params, boxes); FAILS[0] = FAILS[0] + 1 if (med is None or med >= a.hgate) else 0
            print(f'height check: error {None if med is None else round(med, 2)} (limit {a.hgate}), boxes {len(boxes)}, fit {round(q["score"], 1)}', flush=True)
            if med is None or (med >= a.hgate and not (FAILS[0] >= 3 and q["score"] < 8 and med < 0.5)): return    # three consistent good fits in a row are accepted even if players look slightly off
            ft = feats(f, boxes)
            # the calibration took seconds: bring it forward to the NEWEST frame by feature matching (fails if the camera has cut away meanwhile)
            nf = SHARED["f"].copy(); ni = SHARED["i"]; Hn = None
            Hc = P; okc = True
            for j in range(i + 1, ni + 1):
                Hm_ = INC.get(j)
                if Hm_ is None: okc = False; break
                Hc = Hc @ np.linalg.inv(Hm_)
            n2 = 0
            if okc and plausible(Hc): Hn = Hc; n2 = 99
            else:
                H2, n2 = match(ft, feats(nf, boxes))
                if H2 is not None and n2 >= 30 and grass_share(nf) > 0.4: Hn = P @ np.linalg.inv(H2)
            print('forward match', n2, flush=True)
            with LOCK:
                if CAM["state"] == "OK": return
                CAM["refs"] = [(ft, P)] + CAM["refs"][-10:]; CAM["cal_ok"] += 1
                if Hn is not None and plausible(Hn):
                    CAM["Hp"] = Hn; CAM["hist"][ni] = Hn; CAM["state"] = "OK"; CAM["inl"] = n2; PREV["g"] = small_gray(nf)
                else: CAM["Hp"] = P; CAM["state"] = "LOST"
        try: attempt()
        finally: CAM['cal_done'] = CAM.get('cal_done', 0) + 1

# ============================ detection, teams, timeline ============================
samples = collections.deque(maxlen=1200); cents = None; granks = None; tcol = collections.defaultdict(lambda: collections.deque(maxlen=25))
UNITED = (45, 45, 215); SPURS = (215, 120, 40); TEAMCOL = {0: (60, 60, 220), 1: (170, 100, 60)}; TEAMREF = {0: None, 1: None}; VOTES = collections.defaultdict(collections.Counter)
DET = collections.deque(maxlen=2500); PIDX = collections.defaultdict(lambda: collections.deque(maxlen=600)); DLOCK = threading.Lock()
BALLLAST = {"p": None}; ALIAS = {}; LASTSEEN = {}                                           # raw track id -> canonical id; canonical id -> (t, x, y, lab)
STATS = {"dfps": 0.0, "td": 0.0, "balls": 0, "bwin": 0}

def kmeans(X, k=4, it=20):
    rng = np.random.default_rng(0); C = X[rng.choice(len(X), k, replace=False)].astype(np.float32)
    for _ in range(it):
        L = np.argmin(((X[:, None] - C[None]) ** 2).sum(-1), 1)
        for j in range(k):
            if (L == j).any(): C[j] = X[L == j].mean(0)
    return C, np.bincount(L, minlength=k)
def canon(raw, lab, t, x, y):
    if raw in ALIAS: return ALIAS[raw]
    best = None
    for cid, (tl, xl, yl, ll) in LASTSEEN.items():
        gap = t - tl
        if ll != lab or gap < 0.12 or gap > 2.0: continue
        d = math.hypot(x - xl, y - yl)
        if d < 3 + 4 * gap and (best is None or d < best[0]): best = (d, cid)
    ALIAS[raw] = best[1] if best else raw; return ALIAS[raw]

def detect(f, i, t):
    global cents, granks
    grass = cv2.inRange(cv2.cvtColor(f, cv2.COLOR_BGR2HSV), (30, 40, 30), (90, 255, 255)); _ta = time.time()
    with MODEL_LOCK:
        r = model.track(f, persist=True, tracker="bytetrack.yaml", classes=[0], conf=0.25, imgsz=a.imgsz, device=dev, verbose=False)[0]
        rb = model.predict(f, imgsz=a.imgsz, conf=0.04, classes=[32], device=dev, verbose=False)[0]   # ByteTrack drops low-confidence boxes, and the ball is always low-confidence
    STATS["td"] = (time.time() - _ta) * 1000
    raw, ball = [], None
    if rb.boxes is not None and len(rb.boxes):
        for b, cf in zip(rb.boxes.xyxy.cpu().numpy(), rb.boxes.conf.cpu().numpy()):
            x1, y1, x2, y2 = [float(v) for v in b]; cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if not (3 <= x2 - x1 <= 40 and 3 <= y2 - y1 <= 40) or (grass[int(clamp(cy + 6, 0, H - 1)), int(clamp(cx, 0, W - 1))] == 0): continue
            lb = BALLLAST["p"]
            if lb is not None and t - lb[2] < 0.8 and math.hypot(cx - lb[0], cy - lb[1]) > 260 * max(0.3, t - lb[2]) and cf < 0.3: continue
            if ball is None or cf > ball[2]: ball = (cx, cy, float(cf))
        if ball: BALLLAST["p"] = (ball[0], ball[1], t)
    if r.boxes is not None and len(r.boxes):
        xyxy = r.boxes.xyxy.cpu().numpy(); cls = r.boxes.cls.cpu().numpy().astype(int); conf = r.boxes.conf.cpu().numpy()
        ids = r.boxes.id.cpu().numpy().astype(int) if r.boxes.id is not None else -np.ones(len(cls), int)
        for b, c, cf, tid in zip(xyxy, cls, conf, ids):
            x1, y1, x2, y2 = [int(v) for v in b]; h = y2 - y1
            if c == 32:
                if cf > 0.08 and 3 <= x2 - x1 <= 40 and (ball is None or cf > ball[2]): ball = ((x1 + x2) / 2, (y1 + y2) / 2, cf)
                continue
            if c == 0 and cf < 0.25: continue
            if not (22 <= h <= 330) or h / max(1, x2 - x1) < 1.0: continue
            gy1, gy2, gx1, gx2 = max(0, y2 - 12), min(H, y2 + 12), max(0, x1 - 6), min(W, x2 + 6)
            if gy2 > gy1 and (grass[gy1:gy2, gx1:gx2] > 0).mean() < 0.3: continue
            tor = f[y1 + int(.2 * h):y1 + int(.5 * h), x1 + int(.3 * (x2 - x1)):x1 + int(.7 * (x2 - x1))]
            if tor.size == 0: continue
            col = np.median(tor.reshape(-1, 3), 0); raw.append((x1, y1, x2, y2, int(tid), col)); samples.append(col)
    if len(samples) >= 150 and (cents is None or i % 10 == 0):
        cents, cnt = kmeans(np.array(samples)); grp = list(range(len(cents)))
        for p in range(len(cents)):
            for q in range(p + 1, len(cents)):
                if np.linalg.norm(cents[p] - cents[q]) < 60 and cnt[p] > 0 and cnt[q] > 0: og = grp[q]; grp = [grp[p] if g == og else g for g in grp]
        gc = collections.Counter(); [gc.update({grp[j]: int(cnt[j])}) for j in range(len(cents))]; go = [g for g, _ in gc.most_common()]
        granks = {j: go.index(grp[j]) for j in range(len(cents))}
        if TEAMREF[0] is not None:                                                         # keep team identity fixed once known
            for j in range(len(cents)):
                d0, d1 = np.linalg.norm(cents[j] - TEAMREF[0]), np.linalg.norm(cents[j] - TEAMREF[1])
                granks[j] = 0 if d0 < min(d1, 80) else (1 if d1 < 80 else 2)
        else:
            for rk in (0, 1):
                js = [j for j in range(len(cents)) if granks[j] == rk and cnt[j] > 0]
                if js and len(samples) >= 150: TEAMREF[rk] = np.average(cents[js], axis=0, weights=[cnt[j] for j in js]); TEAMCOL[rk] = tuple(int(v) for v in TEAMREF[rk])
            if TEAMREF[0] is not None and TEAMREF[1] is not None:            # United red, Spurs blue, whatever the shirts measure as
                red = 0 if TEAMREF[0][2] - TEAMREF[0][0] >= TEAMREF[1][2] - TEAMREF[1][0] else 1
                TEAMCOL[red] = UNITED; TEAMCOL[1 - red] = SPURS
    people = []
    for x1, y1, x2, y2, tid, col in raw:
        lab = 2
        if cents is not None: tcol[tid].append(col); lab = min(granks[int(np.argmin(((cents - np.mean(tcol[tid], 0)) ** 2).sum(1)))], 2)
        if cents is not None and TEAMREF[0] is not None:
            VOTES[("r", tid)][lab] += 1; v_ = VOTES[("r", tid)]; lab = max(v_, key=lambda k: (v_[k], -k))
        people.append((x1, y1, x2, y2, tid, lab))
    refine_cam(f, [p[:4] for p in people], i)
    with LOCK: Hi = (CAM["hist"].get(i, CAM["Hp"]) if CAM["state"] == "OK" else None)
    pp = []; bp = None
    if Hi is not None:
        for x1, y1, x2, y2, tid, lab in people:
            x, y = to_pitch(Hi, (x1 + x2) / 2, y2)
            if -3 < x < 108 and -3 < y < 71: cid = canon(tid, lab, t, x, y); VOTES[cid][lab] += 1; vv = VOTES[cid]; lab = max(vv, key=lambda k: (vv[k], -k)); pp.append((cid, lab, x, y)); LASTSEEN[cid] = (t, x, y, lab)
        if ball:
            x, y = to_pitch(Hi, ball[0], ball[1])
            if -2 < x < 107 and -2 < y < 70: bp = (x, y)
    if ball: STATS['balls'] += 1
    return {"t": t, "i": i, "ok": Hi is not None, "boxes": people, "pp": pp, "ball": bp}

def worker():
    last = -1; ts = collections.deque(maxlen=10)
    while not STOP:
        if SHARED["f"] is None or SHARED["i"] == last: time.sleep(0.004); continue
        f = SHARED["f"].copy(); i = SHARED["i"]; t = SHARED["t"]; last = i
        s = detect(f, i, t); ts.append(time.time()); STATS["dfps"] = (len(ts) - 1) / (ts[-1] - ts[0]) if len(ts) > 1 else 0.0
        with DLOCK:
            DET.append(s)
            if s["ok"]:
                for cid, lab, x, y in s["pp"]: PIDX[cid].append((t, x, y, lab))

# ============================ ball: clean up over a sliding window (impossible jumps out, possession, flights with arcs) ============================
BALLTRK = {"t0": 0.0, "dt": 0.08, "b2": [], "kicks": []}
def clean_ball(fr, fps=12.5):
    K = len(fr); dt = 1 / fps; raw = {k: np.array(f["b"][:2], float) for k, f in enumerate(fr) if f["b"]}
    def med_filter(P, win=6, tol=7.0):
        o = {}
        for k, p in P.items():
            nb = [P[j] for j in range(k - win, k + win + 1) if j in P and j != k]
            if len(nb) >= 3 and np.hypot(*(p - np.median(nb, 0))) > tol: continue
            o[k] = p
        return o
    P = raw
    for _ in range(3): P = med_filter(P)
    P = {k: p for k, p in P.items() if -3 < p[0] < 108 and -3 < p[1] < 71}; acc = {}; last = None; rej = 0
    for k in sorted(P):
        if last is None: acc[k] = P[k]; last = k; continue
        v = np.hypot(*(P[k] - acc[last])) / ((k - last) * dt)
        if v <= 32 or rej >= 5: acc[k] = P[k]; last = k; rej = 0
        else: rej += 1
    ks = sorted(acc); xy = {}
    for a_, b_ in zip(ks, ks[1:]):
        if b_ - a_ <= 10:
            for k in range(a_, b_ + 1): u = (k - a_) / (b_ - a_); xy[k] = (1 - u) * acc[a_] + u * acc[b_]
    sm = {}
    for k in sorted(xy): sm[k] = np.mean([xy[j] for j in range(k - 1, k + 2) if j in xy], 0)
    xy = sm
    def speed(k):
        a_, b_ = max(0, k - 2), min(K - 1, k + 2)
        return np.hypot(*(xy[b_] - xy[a_])) / ((b_ - a_) * dt) if a_ in xy and b_ in xy else 99
    cand = {}
    for k in sorted(xy):
        Pp = fr[k]["p"]
        if not Pp: continue
        best = min(Pp, key=lambda p: np.hypot(p[2] - xy[k][0], p[3] - xy[k][1]))
        if np.hypot(best[2] - xy[k][0], best[3] - xy[k][1]) < 2.4 and speed(k) < 8.5: cand[k] = best[0]
    carrier = {}
    for k in sorted(cand):
        if all(cand.get(j) == cand[k] for j in (k - 1, k, k + 1)) or all(cand.get(j) == cand[k] for j in (k, k + 1, k + 2)) or all(cand.get(j) == cand[k] for j in (k - 2, k - 1, k)): carrier[k] = cand[k]
    for k in range(1, K - 1):
        if k not in carrier and carrier.get(k - 1) is not None and carrier.get(k - 1) == carrier.get(k + 1): carrier[k] = carrier[k - 1]
    pt = lambda v: (float(v[0]), float(v[1])); b2 = [None] * K; kicks = []
    for k in sorted(carrier):
        if k in xy: b2[k] = pt(xy[k]) + (0.0, int(carrier[k]))
    spells = []
    for k in sorted(carrier):
        if spells and spells[-1][2] == carrier[k] and k - spells[-1][1] <= 2: spells[-1][1] = k
        else: spells.append([k, k, carrier[k]])
    for s0, s1 in zip(spells, spells[1:]):
        r, a_ = s0[1], s1[0]
        if a_ - r < 2 or a_ - r > 60 or r not in xy or a_ not in xy: continue
        p0, p1 = xy[r], xy[a_]; dist = float(np.hypot(*(p1 - p0))); T = (a_ - r) * dt; zp = min(1.226 * T * T, 0.4 * dist) if dist >= 6 else 0.0
        for kk in range(r + 1, a_): u = (kk - r) / (a_ - r); b2[kk] = pt((1 - u) * p0 + u * p1) + (4 * zp * u * (1 - u), -1)
        if dist > 4: kicks.append((r * dt, int(s0[2]), min(1.0, dist / 25)))
    for k in sorted(xy):
        if b2[k] is None: b2[k] = pt(xy[k]) + (0.0, -1)
    return b2, kicks, carrier, xy

def interp_pid(pid, t, maxgap=1.6):
    dq = PIDX.get(pid)
    if not dq: return None
    arr = list(dq)
    if t < arr[0][0] or t > arr[-1][0]: return None
    lo, hi = 0, len(arr) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if arr[mid][0] <= t: lo = mid
        else: hi = mid
    a_, b_ = arr[lo], arr[hi]
    if b_[0] - a_[0] > maxgap: return None
    u = 0 if b_[0] == a_[0] else (t - a_[0]) / (b_[0] - a_[0]); return (lerp(a_[1], b_[1], u), lerp(a_[2], b_[2], u), a_[3])

OFFS = [(-0.6, .1), (-0.4, .3), (-0.2, .6), (0.0, 1.0), (0.2, .6), (0.4, .3), (0.6, .1)]
def sm_pid(pid, t):
    """position smoothed over +-0.6 s (needs the delay buffer: future samples exist)"""
    sx = sy = sw = 0.0; lab = None
    for o, w in OFFS:
        v = interp_pid(pid, t + o)
        if v: sx += w * v[0]; sy += w * v[1]; sw += w; lab = v[2]
    return None if sw < 1.0 else (sx / sw, sy / sw, lab)
def ball_worker():
    while not STOP:
        time.sleep(0.5)
        with DLOCK: ok = [s for s in DET if s["ok"]]; tmax = now()
        if len(ok) < 6: continue
        t0 = max(ok[0]["t"], tmax - 25.0); n = int((tmax - t0) / 0.08); fr = []
        with DLOCK:
            pids = [p for p, dq in PIDX.items() if dq and dq[-1][0] > t0]; bsamp = [(s["t"], s["ball"]) for s in ok if s["ball"] and s["t"] >= t0]
        bi = {}
        for tb, b in bsamp: bi[int(round((tb - t0) / 0.08))] = b
        for k in range(n):
            tg = t0 + k * 0.08; Pp = []
            for pid in pids:
                v = interp_pid(pid, tg)
                if v: Pp.append([pid, v[2], v[0], v[1], 0, 0])
            fr.append({"p": Pp, "b": bi.get(k)})
        STATS['bwin'] = sum(1 for f in fr if f['b'])
        if STATS['bwin'] < 3: continue
        try: b2, kicks, _, _ = clean_ball(fr)
        except Exception: continue
        BALLTRK.update(t0=t0, b2=b2, kicks=[(t0 + kt, pid, pw) for kt, pid, pw in kicks])

# ============================ cartoon figure (OpenCV port of the browser version) ============================
SKIN = [(160, 201, 242), (115, 162, 217), (77, 116, 168), (46, 77, 122), (184, 215, 246)]; HAIR = [(18, 29, 43), (17, 17, 17), (35, 68, 107), (39, 162, 201), (85, 85, 85)]
shade = lambda c, f: tuple(int(v * f) for v in c)
def smooth(e0, e1, v): t = clamp((v - e0) / (e1 - e0), 0, 1); return t * t * (3 - 2 * t)
def hsh(n): n = (n * 2654435761) & 0xffffffff; n ^= n >> 15; n = (n * 2246822519) & 0xffffffff; return n ^ (n >> 13)
def cycle_len(s): return 1.2 + 0.43 * s
def draw_figure(img, x0, y0, Hpx, team_col, shorts_col, role, face, ph, speed, pid, tsec, kick=0.0):
    hs = hsh(pid); skin = SKIN[hs % 5]; hair = HAIR[(hs >> 3) % 5]; gk = role == 3
    sx = (-1 if face < 0 else 1) * (0.3 + 0.7 * abs(face)); T = lambda lx, ly: (int(round(x0 + sx * Hpx * lx)), int(round(y0 + Hpx * ly)))
    def limb(a_, b_, w, col):
        pa, pb = T(*a_), T(*b_); th = max(1, int(round(w * Hpx))); cv2.line(img, pa, pb, col, th, cv2.LINE_AA); cv2.circle(img, pa, th // 2, col, -1, cv2.LINE_AA); cv2.circle(img, pb, th // 2, col, -1, cv2.LINE_AA)
    m = smooth(0.25, 1.3, speed); run = clamp((speed - 1.5) / 5, 0, 1); A_ = m * (0.3 + 0.45 * run); idle = ((hs >> 6) % 7 - 3) * 0.03
    g = lambda p_: max(0.0, math.cos(p_ + 0.35)); Kf = 0.15 + 0.9 * run + 0.25 * m
    thN = A_ * math.sin(ph) + (1 - m) * (0.09 + idle); thF = A_ * math.sin(ph + math.pi) + (1 - m) * (-0.07 - idle)
    kN = (1 - m) * 0.05 + m * (0.1 + Kf * g(ph)); kF = (1 - m) * 0.05 + m * (0.1 + Kf * g(ph + math.pi))
    lean = 0.02 + 0.28 * clamp(speed / 7, 0, 1); bob = -0.026 * run * abs(math.sin(ph)) - 0.004 * math.sin(tsec * 2.2 + hs) * (1 - m)
    B = m * (0.25 + 0.55 * run); lam = 0.45 + 0.9 * run * m + (1 - m) * 0.1
    alN = -B * math.sin(ph) + (1 - m) * 0.06; alF = -B * math.sin(ph + math.pi) + (1 - m) * 0.04
    if kick > 0:
        w = kick * kick * (3 - 2 * kick); thN = -0.75 + 2.1 * w; kN = 1.3 - 1.1 * w; thF = -0.12; kF = 0.12; alN = 0.9 * w - 0.3; alF = -0.9 * w; lean -= 0.14 * w
    hip = (0.0, -0.47 + bob); up = (math.sin(lean), -math.cos(lean)); sh = (hip[0] + 0.31 * up[0], hip[1] + 0.31 * up[1]); hd = (sh[0] + 0.175 * up[0] + 0.02, sh[1] + 0.175 * up[1])
    cv2.ellipse(img, (int(x0), int(y0 + 1)), (int(Hpx * 0.2), max(1, int(Hpx * 0.055))), 0, 0, 360, (30, 70, 35), -1, cv2.LINE_AA)
    def leg(th, kap, far):
        k = (hip[0] + 0.24 * math.sin(th), hip[1] + 0.24 * math.cos(th)); b_ = th - kap; an = (k[0] + 0.24 * math.sin(b_), k[1] + 0.24 * math.cos(b_)); f_ = 0.72 if far else 1
        limb(hip, k, 0.09, shade(skin, f_)); limb(hip, (hip[0] + 0.55 * (k[0] - hip[0]), hip[1] + 0.55 * (k[1] - hip[1])), 0.115, shade(shorts_col, f_))
        limb(k, an, 0.075, shade(team_col if role < 2 else (30, 30, 30), f_)); limb(an, (an[0] + 0.105 * math.cos(b_), an[1] - 0.105 * math.sin(b_)), 0.07, (16, 16, 16))
    def arm(al, far):
        e = (sh[0] + 0.17 * math.sin(al), sh[1] + 0.17 * math.cos(al)); b_ = al + lam; hnd = (e[0] + 0.16 * math.sin(b_), e[1] + 0.16 * math.cos(b_)); f_ = 0.72 if far else 1
        limb(sh, e, 0.07, shade(team_col, f_)); limb(e, hnd, 0.06, shade(skin, f_))
        if gk: cv2.circle(img, T(*hnd), max(2, int(0.05 * Hpx)), (31, 138, 255), -1, cv2.LINE_AA)
    leg(thF, kF, True); arm(alF, True); limb(hip, sh, 0.2, team_col); limb((hip[0], hip[1] + 0.02), (hip[0], hip[1] + 0.1), 0.205, shorts_col); leg(thN, kN, False)
    cv2.circle(img, T(hd[0] - 0.015, hd[1] - 0.012), int(0.133 * Hpx), hair, -1, cv2.LINE_AA); cv2.circle(img, T(hd[0] + 0.014, hd[1] + 0.004), int(0.118 * Hpx), skin, -1, cv2.LINE_AA)
    cv2.circle(img, T(hd[0] + 0.066, hd[1] - 0.008), max(1, int(0.034 * Hpx)), (255, 255, 255), -1, cv2.LINE_AA); cv2.circle(img, T(hd[0] + 0.075, hd[1] - 0.006), max(1, int(0.016 * Hpx)), (17, 17, 17), -1, cv2.LINE_AA)
    arm(alN, False)

# ============================ layout, pitch panel, overlay card ============================
VW, VH, PXW, PXH, TOPM, STATUS = 768, 432, 666, 472, 40, 44
SC = PXW / 105.0; CANW, CANH = VW + PXW, PXH + STATUS
def pitch_base():
    p = np.full((PXH, PXW, 3), (50, 105, 55), np.uint8); L = (235, 235, 235); X = lambda x: int(round(x * SC)); Y = lambda y: TOPM + int(round(y * SC))
    for s in range(21):
        if s % 2: p[:, int(s * 5 * SC):int((s + 1) * 5 * SC)] = (p[:, int(s * 5 * SC):int((s + 1) * 5 * SC)] * 0.94).astype(np.uint8)
    cv2.rectangle(p, (0, Y(0)), (PXW - 1, Y(68)), L, 2); cv2.line(p, (X(52.5), Y(0)), (X(52.5), Y(68)), L, 1); cv2.circle(p, (X(52.5), Y(34)), int(9.15 * SC), L, 1); cv2.circle(p, (X(52.5), Y(34)), 2, L, -1)
    for sx, d in ((0, 1), (105, -1)):
        cv2.rectangle(p, (X(sx), Y(13.84)), (X(sx + d * 16.5), Y(54.16)), L, 1); cv2.rectangle(p, (X(sx), Y(24.84)), (X(sx + d * 5.5), Y(43.16)), L, 1)
        cv2.circle(p, (X(sx + d * 11), Y(34)), 2, L, -1); cv2.ellipse(p, (X(sx + d * 11), Y(34)), (int(9.15 * SC), int(9.15 * SC)), 0, -53 if d > 0 else 127, 53 if d > 0 else 233, L, 1)
    return p
BASE = pitch_base()
FONTS = ["/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", "/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
from PIL import Image, ImageDraw, ImageFont
def font(sz):
    for p in FONTS:
        try: return ImageFont.truetype(p, sz)
        except Exception: pass
    return ImageFont.load_default()
F_T, F_S, F_Q, F_N = font(28), font(19), font(24), font(16)
def wrap(draw, text, fnt, width):
    lines, cur = [], ""
    for w_ in text.split():
        t = (cur + " " + w_).strip()
        if draw.textlength(t, font=fnt) <= width: cur = t
        else: lines.append(cur); cur = w_
    if cur: lines.append(cur)
    return lines
def overlay_card(panel, question, secs):
    im = Image.fromarray(cv2.cvtColor(panel, cv2.COLOR_BGR2RGB)).convert("RGBA"); ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    w, h = im.size; d.rectangle([0, 0, w, h], fill=(10, 20, 40, 150)); x0, y0, x1, y1 = 34, 52, w - 34, h - 40
    d.rounded_rectangle([x0, y0, x1, y1], radius=26, fill=(255, 247, 224, 255), outline=(255, 159, 28, 255), width=5)
    d.rounded_rectangle([x0 + 24, y0 + 20, x0 + 214, y0 + 62], radius=18, fill=(255, 159, 28, 255)); d.text((x0 + 38, y0 + 26), "Kits & Cartoons", font=F_S, fill=(255, 255, 255, 255))
    d.text((x0 + 26, y0 + 82), "While we wait for the main video...", font=F_T, fill=(38, 52, 92, 255))
    d.text((x0 + 26, y0 + 130), "Talk to your dad about what you saw!", font=F_Q, fill=(214, 40, 40, 255))
    y = y0 + 190
    for ln in wrap(d, question, F_Q, x1 - x0 - 60): d.text((x0 + 30, y), ln, font=F_Q, fill=(38, 52, 92, 255)); y += 36
    d.text((x0 + 26, y1 - 40), "The cartoon pitch comes back with the main camera" + "." * (1 + int(secs * 2) % 3), font=F_N, fill=(120, 110, 90, 255))
    return cv2.cvtColor(np.array(Image.alpha_composite(im, ov).convert("RGB")), cv2.COLOR_RGB2BGR)

COLNAMES = [("red", (40, 40, 210)), ("blue", (200, 110, 40)), ("dark blue", (110, 60, 30)), ("white", (235, 235, 235)), ("black", (35, 35, 35)), ("green", (60, 170, 60)), ("yellow", (50, 210, 230)), ("orange", (40, 130, 240)), ("purple", (150, 60, 120)), ("grey", (140, 140, 140))]
def colname(bgr): return min(COLNAMES, key=lambda c: sum((int(a_) - int(b_)) ** 2 for a_, b_ in zip(c[1], bgr)))[0]
GENERIC = ["Who do you think will score next, and why?", "Can you spot the goalkeeper? What is their job?", "What colour kit would YOU design for your own team?", "Why do the players spread out across the pitch?",
           "If you were the coach, what would you tell the team right now?", "What is the best thing you saw so far? Ask your dad his!", "Why do you think the referee blows the whistle? Make a list!"]
def make_prompts():
    out = []
    with DLOCK: ok = [s for s in DET if s["ok"] and s["t"] > now() - 30]
    try:
        best = (0, None)
        for pid, dq in list(PIDX.items()):
            arr = [e for e in list(dq) if e[0] > now() - 30]
            for e0, e1 in zip(arr, arr[1:]):
                if 0.2 < e1[0] - e0[0] < 0.8:
                    v = math.hypot(e1[1] - e0[1], e1[2] - e0[2]) / (e1[0] - e0[0])
                    if v < 9.5 and v > best[0]: best = (v, pid)
        if best[0] > 6.0: out.append(f"Somebody was running at about {int(best[0] * 3.6)} km/h! How fast can YOU run? Race your dad!")
        b2, kicks, carrier, xy = BALLTRK["b2"], BALLTRK["kicks"], None, None
        far = 0.0
        for k in range(len(b2) - 1):
            if b2[k] and b2[k + 1] and b2[k][3] == -1 and b2[k][2] > 1: far = max(far, b2[k][2])
        if far > 2.5: out.append("The ball flew high in the air! Why do you think a player kicks it up instead of along the ground?")
        cnt = collections.Counter()
        for s in ok:
            labs = [p[1] for p in s["pp"]]
        names = {rk: colname(TEAMCOL[rk]) for rk in (0, 1)}
        if names[0] != names[1]: out.append(f"The {names[0]} team and the {names[1]} team are fighting for the ball. Which team do YOU want to win, and why?")
    except Exception: pass
    return out + GENERIC

# ============================ producer: reads the feed, follows the camera, keeps the delay buffer ============================
TS = {}
CLIP = {"frames": 0, "fps": 25.0}
if not a.src.startswith("http"):
    _c = cv2.VideoCapture(a.src); CLIP["frames"] = int(_c.get(cv2.CAP_PROP_FRAME_COUNT) or 0); CLIP["fps"] = _c.get(cv2.CAP_PROP_FPS) or 25.0; _c.release()
def tstamp(i):
    if not a.src.startswith("http"): return now()
    if "t0" not in TS: TS["t0"] = now() - i / 25.0                    # stream time, so network jitter does not become stutter
    return TS["t0"] + i / 25.0
REC = collections.deque(maxlen=int((a.delay + 20) * 30)); RLOCK = threading.Lock()
READY = {"v": False}; AQ = collections.deque(maxlen=80); OKLOG = collections.deque(maxlen=4000)
def okat(t):
    r = False
    for tt, o in reversed(OKLOG):
        if tt <= t: r = o; break
    return r
def tracker():
    while not STOP:
        if not AQ: time.sleep(0.003); continue
        i, f, t = AQ.popleft(); boxes = []
        with DLOCK:
            if DET: boxes = [b[:4] for b in DET[-1]["boxes"]]
        track_step(f, i, boxes); SHARED["f"] = f; SHARED["i"] = i; SHARED["t"] = t; OKLOG.append((t, CAM["state"] == "OK"))
def producer():
    skip = [0]
    for i, f in frames():
        if STOP: break
        if not READY["v"] and CAM["state"] == "OK": READY["v"] = True
        if not READY["v"]:
            SHARED["f"] = f; SHARED["i"] = i; SHARED["t"] = tstamp(i); track_step(f, i, [])
            if not a.src.startswith("http"):                 # saved file: freeze on a main-camera frame until calibration finishes; if it failed, jump ahead 2 s and try again
                if skip[0] > 0: skip[0] -= 1; continue
                if grass_share(f) < 0.45: skip[0] = 25; continue
                tgt = CAM.get("cal_done", 0) + 1
                while not STOP and CAM["state"] != "OK" and CAM.get("cal_done", 0) < tgt: time.sleep(0.05)
                if CAM["state"] != "OK": skip[0] = 50
            continue
        t = tstamp(i)
        with RLOCK: REC.append({"t": t, "i": i, "small": cv2.resize(f, (VW, VH), interpolation=cv2.INTER_AREA)})     # display path: nothing heavy here
        AQ.append((i, f, t))
    time.sleep(a.delay + 1.0)
    global STOP_SOON; STOP_SOON = True
STOP_SOON = False
for fn in (producer, tracker, worker, calib_worker, ball_worker): threading.Thread(target=fn, daemon=True).start()

PE = PT.Engine(); ALERTS = []; ALERT_SECS = 5.0
# ============================ tiny web server for the Next Post UI: /state.json (dots) and /video.mjpg (broadcast) ============================
LABELS = {}                      # dot id -> shirt number text, sent by the Next Post UI
LIVE = {"json": b'{"ready": false, "players": [], "n": 0}', "jpg": None, "n": 0}
FRAMES = {}                      # frame number -> jpeg, so the page can fetch exactly the picture that goes with a given /state.json
if a.serve:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class LiveHandler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def _cors(self): self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "Content-Type"); self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS"); self.send_header("Cache-Control", "no-store")
        def do_OPTIONS(self): self.send_response(204); self._cors(); self.end_headers()
        def do_POST(self):
            if self.path.startswith("/assign"):
                try:
                    n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
                    LABELS.clear(); LABELS.update({int(k): str(v)[:12] for k, v in (body.get("labels") or {}).items()})
                    self.send_response(200); self._cors(); self.end_headers(); self.wfile.write(b"ok")
                except Exception: self.send_response(400); self._cors(); self.end_headers()
            else: self.send_response(404); self.end_headers()
        def do_GET(self):
            if self.path.startswith("/state.json"):
                self.send_response(200); self._cors(); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(LIVE["json"])
            elif self.path.startswith("/frame/"):
                try: n_ = int(self.path.split("/frame/")[1].split(".")[0].split("?")[0])
                except Exception: n_ = -1
                b_ = FRAMES.get(n_)
                if b_ is None: self.send_response(404); self._cors(); self.end_headers(); return
                self.send_response(200); self._cors(); self.send_header("Content-Type", "image/jpeg"); self.send_header("Content-Length", str(len(b_))); self.end_headers(); self.wfile.write(b_)
            elif self.path.startswith("/video.mjpg"):
                self.send_response(200); self._cors(); self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame"); self.end_headers()
                last = -1
                try:
                    while not STOP:
                        if LIVE["jpg"] is None or LIVE["n"] == last: time.sleep(0.01); continue
                        last = LIVE["n"]; b = LIVE["jpg"]
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(b)).encode() + b"\r\n\r\n" + b + b"\r\n")
                except Exception: pass
            else: self.send_response(404); self.end_headers()
    srv = ThreadingHTTPServer(("127.0.0.1", a.serve), LiveHandler); threading.Thread(target=srv.serve_forever, daemon=True).start(); print(f"live data on http://127.0.0.1:{a.serve}/state.json  video on /video.mjpg")

# ============================ consumer: shows the moment t - delay ============================
CS = {}; prompts = []; pidx = 0; pstart = 0.0; not_ok_since = None; ok_since = None; show_card = False; ever_ok = False; vw = None; debug = False; last_disp = now(); frame_n = 0
def kick_amount(pid, t):
    for kt, kp, pw in BALLTRK["kicks"]:
        if kp != pid: continue
        u = (t - (kt - 0.32)) / 0.32
        if 0 < u <= 1: return u
        if 1 < u < 1.6: return 1 - (u - 1) / 0.6
    return 0.0
BSM = {}
def ball_at(t):
    b2, t0, dt = BALLTRK["b2"], BALLTRK["t0"], BALLTRK["dt"]
    if not b2: return None
    k = (t - t0) / dt
    if k < 0 or k > len(b2) - 1: return None
    k0 = int(k); k1 = min(len(b2) - 1, k0 + 1); u = k - k0; p, q = b2[k0], b2[k1]
    if p is None or q is None: return None
    r_ = (lerp(p[0], q[0], u), lerp(p[1], q[1], u), lerp(p[2], q[2], u), p[3])
    sm = BSM.get("p")
    if sm is not None and math.hypot(r_[0] - sm[0], r_[1] - sm[1]) < 12:
        k_ = 0.45; r_ = (sm[0] + (r_[0] - sm[0]) * k_, sm[1] + (r_[1] - sm[1]) * k_, r_[2], r_[3])
    BSM["p"] = r_; return r_
period = 1 / 25.0
while not STOP:
    tn = now(); t_d = tn - a.delay
    with RLOCK: recs = list(REC)
    rec = None
    for r_ in reversed(recs):
        if r_["t"] <= t_d: rec = r_; break
    dt_disp = max(1e-3, tn - last_disp); last_disp = tn
    canvas = np.zeros((CANH, CANW, 3), np.uint8)
    if rec is None or not READY['v']:
        if a.serve: LIVE["json"] = b'{"ready": false, "players": []}'
        msg = 'Getting ready... finding the pitch' if not READY['v'] else 'Buffering the live feed...'
        sz_ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_SIMPLEX, 1.1, 2)[0]; cv2.putText(canvas, msg, ((CANW - sz_[0]) // 2, CANH // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, '.' * (1 + int(tn * 2) % 3), (CANW // 2 - 10, CANH // 2 + 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (120, 220, 120), 3, cv2.LINE_AA)
    else:
        v = rec["small"].copy(); s_ = VW / W
        with DLOCK: dets = [d_ for d_ in DET if abs(d_["t"] - t_d) < 1.5]
        bef = [d_ for d_ in dets if d_["t"] <= t_d]; aft = [d_ for d_ in dets if d_["t"] > t_d]
        if bef and aft:
            d0, d1 = bef[-1], aft[0]; u = (t_d - d0["t"]) / max(1e-3, d1["t"] - d0["t"]); b1 = {b[4]: b for b in d1["boxes"]}
            for x1, y1, x2, y2, tid, lab in d0["boxes"]:
                if tid in b1:
                    q = b1[tid]; bx_ = [lerp(p_, r_, u) for p_, r_ in zip((x1, y1, x2, y2), q[:4])]; c = [TEAMCOL[0], TEAMCOL[1], (200, 200, 200)][lab]
                    cv2.rectangle(v, (int(bx_[0] * s_), int(bx_[1] * s_)), (int(bx_[2] * s_), int(bx_[3] * s_)), c, 2)
                    lbl = LABELS.get(ALIAS.get(tid, tid))
                    if lbl:
                        pt_ = (int(bx_[0] * s_), max(12, int(bx_[1] * s_) - 4)); cv2.putText(v, lbl, pt_, cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4, cv2.LINE_AA); cv2.putText(v, lbl, pt_, cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        canvas[20:20 + VH, :VW] = v
        # camera state with a little hysteresis so a one-frame blip does not flash the card
        okr = okat(rec["t"])
        if okr: ever_ok = True; not_ok_since = None; ok_since = ok_since or t_d
        else: ok_since = None; not_ok_since = not_ok_since or t_d
        if not okr and not_ok_since is not None and t_d - not_ok_since > 1.0 and not show_card:
            show_card = False
        if okr and ok_since is not None and t_d - ok_since > 0.4: show_card = False
        panel = BASE.copy()
        # dots: constant size, held in place for a moment when the detector misses a frame (no popping, no resizing)
        HOLD = 2.0; items = []; drawn = []; bl = None
        with DLOCK: pl = [(p, dq[0][0], dq[-1][0], dq[-1], len(dq)) for p, dq in PIDX.items() if dq and dq[-1][0] >= t_d - HOLD]
        for pid, tf, tl, last, n_ in pl:
            if n_ < 4 or tf > t_d + 0.3 or TEAMREF[0] is None: continue
            pos = sm_pid(pid, t_d) if tl >= t_d else None
            x, y, lab = pos if pos else (last[1], last[2], last[3])
            if not pos and any(q[0] != pid and q[1] > tl - 0.2 and q[3] == last[3] and abs(q[2] - last[3]) >= 0 for q in ()): continue
            st = CS.setdefault(pid, {})
            if "dx" not in st or math.hypot(x - st["dx"], y - st["dy"]) > 10: st["dx"], st["dy"] = x, y
            else: k_ = 1 - math.exp(-dt_disp / 0.2); st["dx"] += (x - st["dx"]) * k_; st["dy"] += (y - st["dy"]) * k_
            st["lab"] = lab; items.append((pid, st, tl >= t_d))
        # a lost track that was replaced by a new one right next to it is the same player: drop the old dot
        live = [(st["dx"], st["dy"], st["lab"]) for pid, st, ok_ in items if ok_]
        for pid, st, ok_ in items:
            if not ok_ and any(l[2] == st["lab"] and math.hypot(l[0] - st["dx"], l[1] - st["dy"]) < 3.0 for l in live): continue
            lab = st["lab"]; col = TEAMCOL[lab] if lab < 2 else (60, 200, 220)
            cx_, cy_ = int(st["dx"] * SC), TOPM + int(st["dy"] * SC)
            cv2.circle(panel, (cx_, cy_), 9, (255, 255, 255), -1, cv2.LINE_AA); cv2.circle(panel, (cx_, cy_), 7, col, -1, cv2.LINE_AA)
            if LABELS.get(pid): cv2.putText(panel, LABELS[pid], (cx_ - 5 * len(LABELS[pid]), cy_ + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)
            drawn.append({"id": int(pid), "team": ("mnu" if TEAMCOL[lab] == UNITED else "tot") if lab < 2 else "ref", "x": round(st["dx"] / 105, 4), "y": round(st["dy"] / 68, 4), "mx": st["dx"], "my": st["dy"]})
        bl = ball_at(t_d)
        if bl is None:                                              # cleaned ball track not ready: use the raw detections, interpolated
            with DLOCK: rb_ = [(d_["t"], d_["ball"]) for d_ in DET if d_["ball"] and abs(d_["t"] - t_d) < 1.5]
            bf_ = [q for q in rb_ if q[0] <= t_d]; af_ = [q for q in rb_ if q[0] > t_d]
            if bf_ and af_ and af_[0][0] - bf_[-1][0] < 1.5: u_ = (t_d - bf_[-1][0]) / (af_[0][0] - bf_[-1][0]); bl = (lerp(bf_[-1][1][0], af_[0][1][0], u_), lerp(bf_[-1][1][1], af_[0][1][1], u_), 0.0, -1)
            elif bf_ and t_d - bf_[-1][0] < 0.8: bl = (bf_[-1][1][0], bf_[-1][1][1], 0.0, -1)
        if bl:
            bx, by = int(bl[0] * SC), TOPM + int(bl[1] * SC)
            cv2.circle(panel, (bx, by), 8, (0, 120, 255), -1, cv2.LINE_AA); cv2.circle(panel, (bx, by), 6, (255, 255, 255), -1, cv2.LINE_AA); cv2.circle(panel, (bx, by), 6, (20, 20, 20), 1, cv2.LINE_AA)
        # --- pattern triggers (only while we are on the main camera) ---
        if okr and drawn:
            for al in PE.step(t_d, [{"id": q["id"], "team": q["team"], "x": q["mx"], "y": q["my"]} for q in drawn], (bl[0], bl[1]) if bl else None):
                al["shown"] = tn; ALERTS.append(al); print(f"TRIGGER {al['title']} ({al['score']}): {al['detail']}", flush=True)
                try: open("triggers.jsonl", "a").write(json.dumps({"wall": time.strftime("%H:%M:%S"), "stream_t": al["t"], **{k: al[k] for k in ("pattern", "score", "detail", "team")}}) + "\n")
                except Exception: pass
        if a.testalert and okr and drawn and int(tn) % 12 == 0 and not ALERTS: ALERTS.append({"pattern": "overload", "title": "OVERLOAD IN THE BOX", "detail": "4 v 2 in the box", "score": 0.8, "ids": [q["id"] for q in drawn[:3]], "region": [82, 13.8, 105, 54.2], "shown": tn})
        ALERTS[:] = [al for al in ALERTS if tn - al["shown"] < ALERT_SECS]
        if ALERTS:
            al = ALERTS[-1]; age = tn - al["shown"]; fade = clamp(min(age / 0.25, (ALERT_SECS - age) / 0.5), 0, 1)
            pos = {q["id"]: (int(q["mx"] * SC), TOPM + int(q["my"] * SC)) for q in drawn}
            if al.get("region"):
                r0 = al["region"]; ov = panel.copy(); cv2.rectangle(ov, (int(r0[0] * SC), TOPM + int(r0[1] * SC)), (int(r0[2] * SC), TOPM + int(r0[3] * SC)), (40, 160, 255), -1); panel = cv2.addWeighted(ov, 0.25 * fade, panel, 1 - 0.25 * fade, 0)
            for i_ in al["ids"]:
                if i_ in pos: cv2.circle(panel, pos[i_], 14, (40, 160, 255), 3, cv2.LINE_AA)
            im_ = Image.fromarray(cv2.cvtColor(panel, cv2.COLOR_BGR2RGB)).convert("RGBA"); ov_ = Image.new("RGBA", im_.size, (0, 0, 0, 0)); dr_ = ImageDraw.Draw(ov_)
            dr_.rounded_rectangle([14, 4, PXW - 14, TOPM - 4], radius=14, fill=(255, 159, 28, int(235 * fade)))
            dr_.text((28, 6), al["title"], font=F_S, fill=(30, 30, 30, int(255 * fade))); dr_.text((28 + dr_.textlength(al["title"], font=F_S) + 16, 9), al["detail"], font=F_N, fill=(50, 40, 20, int(255 * fade)))
            panel = cv2.cvtColor(np.array(Image.alpha_composite(im_, ov_).convert("RGB")), cv2.COLOR_RGB2BGR)
        if a.serve:
            ok_, jb = cv2.imencode(".jpg", v, [cv2.IMWRITE_JPEG_QUALITY, 72])
            if ok_: LIVE["jpg"] = jb.tobytes(); LIVE["n"] += 1; FRAMES[LIVE["n"]] = LIVE["jpg"]; FRAMES.pop(LIVE["n"] - 40, None)
            import json as _json
            LIVE["json"] = _json.dumps({"n": LIVE["n"], "ready": True, "clip": ({"pos": round((rec["i"] % CLIP["frames"]) / CLIP["fps"], 2), "dur": round(CLIP["frames"] / CLIP["fps"], 2)} if (rec and CLIP["frames"]) else None), "cutaway": not okr, "t": round(t_d, 2), "players": drawn,
                                        "alerts": [{"pattern": al["pattern"], "title": al["title"], "detail": al["detail"], "ids": al["ids"], "age": round(tn - al["shown"], 2)} for al in ALERTS], "ball": ({"x": round(bl[0] / 105, 4), "y": round(bl[1] / 68, 4)} if bl else None)}).encode()
        if show_card:
            if tn - pstart > 8.0 * (pidx + 1) and pidx < len(prompts) - 1: pidx += 1
            panel = overlay_card(panel, prompts[min(pidx, len(prompts) - 1)], tn - pstart)
        canvas[:PXH, VW:] = panel
    if debug:
        cv2.putText(canvas, f"disp {1/dt_disp:.0f}fps queue {len(AQ)} | delay {a.delay:.1f}s | camera {CAM['state']} {CAM['inl']} (calibrations {CAM['cal_ok']}/{CAM['cal_tries']}) | boxes {STATS['dfps']:.1f}/s {STATS['td']:.0f}ms | ball seen {STATS['balls']} used {STATS['bwin']} | players on pitch {len([1 for _, _, s_ in (items if rec else [])])}", (10, PXH + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    if a.out:
        if vw is None: vw = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), 25, (CANW, CANH))
        vw.write(canvas)
    if not a.noshow:
        cv2.imshow("Kits & Cartoons - live", canvas); k = cv2.waitKey(1) & 0xFF
        if k == ord("q"): break
        if k == ord("n") and show_card: pidx = min(pidx + 1, len(prompts) - 1); pstart = tn - 8.0 * pidx
        if k == ord("d"): debug = not debug
    frame_n += 1
    if (a.seconds and tn > a.seconds) or STOP_SOON: break
    time.sleep(max(0.0, period - (now() - tn)))
STOP = True
if vw: vw.release()
print(f"done. calibrations ok {CAM['cal_ok']} of {CAM['cal_tries']} tries; detection samples {len(DET)}")
