"""Round-trip tests for editing/models.py (design doc §36, plan §15)."""
from editing.models import DeleteOrCompress, DismissedIssue, RevisionPlan, RewriteBeat, TechnicalFix

from tests.conftest import roundtrip, roundtrip_fixture


def test_rewrite_beat_carries_intent_not_prose():
    roundtrip(RewriteBeat, {"beat_id": "B05", "reason": "x", "intent": "motivate the fix earlier"})


def test_technical_fix_roundtrips():
    roundtrip(TechnicalFix, {"scene_id": "s9", "claim_id": "N004", "required_change": "use decimal GB"})


def test_delete_or_compress_roundtrips():
    roundtrip(DeleteOrCompress, {"scene_id": "s12", "reason": "repeats scene_08"})


def test_revision_plan_roundtrips_full_structure():
    plan = roundtrip_fixture(RevisionPlan, "editing", "RevisionPlan")
    assert plan.revision_level == "targeted"
    assert plan.story_replan_required is False
    assert "hook" in plan.preserve
    assert len(plan.rewrite_beats) == 1
    assert len(plan.technical_fixes) == 1
    assert len(plan.delete_or_compress) == 1


def test_revision_plan_defaults_to_no_replan_needed():
    plan = RevisionPlan(run_id="r1")
    assert plan.story_replan_required is False
    assert plan.revision_level == "targeted"


def test_revision_plan_defaults_to_no_dismissed_issues():
    plan = RevisionPlan(run_id="r1")
    assert plan.dismissed_issues == []


def test_dismissed_issue_roundtrips():
    roundtrip(DismissedIssue, {
        "issue_id": "I1",
        "reason": "already ruled out in rejected_archetypes: 'no comparison of methods present'",
    })
