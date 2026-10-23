import statistics

import pytest

from pipeline.signals import Signals, Tracker, bucket


def _s(loudness: float, voice: float | None = None, roar: float = 0.0, t: float = 0.0) -> Signals:
    return Signals(t=t, duration=2.0, loudness=loudness, voice=loudness if voice is None else voice, roar=roar)


def test_z_is_zero_until_five_samples():
    tr = Tracker()
    for i in range(5):
        s = tr.update(_s(-30.0 + i * 3))
        assert s.loud_z == 0.0 and s.voice_z == 0.0
    assert tr.update(_s(-10.0)).loud_z > 0


def test_flat_baseline_uses_sd_floor():
    tr = Tracker()
    for _ in range(5):
        tr.update(_s(-30.0, voice=-35.0))
    s = tr.update(_s(-27.0, voice=-38.0))
    assert s.loud_z == pytest.approx(3.0 / 1.5)
    assert s.voice_z == pytest.approx(-3.0 / 1.5)


def test_wide_baseline_uses_real_sd():
    tr = Tracker()
    hist = [-30.0, -26.0, -34.0, -30.0, -30.0]
    for x in hist:
        tr.update(_s(x))
    sd = statistics.pstdev(hist)
    assert sd > 1.5
    assert tr.update(_s(-25.0)).loud_z == pytest.approx(5.0 / sd)


def test_drop_is_recent_max_minus_now():
    tr = Tracker()
    for _ in range(5):
        assert tr.update(_s(-30.0)).drop == pytest.approx(0.0)
    peak = tr.update(_s(-27.0))
    assert peak.loud_z == pytest.approx(2.0)
    hush = tr.update(_s(-30.0))
    expected_z = (-30.0 - statistics.fmean([-30.0] * 5 + [-27.0])) / 1.5  # pstdev 1.12 < floor
    assert hush.loud_z == pytest.approx(expected_z)
    assert hush.drop == pytest.approx(2.0 - expected_z)
    # the peak leaves the 6s memory (3 segments) after three more
    for _ in range(3):
        last = tr.update(_s(-30.0))
    assert last.drop < 1.0


def test_cheer_is_relative_to_roar_baseline():
    tr = Tracker()
    assert tr.update(_s(-30, roar=0.6)).cheer == 0.0  # first sample is its own baseline
    for _ in range(4):
        tr.update(_s(-30, roar=0.6))
    assert tr.update(_s(-30, roar=0.65)).cheer == pytest.approx((0.65 - statistics.fmean([0.6] * 5)) / 0.1)
    tr2 = Tracker()
    for _ in range(5):
        tr2.update(_s(-30, roar=0.2))
    assert tr2.update(_s(-30, roar=0.9)).cheer == 1.0  # capped
    assert tr2.update(_s(-30, roar=0.0)).cheer == 0.0  # below baseline


def test_bucket_groups_into_2s_segments():
    series = [(round(i * 0.1, 1), -20.0 - (i // 20), -25.0 - (i // 20)) for i in range(60)]  # 6s
    out = bucket(series, offset=4600.0)
    assert [s.t for s in out] == [4600.0, 4602.0, 4604.0]
    assert [s.duration for s in out] == [2.0] * 3
    assert [s.loudness for s in out] == pytest.approx([-20.0, -21.0, -22.0])
    assert [s.voice for s in out] == pytest.approx([-25.0, -26.0, -27.0])


def test_bucket_partial_last_segment():
    series = [(round(i * 0.1, 1), -20.0, -25.0) for i in range(25)]  # 2.5s
    out = bucket(series, offset=0.0)
    assert [s.t for s in out] == [0.0, 2.0]
