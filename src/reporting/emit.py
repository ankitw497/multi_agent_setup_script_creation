"""R* -- final deliverable emission (plan §8, §16, §17).

Writes everything a finished run's `final/` promotes: `plan.json`,
`narration.json`, `script.md`, `review_summary.md`, `quality_report.json`,
`cost_report.json`. This is a separate module from
`orchestration.pipeline` (not a method on it) specifically to avoid a
circular import -- `reporting.review_summary` and `reporting.quality_report`
both already import `PipelineResult` FROM `orchestration.pipeline`, so the
composition has to live on the reporting side.

Meaningful only for a PASS/PASS_WARN result -- call this before
`orchestration.paths.promote_to_final()`, never for a FAIL/REVISE-exhausted
run (its `runs/vNN/` still keeps full working history via
`orchestration.pipeline.save_result()`, just never promoted to the
video's shared `final/`).
"""
from __future__ import annotations

import json
from pathlib import Path

from llm.usage import UsageLedger
from orchestration.pipeline import PipelineResult

from .cost_report import build_cost_report
from .quality_report import build_quality_report
from .review_summary import render_review_summary
from .run_manifest import build_run_manifest
from .script_md import render_script_md


def emit_final_deliverables(
    result: PipelineResult, run_dir: str | Path, run_id: str, usage_ledger: UsageLedger,
    degraded_capabilities: list[str] | None = None, carried_over_microusd: int = 0,
) -> Path:
    final_dir = Path(run_dir) / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    degraded_capabilities = degraded_capabilities or []

    cost_report = build_cost_report(run_id, usage_ledger, carried_over_microusd=carried_over_microusd)
    quality_report = build_quality_report(run_id, result)
    run_manifest = build_run_manifest(run_id, degraded_capabilities)

    (final_dir / "plan.json").write_text(result.plan.model_dump_json(indent=2))
    (final_dir / "narration.json").write_text(json.dumps([n.model_dump() for n in result.narration], indent=2))
    (final_dir / "script.md").write_text(render_script_md(result.plan, result.narration))
    (final_dir / "review_summary.md").write_text(
        render_review_summary(result, cost_report=cost_report, degraded_capabilities=degraded_capabilities)
    )
    (final_dir / "quality_report.json").write_text(quality_report.model_dump_json(indent=2))
    (final_dir / "cost_report.json").write_text(cost_report.model_dump_json(indent=2))
    (final_dir / "run_manifest.json").write_text(run_manifest.model_dump_json(indent=2))

    return final_dir
