"""HV -- RENDERED checks (plan §13, V1C). Needs a real browser (Playwright);
`render.py`'s static checks never import this module and work with zero
Playwright installed.

Checked against `video_script.html`, not `page.html` -- `page.html` strips
`id`/`data-narration-id` (plan §12.0's metadata-stripped publishable copy),
so it has no per-scene DOM hooks to check against at all.

Every check splits into a pure judgment function (plain floats/bools, no
Playwright types -- unit-tested with zero browser) and thin Playwright I/O
glue (real `Page`/`ElementHandle` calls) per plan §13's own hard-check
list: clipping, overflow, invisible required content, contrast below
readability. `run_rendered_checks` is the runner that owns the browser
lifecycle for both required viewports (1920x1080 desktop, a 390px-wide
mobile viewport).
"""
from __future__ import annotations

from narration.models import SceneNarration

from .render import RenderIssue

CONTRAST_THRESHOLD = 4.5  # WCAG AA for normal text
OVERFLOW_TOLERANCE_PX = 2  # sub-pixel rounding noise, not a real overflow

_DESKTOP_VIEWPORT = (1920, 1080)
_MOBILE_VIEWPORT = (390, 844)


# ---- pure judgment functions (no Playwright types, unit-tested standalone) ----

def _is_clipped_or_overflowing(
    scroll_width: float, client_width: float, scroll_height: float, client_height: float,
    tolerance: float = OVERFLOW_TOLERANCE_PX,
) -> bool:
    return (scroll_width - client_width > tolerance) or (scroll_height - client_height > tolerance)


def _is_invisible(opacity: float, visibility: str, display: str, bbox_width: float, bbox_height: float) -> bool:
    if display == "none" or visibility == "hidden" or opacity <= 0.0:
        return True
    return bbox_width <= 0 or bbox_height <= 0


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        c_norm = c / 255.0
        return c_norm / 12.92 if c_norm <= 0.03928 else ((c_norm + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast_ratio(fg_rgb: tuple[int, int, int], bg_rgb: tuple[int, int, int]) -> float:
    l1 = _relative_luminance(fg_rgb) + 0.05
    l2 = _relative_luminance(bg_rgb) + 0.05
    return max(l1, l2) / min(l1, l2)


def _contrast_fails(ratio: float, threshold: float = CONTRAST_THRESHOLD) -> bool:
    return ratio < threshold


# ---- thin Playwright I/O glue ----

def _scene_element(page, scene_id: str):
    return page.query_selector(f'#{scene_id}, [data-narration-id="{scene_id}"]')


def check_rendered_clipping(page, scene_ids: list[str]) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    for scene_id in scene_ids:
        el = _scene_element(page, scene_id)
        if el is None:
            continue
        candidates = el.evaluate(
            """el => {
                const out = [];
                function walk(node) {
                    const cs = getComputedStyle(node);
                    if (/hidden|clip|scroll|auto/.test(cs.overflow + cs.overflowX + cs.overflowY)) {
                        out.push({
                            scrollWidth: node.scrollWidth, clientWidth: node.clientWidth,
                            scrollHeight: node.scrollHeight, clientHeight: node.clientHeight,
                            tag: node.tagName, cls: node.className,
                        });
                    }
                    for (const child of node.children) walk(child);
                }
                walk(el);
                return out;
            }"""
        )
        for c in candidates:
            if _is_clipped_or_overflowing(c["scrollWidth"], c["clientWidth"], c["scrollHeight"], c["clientHeight"]):
                issues.append(RenderIssue(
                    "rendered_clipping",
                    f"<{c['tag'].lower()} class={c['cls']!r}> content ({c['scrollWidth']}x{c['scrollHeight']}) "
                    f"overflows its box ({c['clientWidth']}x{c['clientHeight']})",
                    scene_id=scene_id,
                ))
    return issues


def check_rendered_invisible_required_content(page, scene_ids: list[str]) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    for scene_id in scene_ids:
        el = _scene_element(page, scene_id)
        if el is None:
            continue
        data = el.evaluate(
            """el => {
                const cs = getComputedStyle(el);
                const box = el.getBoundingClientRect();
                return {
                    opacity: parseFloat(cs.opacity), visibility: cs.visibility, display: cs.display,
                    width: box.width, height: box.height, textLength: el.innerText.trim().length,
                };
            }"""
        )
        if data["textLength"] > 0 and _is_invisible(
            data["opacity"], data["visibility"], data["display"], data["width"], data["height"],
        ):
            issues.append(RenderIssue(
                "rendered_invisible_required_content",
                f"scene has real text content ({data['textLength']} chars) but is invisible "
                f"(opacity={data['opacity']}, visibility={data['visibility']!r}, display={data['display']!r})",
                scene_id=scene_id,
            ))
    return issues


def check_rendered_contrast(page, scene_ids: list[str]) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    for scene_id in scene_ids:
        el = _scene_element(page, scene_id)
        if el is None:
            continue
        pairs = el.evaluate(
            """el => {
                function parseRgb(str) {
                    const m = str.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                    return m ? [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])] : null;
                }
                function bgOf(node) {
                    let cur = node;
                    while (cur) {
                        const cs = getComputedStyle(cur);
                        if (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)') {
                            const rgb = parseRgb(cs.backgroundColor);
                            if (rgb) return rgb;
                        }
                        cur = cur.parentElement;
                    }
                    return [255, 255, 255];
                }
                const out = [];
                const seen = new Set();
                const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
                let node;
                while (node = walker.nextNode()) {
                    if (!node.textContent.trim()) continue;
                    const parent = node.parentElement;
                    if (!parent || seen.has(parent)) continue;
                    seen.add(parent);
                    const cs = getComputedStyle(parent);
                    const fg = parseRgb(cs.color);
                    if (fg) out.push({fg, bg: bgOf(parent), tag: parent.tagName});
                }
                return out;
            }"""
        )
        for pair in pairs:
            ratio = _contrast_ratio(tuple(pair["fg"]), tuple(pair["bg"]))
            if _contrast_fails(ratio):
                issues.append(RenderIssue(
                    "rendered_low_contrast",
                    f"<{pair['tag'].lower()}> text/background contrast {ratio:.2f}:1 is below "
                    f"{CONTRAST_THRESHOLD}:1 (fg={pair['fg']}, bg={pair['bg']})",
                    scene_id=scene_id,
                ))
    return issues


def run_rendered_checks(video_script_html: str, narration: list[SceneNarration]) -> list[RenderIssue]:
    """Opens both required viewports against `video_script_html` (the
    metadata-carrying render source, never the stripped `page.html`) and
    runs every rendered check at each. Raises ImportError if playwright
    isn't installed -- callers are expected to catch that and record a
    visible degradation, never to silently swallow it (plan §14's "a
    degraded run must look degraded")."""
    from playwright.sync_api import sync_playwright  # local: this is the only Playwright import boundary

    scene_ids = [n.scene_id for n in narration]
    issues: list[RenderIssue] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width, height in (_DESKTOP_VIEWPORT, _MOBILE_VIEWPORT):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.emulate_media(reduced_motion="reduce")  # neutralize the .reveal fade-in animation
                page.set_content(video_script_html, wait_until="networkidle")
                tag = f"{width}x{height}"
                for check in (check_rendered_clipping, check_rendered_invisible_required_content, check_rendered_contrast):
                    for issue in check(page, scene_ids):
                        issues.append(RenderIssue(issue.code, f"[{tag}] {issue.detail}", scene_id=issue.scene_id))
                page.close()
        finally:
            browser.close()

    return issues
