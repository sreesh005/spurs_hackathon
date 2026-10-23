"""MediaPipe signals per 2s segment: what the crowd sounds like, and what the camera shows.

- Sound (YAMNet audio classifier): cheer = max of cheering/crowd/applause/shout/yell; whistle.
- Picture, sampled at 2 frames/s at 640x360:
  people count and size (object detector, "person"), largest face share (face detector),
  share of green pitch pixels, frame-to-frame change (camera cuts, stillness).
- Raised arms (pose landmarker), only on close-up-looking frames: in wide shots the players
  are too small for pose to find anyone, so it would only cost time.

ffmpeg only decodes the audio and frames; MediaPipe does the recognition.
"""

import os
import statistics
import subprocess
from dataclasses import dataclass
from functools import lru_cache

os.environ.setdefault("GLOG_minloglevel", "2")  # quiet MediaPipe's own logging
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import mediapipe as mp  # noqa: E402
import numpy as np
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import audio, vision
from mediapipe.tasks.python.components import containers

from .config import ROOT

MODELS = ROOT / "models"
W, H, FPS, SR = 640, 360, 2, 16000
# On a broadcast mix the commentary dominates ("Speech" ~0.9), and a crowd roar mostly reads as noise,
# so roar = cheering-type classes plus noise classes. The Tracker scores it against the recent baseline.
CHEER = {"Cheering", "Crowd", "Applause", "Shout", "Yell", "Children shouting", "Battle cry",
         "White noise", "Pink noise", "Noise", "Hubbub, speech noise, speech babble"}
WHISTLE = {"Whistle", "Whistling"}
CUT_DIFF = 45.0  # mean absolute pixel change between samples that counts as a camera cut
POSE_MIN_HEIGHT, POSE_MIN_FACE = 0.4, 0.03  # run pose only when people or a face look this large
L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST = 11, 12, 15, 16


@dataclass
class SegmentView:
    cheer: float = 0.0
    whistle: float = 0.0
    people: int = 0
    person_height: float = 0.0  # median person box height, share of frame
    face_share: float = 0.0  # largest face box area, share of frame
    green: float = 0.0
    cut: bool = False
    still: float = 0.0  # 1 = nothing moves between samples
    arms_up: bool = False  # someone in a close-up has a wrist above their shoulder


@lru_cache
def _models():
    base = lambda name: mpt.BaseOptions(model_asset_path=str(MODELS / name))  # noqa: E731
    clf = audio.AudioClassifier.create_from_options(
        audio.AudioClassifierOptions(base_options=base("yamnet.tflite"), max_results=-1))
    det = vision.ObjectDetector.create_from_options(
        vision.ObjectDetectorOptions(base_options=base("efficientdet_lite0.tflite"),
                                     score_threshold=0.3, max_results=40, category_allowlist=["person"]))
    face = vision.FaceDetector.create_from_options(
        vision.FaceDetectorOptions(base_options=base("blaze_face_short_range.tflite"), min_detection_confidence=0.5))
    pose = vision.PoseLandmarker.create_from_options(
        vision.PoseLandmarkerOptions(base_options=base("pose_landmarker_lite.task"), num_poses=4,
                                     min_pose_detection_confidence=0.5))
    return clf, det, face, pose


