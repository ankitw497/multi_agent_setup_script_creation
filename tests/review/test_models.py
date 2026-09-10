"""Round-trip tests for review/models.py (plan §5, §10, design doc §28, §49)."""
from review.models import CritiqueIssue, DiagnosticResult, ReviewBundle

from tests.conftest import roundtrip, roundtrip_fixture


def test_critique_issue_roundtrips_and_never_carries_replacement_prose():
    """The critic emits an intent, not prose (design doc §28) — recommended_intent
    is a plain string field describing WHAT must change; by construction there's
    no 'replacement_text' field on this model at all."""
    issue = roundtrip(
        CritiqueIssue,
        {
            "issue_id": "I001", "severity": "minor", "category": "repetition", "layer": "NARRATION",
            "scene_ids": ["scene_10", "scene_12"],
            "problem": "scene_12 repeats the role of Value already established in scene_08",
            "why_it_matters": "redundant explanation slows pacing without adding information",
            "recommended_intent": "compress scene_12's restatement to one clause",
            "repair_owner": "narration_lead",
        },
    )
    assert "replacement_text" not in CritiqueIssue.model_fields
    assert issue.recommended_intent


def test_repair_owner_is_restricted_to_agents_that_actually_rewrite():
    """Critics never rewrite; only story_lead/narration_lead/html_author own a
    repair (plan Appendix G #3/#5, 'producer != validator')."""
    issue = CritiqueIssue(
        issue_id="I1", severity="minor", category="repetition", layer="NARRATION",
        problem="x", why_it_matters="y", recommended_intent="z", repair_owner="narration_lead",
    )
    assert issue.repair_owner in ("story_lead", "narration_lead", "html_author")


def test_diagnostic_result_roundtrips_with_evidence_not_just_a_verdict():
    """Plan §10/§11.3: a diagnostic always carries evidence, never a bare band."""
    d = roundtrip(
        DiagnosticResult,
        {"dimension": "opener_share", "band": "AMBER", "evidence": "top opener 'Now' at 14%",
         "value": 0.14, "target": "<=0.11 green, <=0.17 amber"},
    )
    assert d.band == "AMBER"
    assert d.evidence


def test_review_bundle_roundtrips_hard_failures_and_diagnostics_separately():
    """The aggregator's job: hard failures and graded diagnostics stay two
    separate lists, never merged into one undifferentiated pile (plan §8)."""
    bundle = roundtrip_fixture(ReviewBundle, "review", "ReviewBundle")
    assert bundle.hard_failures == []
    assert len(bundle.issues) == 1
    assert len(bundle.diagnostics) == 2
    assert bundle.diagnostics[1].band == "AMBER"
