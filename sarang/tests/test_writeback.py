"""Request bodies for the ScorePlay write-back. No network: squad, settings and client are faked."""

import dataclasses
from pathlib import Path

import pytest

from pipeline import clients, config, scoreplay_data, writeback

SQUAD = [{"id": 1, "name": "Dominic Ayodele Solanke-Mitchell"}, {"id": 2, "name": "Xavi Quentin Shay Simons"},
         {"id": 3, "name": "Mateus Gonçalo Espanha Fernandes"}, {"id": 4, "name": "Richarlison de Andrade"}]


def make_run(key=24, start=5800.0, end=5845.0, event="goal", highlight=True, **extra):
    return {"clip_id": "t2_goal_tot", "clip": {"source_start_offset": start, "source_end_offset": end},
            "analysis": {"is_highlight": highlight, "event_type": event, "team": "tottenham",
                         "key_moment_seconds": key, "caption": "Solanke equalizes.", "confidence": 0.95,
                         "commentary_names": ["Dominic Solanke", "Xavi"], "is_replay": False,
                         "tottenham_players": ["Dominic Ayodele Solanke-Mitchell", "Richarlison de Andrade"],
                         **extra}}


class FakeApi:
    def __init__(self):
        self.calls = []

    def write(self, method, path, body=None, **kw):
        self.calls.append((method, path, body))
        return None  # behaves like DRY_RUN


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(scoreplay_data, "squad", lambda: SQUAD)
    s = dataclasses.replace(config.load(), scoreplay_company_id=5370, scoreplay_media_id=130851979,
                            scoreplay_event_id=1536128, dry_run=True)
    monkeypatch.setattr(config, "load", lambda: s)
    api = FakeApi()
    monkeypatch.setattr(clients, "scoreplay", lambda _s: api)
    return api


def test_log_body_offset_range_no_external_id():
    body = writeback.build_log_body(make_run(), 131029031, 5370, [1], ["event:goal"])
    entry = body["video_logs"][0]
    assert body["company_id"] == 5370 and entry["media_id"] == 131029031
    assert "external_id" not in entry
    log = entry["log"]
    assert "offset" not in log and "start_timestamp" not in log and "action_timestamp" not in log
    assert (log["start_offset"], log["end_offset"]) == (5816.0, 5836.0)
    assert "source:twelvelabs" in log["raw_tags"] and "clip:t2_goal_tot" in log["raw_tags"]
    assert log["player_ids"] == [1]


def test_log_range_clamped_inside_clip():
    assert writeback.log_range(make_run(key=3))[1:] == (5800.0, 5815.0)    # near the start
    assert writeback.log_range(make_run(key=40))[1:] == (5832.0, 5845.0)   # near the end
    assert writeback.log_range(make_run(key=90))[1:] == (5837.0, 5845.0)   # key past the clip end


def test_upload_body_and_name():
    run = make_run()
    assert writeback.upload_name(run) == "goal_tottenham_t2_goal_tot.mp4"
    body = writeback.build_upload_body("x.mp4", "cap", ["event:goal"])
    assert body["name"] == "x.mp4" and body["description"] == "cap" and "source:twelvelabs" in body["raw_tags"]


def test_player_filter_needs_commentary(fake):
    assert writeback.player_ids(make_run()["analysis"]) == [1]  # Richarlison not heard


@pytest.mark.parametrize("event", ["substitution", "none"])
def test_skip_makes_no_write(fake, event):
    assert writeback.deliver(make_run(event=event), Path("missing.mp4")) == {"skipped": event}
    assert fake.calls == []


def test_media_id_default_and_explicit(fake):
    writeback.deliver(make_run(highlight=False), Path("missing.mp4"))
    writeback.deliver(make_run(highlight=False), Path("missing.mp4"), media_id=131029031)
    assert [c[2]["video_logs"][0]["media_id"] for c in fake.calls] == [130851979, 131029031]
    assert all(c[1] == "/video/logs" for c in fake.calls)  # not a highlight: no upload


def test_highlight_also_uploads(fake):
    out = writeback.deliver(make_run(), Path("missing.mp4"), media_id=131029031)
    paths = [c[1] for c in fake.calls]
    assert paths == ["/video/logs", "/upload/event/1536128"]
    assert fake.calls[1][2]["name"] == "goal_tottenham_t2_goal_tot.mp4"
    assert out["upload"] == {"dry_run": True, "name": "goal_tottenham_t2_goal_tot.mp4"}


def test_player_hyphenated_surname_heard_alone(fake):
    """Commentary often says just "Solanke": that must match "Solanke-Mitchell"."""
    a = make_run(commentary_names=["Solanke"])["analysis"]
    assert writeback.player_ids(a) == [1]
