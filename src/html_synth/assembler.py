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

from .component_library import BASE_STYLESHEET, REVEAL_SCRIPT, css_tokens, escape_script_json, render_component
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
    component_html = render_component(scene.component_id, scene.component_data) if scene.component_id else ""
    narration_attr = f' data-narration-id="{_esc(scene.scene_id)}"' if include_metadata else ""
    scene_id_attr = f' id="{_esc(scene.scene_id)}"' if include_metadata else ""
    return (
        f'<div{scene_id_attr} class="reveal"{narration_attr}>'
        f'<p class="subsection-body">{prose_html}</p>{component_html}</div>'
    )


def _render_beat(beat: BeatVisual, wrap_class: str, include_metadata: bool) -> str:
    scenes_html = "".join(_render_scene(s, include_metadata) for s in beat.scenes)
    return (
        f'<div class="{wrap_class}"><section class="reveal">'
        f'<h2 class="section-title">{_esc(beat.heading)}</h2>'
        f'<p class="section-sub">{_esc(beat.subheading)}</p>'
        f"{scenes_html}</section></div>"
    )


def narration_hash(narration: list[SceneNarration]) -> str:
    payload = json.dumps([n.model_dump() for n in narration])
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _render_page(
    plan: StoryPlan, hero: HeroContent, beat_visuals: list[BeatVisual],
    narration: list[SceneNarration], include_metadata: bool,
) -> str:
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
        f"{hero_html}\n{beats_html}\n{narration_block}\n"
        f"<script>{REVEAL_SCRIPT}</script>\n"
        "</body>\n</html>\n"
    )


def synthesize_page(
    plan: StoryPlan, hero: HeroContent, beat_visuals: list[BeatVisual], narration: list[SceneNarration],
) -> tuple[str, str]:
    """Returns (video_script_html, page_html)."""
    video_script_html = _render_page(plan, hero, beat_visuals, narration, include_metadata=True)
    page_html = _render_page(plan, hero, beat_visuals, narration, include_metadata=False)
    return video_script_html, page_html
