#!/bin/bash
# One command for the whole Live dots demo (run from anywhere):
#   live/demo.sh start [clip.mp4] | stop | status | logs
# Uses whatever python3 is active (activate your venv first). Starts the UI server, the Twelve Labs transcript and the
# looping dots in the background, restarts any that crash, keeps the machine awake (Mac), logs to live/run/.
LIVE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$LIVE/.." && pwd)"; RUN="$LIVE/run"; mkdir -p "$RUN"
CLIP="${2:-${CLIP:-$LIVE/clips/demo90.mp4}}"
keep() { local name=$1 dir=$2; shift 2
  ( cd "$dir" && while true; do "$@" >>"$RUN/$name.log" 2>&1; echo "[$(date +%T)] $name exited, restarting in 3s" >>"$RUN/$name.log"; sleep 3; done ) &
  echo $! >"$RUN/$name.pid"; }
case "$1" in
  start)
    "$0" stop >/dev/null 2>&1
    [ -f "$CLIP" ] || { echo "No clip at $CLIP. Pass one:  live/demo.sh start path/to/clip.mp4"; exit 1; }
    [ -f "$ROOT/.env" ] || { echo "No .env in $ROOT (needs SCOREPLAY_API_KEY and TWELVELABS_API_KEY)"; exit 1; }
    for n in ui tl dots; do : >"$RUN/$n.log"; done
    command -v caffeinate >/dev/null && { caffeinate -i -w $$ >/dev/null 2>&1 & }
    CACHE="$RUN/clip_transcript.json"; UP="--upload $CLIP"; [ -f "$CACHE" ] && [ "$CACHE" -nt "$CLIP" ] && UP=""
    keep ui   "$ROOT" python3 -m uvicorn server:app --host 127.0.0.1 --port 8765
    keep tl   "$LIVE" python3 tl_transcript.py $UP --serve 8767 --env "$ROOT/.env" --cache "$CACHE"
    keep dots "$LIVE" python3 hack_live_dots12.py --src "$CLIP" --loop --serve 8766 --noshow
    echo "Started. The dots take about a minute to find the pitch. Open http://127.0.0.1:8765 (Live dots tab), then hard-refresh."
    echo "live/demo.sh status | logs | stop"
    trap '"$0" stop' INT TERM; wait ;;
  stop)
    for n in ui tl dots; do [ -f "$RUN/$n.pid" ] && kill "$(cat "$RUN/$n.pid")" 2>/dev/null; rm -f "$RUN/$n.pid"; done
    pkill -f "uvicorn server:app" 2>/dev/null; pkill -f tl_transcript.py 2>/dev/null; pkill -f hack_live_dots12.py 2>/dev/null; echo stopped ;;
  status)
    for p in "UI:8765:/" "dots:8766:/state.json" "transcript:8767:/clip_transcript.json"; do IFS=: read n port path <<<"$p"
      code=$(curl -s -o /dev/null -m 3 -w "%{http_code}" "http://127.0.0.1:$port$path"); echo "$n  port $port  -> ${code/000/not responding}"; done
    echo "dots ready? $(curl -s -m 3 http://127.0.0.1:8766/state.json | python3 -c 'import sys,json;print("yes" if json.load(sys.stdin).get("ready") else "not yet")' 2>/dev/null || echo no)" ;;
  logs) tail -n 20 "$RUN"/*.log ;;
  *) echo "usage: live/demo.sh start [clip.mp4] | stop | status | logs" ;;
esac
