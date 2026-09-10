"""Tests for orchestration/policy_gate.py -- the plan §14 final status policy."""
from orchestration.policy_gate import apply_editorial_downgrade, compute_final_status
from review.models import DiagnosticResult


def diag(band, dim="x") -> DiagnosticResult:
    return DiagnosticResult(dimension=dim, band=band, evidence="e")


def test_hard_failure_with_budget_remaining_is_revise_not_fail():
    status = compute_final_status(hard_failures=["x"], diagnostics=[], revision_budget_remaining=True)
    assert status == "REVISE"


def test_hard_failure_with_budget_exhausted_is_fail():
    status = compute_final_status(hard_failures=["x"], diagnostics=[], revision_budget_remaining=False)
    assert status == "FAIL"


def test_no_hard_failures_no_diagnostics_is_pass():
    assert compute_final_status([], [], revision_budget_remaining=True) == "PASS"


def test_a_single_amber_within_allowance_is_still_pass():
    diagnostics = [diag("AMBER"), diag("AMBER")]
    assert compute_final_status([], diagnostics, revision_budget_remaining=True) == "PASS"


def test_ambers_over_the_allowance_escalate_to_revise_when_budget_remains():
    diagnostics = [diag("AMBER"), diag("AMBER"), diag("AMBER"), diag("AMBER")]  # 4 > default allowance 3
    assert compute_final_status([], diagnostics, revision_budget_remaining=True) == "REVISE"


def test_ambers_over_the_allowance_become_pass_warn_when_budget_exhausted():
    diagnostics = [diag("AMBER")] * 4
    assert compute_final_status([], diagnostics, revision_budget_remaining=False) == "PASS_WARN"


def test_a_single_red_with_budget_remaining_and_below_escalation_threshold_is_pass_warn():
    """A single first-pass RED (not >=3, hasn't survived a round) doesn't
    force another revision cycle on its own (plan §10 escalation rule)."""
    diagnostics = [diag("RED")]
    assert compute_final_status([], diagnostics, revision_budget_remaining=True) == "PASS_WARN"


def test_three_or_more_reds_escalate_to_revise():
    diagnostics = [diag("RED"), diag("RED"), diag("RED")]
    assert compute_final_status([], diagnostics, revision_budget_remaining=True) == "REVISE"


def test_a_red_that_survived_a_round_escalates_even_if_its_the_only_one():
    diagnostics = [diag("RED")]
    status = compute_final_status([], diagnostics, revision_budget_remaining=True, red_survived_a_round=True)
    assert status == "REVISE"


def test_escalation_criteria_met_but_budget_exhausted_is_pass_warn_not_revise():
    diagnostics = [diag("RED"), diag("RED"), diag("RED")]
    status = compute_final_status([], diagnostics, revision_budget_remaining=False)
    assert status == "PASS_WARN"


def test_custom_amber_allowance_is_respected():
    diagnostics = [diag("AMBER"), diag("AMBER")]
    assert compute_final_status([], diagnostics, revision_budget_remaining=True, pass_amber_allowance=1) == "REVISE"


# ---- A4 editorial downgrade ---------------------------------------------------

def test_a4_can_downgrade_pass_to_pass_warn():
    assert apply_editorial_downgrade("PASS", "PASS_WARN") == "PASS_WARN"


def test_a4_cannot_upgrade_pass_warn_to_pass():
    """A4 may never clear a failure or upgrade a status (plan Appendix G #16)."""
    assert apply_editorial_downgrade("PASS_WARN", "PASS") == "PASS_WARN"


def test_a4_cannot_clear_a_fail():
    assert apply_editorial_downgrade("FAIL", "PASS") == "FAIL"


def test_a4_with_no_opinion_leaves_the_computed_status_untouched():
    assert apply_editorial_downgrade("PASS", None) == "PASS"
