"""Tests for verification/hard/vertical.py -- vertical-short hard gates (plan §20.9)."""
from html_synth.vertical_assembler import synthesize_short_html
from narration.models import SceneNarration, SentenceNarration
from planning.shorts_models import HookEvent, ShortPlan
from verification.hard.vertical import (
    check_safe_zones_present, check_vertical_canvas_size, check_vertical_short,
)


def make_plan() -> ShortPlan:
    return ShortPlan(title="t", central_insight="x", micro_arc="problem_fix", hook=HookEvent(starts_at_seconds=1.0))


def make_narration() -> list[SceneNarration]:
    return [
        SceneNarration(scene_id="hook", sentences=[SentenceNarration(text="x", sentence_type="transition")]),
        SceneNarration(scene_id="payoff", sentences=[SentenceNarration(text="y", sentence_type="payoff")]),
    ]


def test_real_template_output_is_fully_clean():
    html = synthesize_short_html(make_plan(), make_narration())
    assert check_vertical_short(html, make_narration()) == []


def test_safe_zones_present_on_the_real_template():
    html = synthesize_short_html(make_plan(), make_narration())
    assert check_safe_zones_present(html) == []


def test_missing_safe_zone_padding_is_flagged():
    html = synthesize_short_html(make_plan(), make_narration()).replace("180px", "0px")
    issues = check_safe_zones_present(html)
    assert any(i.code == "safe_zone_top_missing" for i in issues)


def test_canvas_size_present_on_the_real_template():
    html = synthesize_short_html(make_plan(), make_narration())
    assert check_vertical_canvas_size(html) == []


def test_missing_canvas_width_is_flagged():
    html = synthesize_short_html(make_plan(), make_narration()).replace("1080px", "0px")
    issues = check_vertical_canvas_size(html)
    assert any(i.code == "vertical_width_missing" for i in issues)


def test_missing_segment_is_caught_by_the_shared_scene_check():
    html = synthesize_short_html(make_plan(), make_narration())
    issues = check_vertical_short(html, make_narration() + [
        SceneNarration(scene_id="mechanism", sentences=[]),
    ])
    assert any(i.code == "scene_missing_from_dom" for i in issues)


def test_tampered_narration_hash_is_caught_by_the_shared_hash_check():
    html = synthesize_short_html(make_plan(), make_narration())
    different_narration = [SceneNarration(scene_id="hook", sentences=[SentenceNarration(text="different", sentence_type="transition")])]
    issues = check_vertical_short(html, different_narration)
    assert any(i.code == "narration_hash_mismatch" for i in issues)
