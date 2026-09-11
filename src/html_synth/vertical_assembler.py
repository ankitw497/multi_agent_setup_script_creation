"""Vertical shorts template (plan §20.9, §20.11). One `short.html` per
ShortPlan (plan §16's artifact layout) -- a single scrollable page of four
full-bleed 1080x1920 "screens" (hook, setup, mechanism, payoff), each
reserving top/bottom safe zones for platform UI overlays (username/header,
caption/engagement buttons).

Structural only, matching V1A-S/V1B's own scope: actual pixel-level
clipping/overflow verification needs a real browser at this exact
viewport (Playwright, V1C -- plan §20.9's own "hard-gate only clipping..."
list is a RENDERED check). This guarantees the safe zones exist in the
template BY CONSTRUCTION (the safe content region is padded away from the
reserved edges in the CSS itself, not left to chance), which is what's
checkable without a browser.

Deliberately simpler than the long-form assembler: no numeric-claim
annotation or component library assembly -- plan §20.9's hard gates for
shorts never ask for `data-numeric-claim-id` traceability the way
long-form's H stage does; this only needs to get spoken narration onto a
safe, vertical-safe canvas.
"""
from __future__ import annotations

import hashlib
import html as html_module
import json

from narration.models import SceneNarration
from planning.shorts_models import ShortPlan

VERTICAL_WIDTH = 1080
VERTICAL_HEIGHT = 1920
SAFE_TOP = 180  # reserved for a platform's username/header overlay
SAFE_BOTTOM = 320  # reserved for caption/engagement-button overlays

_SEGMENT_ORDER = ("hook", "setup", "mechanism", "payoff")

# Real type-scale hierarchy per screen role (2026-09-11 redesign, replacing a
# uniform 36px everywhere on every screen regardless of role -- the flat
# treatment read as "unfinished" rather than minimal). hook/payoff bookend
# the short with the same large, bold voice; setup/mechanism read more like
# body copy since they carry the longer explanatory sentences.
_PROSE_STYLE = {
    "hook": "font-size:58px;line-height:1.15;font-weight:700;letter-spacing:-1.4px;",
    "setup": "font-size:32px;line-height:1.5;font-weight:500;letter-spacing:-0.2px;",
    "mechanism": "font-size:30px;line-height:1.5;font-weight:500;letter-spacing:-0.2px;",
    "payoff": "font-size:44px;line-height:1.25;font-weight:700;letter-spacing:-0.8px;",
}

VERTICAL_STYLESHEET = f"""\
body{{background:#111;}}
.short-page{{max-width:{VERTICAL_WIDTH}px;margin:0 auto;}}
.short-screen{{width:{VERTICAL_WIDTH}px;height:{VERTICAL_HEIGHT}px;margin-bottom:24px;position:relative;
  background:var(--bg2);overflow:hidden;display:flex;flex-direction:column;justify-content:center;}}
.short-safe-content{{position:relative;padding:{SAFE_TOP}px 64px {SAFE_BOTTOM}px;box-sizing:border-box;
  height:100%;display:flex;align-items:center;}}
.short-label{{display:inline-block;font-size:11px;font-weight:600;text-transform:uppercase;
  letter-spacing:0.1em;color:var(--accent);background:var(--bg3);
  padding:6px 14px;border-radius:20px;position:absolute;top:32px;left:32px;}}
.short-prose{{color:var(--text);font-family:var(--sans);}}
.short-flow{{display:flex;flex-direction:column;gap:0;margin-bottom:36px;}}
.short-flow-node{{display:flex;gap:18px;align-items:flex-start;}}
.short-flow-dot{{width:14px;height:14px;border-radius:50%;background:var(--accent);
  flex-shrink:0;margin-top:8px;}}
.short-flow-connector{{width:2px;flex-grow:1;background:var(--border);margin:2px 0 2px 6px;min-height:24px;}}
.short-flow-label{{font-family:var(--sans);font-size:24px;font-weight:500;color:var(--text);line-height:1.4;padding-bottom:20px;}}
"""


def _esc(text: str) -> str:
    return html_module.escape(text, quote=False)


def _flow_stages(plan: ShortPlan) -> list[str]:
    """A2s's own `visual.dominant_object`/`states` (plan §20.5) -- real
    content already authored by a real LLM call, previously silently
    dropped (user-reported 2026-09-11). No new call is needed; this only
    draws what A2s already decided."""
    states = [s for s in plan.visual.states if s.strip()]
    if not states:
        return []
    return ([plan.visual.dominant_object] if plan.visual.dominant_object.strip() else []) + states


def _render_flow_diagram(stages: list[str]) -> str:
    """A real connected node-flow diagram (HTML/CSS, not monospace arrow
    text) -- a labelled dot per stage joined by a connecting line, the
    same visual idiom as the long-form `step_list` component. HTML text
    wraps naturally regardless of label length, unlike hand-authored SVG
    text (which does not wrap without manual line-breaking)."""
    if not stages:
        return ""
    nodes = []
    for i, stage in enumerate(stages):
        connector = '<div class="short-flow-connector"></div>' if i < len(stages) - 1 else ""
        nodes.append(
            '<div class="short-flow-node">'
            '<div style="display:flex;flex-direction:column;align-items:center;">'
            f'<div class="short-flow-dot"></div>{connector}'
            "</div>"
            f'<div class="short-flow-label">{_esc(stage)}</div>'
            "</div>"
        )
    return f'<div class="short-flow">{"".join(nodes)}</div>'


def _render_screen(segment: str, prose: str, include_metadata: bool, diagram: str = "") -> str:
    narration_attr = f' data-narration-id="{_esc(segment)}"' if include_metadata else ""
    prose_style = _PROSE_STYLE.get(segment, _PROSE_STYLE["setup"])
    return (
        f'<div id="{_esc(segment)}" class="short-screen reveal"{narration_attr}>'
        f'<div class="short-label">{_esc(segment)}</div>'
        f'<div class="short-safe-content"><div>{diagram}<p class="short-prose" style="{prose_style}">{_esc(prose)}</p></div></div>'
        f"</div>"
    )


def synthesize_short_html(plan: ShortPlan, narration: list[SceneNarration]) -> str:
    from .component_library import BASE_STYLESHEET, css_tokens, escape_script_json

    narration_by_id = {n.scene_id: n for n in narration}
    diagram = _render_flow_diagram(_flow_stages(plan))
    screens_html = "".join(
        _render_screen(
            seg, " ".join(s.text for s in narration_by_id[seg].sentences), include_metadata=True,
            diagram=diagram if seg == "mechanism" else "",
        )
        for seg in _SEGMENT_ORDER if seg in narration_by_id
    )

    raw_narration_json = json.dumps([n.model_dump() for n in narration])
    narration_hash = "sha256:" + hashlib.sha256(raw_narration_json.encode("utf-8")).hexdigest()
    narration_block = (
        f'<script id="narration-data" type="application/json" '
        f'data-narration-hash="{narration_hash}">{escape_script_json(raw_narration_json)}</script>'
    )

    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"UTF-8\">\n"
        f'<meta name="viewport" content="width={VERTICAL_WIDTH}, initial-scale=1.0">\n'
        f"<title>{_esc(plan.title)}</title>\n"
        f"<style>{css_tokens()}\n{BASE_STYLESHEET}\n{VERTICAL_STYLESHEET}</style>\n"
        "</head>\n<body>\n"
        f'<div class="short-page">{screens_html}</div>\n{narration_block}\n'
        "</body>\n</html>\n"
    )
