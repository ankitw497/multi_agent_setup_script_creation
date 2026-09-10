"""Tests for html_synth/component_library.py -- the channel component library (plan §7)."""
import pytest

from html_synth.component_library import (
    all_component_ids, components_for_story_role, css_tokens, render_component,
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
