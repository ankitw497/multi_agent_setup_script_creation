"""Tests for review/visual_sample.py -- C3's deterministic image budget (plan §13)."""
from review.visual_sample import select_scenes_for_visual_audit


def make_scenes(n: int) -> list[str]:
    return [f"s{i:02d}" for i in range(n)]


def test_no_flagged_scenes_returns_a_systematic_sample_only():
    scenes = make_scenes(20)
    result = select_scenes_for_visual_audit(scenes, flagged_scene_ids=set())
    assert result  # 20% of 20 = 4, well within the 8-image budget
    assert len(result) == 4
    assert all(s in scenes for s in result)


def test_flagged_scenes_come_first_in_plan_order():
    scenes = make_scenes(20)
    flagged = {"s05", "s02"}
    result = select_scenes_for_visual_audit(scenes, flagged_scene_ids=flagged)
    assert result[0] == "s02"  # plan order, not insertion order into the set
    assert result[1] == "s05"


def test_flagged_alone_exceeding_the_budget_is_truncated_no_sample_slot_left():
    scenes = make_scenes(20)
    flagged = set(scenes[:10])  # 10 flagged, budget is 8
    result = select_scenes_for_visual_audit(scenes, flagged_scene_ids=flagged, max_images=8)
    assert len(result) == 8
    assert result == scenes[:8]  # first 8 flagged scenes, in plan order


def test_mixed_flagged_and_sampled_never_exceeds_max_images():
    scenes = make_scenes(30)
    flagged = {"s01", "s02", "s03"}
    result = select_scenes_for_visual_audit(scenes, flagged_scene_ids=flagged, max_images=8)
    assert len(result) <= 8
    assert result[:3] == ["s01", "s02", "s03"]
    assert set(result[3:]).isdisjoint(flagged)  # the sample never repeats a flagged scene


def test_determinism_same_input_same_output():
    scenes = make_scenes(17)
    flagged = {"s04", "s09"}
    r1 = select_scenes_for_visual_audit(scenes, flagged_scene_ids=flagged)
    r2 = select_scenes_for_visual_audit(scenes, flagged_scene_ids=flagged)
    assert r1 == r2


def test_fewer_total_scenes_than_the_image_budget_returns_everything_reasonable():
    scenes = make_scenes(3)
    result = select_scenes_for_visual_audit(scenes, flagged_scene_ids=set(), max_images=8)
    assert len(result) <= 3
    assert set(result).issubset(set(scenes))


def test_no_scenes_at_all_returns_empty_not_a_crash():
    assert select_scenes_for_visual_audit([], flagged_scene_ids=set()) == []


def test_all_scenes_flagged_returns_every_scene_up_to_the_budget():
    scenes = make_scenes(5)
    result = select_scenes_for_visual_audit(scenes, flagged_scene_ids=set(scenes), max_images=8)
    assert result == scenes
