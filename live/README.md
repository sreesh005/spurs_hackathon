# Live dots (video + pitch map + commentary)
Scripts behind the Live dots tab. Run from this folder with the project venv (ultralytics, opencv, scipy, faster-whisper).
- `hack_live_dots12.py --src demo90.mp4 --loop --serve 8766 --noshow` : auto-calibrates the pitch, tracks players and ball, serves /state.json, /frame/N.jpg and /video.mjpg
- `tl_transcript.py --upload demo90.mp4 --serve 8767` : Twelve Labs transcript of the clip (key read from ../.env, never printed)
- `commentary.py --src <stream> --serve 8767` : live Whisper transcript instead
- `find_clip.py full_rec.mp4 --len 90` : cuts the longest main-camera stretch
- `patterns.py` : formation triggers (overload, overlap, line break, counter, switch, press)
Model weights (yolov8s.pt) and recordings are not committed.
