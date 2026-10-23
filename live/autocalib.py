"""Automatic pitch calibration for a FIXED main broadcast camera: find pan, tilt, roll, zoom by matching the pitch-line model to the white-line mask."""
import numpy as np, cv2, time
from scipy.optimize import least_squares
from scipy.ndimage import map_coordinates

C = np.array([52.5, 90.6, -16.0])           # camera centre in pitch metres (x along the pitch, y across, z down), recovered from the validated clip


def model_points(step=0.5):
    pts = []
    def seg(p, q):
        n = max(int(np.hypot(q[0] - p[0], q[1] - p[1]) / step), 2)
        for t in np.linspace(0, 1, n): pts.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    def arc(c, r, a0, a1):
        n = max(int(abs(a1 - a0) * r / step), 8)
        for t in np.linspace(a0, a1, n): pts.append((c[0] + r * np.cos(t), c[1] + r * np.sin(t)))
    L, Wd = 105.0, 68.0
    seg((0, 0), (L, 0)); seg((0, Wd), (L, Wd)); seg((0, 0), (0, Wd)); seg((L, 0), (L, Wd)); seg((L / 2, 0), (L / 2, Wd))
    arc((L / 2, Wd / 2), 9.15, 0, 2 * np.pi)
    for sx, sg in ((0.0, 1), (L, -1)):
        for d, half in ((16.5, 20.16), (5.5, 9.16)):
            seg((sx, Wd / 2 - half), (sx + sg * d, Wd / 2 - half)); seg((sx, Wd / 2 + half), (sx + sg * d, Wd / 2 + half)); seg((sx + sg * d, Wd / 2 - half), (sx + sg * d, Wd / 2 + half))
        spot = (sx + sg * 11.0, Wd / 2); a = np.arccos(5.5 / 9.15)
        arc(spot, 9.15, -a, a) if sg == 1 else arc(spot, 9.15, np.pi - a, np.pi + a)
    return np.array(pts, float)
MODEL = model_points()


def line_mask(img_bgr):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV); gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
    white = (th > 28) & (gray > 140) & (hsv[..., 1] < 90)
    grass = ((hsv[..., 0] > 30) & (hsv[..., 0] < 85) & (hsv[..., 1] > 55)).astype(np.uint8)
    grass = cv2.dilate(cv2.morphologyEx(grass, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8)), np.ones((9, 9), np.uint8))
    m = (white & (grass > 0)).astype(np.uint8); m[:60, :330] = 0
    return m


def rot(theta, phi, rho):
    f = np.array([np.sin(theta) * np.cos(phi), -np.cos(theta) * np.cos(phi), np.sin(phi)])
    x = np.cross([0, 0, 1.0], f); x /= np.linalg.norm(x); y = np.cross(f, x)
    c, s = np.cos(rho), np.sin(rho)
    return np.stack([c * x + s * y, -s * x + c * y, f])


def ground_H(theta, phi, rho, fpx, W, H):
    """pitch plane (x, y, 1) -> image pixels, for an image W x H"""
    K = np.array([[fpx, 0, W / 2], [0, fpx, H / 2], [0, 0, 1.0]])
    Ph = K @ rot(theta, phi, rho) @ np.c_[np.eye(3), -C]
    return Ph[:, [0, 1, 3]]


def project(Hg, pts):
    p = np.c_[pts, np.ones(len(pts))] @ Hg.T
    w = p[:, 2]; ok = w > 1e-6
    uv = np.full((len(pts), 2), np.nan); uv[ok] = p[ok, :2] / w[ok, None]
    return uv


def coarse_search(mask, W, H, thetas=None, phis=None, fs=None, scale=6):
    h, w = H // scale, W // scale
    m = cv2.resize(mask * 255, (w, h), interpolation=cv2.INTER_AREA) > 20
    if m.sum() < 30: return []
    dtm = cv2.distanceTransform((~m).astype(np.uint8), cv2.DIST_L2, 3)
    mp = np.argwhere(m)
    thetas = np.deg2rad(np.arange(-62, 63, 2.5)) if thetas is None else thetas
    phis = np.deg2rad(np.arange(4, 46, 2.5)) if phis is None else phis
    fs = np.array([1500, 1750, 2000, 2300, 2650, 3000, 3500, 4100]) if fs is None else fs
    out = []
    for f in fs:
        for th in thetas:
            for ph in phis:
                Hg = ground_H(th, ph, 0.0, f / scale, w, h); uv = project(Hg, MODEL)
                ok = np.isfinite(uv[:, 0]) & (uv[:, 0] >= 0) & (uv[:, 0] < w - 1) & (uv[:, 1] >= 0) & (uv[:, 1] < h - 1)
                if ok.sum() < 40: continue
                q = uv[ok]; M = np.zeros((h, w), np.uint8); M[q[:, 1].astype(int), q[:, 0].astype(int)] = 1
                c1 = np.minimum(dtm[M > 0], 12).mean()
                dtM = cv2.distanceTransform((M == 0).astype(np.uint8), cv2.DIST_L2, 3)
                c2 = np.minimum(dtM[m], 12).mean()
                out.append((c1 + 0.6 * c2, th, ph, f))
    out.sort(key=lambda t: t[0]); return out


