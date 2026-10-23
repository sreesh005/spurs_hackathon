from pipeline.scoreplay_live import is_finished, playlist_url

FOLDER = "https://example-bucket.s3.amazonaws.example/hls/123/abcd"  # shape of a real recording folder


def test_playlist_url_from_live_master():
    media = {"status": "DONE", "video": {"live_master_url": f"{FOLDER}/master.m3u8",
                                         "proxy_large": f"{FOLDER}/1080p.m3u8"}}
    assert playlist_url(media) == f"{FOLDER}/original.m3u8"


def test_playlist_url_not_ready():
    assert playlist_url({"status": "WAITING", "video": {}, "files": []}) is None
    assert playlist_url({"status": "WAITING", "video": None, "files": None}) is None
    assert playlist_url({"video": {"live_master_url": ""}}) is None


def test_playlist_url_files_fallback():
    media = {"video": {}, "files": [{"details": "thumbnail_quality", "url": f"{FOLDER}/thumbnail.jpg"},
                                    {"details": "photographer_quality", "url": f"{FOLDER}/original.m3u8"}]}
    assert playlist_url(media) == f"{FOLDER}/original.m3u8"


def test_is_finished():
    growing = "#EXTM3U\n#EXT-X-PLAYLIST-TYPE:EVENT\n#EXTINF:2.000000,\noriginal_0.ts\n"
    assert not is_finished(growing)
    assert is_finished(growing + "#EXT-X-ENDLIST\n")
