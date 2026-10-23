#!/usr/bin/env python3
"""Finds the longest stretch of one main-camera shot in a recording and cuts it out as a demo clip.
   python3 find_clip.py full_rec.mp4 --len 90 --out demo90.mp4"""
import argparse, subprocess, sys, cv2, numpy as np
import autocalib as A
ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("--len", type=float, default=90); ap.add_argument("--out", default="demo_clip.mp4")
ap.add_argument("--checks", type=int, default=5, help="frames per candidate to calibrate"); ap.add_argument("--tries", type=int, default=6)
a = ap.parse_args()
cap = cv2.VideoCapture(a.src); fps = cap.get(5) or 25; step = max(1, int(round(fps / 5))); n = 0
T, G, CUT = [], [], []; prev = None; ph = None
while True:
    ok, f = cap.read()
    if not ok: break
    if n % step == 0:
        s = cv2.resize(f, (160, 90)); hsv = cv2.cvtColor(s, cv2.COLOR_BGR2HSV)
        g = ((hsv[..., 0] > 35) & (hsv[..., 0] < 85) & (hsv[..., 1] > 60)).mean()
        h = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256]); cv2.normalize(h, h)
        cut = ph is not None and cv2.compareHist(ph, h, cv2.HISTCMP_CORREL) < 0.80; ph = h
        T.append(n / fps); G.append(g); CUT.append(cut)
    n += 1
T = np.array(T); G = np.array(G); CUT = np.array(CUT); dur = n / fps
good = (G > 0.55) & ~CUT                      # looks like the wide camera and is not a cut
print(f"{dur:.0f}s of video, {int(CUT.sum())} cuts, {good.mean() * 100:.0f}% of it looks like the main camera")
# the camera stays on the pitch: runs of consecutive good samples; a cut or a non-pitch frame ends the run
runs = []; i = 0
while i < len(good):
    if not good[i]: i += 1; continue
    j = i
    while j + 1 < len(good) and good[j + 1]: j += 1
    runs.append((T[i], T[j] + 0.2)); i = j + 1
runs.sort(key=lambda r: r[0] - r[1])
print("longest main-camera runs:", ", ".join(f"{r[0]:.0f}-{r[1]:.0f}s ({r[1] - r[0]:.0f}s)" for r in runs[:5]))
if not runs: sys.exit("no main-camera footage found")
best = None
for (r0, r1) in runs[:a.tries]:
    L = min(a.len, r1 - r0)
    # slide inside the run, check the middle part first
    starts = [r0 + (r1 - r0 - L) / 2] if r1 - r0 > L else [r0]
    for s0 in starts:
        okn = 0
        for k in range(a.checks):
            cap.set(cv2.CAP_PROP_POS_MSEC, (s0 + (k + 0.5) * L / a.checks) * 1000); ok, f = cap.read()
            if not ok: continue
            res = A.calibrate(f)
            if res is not None and res[2]["score"] <= 12: okn += 1
        print(f"  {s0:.0f}-{s0 + L:.0f}s: pitch found in {okn}/{a.checks} checks", flush=True)
        if best is None or (L, okn) > (best[1], best[2]): best = (s0, L, okn)
        if L >= a.len - 0.5 and okn >= a.checks - 1: break
    else: continue
    break
s0, L, okn = best
print(f"cutting {s0:.1f}s for {L:.1f}s ->", a.out)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{s0:.2f}", "-i", a.src, "-t", f"{L:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-c:a", "aac", "-movflags", "+faststart", a.out], check=True)
if L < a.len - 0.5: print(f"WARNING: the longest clean stretch is {L:.0f}s, not {a.len:.0f}s. Record more footage and run again.")
print("done:", a.out)
