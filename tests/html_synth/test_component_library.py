"""Tests for html_synth/component_library.py -- the channel component library (plan §7)."""
import pytest

import json

from html_synth.component_library import (
    all_component_ids, components_for_story_role, css_tokens, escape_script_json, render_component,
)


def test_css_tokens_includes_every_color():
    css = css_tokens()
    assert "--bg:#f5f5f7" in css
    assert "--accent:#0071e3" in css


def test_hero_renders_all_slots():
    out = render_component("hero", {"badge": "Series X", "title": "The Title", "subtitle": "Sub text"})
    assert "Series X" in out
    assert "The Title" in out
    assert "Sub text" in out
    assert 'id="hero-story"' in out


def test_slot_content_is_html_escaped():
    """No component may let model-provided text inject markup -- every
    slot is a plain string substitution, never raw HTML."""
    out = render_component("card", {"title": "x", "value": "<img src=x onerror=alert(1)>", "desc": "y"})
    assert "<img" not in out
    assert "&lt;img" in out


def test_callout_variants_use_the_right_class():
    assert 'callout-danger' in render_component("callout_danger", {"text": "x"})
    assert 'callout-success' in render_component("callout_success", {"text": "x"})


def test_step_list_numbers_items_in_order():
    out = render_component("step_list", {"items": [
        {"title": "First", "desc": "a"}, {"title": "Second", "desc": "b"}, {"title": "Third", "desc": "c"},
    ]})
    assert out.index("First") < out.index("Second") < out.index("Third")
    assert '<div class="step-num">1</div>' in out
    assert '<div class="step-num">3</div>' in out


def test_grid_2_renders_items_as_mini_cards():
    """Real gap found live (2026-09-10): the model naturally returns grid
    items as plain {title, value, desc} data, never a pre-rendered HTML
    snippet -- also the safer design, since the LLM never touches markup."""
    out = render_component("grid_2", {"items": [
        {"title": "Before", "value": "5s", "desc": "x"}, {"title": "After", "value": "0.5s", "desc": "y"},
    ]})
    assert out.count("card-value") == 2
    assert "Before" in out and "After" in out
    assert '<div class="grid-2">' in out


def test_grid_items_are_html_escaped_same_as_a_standalone_card():
    out = render_component("grid_2", {"items": [{"title": "<b>x</b>", "value": "v", "desc": "d"}]})
    assert "<b>" not in out
    assert "&lt;b&gt;" in out


def test_grid_3_handles_plain_string_items_without_crashing():
    """Real gap found live (2026-09-10): a second run returned grid_3 items
    as plain strings (a grid of short observations), not {title,value,desc}
    dicts -- nothing pins the inner item shape, so both must work."""
    out = render_component("grid_3", {"items": ["First observation", "Second observation"]})
    assert "First observation" in out
    assert "Second observation" in out


def test_grid_string_items_are_html_escaped():
    out = render_component("grid_2", {"items": ["<b>x</b>"]})
    assert "<b>" not in out
    assert "&lt;b&gt;" in out


def test_step_list_handles_plain_string_items_without_crashing():
    out = render_component("step_list", {"items": ["Just a plain step description"]})
    assert "Just a plain step description" in out


def test_metric_table_renders_headers_and_rows():
    out = render_component("metric_table", {"headers": ["A", "B"], "rows": [["1", "2"], ["3", "4"]]})
    assert "<th>A</th>" in out
    assert "<td>3</td>" in out


def test_math_block_renders_label_and_equation():
    out = render_component("math_block", {"label": "Scaling", "equation": "QK^T / sqrt(d_k)"})
    assert "Scaling" in out
    assert "sqrt(d_k)" in out


def test_diagram_card_renders_real_content_not_an_empty_placeholder():
    """Real gap found 2026-09-11 (user-reported): diagram_card used to
    render an empty `.diagram-placeholder` div -- every figure in the
    final HTML was visually blank regardless of what H produced, since
    the component had no slot to put content in at all. `content` is now
    a real slot, rendered as a monospace ASCII-art block."""
    out = render_component("diagram_card", {
        "content": "query → score → softmax → weighted sum", "caption": "The retrieval loop.",
    })
    assert "diagram-placeholder" not in out
    assert "query → score → softmax → weighted sum" in out
    assert "The retrieval loop." in out
    assert '<pre class="diagram-pre">' in out


def test_diagram_card_content_is_html_escaped():
    out = render_component("diagram_card", {"content": "<script>alert(1)</script>", "caption": "x"})
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_headline_components_use_the_sans_apple_system_stack_not_serif():
    """Real gap found 2026-09-11 (user-reported): headline components
    rendered in an external Google-Fonts serif face (DM Serif Display),
    not the Apple-style sans system stack the source itself actually
    uses for its own headlines."""
    from html_synth.component_library import BASE_STYLESHEET

    assert "font-family:var(--serif)" not in BASE_STYLESHEET
    ds_sans = css_tokens()
    assert "-apple-system" in ds_sans


def test_reveal_is_visible_at_rest_with_no_js_or_scroll_dependency():
    """Real gap found 2026-09-11 (user-reported "lot of empty space"):
    `.reveal` used to start at opacity:0, only becoming visible once an
    IntersectionObserver saw an element scroll into view -- every screen
    past the first was genuinely blank in any viewer that doesn't run/
    scroll the page (a static preview, a thumbnail, JS blocked). Fixed
    with a pure-CSS fade-in that plays on load; base opacity must be 1 so
    content stays visible even if the animation itself never runs."""
    from html_synth.component_library import BASE_STYLESHEET

    assert "opacity:1" in BASE_STYLESHEET.split(".reveal{")[1].split("}")[0]
    assert "prefers-reduced-motion" in BASE_STYLESHEET


def test_unknown_component_id_raises():
    with pytest.raises(ValueError, match="unknown component_id"):
        render_component("not_a_real_component", {})


def test_components_for_story_role_matches_the_plan_table():
    assert set(components_for_story_role("hook")) == {"hero", "card"}
    assert "math_block" in components_for_story_role("mechanism")
    assert "math_block" in components_for_story_role("derivation")


def test_unknown_story_role_returns_empty_not_a_crash():
    assert components_for_story_role("not_a_real_role") == []


def test_all_component_ids_covers_every_role_in_the_plan_table():
    """Every component the story_roles table references must actually
    exist in the components catalogue -- no dangling reference."""
    from html_synth.component_library import _design_system

    ds = _design_system()
    referenced = {cid for role_components in ds["story_roles"].values() for cid in role_components}
    assert referenced.issubset(set(all_component_ids()))


def test_escape_script_json_neutralizes_script_close_tag():
    raw = json.dumps({"text": "the </script> tag"})
    escaped = escape_script_json(raw)
    assert "</script" not in escaped
    assert json.loads(escaped.replace("<\\/", "</")) == json.loads(raw)


def test_escape_script_json_round_trips_via_real_json_slash_escape():
    """The mitigation relies on JSON permitting an optional \\/ escape for
    '/' -- confirm json.loads() actually accepts and decodes it back."""
    raw = json.dumps({"text": "a/b</script>c"})
    escaped = escape_script_json(raw)
    assert json.loads(escaped) == {"text": "a/b</script>c"}
