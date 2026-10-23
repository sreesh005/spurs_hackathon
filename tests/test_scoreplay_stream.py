"""scoreplay_stream.py: finding the recording's playlist and pointing it back at the desk.

Run from the repo root: python -m pytest tests -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scoreplay_stream as ss  # noqa: E402

PLAYLIST = "https://bucket.s3.amazonaws.com/5370/131029031/abc/hls/original.m3u8"
BASE = PLAYLIST.rsplit("/", 1)[0] + "/"


def test_playlist_url_from_the_live_master():
    media = {"video": {"live_master_url": BASE + "master.m3u8"}}
    assert ss.playlist_url(media) == PLAYLIST


def test_playlist_url_from_files_and_not_ready():
    assert ss.playlist_url({"files": [{"url": PLAYLIST}]}) == PLAYLIST
    assert ss.playlist_url({"status": "WAITING"}) is None


def test_segments_point_at_the_desk():
    text = "#EXTM3U\n#EXT-X-PLAYLIST-TYPE:EVENT\n#EXTINF:2.0,\noriginal_0.ts\n#EXTINF:2.0,\noriginal_1.ts?sig=a/b\n"
    out = ss.rewrite(text, PLAYLIST, BASE)
    assert "/api/live/stream/seg/original_0.ts\n" in out
    assert "/api/live/stream/seg/original_1.ts?q=sig%3Da%2Fb" in out
    assert "#EXT-X-PLAYLIST-TYPE:EVENT" in out


def test_variant_playlists_and_uri_attributes():
    text = '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXT-X-STREAM-INF:BANDWIDTH=1\n720p.m3u8\n'
    out = ss.rewrite(text, PLAYLIST, BASE)
    assert 'URI="/api/live/stream/seg/init.mp4"' in out
    assert "/api/live/stream/playlist.m3u8?v=720p.m3u8" in out


def test_anything_outside_the_folder_is_left_alone():
    text = "#EXTM3U\nhttps://elsewhere.example/x.ts\n../other/secret.ts\n"
    out = ss.rewrite(text, PLAYLIST, BASE)
    assert "https://elsewhere.example/x.ts" in out
    assert "../other/secret.ts" in out
    assert "/api/live/stream/seg" not in out


def test_segment_names_are_checked_before_fetching():
    stream = ss.LiveStream()
    for bad in ("../x.ts", "a/../../x.ts", "/etc/passwd", ""):
        try:
            stream.segment(bad)
        except LookupError:
            continue
        raise AssertionError(f"{bad!r} was accepted")
