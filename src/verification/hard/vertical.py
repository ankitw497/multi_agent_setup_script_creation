"""Hard gates for the vertical shorts template (plan §20.9). Deterministic,
no browser -- pixel-level clipping/overflow verification needs a real
Playwright render at this exact viewport (V1C); this checks what IS
verifiable from the HTML/CSS alone: the safe-zone padding the template
promises is actually present (not just documented as a constant, which a
future template edit could silently drop), every expected segment
renders, and the narration hash matches.

Reuses RenderIssue (not a parallel type) since the shape is identical --
and reuses check_scenes_present_in_order/check_narration_hash_matches
outright, since a "screen" id here is exactly a scene id there.
"""
from __future__ import annotations

from html_synth.vertical_assembler import SAFE_BOTTOM, SAFE_TOP, VERTICAL_HEIGHT, VERTICAL_WIDTH
from narration.models import SceneNarration

from .render import RenderIssue, check_narration_hash_matches, check_scenes_present_in_order


def check_safe_zones_present(html: str) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    if f"{SAFE_TOP}px" not in html:
        issues.append(RenderIssue("safe_zone_top_missing", f"expected top safe-zone padding of {SAFE_TOP}px in the stylesheet"))
    if f"{SAFE_BOTTOM}px" not in html:
        issues.append(RenderIssue("safe_zone_bottom_missing", f"expected bottom safe-zone padding of {SAFE_BOTTOM}px in the stylesheet"))
    return issues


def check_vertical_canvas_size(html: str) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    if f"{VERTICAL_WIDTH}px" not in html:
        issues.append(RenderIssue("vertical_width_missing", f"expected a {VERTICAL_WIDTH}px canvas width"))
    if f"{VERTICAL_HEIGHT}px" not in html:
        issues.append(RenderIssue("vertical_height_missing", f"expected a {VERTICAL_HEIGHT}px canvas height"))
    return issues


def check_vertical_short(html: str, narration: list[SceneNarration]) -> list[RenderIssue]:
    """The full vertical-short static pass -- every check, one call."""
    expected_segments = [n.scene_id for n in narration]
    return (
        check_scenes_present_in_order(html, expected_segments)
        + check_narration_hash_matches(html, narration)
        + check_safe_zones_present(html)
        + check_vertical_canvas_size(html)
    )
