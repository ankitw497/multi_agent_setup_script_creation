"""Tests for reporting/emit_html.py -- R* for HTML (plan §16)."""
import json

from orchestration.html_pipeline import HtmlSynthesisResult
from reporting.emit_html import emit_html_deliverables
from review.models import CritiqueIssue
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


def test_visual_critique_issues_are_captured_in_the_report(tmp_path):
    """STORY_IMPROVEMENT_PLAN.md Phase 6 fix: C3's non-structural findings
    used to be computed and then silently discarded -- confirms they now
    reach a real, visible home."""
    issue = CritiqueIssue(
        issue_id="V1", severity="major", category="repetition", layer="NARRATION",
        scene_ids=["s1"], problem="re-explains an already-taught concept", why_it_matters="y",
        recommended_intent="compress it", repair_owner="html_author",
    )
    result = HtmlSynthesisResult(
        video_script_html="<html></html>", page_html="<html></html>", hero=None, beat_visuals=[],
        visual_critique_issues=[issue],
    )
    out = emit_html_deliverables(result, tmp_path / "html")
    report = json.loads((out / "render_report.json").read_text())
    assert report["visual_critique_issues"][0]["category"] == "repetition"
    assert report["visual_critique_issues"][0]["scene_ids"] == ["s1"]
