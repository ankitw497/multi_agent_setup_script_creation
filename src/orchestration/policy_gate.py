"""The final status policy (plan §14). A deterministic function -- A4 may
write an editorial summary and DOWNGRADE this result, but may never clear
a hard failure or upgrade a status (plan §9, Appendix G #16).

Evaluated once revision attempts are exhausted or unnecessary -- not after
every stage. Mid-loop, `hard_failures` present with budget remaining means
"revise again," which this function represents as REVISE, not FAIL.
"""
from __future__ import annotations

from typing import Literal

from review.models import DiagnosticResult

FinalStatus = Literal["FAIL", "REVISE", "PASS_WARN", "PASS"]

DEFAULT_PASS_AMBER_ALLOWANCE = 3  # plan §14 default


def compute_final_status(
    hard_failures: list,
    diagnostics: list[DiagnosticResult],
    revision_budget_remaining: bool,
    red_survived_a_round: bool = False,
    pass_amber_allowance: int = DEFAULT_PASS_AMBER_ALLOWANCE,
) -> FinalStatus:
    if hard_failures:
        return "REVISE" if revision_budget_remaining else "FAIL"

    red_count = sum(1 for d in diagnostics if d.band == "RED")
    amber_count = sum(1 for d in diagnostics if d.band == "AMBER")

    # plan §10 escalation rule: >=3 REDs across dimensions, or a RED that
    # survived a prior revision round -- not any single first-pass RED.
    escalate = red_count >= 3 or red_survived_a_round or amber_count > pass_amber_allowance

    if escalate and revision_budget_remaining:
        return "REVISE"
    if red_count > 0 or amber_count > pass_amber_allowance:
        return "PASS_WARN"
    return "PASS"


_STATUS_RANK: dict[FinalStatus, int] = {"PASS": 0, "PASS_WARN": 1, "REVISE": 2, "FAIL": 3}


def apply_editorial_downgrade(computed: FinalStatus, requested: FinalStatus | None) -> FinalStatus:
    """A4 may only move the status toward FAIL, never toward PASS (plan Appendix G #16)."""
    if requested is None:
        return computed
    return requested if _STATUS_RANK[requested] > _STATUS_RANK[computed] else computed
