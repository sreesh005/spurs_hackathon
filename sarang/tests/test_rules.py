from conftest import calm, run, sig

from pipeline import rules


def goal(t0: float = 60.0):
    """Calm baseline, a build-up rise, ~14s of loud_z 1.8 (wide -> closeup), then play restarts.

    Returns (signals, end of the loud spell)."""
    s = calm(0, t0)
    s[int(t0 // 2) - 5].cut = True  # last camera cut into the wide shot, 10s before the build-up
    s.append(sig(t0, loud_z=1.2, voice_z=1.0))  # build-up: +1.2 in one segment, wide
    t = t0 + 2
    for i in range(7):  # 14s of sustained noise; the picture cuts to a close-up after 4s
        s.append(sig(t, loud_z=1.8, voice_z=1.5, shot="wide" if i < 2 else "closeup", cut=(i == 2)))
        t += 2
    return s + calm(t, t + 10, loud_z=0.2), t  # full fires after 4s of calm


def test_goal_emits_quick_then_full(cfg):
    eng = rules.Engine(cfg)
    signals, _ = goal()
    events = run(eng, signals)
    kinds = [k for _, k, _ in events]
    assert kinds == ["arm", "quick", "full"]
    m = events[-1][2]
    assert events[1][2] is m  # one moment throughout
    assert m.start < m.peak
    assert cfg["clip"]["full_min"] <= m.end - m.start <= cfg["clip"]["full_max"]
    assert "build-up" in m.reasons and "silence" not in m.reasons
    q0, q1 = eng.quick_window(m)
    assert q0 < m.peak < q1
    assert eng.state == "cooldown"


def test_quiet_play_emits_nothing(cfg):
    eng = rules.Engine(cfg)
    wobble = [0.0, 0.3, -0.2, 0.4, -0.4, 0.1, -0.1, 0.2]  # never rises 1.0 in a segment
    signals = [sig(t, loud_z=wobble[i % len(wobble)], voice_z=wobble[(i + 3) % len(wobble)], cheer=0.1)
               for i, t in enumerate(range(0, 180, 2))]
    kinds = [k for _, k, _ in run(eng, signals)]
    assert "quick" not in kinds and "full" not in kinds
    assert kinds == []


def test_silence_then_loud_is_a_reason(cfg):
    """Away goal: home crowd falls quiet after a build-up, then the away end erupts."""
    eng = rules.Engine(cfg)
    drop = cfg["trigger"]["silence_drop"] + 0.2
    signals = calm(0, 60) + [
        sig(60, loud_z=1.1),  # build-up arms
        sig(62, loud_z=1.2),
        sig(64, loud_z=-1.0, drop=drop),  # hush
        sig(66, loud_z=-0.8),
        sig(68, loud_z=1.8),  # eruption, 4s after the hush (within silence_memory_seconds)
        sig(70, loud_z=1.8),
        sig(72, loud_z=1.8),
    ] + calm(74, 120, loud_z=0.2)
    assert 68 - 64 <= cfg["trigger"]["silence_memory_seconds"]
    events = run(eng, signals)
    quick = [m for _, k, m in events if k == "quick"]
    assert quick, [k for _, k, _ in events]
    assert "silence" in quick[0].reasons


def test_cooldown_blocks_a_second_moment(cfg):
    eng = rules.Engine(cfg)
    signals, _ = goal()
    events = run(eng, signals)
    t_full, kind, m = events[-1]
    assert kind == "full"
    cooldown_end = m.end + cfg["clip"]["cooldown_seconds"]
    t = signals[-1].t + 2
    assert t < cooldown_end
    spike = [sig(t + i * 2, loud_z=2.0, voice_z=2.0, cheer=1.0,
                 shot="wide" if i < 2 else "closeup") for i in range(int((cooldown_end - t) // 2))]
    assert spike and spike[-1].t < cooldown_end
    later = run(eng, spike)
    assert later == []
    assert eng.state == "cooldown" and eng.moment is None


def test_armed_moment_expires(cfg):
    eng = rules.Engine(cfg)
    expire = cfg["arm"]["expire_seconds"]
    events = run(eng, calm(0, 60) + [sig(60, loud_z=1.1)])
    assert [k for _, k, _ in events] == ["arm"]
    assert eng.state == "watching"
    t = 62
    while t - 60 <= expire:  # still watching up to and including expire_seconds
        assert run(eng, [sig(t)]) == []
        assert eng.state == "watching", t
        t += 2
    assert run(eng, [sig(t)]) == []
    assert eng.state == "calm" and eng.moment is None
    assert run(eng, calm(t + 2, t + 60)) == []
