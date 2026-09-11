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

VERTICAL_STYLESHEET = f"""\
body{{background:#111;}}
.short-page{{max-width:{VERTICAL_WIDTH}px;margin:0 auto;}}
.short-screen{{width:{VERTICAL_WIDTH}px;height:{VERTICAL_HEIGHT}px;margin-bottom:24px;position:relative;
  background:var(--bg2);overflow:hidden;display:flex;flex-direction:column;justify-content:center;}}
.short-safe-content{{padding:{SAFE_TOP}px 64px {SAFE_BOTTOM}px;box-sizing:border-box;height:100%;
  display:flex;align-items:center;}}
.short-label{{position:absolute;top:24px;left:32px;font-size:15px;color:var(--text3);
  text-transform:uppercase;letter-spacing:0.08em;}}
.short-prose{{font-size:38px;line-height:1.4;color:var(--text);font-family:var(--serif);}}
"""


def _esc(text: str) -> str:
    return html_module.escape(text, quote=False)


def _render_screen(segment: str, prose: str, include_metadata: bool) -> str:
    narration_attr = f' data-narration-id="{_esc(segment)}"' if include_metadata else ""
    return (
        f'<div id="{_esc(segment)}" class="short-screen reveal"{narration_attr}>'
        f'<div class="short-label">{_esc(segment)}</div>'
        f'<div class="short-safe-content"><p class="short-prose">{_esc(prose)}</p></div>'
        f"</div>"
    )


def synthesize_short_html(plan: ShortPlan, narration: list[SceneNarration]) -> str:
    from .component_library import BASE_STYLESHEET, REVEAL_SCRIPT, css_tokens, escape_script_json

    narration_by_id = {n.scene_id: n for n in narration}
    screens_html = "".join(
        _render_screen(seg, " ".join(s.text for s in narration_by_id[seg].sentences), include_metadata=True)
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
        f"<script>{REVEAL_SCRIPT}</script>\n"
        "</body>\n</html>\n"
    )
