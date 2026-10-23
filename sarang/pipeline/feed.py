"""M1: rolling buffer over the live HLS feed, and cutting clips from it.

The playlist only lists ~6 segments (12s), so we poll it and keep our own
copy of the last `keep` segments. Each segment carries its wall-clock time
(EXT-X-PROGRAM-DATE-TIME) and its offset in the source match (N * 2s from
the `video_N.ts` name), so a clip can be addressed either way.
"""

import json
import re
import subprocess
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .config import ROOT

SEGMENTS_DIR = ROOT / "segments"
CLIPS_DIR = ROOT / "clips"
SEGMENT_SECONDS = 2.0  # EXT-X-TARGETDURATION; video_N.ts starts at N * 2s in the source
# Organizer feed: video_001234.ts. ScorePlay live recording: original_12.ts / 720p_12.ts.
# Either way N * 2s is the segment's offset into its source (the match, or the recording).
NAME_RE = re.compile(r"_(\d+)\.ts")


@dataclass
class Segment:
    seq: int  # media sequence number, unique across loops of the replay
    name: str  # video_NNNNNN.ts, repeats every loop
    url: str
    pdt: str  # wall-clock start, ISO 8601
    start_unix: float
    duration: float
    source_offset: float  # start offset in the source match, seconds
    discontinuity: bool
    path: str = ""

    @property
    def end_unix(self) -> float:
        return self.start_unix + self.duration


def parse_playlist(text: str, base_url: str = "") -> list[Segment]:
    from urllib.parse import urljoin

    media_seq = int(re.search(r"#EXT-X-MEDIA-SEQUENCE:(\d+)", text).group(1))
    out, pdt, dur, disc = [], None, SEGMENT_SECONDS, False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            pdt = line.split(":", 1)[1]
        elif line.startswith("#EXTINF:"):
            dur = float(line.split(":", 1)[1].rstrip(","))
        elif line == "#EXT-X-DISCONTINUITY":
            disc = True
        elif line and not line.startswith("#"):
            name = line.rsplit("/", 1)[-1]
            n = int(NAME_RE.search(name).group(1))
            start = datetime.fromisoformat(re.sub(r"\+0000$", "+00:00", pdt.replace("Z", "+00:00"))).timestamp()
            out.append(Segment(media_seq + len(out), name, urljoin(base_url, line), pdt, start, dur,
                               n * SEGMENT_SECONDS, disc))
            disc = False
    return out


class Buffer:
    """Polls the playlist and keeps the last `keep` segments on disk."""

    def __init__(self, feed_url: str, keep: int = 30):
        self.feed_url = feed_url
        self.segments: deque[Segment] = deque()
        self.keep = keep
        self.http = httpx.Client(timeout=20)
        SEGMENTS_DIR.mkdir(exist_ok=True)
        for old in SEGMENTS_DIR.glob("*.ts"):  # the buffer lives in memory, so files from old runs are stale
            old.unlink()

    def poll(self) -> list[Segment]:
        """Fetch the playlist once, download segments we don't have. Returns the new ones."""
        listed = parse_playlist(self.http.get(self.feed_url).text, self.feed_url)
        if not self.segments:
            listed = listed[-3:]  # a recording's playlist lists everything since it began: start from now
        last = self.segments[-1].seq if self.segments else -1
        new = [s for s in listed if s.seq > last]
        for s in new:
            path = SEGMENTS_DIR / f"{s.seq}.ts"
            path.write_bytes(self.http.get(s.url).content)
            s.path = str(path)
            self.segments.append(s)
        while len(self.segments) > self.keep:
            Path(self.segments.popleft().path).unlink(missing_ok=True)
        return new

    def window(self, start_unix: float, end_unix: float) -> list[Segment]:
        return [s for s in self.segments if s.end_unix > start_unix and s.start_unix < end_unix]


def cut(segments: list[Segment], clip_id: str | None = None) -> Path:
    """Concat segments into clips/<id>.mp4 and write clips/<id>.json next to it."""
    if not segments:
        raise ValueError("no segments to cut")
    CLIPS_DIR.mkdir(exist_ok=True)
    first, last = segments[0], segments[-1]
    clip_id = clip_id or "clip_" + datetime.fromtimestamp(first.start_unix, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mp4 = CLIPS_DIR / f"{clip_id}.mp4"
    # TS segments of one stream join byte for byte, which keeps timestamps continuous
    # (the concat demuxer produced duplicate DTS here).
    joined = "concat:" + "|".join(str(Path(s.path).resolve()) for s in segments)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", joined, "-c", "copy", "-movflags", "+faststart", str(mp4)],
        check=True,
    )
    meta = {
        "id": clip_id,
        "file": str(mp4.relative_to(ROOT)),
        "start_pdt": first.pdt,
        "end_pdt": datetime.fromtimestamp(last.end_unix, timezone.utc)
        .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "start_unix": first.start_unix,
        "end_unix": last.end_unix,
        "duration": round(last.end_unix - first.start_unix, 3),
        "source_start_offset": first.source_offset,
        "source_end_offset": last.source_offset + last.duration,
        "discontinuity": any(s.discontinuity for s in segments[1:]),
        "segments": [{k: v for k, v in asdict(s).items() if k not in ("url", "path")} for s in segments],
    }
    mp4.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return mp4


def cut_source(source_url: str, media_id: int, start: float, end: float, clip_id: str) -> Path:
    """Cut a test clip straight from the recorded match, re-encoded to 720p like the feed."""
    CLIPS_DIR.mkdir(exist_ok=True)
    mp4 = CLIPS_DIR / f"{clip_id}.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", source_url, "-t", str(end - start),
         "-vf", "scale=-2:720", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(mp4)],
        check=True,
    )
    meta = {
        "id": clip_id,
        "file": str(mp4.relative_to(ROOT)),
        "source_media_id": media_id,
        "source_start_offset": start,
        "source_end_offset": end,
        "duration": end - start,
        "start_unix": None,  # not from the live feed, so no wall-clock time
        "end_unix": None,
    }
    mp4.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return mp4


def record(feed_url: str, seconds: float, poll_every: float = 2.0) -> Path:
    """Record `seconds` of the feed from now on and cut it into a clip."""
    buf = Buffer(feed_url)
    buf.poll()  # prime: we only want segments that start after this point
    start = buf.segments[-1].end_unix if buf.segments else time.time()
    print(f"recording {seconds:.0f}s from {datetime.fromtimestamp(start, timezone.utc):%H:%M:%S}Z")
    while True:
        time.sleep(poll_every)
        for s in buf.poll():
            print(f"  + {s.name}  {s.pdt}  source {s.source_offset:.0f}s")
        got = buf.window(start, float("inf"))
        if got and got[-1].end_unix - got[0].start_unix >= seconds:
            return cut(got)
