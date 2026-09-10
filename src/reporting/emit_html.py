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
    }, indent=2))

    return target_dir
