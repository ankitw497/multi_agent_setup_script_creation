"""Tests for html_synth/vertical_assembler.py -- the vertical shorts template (plan §20.9)."""
from html_synth.vertical_assembler import (
    SAFE_BOTTOM, SAFE_TOP, VERTICAL_HEIGHT, VERTICAL_WIDTH, synthesize_short_html,
)
from narration.models import SceneNarration, SentenceNarration
from planning.shorts_models import HookEvent, ShortPlan, ShortVisual


def make_plan(title="A Short Title", visual=None) -> ShortPlan:
    return ShortPlan(
        title=title, central_insight="x", micro_arc="problem_fix", hook=HookEvent(starts_at_seconds=1.0),
        visual=visual or ShortVisual(),
    )


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


def test_short_prose_uses_the_sans_apple_system_stack_not_serif():
    from html_synth.vertical_assembler import VERTICAL_STYLESHEET

    assert "font-family:var(--serif)" not in VERTICAL_STYLESHEET


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
    hook_screen = html.split('<div id="hook"')[1].split('<div id="setup"')[0] if '<div id="setup"' in html else html.split('<div id="hook"')[1]
    assert "&lt;b&gt;x&lt;/b&gt;" in hook_screen
    assert "<b>x</b>" not in hook_screen


def test_visual_dominant_object_and_states_render_as_a_flow_diagram_on_the_mechanism_screen():
    """Real gap found 2026-09-11 (user-reported): A2s's own `visual` field
    (dominant_object + states, plan §20.5) was authored by a real LLM call
    and then never rendered anywhere -- shorts were bare prose with no
    visual at all. Rendered as a real connected node-flow diagram (a
    labelled dot per stage, HTML/CSS not monospace text) rather than one
    joined arrow-string, per direct user feedback that plain text never
    reads as "a real visual"."""
    plan = make_plan(visual=ShortVisual(dominant_object="attention weights", states=["uniform", "peaked", "dominant"]))
    html = synthesize_short_html(plan, make_narration())
    # the diagram belongs on the mechanism screen specifically -- split on
    # the screen's own opening `<div id="...">` tag, not the bare "id=..."
    # substring (which also matches this same screen's `data-narration-id`)
    mechanism_screen = html.split('<div id="mechanism"')[1].split('<div id="payoff"')[0]
    assert 'class="short-flow"' in mechanism_screen
    for stage in ("attention weights", "uniform", "peaked", "dominant"):
        assert f'class="short-flow-label">{stage}<' in mechanism_screen
    hook_screen = html.split('<div id="hook"')[1].split('<div id="setup"')[0]
    assert 'class="short-flow"' not in hook_screen


def test_no_visual_states_renders_no_diagram_block_not_a_crash():
    html = synthesize_short_html(make_plan(visual=ShortVisual()), make_narration())
    assert 'class="short-flow"' not in html


def test_dominant_object_alone_with_no_states_renders_no_diagram():
    """A single label with no states to move through isn't a flow diagram --
    nothing forced onto the page just because one field is set."""
    html = synthesize_short_html(make_plan(visual=ShortVisual(dominant_object="attention weights")), make_narration())
    assert 'class="short-flow"' not in html


def test_diagram_content_is_html_escaped():
    plan = make_plan(visual=ShortVisual(dominant_object="<b>x</b>", states=["<i>y</i>"]))
    html = synthesize_short_html(plan, make_narration())
    assert "<b>x</b>" not in html
    assert "<i>y</i>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "&lt;i&gt;y&lt;/i&gt;" in html


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
