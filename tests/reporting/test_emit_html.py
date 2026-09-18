"""Tests for reporting/emit_html.py -- R* for HTML (plan §16)."""
import json

from orchestration.html_pipeline import HtmlSynthesisResult
from reporting.emit_html import emit_html_deliverables
from review.models import CritiqueIssue, DiagnosticResult
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


def test_entity_consistency_diagnostic_is_captured_in_the_report(tmp_path):
    """Phase 6 item #20: the cross-artifact entity-consistency diagnostic
    must reach a real, visible home too, same as visual_critique_issues."""
    diagnostic = DiagnosticResult(
        dimension="cross_artifact.running_example_entities", band="AMBER",
        evidence="scene s1 quotes 'dog' which matches neither the locked example nor any claim",
    )
    result = HtmlSynthesisResult(
        video_script_html="<html></html>", page_html="<html></html>", hero=None, beat_visuals=[],
        entity_consistency=diagnostic,
    )
    out = emit_html_deliverables(result, tmp_path / "html")
    report = json.loads((out / "render_report.json").read_text())
    assert report["entity_consistency"]["band"] == "AMBER"


def test_entity_consistency_defaults_to_none_when_not_set(tmp_path):
    result = HtmlSynthesisResult(video_script_html="<html></html>", page_html="<html></html>", hero=None, beat_visuals=[])
    out = emit_html_deliverables(result, tmp_path / "html")
    report = json.loads((out / "render_report.json").read_text())
    assert report["entity_consistency"] is None


def test_visual_variety_diagnostic_is_captured_in_the_report(tmp_path):
    """PIPELINE_AUDIT_2026-09-17.md (visual monotony): the consecutive-component-repetition
    diagnostic must reach a real, visible home too, same as entity_consistency."""
    diagnostic = DiagnosticResult(
        dimension="render.consecutive_component_repetition", band="AMBER",
        evidence="8 consecutive scenes all use the 'card' component",
    )
    result = HtmlSynthesisResult(
        video_script_html="<html></html>", page_html="<html></html>", hero=None, beat_visuals=[],
        visual_variety=diagnostic,
    )
    out = emit_html_deliverables(result, tmp_path / "html")
    report = json.loads((out / "render_report.json").read_text())
    assert report["visual_variety"]["band"] == "AMBER"


def test_visual_variety_defaults_to_none_when_not_set(tmp_path):
    result = HtmlSynthesisResult(video_script_html="<html></html>", page_html="<html></html>", hero=None, beat_visuals=[])
    out = emit_html_deliverables(result, tmp_path / "html")
    report = json.loads((out / "render_report.json").read_text())
    assert report["visual_variety"] is None


def test_sequence_critique_issues_are_captured_in_the_report(tmp_path):
    """2026-09-17 fix: critique_visual_sequence()'s (Phase 15, compositional-monotony)
    findings were computed onto HtmlSynthesisResult.sequence_critique_issues but never
    actually written anywhere -- the same "computed, never surfaced" gap already fixed
    twice above for entity_consistency/visual_variety, confirmed to have recurred here too."""
    issue = CritiqueIssue(
        issue_id="SEQ1", severity="major", category="repetition", layer="VISUAL",
        scene_ids=["s3", "s4", "s5", "s6"], problem="4 consecutive scenes all use the card layout",
        why_it_matters="visual monotony", recommended_intent="vary the component",
        repair_owner="html_author",
    )
    result = HtmlSynthesisResult(
        video_script_html="<html></html>", page_html="<html></html>", hero=None, beat_visuals=[],
        sequence_critique_issues=[issue],
    )
    out = emit_html_deliverables(result, tmp_path / "html")
    report = json.loads((out / "render_report.json").read_text())
    assert report["sequence_critique_issues"][0]["category"] == "repetition"
    assert report["sequence_critique_issues"][0]["scene_ids"] == ["s3", "s4", "s5", "s6"]


def test_sequence_critique_issues_default_to_empty_list_when_not_set(tmp_path):
    result = HtmlSynthesisResult(video_script_html="<html></html>", page_html="<html></html>", hero=None, beat_visuals=[])
    out = emit_html_deliverables(result, tmp_path / "html")
    report = json.loads((out / "render_report.json").read_text())
    assert report["sequence_critique_issues"] == []


def test_late_narration_repairs_used_is_captured_in_the_report(tmp_path):
    result = HtmlSynthesisResult(
        video_script_html="<html></html>", page_html="<html></html>", hero=None, beat_visuals=[],
        late_narration_repairs_used=2,
    )
    out = emit_html_deliverables(result, tmp_path / "html")
    report = json.loads((out / "render_report.json").read_text())
    assert report["late_narration_repairs_used"] == 2


def test_repairs_used_is_captured_in_the_report(tmp_path):
    """2026-09-17 (Round 2 sweep): repairs_used used to reach only the console log line in
    run_pipeline.py, with no on-disk trace at all -- unlike every sibling repair count next
    to it in this same report."""
    result = HtmlSynthesisResult(
        video_script_html="<html></html>", page_html="<html></html>", hero=None, beat_visuals=[],
        repairs_used=3,
    )
    out = emit_html_deliverables(result, tmp_path / "html")
    report = json.loads((out / "render_report.json").read_text())
    assert report["repairs_used"] == 3
