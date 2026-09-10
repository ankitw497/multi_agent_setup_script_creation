"""Tests for orchestration/routing.py (plan §15)."""
from editing.models import RevisionPlan, RewriteBeat
from orchestration.routing import RevisionAction, decide_action


def test_story_replan_required_routes_to_replan():
    plan = RevisionPlan(run_id="r1", story_replan_required=True)
    assert decide_action(plan) == RevisionAction.REPLAN


def test_replan_wins_even_if_rewrite_beats_are_also_present():
    plan = RevisionPlan(run_id="r1", story_replan_required=True,
                         rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="y")])
    assert decide_action(plan) == RevisionAction.REPLAN


def test_rewrite_beats_alone_routes_to_targeted_rewrite():
    plan = RevisionPlan(run_id="r1", rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="y")])
    assert decide_action(plan) == RevisionAction.TARGETED_REWRITE


def test_technical_fixes_alone_routes_to_targeted_rewrite():
    plan = RevisionPlan(run_id="r1", technical_fixes=[{"scene_id": "s1", "required_change": "x"}])
    assert decide_action(plan) == RevisionAction.TARGETED_REWRITE


def test_delete_or_compress_alone_routes_to_targeted_rewrite():
    plan = RevisionPlan(run_id="r1", delete_or_compress=[{"scene_id": "s1", "reason": "x"}])
    assert decide_action(plan) == RevisionAction.TARGETED_REWRITE


def test_nothing_to_do_routes_to_none():
    """Nothing runs because it exists -- a clean revision plan does nothing (plan §15)."""
    plan = RevisionPlan(run_id="r1")
    assert decide_action(plan) == RevisionAction.NONE
