"""Deterministic assembly: (plan, hero, beat visuals, narration) -> the two
files the dual-audience contract requires (plan §12.0).

`video_script.html` and `page.html` are rendered by the SAME function,
parameterized only by `include_metadata` -- visible content is identical
by construction (one render path, not a stripped copy of the other), so
parity between the two isn't something a later check has to hope for.
"""
from __future__ import annotations

import hashlib
import html as html_module
import json

from narration.models import SceneNarration
from planning.models import StoryPlan

from .component_library import BASE_STYLESHEET, all_component_ids, css_tokens, escape_script_json, render_component
from .synthesizer import BeatVisual, HeroContent, SceneVisual

_SECTION_WRAP_CLASSES = ("sec-wrap", "sec-alt")


def _esc(text: str) -> str:
    return html_module.escape(text, quote=False)


def _annotate_numbers(prose: str, scene: SceneVisual, include_metadata: bool) -> str:
    escaped = _esc(prose)
    if not include_metadata:
        return escaped
    for ann in scene.annotated_numbers:
        needle = _esc(ann.text)
        if needle and needle in escaped:
            replacement = f'<span data-numeric-claim-id="{_esc(ann.claim_id)}">{needle}</span>'
            escaped = escaped.replace(needle, replacement, 1)  # first occurrence only -- never double-wrap
    return escaped


def _render_scene(scene: SceneVisual, include_metadata: bool) -> str:
    prose_html = _annotate_numbers(scene.screen_prose, scene, include_metadata)
    # `scene.component_id in all_component_ids()` (2026-09-27, same audit that found the
    # beat_id/item-key crashes): `component_id` is a plain `str | None` on the model's own
    # response, not schema-restricted to `allowed_components` -- render_component() itself
    # intentionally raises ValueError for an id outside design_system.yaml (a useful loud
    # failure for a programmer typo in CODE, tested directly), but that same strictness
    # would crash the whole page synthesis on a model-hallucinated id, which is a real,
    # reachable input here, not a code bug. Falls back to no component, same as the
    # existing "no component_id at all" case -- the scene's prose still renders either way.
    has_valid_component = scene.component_id and scene.component_id in all_component_ids()
    component_html = render_component(scene.component_id, scene.component_data) if has_valid_component else ""
    narration_attr = f' data-narration-id="{_esc(scene.scene_id)}"' if include_metadata else ""
    scene_id_attr = f' id="{_esc(scene.scene_id)}"' if include_metadata else ""
    return (
        f'<div{scene_id_attr} class="reveal"{narration_attr}>'
        f'<p class="subsection-body">{prose_html}</p>{component_html}</div>'
    )


def _render_beat(beat: BeatVisual, wrap_class: str, include_metadata: bool) -> str:
    scenes_html = "".join(_render_scene(s, include_metadata) for s in beat.scenes)
    return (
        f'<div class="{wrap_class}"><section class="reveal" id="beat-{_esc(beat.beat_id)}">'
        f'<h2 class="section-title">{_esc(beat.heading)}</h2>'
        f'<p class="section-sub">{_esc(beat.subheading)}</p>'
        f"{scenes_html}</section></div>"
    )


def _render_nav(plan: StoryPlan, beat_visuals: list[BeatVisual]) -> str:
    """Deterministic page chrome (STORY_IMPROVEMENT_PLAN.md Phase 31 item 1) -- a sticky nav
    with one progress-tracker entry per beat, built entirely from `beat_visuals`/`plan.title`
    (data H already produced), no new LLM call and no new content-generation risk. Renders
    the same in both `video_script.html` and `page.html` -- pure navigation chrome, not
    narration content, so it carries no dual-audience parity concern."""
    if not beat_visuals:
        return ""
    steps = "".join(
        f'<a class="prog-step" href="#beat-{_esc(bv.beat_id)}">'
        f'<span class="prog-dot"></span><span class="prog-label">{_esc(bv.heading)}</span></a>'
        for bv in beat_visuals
    )
    return (
        '<nav><div class="nav-main">'
        f'<span class="nav-logo">{_esc(plan.title.chosen)}</span>'
        "</div>"
        f'<div class="progress-tracker">{steps}</div>'
        "</nav>"
    )


def narration_hash(narration: list[SceneNarration]) -> str:
    payload = json.dumps([n.model_dump() for n in narration])
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _render_page(
    plan: StoryPlan, hero: HeroContent, beat_visuals: list[BeatVisual],
    narration: list[SceneNarration], include_metadata: bool,
) -> str:
    nav_html = _render_nav(plan, beat_visuals)
    hero_html = render_component("hero", {"badge": hero.badge, "title": hero.title, "subtitle": hero.subtitle})
    beats_html = "".join(
        _render_beat(bv, _SECTION_WRAP_CLASSES[i % 2], include_metadata)
        for i, bv in enumerate(beat_visuals)
    )

    narration_block = ""
    if include_metadata:
        narration_json = escape_script_json(json.dumps([n.model_dump() for n in narration]))
        narration_block = (
            f'<script id="narration-data" type="application/json" '
            f'data-narration-hash="{narration_hash(narration)}">{narration_json}</script>'
        )

    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        f"<title>{_esc(plan.title.chosen)}</title>\n"
        f"<style>{css_tokens()}\n{BASE_STYLESHEET}</style>\n"
        "</head>\n<body>\n"
        f"{nav_html}\n{hero_html}\n{beats_html}\n{narration_block}\n"
        "</body>\n</html>\n"
    )


def synthesize_page(
    plan: StoryPlan, hero: HeroContent, beat_visuals: list[BeatVisual], narration: list[SceneNarration],
) -> tuple[str, str]:
    """Returns (video_script_html, page_html)."""
    video_script_html = _render_page(plan, hero, beat_visuals, narration, include_metadata=True)
    page_html = _render_page(plan, hero, beat_visuals, narration, include_metadata=False)
    return video_script_html, page_html
