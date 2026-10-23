"""live_clips.py: reading the auto-clipper's output, naming players, and grouping angles of one play.

Run from the repo root: python -m pytest tests -q
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import live_clips as lc  # noqa: E402

MEDIA = 130851979
T0 = 1792770000.0  # some afternoon, UTC
PEOPLE = [
    {"id": 1, "name": "Dominic Ayodele Solanke", "short": "Solanke"},
    {"id": 2, "name": "Mohammed Kudus", "short": "Kudus"},
    {"id": 3, "name": "Antonín Kinský", "short": "Kinsky"},
    {"id": 4, "name": "Brennan Johnson", "short": "Johnson"},
    {"id": 5, "name": "Keldon Johnson", "short": "Johnson"},
]


def record(name, event="goal", key_at=4000.0, cut="full", replay=False, players=(1,), names=("Dominic Ayodele Solanke",), highlight=True):
    return {
        "clip": f"{name}.mp4",
        "media_id": MEDIA,
        "cut": cut,
        "found_by": "rules",
        "analysis": {
            "is_highlight": highlight,
            "event_type": event,
            "team": "tottenham",
            "key_moment_seconds": 8,
            "commentary_names": ["Solanke"],
            "tottenham_players": list(names),
            "is_replay": replay,
            "caption": f"{event} caption",
            "confidence": 0.9,
        },
        "writeback": {"media_id": MEDIA, "log_at": key_at, "log_range": [key_at - 8, key_at + 12], "players": list(players), "tags": ["source:twelvelabs"]},
    }


def sidecar(start_unix, key_at):
    return {"start_unix": start_unix, "end_unix": start_unix + 16, "duration": 16, "source_start_offset": key_at - 8, "source_end_offset": key_at + 8}


def live(name, run="run", key_at=4000.0, unix=None, **kw):
    unix = T0 + (key_at - 4000.0) if unix is None else unix
    clip = lc.normalize_record(record(name, key_at=key_at, **kw), sidecar(unix - 8, key_at), name, run, unix + 30)
    assert clip is not None
    return clip


def upload(uid, key_unix, players=(), name="IMG_1 9x16.mov", date=None):
    midnight = T0 - (T0 % 86400)
    rec = {
        "ID": uid, "name": name, "type": "video", "compressed_url": f"/u/{uid}.mp4",
        "tc_in": round((key_unix - 5 - midnight) * 1000), "tc_out": round((key_unix + 5 - midnight) * 1000),
        "date": date or lc._day(key_unix), "player_ids": list(players),
    }
    return lc.normalize_upload(rec, key_unix + 40)


def library_play(pid, action="GOAL", angles=(("A", 900),), title="Solanke goal", date="2026-09-28"):
    return {
        "id": f"cut-{title.lower().replace(' ', '-')}",
        "club": "thfc",
        "mode": "action",
        "action": action,
        "title": title,
        "importance": 0.9,
        "named_id": pid,
        "players": [{"id": pid}],
        "captions": {"matchday": f"{title}."},
        "angles": [{"id": mid, "label": label, "video": f"/v/{mid}.mp4", "thumb": "", "duration": 8, "tc_in": 1000, "tc_out": 9000, "date": date} for label, mid in angles],
    }


# ---------- normalizing ----------


def test_none_is_skipped():
    assert lc.normalize_record(record("x", event="none"), None, "x", "run", T0) is None


def test_match_time_is_the_key_moment_not_the_log_window():
    clip = live("m1_full_1", key_at=4000.0)
    assert clip.match == (MEDIA, 4000.0 - lc.KEY_SPAN, 4000.0 + lc.KEY_SPAN)
    assert clip.extra["log_range"] == [3992.0, 4012.0]
    assert clip.group_hint == "run:m1"
    assert clip.label == "Broadcast"


def test_a_replay_has_no_capture_time():
    clip = live("m9_full_1", replay=True)
    assert clip.label == "Broadcast replay"
    assert clip.tod is None and clip.match is not None


def test_captured_at_never_in_the_future():
    rec = record("m1_full_1")
    clip = lc.normalize_record(rec, sidecar(T0 + 999, 4000), "k", "run", seen_at=T0)
    assert clip.captured_at == T0


# ---------- players ----------


def test_tagged_ids_win():
    assert lc.resolve_players(live("m1_full_1", players=(2,), names=("Dominic Ayodele Solanke",)), PEOPLE) == [2]


def test_names_when_untagged():
    assert lc.resolve_players(live("m1_full_1", players=(), names=("Dominic Ayodele Solanke",)), PEOPLE) == [1]
    assert lc.resolve_players(live("m1_full_1", players=(), names=("Kudus",)), PEOPLE) == [2]
    assert lc.resolve_players(live("m1_full_1", players=(), names=("Antonín Kinský",)), PEOPLE) == [3]


def test_two_johnsons_is_not_a_guess():
    assert lc.resolve_players(live("m1_full_1", players=(), names=("Johnson",)), PEOPLE) == []


def test_unknown_ids_fall_back_to_names():
    assert lc.resolve_players(live("m1_full_1", players=(999,), names=("Mohammed Kudus",)), PEOPLE) == [2]


# ---------- grouping ----------


def by_size(moments):
    return sorted(len(m["angles"]) for m in moments)


def test_quick_and_full_of_one_moment_group():
    moments = lc.group_moments([live("m1_quick_1", cut="quick"), live("m1_full_1")])
    assert by_size(moments) == [2]


def test_broadcast_replay_joins_the_play():
    play = live("m1_full_1", key_at=4000)
    replay = live("m1001_full_2", key_at=4012, replay=True)
    moments = lc.group_moments([play, replay])
    assert by_size(moments) == [2]
    assert "broadcast replay of the play" in moments[0]["grouped_by"]
    assert moments[0]["angles"][0]["label"] == "Broadcast"  # the live angle leads


def test_plays_18s_apart_stay_apart():
    # their log windows (key-8..key+12) overlap, their key moments don't
    a = live("m1_full_1", key_at=4000, event="save")
    b = live("m2_full_2", key_at=4018, event="tackle")
    assert by_size(lc.group_moments([a, b])) == [1, 1]


def test_replay_of_another_event_stays_apart():
    play = live("m1_full_1", key_at=4000, event="save")
    replay = live("m1001_full_2", key_at=4012, event="goal", replay=True)
    assert by_size(lc.group_moments([play, replay])) == [1, 1]


def test_untagged_phone_upload_joins_by_capture_time():
    play = live("m1_full_1", key_at=4000)
    phone = upload(77, key_unix=T0 + 1)
    moments = lc.group_moments([play, phone])
    assert by_size(moments) == [2]
    assert "same capture time" in moments[0]["grouped_by"]
    assert moments[0]["player_ids"] == [1]  # the phone clip inherits the player from the live angle


def test_phone_upload_from_another_day_does_not_join():
    play = live("m1_full_1", key_at=4000)
    phone = upload(77, key_unix=T0 + 1, date="2026-09-28")
    assert by_size(lc.group_moments([play, phone])) == [1, 1]


def test_same_media_ignores_capture_time():
    # sped-up or skewed wall clocks must not merge two plays the match clock keeps apart
    a = live("m1_full_1", key_at=4000, unix=T0)
    b = live("m2_full_2", key_at=4030, unix=T0 + 1, event="save")
    assert by_size(lc.group_moments([a, b])) == [1, 1]


def test_library_goal_joins_the_live_goal_by_content():
    clips = [live("m1_full_1")] + lc.library_clips({"plays": [library_play(1, angles=(("16x9", 900), ("9x16", 901)))]})
    moments = lc.group_moments(clips)
    assert by_size(moments) == [3]
    assert "same goal, same player" in moments[0]["grouped_by"]


def test_library_tackle_needs_more_than_content():
    clips = [live("m1_full_1", event="tackle")] + lc.library_clips({"plays": [library_play(1, action="TACKLE", title="Solanke tackle")]})
    assert by_size(lc.group_moments(clips)) == [1, 1]


def test_a_brace_keeps_the_library_goal_on_one_of_them():
    first = live("m1_full_1", key_at=4000)
    second = live("m2_full_2", key_at=4200)
    clips = [first, second] + lc.library_clips({"plays": [library_play(1)]})
    assert by_size(lc.group_moments(clips)) == [1, 2]


def test_two_library_plays_never_merge():
    lib = lc.library_clips({"plays": [library_play(1), library_play(1, title="Solanke goal again", angles=(("A", 950),))]})
    assert by_size(lc.group_moments(lib)) == [1, 1]


# ---------- the index tailing real files ----------


def write_run(root: Path, records, partial: str = ""):
    (root / "runs").mkdir(parents=True, exist_ok=True)
    (root / "clips").mkdir(parents=True, exist_ok=True)
    run = root / "runs" / "live_20261023T000000Z.jsonl"
    with run.open("a", encoding="utf-8") as f:
        for rec in records:
            (root / "clips" / rec["clip"]).write_bytes(b"\x00")
            f.write(json.dumps(rec) + "\n")
        f.write(partial)
    return run


def library():
    club = {"id": "thfc", "lineup": [dict(p) for p in PEOPLE[:3]], "bench": []}
    return {"clubs": [club], "plays": [library_play(2, action="CHANCE", title="Kudus chance")]}


def test_index_tails_supersedes_and_falls_back(tmp_path):
    root = tmp_path / "clipper"
    index = lc.ClipIndex([root], library(), min_refresh=0)
    write_run(root, [record("m1_quick_1", cut="quick")], partial='{"clip": "half')
    feed = index.feed()
    assert feed["counts"] == {"1": 1} and feed["live_clips"] == 1

    write_run(root, [])  # nothing new: the half line is still waiting
    assert index.feed()["live_clips"] == 1

    run = root / "runs" / "live_20261023T000000Z.jsonl"
    text = run.read_text(encoding="utf-8")
    run.write_text(text[: text.rfind('{"clip": "half')], encoding="utf-8")  # the writer finishes the file properly
    write_run(root, [record("m1_full_1")])
    index.refresh(force=True)
    solanke = index.for_player(1)
    assert solanke["showing"] == "live"
    assert len(solanke["live"]) == 1
    assert [a["label"] for a in solanke["live"][0]["angles"]] == ["Broadcast"]  # quick cut replaced
    assert solanke["live"][0]["angles"][0]["video"].startswith("/api/live/media/clipper-m1_full_1.mp4")
    assert index.media_path("clipper-m1_full_1") == root / "clips" / "m1_full_1.mp4"
    assert index.media_path("../../etc/passwd") is None

    kudus = index.for_player(2)
    assert kudus["showing"] == "scoreplay" and kudus["live"] == [] and len(kudus["library"]) == 1

    kinsky = index.for_player(3)
    assert kinsky["showing"] == "none"


# ---------- clips read back from ScorePlay (what the auto-clipper wrote) ----------


def sp_log(log_id, clip="m1_full_1792770000", event="goal", start=3992.0, players=({"id": 1, "name": "Dominic Ayodele Solanke"},), url="https://cdn.scoreplay.io/x/clip.m3u8", extra_tags=()):
    return {
        "ID": log_id, "start_offset": start, "end_offset": start + 20,
        "comment": 'Solanke equalises.\nCommentary: "What a finish!"',
        "raw_tags": ["source:twelvelabs", f"event:{event}", "team:tottenham", f"cut:{'quick' if '_quick_' in clip else 'full'}", f"clip:{clip}", *extra_tags],
        "players": list(players), "playback_url": url, "created_at": "2026-10-23T20:00:00Z",
    }


def test_a_log_becomes_a_clip():
    clip = lc.normalize_log(sp_log(17905257), MEDIA, T0 + 1e6, relay=lambda u: "/relay?" + u)
    assert clip.id == "log:17905257" and clip.source == "live" and clip.event == "goal"
    assert clip.caption == "Solanke equalises." and clip.extra["quote"] == "What a finish!"
    assert clip.match == (MEDIA, 4000.0 - lc.KEY_SPAN, 4000.0 + lc.KEY_SPAN)  # key moment 8s into the log
    assert clip.player_ids == [1] and clip.video.startswith("/relay?")


def test_logs_not_from_the_pipeline_or_without_a_clip_are_ignored():
    manual = sp_log(1); manual["raw_tags"] = ["goal"]
    assert lc.normalize_log(manual, MEDIA, T0) is None
    assert lc.normalize_log(sp_log(2, url=""), MEDIA, T0) is None


def test_tag_objects_are_read_too():
    log = sp_log(3); log["raw_tags"] = [{"name": t} for t in log["raw_tags"]]
    assert lc.normalize_log(log, MEDIA, T0).event == "goal"


def test_scoreplay_copy_replaces_the_local_file_and_updates_count(tmp_path):
    root = tmp_path / "sarang"
    index = lc.ClipIndex([root], library(), min_refresh=0)
    write_run(root, [record("m1_full_1792770000")])
    assert index.feed()["live_clips"] == 1
    v = index.version
    assert index.add_scoreplay_logs(MEDIA, [sp_log(11)]) == 1
    feed = index.feed()
    assert index.version > v
    assert feed["live_clips"] == 1 and feed["from_scoreplay"] == 1
    angles = index.for_player(1)["live"][0]["angles"]
    assert [a["id"] for a in angles] == ["log:11"]
    # same log again: nothing changes
    v = index.version
    assert index.add_scoreplay_logs(MEDIA, [sp_log(11)]) == 0 and index.version == v


def test_players_added_later_in_scoreplay_show_up(tmp_path):
    index = lc.ClipIndex([tmp_path], library(), min_refresh=0)
    untagged = sp_log(12, players=()); untagged["comment"] = "Equaliser at the far post."  # nobody named
    index.add_scoreplay_logs(MEDIA, [untagged])
    assert index.feed()["counts"] == {}
    tagged = sp_log(12, players=({"id": 2, "name": "Mohammed Kudus"},)); tagged["comment"] = untagged["comment"]
    index.add_scoreplay_logs(MEDIA, [tagged])  # face recognition tagged him
    assert index.feed()["counts"] == {"2": 1}


def test_quick_and_full_logs_group_and_the_replay_joins(tmp_path):
    index = lc.ClipIndex([tmp_path], library(), min_refresh=0)
    index.add_scoreplay_logs(MEDIA, [
        sp_log(21, clip="m4_quick_1792770000"),
        sp_log(22, clip="m4_full_1792770000"),
        sp_log(23, clip="m1004_full_1792770012", start=4004.0, extra_tags=("replay",)),
    ])
    live = index.for_player(1)["live"]
    assert len(live) == 1
    assert [a["label"] for a in live[0]["angles"]] == ["Broadcast", "Broadcast replay"]


def test_players_named_in_the_caption_when_scoreplay_has_no_tag():
    people = PEOPLE + [{"id": 6, "name": "Jan Paul van Hecke", "short": "Van Hecke"}]
    clip = lc.normalize_log(sp_log(30, players=()), MEDIA, T0)
    clip.caption = "Jan Paul van Hecke receives a yellow card; Kinsky looks on."
    assert lc.resolve_players(clip, people) == [6, 3] or sorted(lc.resolve_players(clip, people)) == [3, 6]
    clip.caption = "Johnson shoots wide."  # two Johnsons: no guess
    assert lc.resolve_players(clip, people) == []
