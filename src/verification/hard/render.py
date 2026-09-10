"""HV -- render verification, STATIC checks only (plan §13). Deterministic, no LLM.

The *rendered* checks (Playwright, clipping, contrast, C3 screenshot
audit) are V1C scope -- nothing here opens a browser. This covers exactly
what plan §13 lists as "Hard (static)": HTML parses, unique ids, every
scene present in order, the narration-data hash matches narration.json,
every `data-numeric-claim-id` exists and traces to a real claim, and
`page.html`/`video_script.html` visual (here: text) parity.

Deliberately NOT yet implemented (flagged, not silently skipped -- see
BUILD_PLAN.md): the reader-standalone word-count-band check and
`renderer_compat`'s >=1500-claim-backed-words gate both need a calibration
decision (the plan's ~2,000-3,200 band is tuned to that channel's own
10-minute samples) that shouldn't be guessed at; deictic-reference
resolution needs real NLP, not pattern matching.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from facts.models import Claim
from html_synth.assembler import narration_hash
from narration.models import SceneNarration

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class RenderIssue:
    code: str
    detail: str


def visible_text(html: str) -> str:
    """What a reader actually sees -- <script>/<style> CONTENT is never
    visible in a browser (unlike other tags, where only the tag itself
    disappears), so those are stripped wholesale first."""
    without_scripts = _SCRIPT_STYLE_RE.sub("", html)
    return _TAG_RE.sub("", without_scripts)


def check_html_parses(html: str) -> list[RenderIssue]:
    try:
        BeautifulSoup(html, "lxml")
    except Exception as e:  # pragma: no cover -- lxml is extremely tolerant; kept as a real safety net
        return [RenderIssue("html_parse_error", str(e))]
    return []


def check_unique_ids(html: str) -> list[RenderIssue]:
    soup = BeautifulSoup(html, "lxml")
    ids = [el.get("id") for el in soup.find_all(id=True)]
    seen: set[str] = set()
    issues: list[RenderIssue] = []
    for id_ in ids:
        if id_ in seen:
            issues.append(RenderIssue("duplicate_id", f"id={id_!r} appears more than once"))
        seen.add(id_)
    return issues


def check_scenes_present_in_order(html: str, expected_scene_ids: list[str]) -> list[RenderIssue]:
    soup = BeautifulSoup(html, "lxml")
    present_ids_in_order = [el.get("id") for el in soup.find_all(id=True)]
    issues: list[RenderIssue] = []

    missing = [sid for sid in expected_scene_ids if sid not in present_ids_in_order]
    if missing:
        issues.append(RenderIssue("scene_missing_from_dom", f"scene ids never rendered: {missing}"))

    present_expected = [sid for sid in present_ids_in_order if sid in expected_scene_ids]
    if present_expected != [sid for sid in expected_scene_ids if sid in present_expected]:
        issues.append(RenderIssue("scenes_out_of_order", f"rendered order {present_expected} != plan order"))
    return issues


def check_narration_hash_matches(html: str, narration: list[SceneNarration]) -> list[RenderIssue]:
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find(id="narration-data")
    if tag is None:
        return [RenderIssue("narration_data_missing", "no #narration-data script block found")]
    dom_hash = tag.get("data-narration-hash")
    expected_hash = narration_hash(narration)
    if dom_hash != expected_hash:
        return [RenderIssue(
            "narration_hash_mismatch", f"DOM hash {dom_hash!r} != narration.json hash {expected_hash!r}",
        )]
    return []


def check_numeric_claim_ids_exist(html: str, claims: list[Claim]) -> list[RenderIssue]:
    known_ids = {c.claim_id for c in claims}
    soup = BeautifulSoup(html, "lxml")
    issues: list[RenderIssue] = []
    for el in soup.find_all(attrs={"data-numeric-claim-id": True}):
        claim_id = el["data-numeric-claim-id"]
        if claim_id not in known_ids:
            issues.append(RenderIssue(
                "numeric_claim_id_unknown", f"data-numeric-claim-id={claim_id!r} is not in the claim registry",
            ))
    return issues


def check_page_parity(video_script_html: str, page_html: str) -> list[RenderIssue]:
    """The text-level version of plan §12.0's "HV asserts the two render
    pixel-identically" -- V1B has no browser (that's V1C); this is what's
    checkable without one, and should never fail given both files come
    from html_synth.assembler's single shared render path."""
    if visible_text(video_script_html) != visible_text(page_html):
        return [RenderIssue("page_parity_mismatch", "video_script.html and page.html have different visible text")]
    return []


def check_render_static(
    video_script_html: str, page_html: str, narration: list[SceneNarration], claims: list[Claim],
) -> list[RenderIssue]:
    """The full HV static pass -- every check, one call."""
    expected_scene_ids = [s.scene_id for s in narration]
    return (
        check_html_parses(video_script_html)
        + check_unique_ids(video_script_html)
        + check_scenes_present_in_order(video_script_html, expected_scene_ids)
        + check_narration_hash_matches(video_script_html, narration)
        + check_numeric_claim_ids_exist(video_script_html, claims)
        + check_page_parity(video_script_html, page_html)
    )
