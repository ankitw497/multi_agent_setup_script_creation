"""R* for HTML (plan §16): `html/{v0N.html, render_report.json}` in the
working run dir; `final/{video_script.html, page.html}` once promoted.
Screenshots are V1C (Playwright never runs here).
"""
from __future__ import annotations

import json
from pathlib import Path

from orchestration.html_pipeline import HtmlSynthesisResult


def emit_html_deliverables(result: HtmlSynthesisResult, target_dir: str | Path) -> Path:
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    (target_dir / "video_script.html").write_text(result.video_script_html)
    (target_dir / "page.html").write_text(result.page_html)
    (target_dir / "render_report.json").write_text(json.dumps({
        "render_issues": [{"code": i.code, "detail": i.detail} for i in result.render_issues],
        "renderer_compat_ok": len(result.render_issues) == 0,
        # Every C3 finding, not just the structural subset that already
        # routed to repair -- STORY_IMPROVEMENT_PLAN.md Phase 6 fix: these
        # used to be silently discarded once the structural ones were
        # pulled out (never surfaced anywhere, not even here).
        "visual_critique_issues": [i.model_dump() for i in result.visual_critique_issues],
        # 2026-09-17 fix: computed by critique_visual_sequence() (Phase 15,
        # compositional-monotony check) but never actually written anywhere --
        # the same "computed, never surfaced" gap already fixed twice for
        # entity_consistency/visual_variety, confirmed live to have recurred a
        # third time on this exact field.
        "sequence_critique_issues": [i.model_dump() for i in result.sequence_critique_issues],
        "late_narration_repairs_used": result.late_narration_repairs_used,
        # 2026-09-17 (Round 2 sweep): previously reached only the console log line
        # (run_pipeline.py), with no on-disk trace at all -- unlike every sibling repair
        # count next to it here.
        "repairs_used": result.repairs_used,
        # AMBER-banded diagnostic, never a hard gate (Phase 6 item #20) --
        # None only if a caller constructed HtmlSynthesisResult without going
        # through synthesize_video_html()/synthesize_and_repair_video_html().
        "entity_consistency": result.entity_consistency.model_dump() if result.entity_consistency else None,
        # AMBER-banded diagnostic, never a hard gate (PIPELINE_AUDIT_2026-09-17.md, visual
        # monotony) -- None only if a caller constructed HtmlSynthesisResult without going
        # through synthesize_video_html()/synthesize_and_repair_video_html().
        "visual_variety": result.visual_variety.model_dump() if result.visual_variety else None,
    }, indent=2))

    return target_dir
