"""Tests for reporting/emit_html.py -- R* for HTML (plan §16)."""
import json

from orchestration.html_pipeline import HtmlSynthesisResult
from reporting.emit_html import emit_html_deliverables
from verification.hard.render import RenderIssue


def test_writes_both_html_files_and_report(tmp_path):
    result = HtmlSynthesisResult(video_script_html="<html>vs</html>", page_html="<html>page</html>",
                                  hero=None, beat_visuals=[])
    out = emit_html_deliverables(result, tmp_path / "html")
    assert (out / "video_script.html").read_text() == "<html>vs</html>"
    assert (out / "page.html").read_text() == "<html>page</html>"
    report = json.loads((out / "render_report.json").read_text())
    assert report["renderer_compat_ok"] is True
    assert report["render_issues"] == []


def test_render_issues_are_captured_in_the_report(tmp_path):
    result = HtmlSynthesisResult(
        video_script_html="<html></html>", page_html="<html></html>", hero=None, beat_visuals=[],
        render_issues=[RenderIssue("scene_missing_from_dom", "s2 never rendered")],
    )
    out = emit_html_deliverables(result, tmp_path / "html")
    report = json.loads((out / "render_report.json").read_text())
    assert report["renderer_compat_ok"] is False
    assert report["render_issues"][0]["code"] == "scene_missing_from_dom"
