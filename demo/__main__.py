"""python -m demo: the whole Live dots prototype on one laptop, no API keys needed.

Starts the fake tracker (port 8766), the fake auto-clipper, and the desk (port 8765) in demo mode.
  python -m demo                 everything, demo library
  python -m demo --speed 2       the scripted match runs twice as fast
  python -m demo --no-desk       only the fakes, for a desk you start yourself
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m demo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765, help="desk port")
    ap.add_argument("--tracker-port", type=int, default=8766)
    ap.add_argument("--speed", type=float, default=1.0, help="how fast the scripted match runs")
    ap.add_argument("--no-desk", action="store_true", help="run only the fake tracker and clipper")
    ap.add_argument("--real-library", action="store_true", help="with --no-desk: name players from data/library.json")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    demo_library = not (args.no_desk and args.real_library)
    if not args.no_desk:
        os.environ["NEXT_POST_DEMO"] = "1"  # read by server.py at import

    from demo import clipper, footage, tracker
    from demo.fixture import library_for_sim
    from demo.scenario import Clock

    if not footage.available():
        print("ffmpeg is not on PATH: the dots and the drawer work, but the demo clips will not play.")
    print("demo: preparing the library and footage (first run takes ~20s)...")
    library = library_for_sim(demo=demo_library)
    clock = Clock(args.speed)
    try:  # bind first: a second demo must not wipe the folders of one that is already running
        tracker.serve(tracker.Tracker(clock, library), args.host, args.tracker_port)
    except OSError as exc:
        raise SystemExit(f"demo: port {args.tracker_port} is busy ({exc.strerror}). Is another demo or the real tracker running?")
    clipper.reset()
    clipper.FakeClipper(clock, library, verbose=not args.quiet).start()

    live = f"http://{args.host}:{args.tracker_port}"
    if args.no_desk:
        sep = ";" if os.name == "nt" else ":"
        print(f"demo: tracker at {live}, clips written to {clipper.ROOT}")
        print(f"demo: start the desk with  CLIPPER_DIRS=\"sarang{sep}{clipper.ROOT}\"  and open it with ?live={live}")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return
    import uvicorn

    print(f"demo: open http://{args.host}:{args.port}/?live={live}")
    print("demo: the first play lands ~14s after start; a full cycle of 5 plays takes ~2 minutes.")
    uvicorn.run("server:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
