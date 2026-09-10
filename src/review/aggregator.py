"""Review aggregator (design doc §35, plan §8): hard failures + graded
diagnostics into one ReviewBundle -- never raw comments dumped straight
into the editor."""
from __future__ import annotations

from verification.hard.grounding import GroundingViolation
from verification.hard.structure import StructuralIssue

from .models import CritiqueIssue, DiagnosticResult, ReviewBundle


def aggregate_review(
    run_id: str,
    structural_issues: list[StructuralIssue],
    grounding_violations: list[GroundingViolation],
    critique_issues: list[CritiqueIssue],
    diagnostics: list[DiagnosticResult],
) -> ReviewBundle:
    hard_failures = [f"{i.code}: {i.detail}" for i in structural_issues]
    hard_failures += [f"{v.code} ({v.scene_id}): {v.detail}" for v in grounding_violations]
    critical_llm_issues = [i for i in critique_issues if i.severity == "critical"]
    hard_failures += [f"critical/{i.category} ({i.layer}): {i.problem}" for i in critical_llm_issues]

    return ReviewBundle(
        run_id=run_id,
        hard_failures=hard_failures,
        issues=critique_issues,
        diagnostics=diagnostics,
    )