def refine(mask, W, H, th, ph, f, rho=0.0):
    dt = cv2.distanceTransform((mask == 0).astype(np.uint8), cv2.DIST_L2, 5).astype(np.float32); cap = 40.0
    def resid(p):
        Hg = ground_H(p[0], p[1], p[2], p[3], W, H); uv = project(Hg, MODEL)
        ok = np.isfinite(uv[:, 0]) & (uv[:, 0] >= 0) & (uv[:, 0] < W - 1) & (uv[:, 1] >= 0) & (uv[:, 1] < H - 1)
        r = np.full(len(MODEL), cap, np.float64)
        if ok.sum() > 0: r[ok] = np.minimum(map_coordinates(dt, [uv[ok, 1], uv[ok, 0]], order=1), cap)
        return np.r_[r, 0.002 * p[2] * 1e3]
    s = least_squares(resid, [th, ph, rho, f], loss='soft_l1', f_scale=4.0, x_scale=[0.01, 0.01, 0.005, 60.0], max_nfev=60)
    return s.x, resid(s.x)[:-1]


def score_params(mask, W, H, p, scale=4):
    """same two-way chamfer as the coarse search, evaluated for one parameter set (lower = better); also returns the visible share"""
    h, w = H // scale, W // scale
    m = cv2.resize(mask * 255, (w, h), interpolation=cv2.INTER_AREA) > 20
    dtm = cv2.distanceTransform((~m).astype(np.uint8), cv2.DIST_L2, 3)
    uv = project(ground_H(p[0], p[1], p[2], p[3] / scale, w, h), MODEL)
    ok = np.isfinite(uv[:, 0]) & (uv[:, 0] >= 0) & (uv[:, 0] < w - 1) & (uv[:, 1] >= 0) & (uv[:, 1] < h - 1)
    if ok.sum() < 40: return 99.0, 0.0, 99.0
    q = uv[ok]; M = np.zeros((h, w), np.uint8); M[q[:, 1].astype(int), q[:, 0].astype(int)] = 1
    c1 = np.minimum(dtm[M > 0], 12 / 6 * scale / 1.0).mean() * scale / 1.0 / scale
    c1 = np.minimum(dtm[M > 0], 12).mean(); dtM = cv2.distanceTransform((M == 0).astype(np.uint8), cv2.DIST_L2, 3); c2 = np.minimum(dtM[m], 12).mean()
    return c1 + 0.6 * c2, c1, c2


def refine_h(mask, W, H, Hg):
    """let the 8 homography numbers move a little around the camera-model solution (sub-pixel line alignment)"""
    dt = cv2.distanceTransform((mask == 0).astype(np.uint8), cv2.DIST_L2, 5).astype(np.float32); cap = 25.0
    base = Hg / Hg[2, 2]
    def make(p):
        Hn = base.copy().ravel(); Hn[:8] *= (1 + p); return Hn.reshape(3, 3)
    def resid(p):
        uv = project(make(p), MODEL)
        ok = np.isfinite(uv[:, 0]) & (uv[:, 0] >= 0) & (uv[:, 0] < W - 1) & (uv[:, 1] >= 0) & (uv[:, 1] < H - 1)
        r = np.full(len(MODEL), 0.0)
        if ok.sum() > 60: r[ok] = np.minimum(map_coordinates(dt, [uv[ok, 1], uv[ok, 0]], order=1), cap)
        return np.r_[r, 30.0 * p]                                   # stay close to the camera-model solution
    s = least_squares(resid, np.zeros(8), loss='soft_l1', f_scale=3.0, x_scale=0.004, max_nfev=40)
    return make(s.x)


def calibrate(frame_bgr, top=8, verbose=False):
    """frame (any size) -> (img->pitch 3x3 for that image size, camera params, quality dict); None if no fit"""
    H0, W0 = frame_bgr.shape[:2]; W, H = 1920, 1080
    fr = cv2.resize(frame_bgr, (W, H)) if (W0, H0) != (W, H) else frame_bgr
    mask = line_mask(fr); cand = coarse_search(mask, W, H)
    if not cand: return None
    best = None; seen = []
    for c, th, ph, f in cand[:80]:
        if any(abs(th - a) < 0.05 and abs(ph - b) < 0.05 and abs(f - g) < 250 for a, b, g in seen): continue
        seen.append((th, ph, f))
        if len(seen) > top: break
        x, r = refine(mask, W, H, th, ph, f)
        sc, c1, c2 = score_params(mask, W, H, x)
        if verbose: print("  cand pan %.1f tilt %.1f f %.0f -> refined score %.2f (to-image %.2f, to-model %.2f)" % (np.rad2deg(x[0]), np.rad2deg(x[1]), x[3], sc, c1, c2))
        if best is None or sc < best[0]: best = (sc, c1, c2, x)
    sc, c1, c2, x = best
    Hg = refine_h(mask, W, H, ground_H(x[0], x[1], x[2], x[3], W, H))
    S = np.diag([W0 / W, H0 / H, 1.0])
    return np.linalg.inv(S @ Hg), x, {"score": float(sc), "to_image_px": float(c1), "to_model_px": float(c2)}