def _decode(src: str, start: float | None, duration: float | None) -> tuple[np.ndarray, np.ndarray]:
    pre = (["-ss", str(start)] if start is not None else []) + (["-t", str(duration)] if duration is not None else [])
    pcm = subprocess.run(["ffmpeg", "-v", "error", *pre, "-i", src, "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True).stdout
    raw = subprocess.run(["ffmpeg", "-v", "error", *pre, "-i", src, "-an", "-vf", f"fps={FPS},scale={W}:{H}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    frames = np.frombuffer(raw, np.uint8)[: len(raw) // (W * H * 3) * W * H * 3].reshape(-1, H, W, 3)
    return np.frombuffer(pcm, np.float32), frames


def _sound(pcm: np.ndarray) -> list[tuple[float, float, float]]:
    """[(t_seconds, cheer, whistle)] about once a second."""
    if len(pcm) < SR // 2:
        return []
    clf, *_ = _models()
    out = []
    for r in clf.classify(containers.AudioData.create_from_array(pcm.astype(np.float32), SR)):
        cats = {c.category_name: c.score for c in r.classifications[0].categories}
        out.append((r.timestamp_ms / 1000, max(cats.get(n, 0.0) for n in CHEER), max(cats.get(n, 0.0) for n in WHISTLE)))
    return out


def arms_up(poses) -> bool:
    """True if any pose has a wrist above its same-side shoulder (image y grows downward)."""
    return any(p[L_WRIST].y < p[L_SHOULDER].y or p[R_WRIST].y < p[R_SHOULDER].y for p in poses if len(p) > R_WRIST)


def _frame(frame: np.ndarray) -> tuple[int, float, float, float, bool]:
    """(people, median person height, largest face share, green share, arms up) for one RGB frame."""
    _, det, face, pose = _models()
    img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame))
    boxes = det.detect(img).detections
    heights = [d.bounding_box.height / H for d in boxes]
    faces = [d.bounding_box.width * d.bounding_box.height / (W * H) for d in face.detect(img).detections]
    r, g, b = (frame[..., i].astype(np.int16) for i in range(3))
    green = float(((g > r + 15) & (g > b + 15)).mean())
    height, face_share = statistics.median(heights) if heights else 0.0, max(faces, default=0.0)
    closeup = height >= POSE_MIN_HEIGHT or face_share >= POSE_MIN_FACE
    return len(boxes), height, face_share, green, closeup and arms_up(pose.detect(img).pose_landmarks)


def views(src: str, start: float | None = None, duration: float | None = None, seg: float = 2.0) -> list[SegmentView]:
    """One SegmentView per `seg` seconds of `src` (a segment file, or a range of a longer video)."""
    pcm, frames = _decode(src, start, duration)
    n = max(1, round((len(pcm) / SR) / seg)) if len(pcm) else max(1, round(len(frames) / (FPS * seg)))
    out = [SegmentView() for _ in range(n)]
    for t, cheer, whistle in _sound(pcm):
        v = out[min(n - 1, int(t // seg))]
        v.cheer, v.whistle = max(v.cheer, cheer), max(v.whistle, whistle)
    per = int(FPS * seg)
    prev = None
    for k in range(n):
        chunk = frames[k * per:(k + 1) * per]
        if not len(chunk):
            continue
        stats = [_frame(f) for f in chunk]
        v = out[k]
        v.people = round(statistics.median(s[0] for s in stats))
        v.person_height = statistics.median(s[1] for s in stats)
        v.face_share = max(s[2] for s in stats)
        v.green = statistics.fmean(s[3] for s in stats)
        v.arms_up = any(s[4] for s in stats)
        diffs = []
        for f in chunk:
            if prev is not None:
                diffs.append(float(np.abs(f.astype(np.int16) - prev.astype(np.int16)).mean()))
            prev = f
        v.cut = any(d > CUT_DIFF for d in diffs)
        calm = [d for d in diffs if d <= CUT_DIFF]
        v.still = max(0.0, 1 - statistics.fmean(calm) / 20) if calm else 0.0
    return out


def shot_type(v: SegmentView, cfg: dict) -> str:
    # A large face counts only off the pitch: the face detector finds false faces in wide shots of grass.
    if (v.face_share >= cfg["closeup_face_share"] and v.green < 0.45) or (0 < v.people <= 2 and v.person_height >= 0.5):
        return "closeup"
    if v.green >= 0.45 and (v.people >= cfg["wide_min_people"] or v.person_height < 0.2):
        return "wide"
    if v.green < cfg["crowd_max_green"]:
        return "crowd"
    return "medium"
