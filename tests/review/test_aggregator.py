"""Tests for review/aggregator.py (design doc §35, plan §8)."""
from review.aggregator import aggregate_review
from review.models import CritiqueIssue, DiagnosticResult
from verification.hard.grounding import GroundingViolation
from verification.hard.structure import StructuralIssue


def make_issue(severity="minor") -> CritiqueIssue:
    return CritiqueIssue(issue_id="I1", severity=severity, category="repetition", layer="NARRATION",
                          problem="x", why_it_matters="y", recommended_intent="z", repair_owner="narration_lead")


def test_structural_issues_become_hard_failures():
    bundle = aggregate_review("r1", [StructuralIssue("word_budget_mismatch", "320 vs 1670")], [], [], [])
    assert len(bundle.hard_failures) == 1
    assert "word_budget_mismatch" in bundle.hard_failures[0]


def test_grounding_violations_become_hard_failures():
    bundle = aggregate_review("r1", [], [GroundingViolation("s1", 0, "grounding_policy_violation", "x")], [], [])
    assert len(bundle.hard_failures) == 1
    assert "s1" in bundle.hard_failures[0]


def test_critical_critique_issues_become_hard_failures_but_minor_ones_dont():
    bundle = aggregate_review("r1", [], [], [make_issue("critical"), make_issue("minor")], [])
    assert len(bundle.hard_failures) == 1
    assert len(bundle.issues) == 2  # both still preserved in the full issue list


def test_a_clean_review_has_no_hard_failures():
    bundle = aggregate_review("r1", [], [], [], [])
    assert bundle.hard_failures == []
    assert bundle.issues == []


def test_diagnostics_pass_through_untouched():
    diagnostics = [DiagnosticResult(dimension="x", band="AMBER", evidence="e")]
    bundle = aggregate_review("r1", [], [], [], diagnostics)
    assert bundle.diagnostics == diagnostics


def test_run_id_is_preserved():
    bundle = aggregate_review("my-run-42", [], [], [], [])
    assert bundle.run_id == "my-run-42"
