from pipeline.sweep import missed

EVENTS = [
    {"seconds": 10, "event_type": "shot_on_target", "team": "tottenham", "caption": "a"},
    {"seconds": 100, "event_type": "save", "team": "manchester_united", "caption": "b"},
    {"seconds": "250.5", "event_type": "corner", "team": "tottenham", "caption": "c"},
]


def test_drops_events_near_clips_and_keeps_others():
    out = missed(EVENTS, window_start=1000.0, clipped_times=[1015.0], within=20)
    assert [e["caption"] for e in out] == ["b", "c"]
    assert [e["at"] for e in out] == [1100.0, 1250.5]
    assert out[0]["event_type"] == "save" and out[0]["seconds"] == 100  # original fields kept


def test_within_is_inclusive():
    out = missed(EVENTS[:1], window_start=1000.0, clipped_times=[1030.0], within=20)
    assert out == []
    out = missed(EVENTS[:1], window_start=1000.0, clipped_times=[1030.1], within=20)
    assert [e["at"] for e in out] == [1010.0]


def test_no_clips_keeps_everything():
    out = missed(EVENTS, window_start=0.0, clipped_times=[], within=20)
    assert [e["at"] for e in out] == [10.0, 100.0, 250.5]
    assert missed([], 0.0, [5.0], 20) == []
