"""Pure-logic tests for mp_signals: no models, no video files."""

from types import SimpleNamespace

import yaml

from pipeline.config import ROOT
from pipeline.mp_signals import SegmentView, arms_up, shot_type

SHOT = yaml.safe_load((ROOT / "rules.yaml").read_text())["shot"]


def pose(l_wrist: float, r_wrist: float, shoulders: float = 0.4) -> list:
    """33 landmarks at y=0.5, with shoulders (11, 12) and wrists (15, 16) set."""
    pts = [SimpleNamespace(y=0.5) for _ in range(33)]
    pts[11].y = pts[12].y = shoulders
    pts[15].y, pts[16].y = l_wrist, r_wrist
    return pts


def test_arms_up_raised():
    assert arms_up([pose(0.2, 0.6)])  # left wrist above left shoulder
    assert arms_up([pose(0.6, 0.1)])


def test_arms_up_not_raised():
    assert not arms_up([pose(0.6, 0.7)])


def test_arms_up_multiple_poses():
    assert arms_up([pose(0.6, 0.7), pose(0.3, 0.6)])
    assert not arms_up([pose(0.6, 0.7), pose(0.5, 0.45)])


def test_arms_up_empty():
    assert not arms_up([])
    assert not arms_up([[]])


def test_shot_closeup():
    assert shot_type(SegmentView(face_share=SHOT["closeup_face_share"]), SHOT) == "closeup"
    assert shot_type(SegmentView(people=1, person_height=0.8, green=0.0), SHOT) == "closeup"


def test_shot_wide():
    assert shot_type(SegmentView(people=SHOT["wide_min_people"], person_height=0.08, green=0.7), SHOT) == "wide"
    assert shot_type(SegmentView(people=3, person_height=0.1, green=0.6), SHOT) == "wide"  # few, all small


def test_shot_crowd():
    assert shot_type(SegmentView(people=10, person_height=0.3, green=0.05), SHOT) == "crowd"


def test_shot_medium():
    assert shot_type(SegmentView(people=4, person_height=0.3, green=0.5), SHOT) == "medium"
    assert shot_type(SegmentView(people=3, person_height=0.3, green=0.3), SHOT) == "medium"


def test_big_face_on_green_pitch_is_not_a_closeup():
    """The face detector sometimes finds a large false face in a wide shot of the pitch."""
    v = SegmentView(face_share=0.17, people=6, person_height=0.08, green=0.66)
    assert shot_type(v, SHOT) == "wide"
