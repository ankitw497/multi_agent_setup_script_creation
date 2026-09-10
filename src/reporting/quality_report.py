"""quality_report.json (plan §14) -- the machine-readable counterpart to
review_summary.md. Built directly from a PipelineResult; never
hand-assembled elsewhere, so there is exactly one source of truth for what
a run's final status actually was and why.
"""
from __future__ import annotations

from verification.models import QualityReport

from orchestration.pipeline import PipelineResult


def build_quality_report(run_id: str, result: PipelineResult) -> QualityReport:
    diagnostics = result.review_bundle.diagnostics
    return QualityReport(
        run_id=run_id,
        final_status=result.final_status,
        hard_gate_failures=result.review_bundle.hard_failures,
        diagnostics=diagnostics,
        amber_count=sum(1 for d in diagnostics if d.band == "AMBER"),
        red_count=sum(1 for d in diagnostics if d.band == "RED"),
        archetype_resolved=result.plan.archetype,
        revisions=result.story_replans_used + result.major_revisions_used,
    )
