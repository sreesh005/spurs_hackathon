from datetime import datetime, timezone

from pipeline.feed import parse_playlist

ORGANIZER = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:2
#EXT-X-MEDIA-SEQUENCE:36725
#EXT-X-DISCONTINUITY-SEQUENCE:11
#EXT-X-PROGRAM-DATE-TIME:2026-10-22T20:23:58.560Z
#EXTINF:2.000000,
https://feed.example.com/live/hls/video_001877.ts
#EXT-X-PROGRAM-DATE-TIME:2026-10-22T20:24:00.560Z
#EXTINF:2.000000,
https://feed.example.com/live/hls/video_001878.ts
#EXT-X-DISCONTINUITY
#EXT-X-PROGRAM-DATE-TIME:2026-10-22T20:24:02.560Z
#EXTINF:2.000000,
https://feed.example.com/live/hls/video_000000.ts
#EXT-X-PROGRAM-DATE-TIME:2026-10-22T20:24:04.560Z
#EXTINF:2.000000,
https://feed.example.com/live/hls/video_000001.ts
"""

SCOREPLAY = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:2
#EXT-X-PLAYLIST-TYPE:EVENT
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-DISCONTINUITY
#EXTINF:2.000000,
#EXT-X-PROGRAM-DATE-TIME:2026-10-23T13:18:48.924+0000
original_0.ts
#EXTINF:2.000000,
#EXT-X-PROGRAM-DATE-TIME:2026-10-23T13:18:50.924+0000
original_1.ts
#EXTINF:2.000000,
#EXT-X-PROGRAM-DATE-TIME:2026-10-23T13:18:52.924+0000
original_2.ts
"""


def _unix(*args) -> float:
    return datetime(*args, tzinfo=timezone.utc).timestamp()


def test_organizer_feed():
    segs = parse_playlist(ORGANIZER, "https://feed.example.com/live/hls/index.m3u8")
    assert [s.seq for s in segs] == [36725, 36726, 36727, 36728]
    assert [s.name for s in segs] == ["video_001877.ts", "video_001878.ts", "video_000000.ts", "video_000001.ts"]
    assert segs[0].url == "https://feed.example.com/live/hls/video_001877.ts"  # absolute URL kept as is
    assert [s.source_offset for s in segs] == [1877 * 2, 1878 * 2, 0, 2]
    assert segs[0].start_unix == _unix(2026, 10, 22, 20, 23, 58, 560000)
    assert segs[1].start_unix - segs[0].start_unix == 2.0
    assert [s.duration for s in segs] == [2.0] * 4
    assert segs[0].end_unix == segs[0].start_unix + 2.0
    # only the segment right after the tag is flagged
    assert [s.discontinuity for s in segs] == [False, False, True, False]


def test_scoreplay_recording():
    base = "https://live.example.com/rec/abc123/original.m3u8"
    segs = parse_playlist(SCOREPLAY, base)
    assert [s.seq for s in segs] == [0, 1, 2]
    assert [s.name for s in segs] == ["original_0.ts", "original_1.ts", "original_2.ts"]
    assert [s.url for s in segs] == [f"https://live.example.com/rec/abc123/original_{i}.ts" for i in range(3)]
    assert [s.source_offset for s in segs] == [0.0, 2.0, 4.0]
    # +0000 offset and EXTINF before the PDT
    assert segs[0].pdt == "2026-10-23T13:18:48.924+0000"
    assert segs[0].start_unix == _unix(2026, 10, 23, 13, 18, 48, 924000)
    assert segs[2].start_unix - segs[0].start_unix == 4.0
    assert [s.discontinuity for s in segs] == [True, False, False]
