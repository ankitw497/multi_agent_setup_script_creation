"""Tests for html_synth/vertical_assembler.py -- the vertical shorts template (plan §20.9)."""
from html_synth.vertical_assembler import (
    SAFE_BOTTOM, SAFE_TOP, VERTICAL_HEIGHT, VERTICAL_WIDTH, synthesize_short_html,
)
from narration.models import SceneNarration, SentenceNarration
from planning.shorts_models import HookEvent, ShortPlan


def make_plan(title="A Short Title") -> ShortPlan:
    return ShortPlan(title=title, central_insight="x", micro_arc="problem_fix", hook=HookEvent(starts_at_seconds=1.0))


def make_narration() -> list[SceneNarration]:
    return [
        SceneNarration(scene_id="hook", sentences=[SentenceNarration(text="Hook text.", sentence_type="transition")]),
        SceneNarration(scene_id="setup", sentences=[SentenceNarration(text="Setup text.", sentence_type="transition")]),
        SceneNarration(scene_id="mechanism", sentences=[SentenceNarration(text="Mechanism text.", sentence_type="technical_assertion")]),
        SceneNarration(scene_id="payoff", sentences=[SentenceNarration(text="Payoff text.", sentence_type="payoff")]),
    ]


def test_all_four_segments_render_in_order():
    html = synthesize_short_html(make_plan(), make_narration())
    assert html.index('id="hook"') < html.index('id="setup"') < html.index('id="mechanism"') < html.index('id="payoff"')


def test_segment_text_appears():
    html = synthesize_short_html(make_plan(), make_narration())
    assert "Hook text." in html
    assert "Payoff text." in html


def test_missing_segment_is_simply_omitted_not_a_crash():
    narration = [n for n in make_narration() if n.scene_id != "setup"]
    html = synthesize_short_html(make_plan(), narration)
    assert 'id="setup"' not in html
    assert 'id="hook"' in html


def test_canvas_size_and_safe_zones_are_in_the_stylesheet():
    html = synthesize_short_html(make_plan(), make_narration())
    assert f"{VERTICAL_WIDTH}px" in html
    assert f"{VERTICAL_HEIGHT}px" in html
    assert f"{SAFE_TOP}px" in html
    assert f"{SAFE_BOTTOM}px" in html


def test_narration_data_block_is_embedded_with_a_hash():
    html = synthesize_short_html(make_plan(), make_narration())
    assert 'id="narration-data"' in html
    assert "data-narration-hash=" in html


def test_title_is_html_escaped():
    html = synthesize_short_html(make_plan(title="<script>alert(1)</script>"), make_narration())
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_prose_is_html_escaped():
    """Checked in the VISIBLE prose only -- the same raw text also
    legitimately appears, unescaped, inside the embedded narration-data
    JSON blob, which is safe (script content is never HTML-parsed)."""
    narration = [SceneNarration(scene_id="hook", sentences=[SentenceNarration(text="<b>x</b>", sentence_type="transition")])]
    html = synthesize_short_html(make_plan(), narration)
    assert '<p class="short-prose">&lt;b&gt;x&lt;/b&gt;</p>' in html


def test_narration_containing_script_close_tag_cannot_break_out_of_the_script_block():
    """Real gap found while writing this test: narration text containing
    the literal substring "</script>" (e.g. a sentence discussing HTML
    tags) would otherwise close the embedded <script> block early and let
    the rest of the JSON render as a real, parsed <img> ELEMENT rather
    than inert script text. Checked via a real DOM parse, not a substring
    search -- the raw text "<img...>" legitimately still appears as inert
    data INSIDE the (correctly, still-closed) script block."""
    from bs4 import BeautifulSoup

    narration = [SceneNarration(scene_id="hook", sentences=[
        SentenceNarration(text="the </script><img src=x onerror=alert(1)> tag", sentence_type="transition"),
    ])]
    html = synthesize_short_html(make_plan(), narration)
    assert "<\\/script" in html
    assert BeautifulSoup(html, "lxml").find("img") is None
