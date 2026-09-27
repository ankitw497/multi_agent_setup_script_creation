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


def test_text3_on_bg3_clears_wcag_aa_contrast():
    """Real, systemic finding (2026-09-11): text3 on bg3 used to be a
    4.15:1 contrast, just under WCAG AA's 4.5:1 -- it survived 2 real
    H-repair attempts every single live run, because no content
    regeneration can fix a CSS color choice. Locks in the corrected token
    directly against the same contrast math the rendered check uses."""
    from html_synth.component_library import _design_system
    from verification.hard.render_rendered import _contrast_ratio

    ds = _design_system()
    text3 = tuple(int(ds["tokens"]["colors"]["text3"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    bg3 = tuple(int(ds["tokens"]["colors"]["bg3"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    assert _contrast_ratio(text3, bg3) >= 4.5


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


def test_card_renders_all_slots_when_all_present():
    out = render_component("card", {"title": "Speed", "value": "3.2x", "desc": "faster"})
    assert '<div class="card-title">Speed</div>' in out
    assert '<div class="card-value">3.2x</div>' in out
    assert '<div class="card-desc">faster</div>' in out


def test_card_omits_blank_slots_instead_of_rendering_an_empty_box():
    """Real bug found live 2026-09-14: a partial card (e.g. title+desc, no
    value -- a legitimate shape for a grid_2/grid_3 item) used to still
    render a visibly empty <div class="card-value"></div> box. Confirmed
    on a real run: 36 empty step-desc/card-* boxes in one page. Omit the
    div entirely instead of rendering it blank."""
    out = render_component("card", {"title": "Speed", "desc": "faster"})
    assert '<div class="card-title">Speed</div>' in out
    assert '<div class="card-desc">faster</div>' in out
    assert "card-value" not in out


def test_card_with_only_a_title_omits_both_other_blocks():
    out = render_component("card", {"title": "Speed"})
    assert '<div class="card-title">Speed</div>' in out
    assert "card-value" not in out
    assert "card-desc" not in out


def test_step_list_item_with_no_desc_omits_the_desc_div():
    out = render_component("step_list", {"items": [{"title": "Step one"}]})
    assert '<div class="step-title">Step one</div>' in out
    assert "step-desc" not in out


def test_step_list_plain_string_item_omits_the_desc_div_too():
    """A plain-string item's whole content becomes the title (per this
    renderer's own existing contract) -- it has no desc at all, so no
    step-desc div should appear."""
    out = render_component("step_list", {"items": ["Just a step"]})
    assert '<div class="step-title">Just a step</div>' in out
    assert "step-desc" not in out


def test_step_list_item_with_a_real_desc_still_renders_it():
    out = render_component("step_list", {"items": [{"title": "Step one", "desc": "does the thing"}]})
    assert '<div class="step-desc">does the thing</div>' in out


def test_step_list_item_missing_title_degrades_to_blank_not_a_crash():
    """Real crash, 2026-09-27: a dict item missing "title" raised KeyError instead of
    degrading like every other missing field on this same item already does."""
    out = render_component("step_list", {"items": [{"desc": "does the thing"}]})
    assert '<div class="step-title"></div>' in out


def test_suspect_board_renders_one_suspect_per_item():
    out = render_component("suspect_board", {"items": [
        {"name": "Weights", "note": "the model parameters themselves"},
        {"name": "KV Cache", "note": "stored K/V history"},
    ]})
    assert out.count('class="suspect"') == 2
    assert '<div class="suspect-name">Weights</div>' in out
    assert '<div class="suspect-note">the model parameters themselves</div>' in out


def test_suspect_board_item_with_no_note_omits_the_note_div():
    out = render_component("suspect_board", {"items": [{"name": "Weights"}]})
    assert '<div class="suspect-name">Weights</div>' in out
    assert "suspect-note" not in out


def test_suspect_board_item_missing_name_degrades_to_blank_not_a_crash():
    """Real crash, 2026-09-27: same bug class as step_list -- a dict item missing "name"
    must degrade to a blank slot, not KeyError the whole page."""
    out = render_component("suspect_board", {"items": [{"note": "stored K/V history"}]})
    assert '<div class="suspect-name"></div>' in out


def test_solution_grid_renders_one_option_per_item():
    out = render_component("solution_grid", {"items": [
        {"name": "QLoRA", "body": "quantized base weights"},
        {"name": "Full fine-tune", "body": "every parameter updated"},
    ]})
    assert out.count('class="solution-card"') == 2
    assert '<div class="solution-name">QLoRA</div>' in out
    assert '<div class="solution-body">quantized base weights</div>' in out


def test_solution_grid_item_with_no_body_omits_the_body_div():
    out = render_component("solution_grid", {"items": [{"name": "QLoRA"}]})
    assert '<div class="solution-name">QLoRA</div>' in out
    assert "solution-body" not in out


def test_solution_grid_item_missing_name_degrades_to_blank_not_a_crash():
    """Real crash, 2026-09-27: a live run's first-ever solution_grid use (surfaced only
    once the Phase 32 prompt nudge away from diagram_card's monopoly made the model
    actually reach for this component) crashed with KeyError on a dict item that omitted
    "name" -- must degrade to a blank slot like every other missing field already does."""
    out = render_component("solution_grid", {"items": [{"body": "quantized base weights"}]})
    assert '<div class="solution-name"></div>' in out


def test_case_card_renders_title_sub_and_body():
    out = render_component("case_card", {"title": "The T4 case", "sub": "16GB VRAM", "body": "weights alone take 15.2GB"})
    assert '<div class="case-title">The T4 case</div>' in out
    assert '<div class="case-sub">16GB VRAM</div>' in out
    assert "weights alone take 15.2GB" in out


def test_case_card_omits_blank_sub_and_body():
    out = render_component("case_card", {"title": "The T4 case"})
    assert '<div class="case-title">The T4 case</div>' in out
    assert "case-sub" not in out
    assert "subsection-body" not in out


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


def test_metric_table_scalar_row_degrades_to_a_single_cell_not_a_crash():
    """Found live, 2026-09-27 audit: `for cell in row` on a scalar row (the model
    returning a bare value instead of a list) would raise TypeError and crash the
    whole page -- must degrade to a single-cell row instead."""
    out = render_component("metric_table", {"headers": ["A"], "rows": ["just a string", ["1"]]})
    assert "<td>just a string</td>" in out
    assert "<td>1</td>" in out


def test_metric_table_dict_shaped_row_renders_its_values_not_its_keys():
    """2026-09-27 audit: metric_table's item shape is documented only in a YAML comment,
    never sent to the model -- a model guessing the same dict-per-item shape every
    sibling component actually uses is a real, plausible response. Must render the
    dict's VALUES as cells, not its keys (and not crash)."""
    out = render_component("metric_table", {
        "headers": ["Metric", "Before", "After"],
        "rows": [{"metric": "Accuracy", "before": "62%", "after": "89%"}],
    })
    assert "<td>Accuracy</td>" in out
    assert "<td>62%</td>" in out
    assert "metric</td>" not in out  # the dict's KEY must not leak into a cell


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
    assert "math_block" in components_for_story_role("mechanism")
    assert "math_block" in components_for_story_role("derivation")


def test_hero_is_never_offered_as_a_per_scene_choice():
    """PIPELINE_AUDIT_2026-09-17.md finding #2: "hero" is page-singleton (assembler.py
    already renders exactly one, unconditionally, before any beat content) -- offering it
    as a per-scene "hook" role choice let H pick it again, producing a real duplicate
    id="hero-story" that check_unique_ids can never attribute to a repairable scene_id."""
    assert "hero" not in components_for_story_role("hook")
    assert "card" in components_for_story_role("hook")


def test_unknown_story_role_returns_empty_not_a_crash():
    assert components_for_story_role("not_a_real_role") == []


def test_diagram_card_is_available_to_comparison_derivation_and_payoff_too():
    """STORY_IMPROVEMENT_PLAN.md Phase 27 item 1, confirmed live (v05): H picks diagram_card
    83% of the time where it's actually offered (mechanism role), but most mechanism-shaped
    content in a real video gets tagged payoff/comparison/derivation instead of mechanism,
    and those roles never had diagram_card in their allowlist at all -- a real payoff-role
    scene narrating a 4-stage pipeline rendered as a plain card purely because of this."""
    for role in ("comparison", "derivation", "payoff"):
        assert "diagram_card" in components_for_story_role(role), f"{role!r} still excludes diagram_card"
        assert "card" in components_for_story_role(role)  # the plain option must still remain available


def test_diagram_card_is_available_to_problem_fix_too():
    """2026-09-24: the one role Phase 27 item 1 missed -- confirmed live (Opus 5.5
    story_lead comparison run) that a build-archetype plan can tag nearly half its beats
    problem_fix (6/13), and problem_fix had zero diagram-capable options, locking a
    build video's own problem->fix chain (very often a mechanism/pipeline/equation) out
    of the one component built for exactly that content."""
    assert "diagram_card" in components_for_story_role("problem_fix")
    assert "step_list" in components_for_story_role("problem_fix")
    assert "callout_warn" in components_for_story_role("problem_fix")


def test_suspect_board_is_available_to_contradiction_and_investigation():
    """STORY_IMPROVEMENT_PLAN.md Phase 31 item 3: a lineup of candidate causes is exactly
    the shape a sustained mystery archetype needs for these two roles."""
    for role in ("contradiction", "investigation"):
        assert "suspect_board" in components_for_story_role(role)


def test_solution_grid_is_available_to_payoff_only():
    assert "solution_grid" in components_for_story_role("payoff")
    for role in ("hook", "mechanism", "problem_fix", "derivation", "observations"):
        assert "solution_grid" not in components_for_story_role(role)


def test_case_card_is_available_to_observations_and_mechanism():
    for role in ("observations", "mechanism"):
        assert "case_card" in components_for_story_role(role)


def test_case_card_is_available_to_problem_fix_too():
    """Phase 32 P1: confirmed live -- problem_fix is the single most-repeated role in a
    real build-archetype plan (3-4 of ~11-12 beats), and "here's a specific problem,
    here's its specific fix" is a near-verbatim match for case_card's own "here's a
    specific instance of the general rule" shape. Two real generated pages defaulted to
    diagram_card for every single problem_fix scene with no alternative available."""
    assert "case_card" in components_for_story_role("problem_fix")
    assert "diagram_card" in components_for_story_role("problem_fix")  # still available too


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
