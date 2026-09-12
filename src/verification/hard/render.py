"""HV -- render verification, STATIC checks only (plan §13). Deterministic, no LLM.

The *rendered* checks (Playwright, clipping, contrast) now live in
`.render_rendered` (V1C) -- nothing in THIS module opens a browser.
`check_render_static`
covers plan §13's DOM-level "Hard (static)" list: HTML parses, unique ids,
every scene present in order, the narration-data hash matches
narration.json, every `data-numeric-claim-id` exists and traces to a real
claim, and `page.html`/`video_script.html` visual (here: text) parity.

`check_render_content` covers the content-level static checks that need
richer inputs than raw HTML (the plan, the hero, the beat visuals):
`renderer_compat` (Gate 1: >=3 sections, >=1,500 words -- a compatibility
rule, not a quality rule, plan §1/§9), the reader-standalone word-count
band, every scene actually carrying visible prose (not just a heading or a
diagram), and deictic-reference resolution. The reader-standalone band
(~2,000-3,200 words) is the plan's own stated figure for its sample
corpus, used as written rather than guessed at -- V1D may recalibrate it
per channel once more real output exists to calibrate against.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from facts.models import Claim
from html_synth.assembler import narration_hash
from html_synth.component_library import component_slots
from html_synth.synthesizer import BeatVisual, HeroContent
from narration.models import SceneNarration
from planning.models import StoryPlan

from .text_overlap import overlap

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class RenderIssue:
    code: str
    detail: str
    scene_id: str | None = None  # V1C: which scene this is about, when known --
    # load-bearing for the H-repair loop (which beat to regenerate) and the C3
    # sampler (which scenes are already flagged), not cosmetic. None for
    # page-wide static issues that were never scene-scoped to begin with.


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
    """The full HV static (DOM-level) pass -- every check, one call."""
    expected_scene_ids = [s.scene_id for s in narration]
    return (
        check_html_parses(video_script_html)
        + check_unique_ids(video_script_html)
        + check_scenes_present_in_order(video_script_html, expected_scene_ids)
        + check_narration_hash_matches(video_script_html, narration)
        + check_numeric_claim_ids_exist(video_script_html, claims)
        + check_page_parity(video_script_html, page_html)
    )


# plan §1/§9/§22: "Renderer compatibility is a compatibility rule, not a
# quality rule" -- Gate 1 from the separate render pipeline. Format-driven
# (a short's threshold would be far smaller); these are the long-form
# defaults.
RENDERER_COMPAT_MIN_SECTIONS = 3
RENDERER_COMPAT_MIN_WORDS = 1500

# plan §12.0: "visible word count sits in the article band (the samples:
# ~2,000-3,200)" -- the plan's own stated figure for its sample corpus,
# not a guess. A real V1B output landed at 3,218 words, just inside it.
READER_STANDALONE_WORD_BAND = (2000, 3200)


def check_renderer_compat(
    page_html: str, min_sections: int = RENDERER_COMPAT_MIN_SECTIONS, min_words: int = RENDERER_COMPAT_MIN_WORDS,
) -> list[RenderIssue]:
    soup = BeautifulSoup(page_html, "lxml")
    n_sections = len(soup.find_all("section"))
    word_count = len(visible_text(page_html).split())

    issues: list[RenderIssue] = []
    if n_sections < min_sections:
        issues.append(RenderIssue(
            "renderer_compat_too_few_sections", f"{n_sections} <section> elements, need >= {min_sections}",
        ))
    if word_count < min_words:
        issues.append(RenderIssue(
            "renderer_compat_too_few_words", f"{word_count} visible words, need >= {min_words}",
        ))
    return issues


def check_reader_standalone_word_count(
    page_html: str, low: int = READER_STANDALONE_WORD_BAND[0], high: int = READER_STANDALONE_WORD_BAND[1],
) -> list[RenderIssue]:
    word_count = len(visible_text(page_html).split())
    if not (low <= word_count <= high):
        return [RenderIssue(
            "reader_standalone_word_count_out_of_band", f"{word_count} visible words, expected {low}-{high}",
        )]
    return []


def check_every_scene_has_prose(beat_visuals: list[BeatVisual], min_words: int = 5) -> list[RenderIssue]:
    """plan §12.0: "every scene has visible prose, not just a heading and a
    diagram" -- a component alone is never a substitute for real screen text."""
    issues: list[RenderIssue] = []
    for beat in beat_visuals:
        for scene in beat.scenes:
            if len(scene.screen_prose.split()) < min_words:
                issues.append(RenderIssue(
                    "scene_missing_visible_prose",
                    f"{scene.scene_id} has no real screen prose (a component/diagram alone is not enough)",
                    scene_id=scene.scene_id,
                ))
    return issues


def _is_blank_slot_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def check_component_slots_filled(beat_visuals: list[BeatVisual]) -> list[RenderIssue]:
    """A chosen component whose own slots aren't all filled in renders as a
    visibly broken empty box -- `render_component()`'s generic path
    (`html_synth/component_library.py`) silently defaults a missing slot to
    "" rather than failing loudly. Confirmed live on two separate real runs
    (14 empty component-slot boxes each, regardless of story_lead model --
    H always runs on the same narration_lead) -- this was never checked
    for at all; only whether a scene has SOME screen prose
    (`check_every_scene_has_prose`), never whether its chosen component is
    actually complete."""
    issues: list[RenderIssue] = []
    for beat in beat_visuals:
        for scene in beat.scenes:
            if not scene.component_id:
                continue
            data = scene.component_data or {}
            blank_fields = sorted({
                slot for slot in component_slots(scene.component_id)
                if _is_blank_slot_value(data.get(slot))
            })
            items = data.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        blank_fields.extend(sorted(k for k, v in item.items() if _is_blank_slot_value(v)))
            if blank_fields:
                issues.append(RenderIssue(
                    "component_slot_blank",
                    f"{scene.scene_id}'s {scene.component_id!r} component has blank slot(s): {sorted(set(blank_fields))}",
                    scene_id=scene.scene_id,
                ))
    return issues


def check_hero_states_problem(hero: HeroContent, plan: StoryPlan, threshold: float = 0.1) -> list[RenderIssue]:
    """plan §12.0: "the hero states the problem." Checked against the
    plan's own hook (what the hero's badge/title/subtitle are meant to
    set up), the same generous word-overlap heuristic used for the
    promise-chain gate -- real semantic judgement stays with C1."""
    hero_text = f"{hero.title} {hero.subtitle}"
    if overlap(plan.hook.viewer_problem, hero_text) < threshold and overlap(plan.hook.tension, hero_text) < threshold:
        return [RenderIssue(
            "hero_does_not_state_the_problem",
            f"hero content ({hero_text!r}) shares little with the hook's viewer_problem/tension",
            scene_id="hero",  # sentinel: the H-repair loop routes this to repair_hero, not a beat
        )]
    return []


def check_payoff_closes(beat_visuals: list[BeatVisual], plan: StoryPlan, threshold: float = 0.1) -> list[RenderIssue]:
    """plan §12.0: "the payoff section closes it" -- the LAST scene's
    screen prose should connect to the plan's own stated ending.

    NOT included in check_render_content's hard aggregate -- see that
    function's docstring. First real false positive: a "Part 1 of 3"
    source correctly ends on `ending.next_video_bridge` rather than
    restating `capstone_payoff`/`compressed_mental_model` (fixed by
    including the bridge field in the comparison text). Second real false
    positive, on the SAME source, a different live run later: a
    differently-worded but equally valid bridge sentence still scored
    below threshold -- confirming this is a genuine semantic-relatedness
    judgment a word-overlap heuristic can't reliably make when the
    "matching" text is a paraphrase-prone bridge rather than a restated
    central topic. Kept here, tested, available for a future design that
    can actually judge it (a cheap LLM check, most likely)."""
    if not beat_visuals or not beat_visuals[-1].scenes:
        return [RenderIssue("no_payoff_scene", "no beats/scenes to check for a closing payoff")]
    last_prose = beat_visuals[-1].scenes[-1].screen_prose
    ending_text = (
        f"{plan.ending.compressed_mental_model} {plan.ending.capstone_payoff} "
        f"{plan.ending.next_video_bridge or ''}"
    )
    if overlap(ending_text, last_prose) < threshold:
        return [RenderIssue(
            "payoff_does_not_close",
            f"the final scene's prose ({last_prose!r}) shares little with the plan's ending "
            "(capstone_payoff/compressed_mental_model/next_video_bridge)",
        )]
    return []


# A demonstrative opening a sentence with nothing to visually point at is a
# real, narrow signal (plan §12: "deictic narration must resolve"). "it" is
# deliberately excluded -- it is used constantly for ordinary anaphoric
# reference within a sentence (as in this very source's own running "it"
# example) and would make this check almost pure noise.
_DEICTIC_STARTERS = ("this ", "that ")


def check_deictic_resolution(plan: StoryPlan, narration: list[SceneNarration]) -> list[RenderIssue]:
    scene_visual_desc = {s.scene_id: s.visual_description for s in plan.scene_plan}
    issues: list[RenderIssue] = []
    for scene in narration:
        if scene_visual_desc.get(scene.scene_id, "").strip():
            continue  # has something to point at
        for i, sentence in enumerate(scene.sentences):
            lowered = sentence.text.strip().lower()
            if lowered.startswith(_DEICTIC_STARTERS):
                issues.append(RenderIssue(
                    "deictic_reference_unresolved",
                    f"{scene.scene_id} sentence {i} opens with a demonstrative ({sentence.text[:50]!r}) "
                    "but the scene has no visual_description to resolve it against",
                    scene_id=scene.scene_id,
                ))
    return issues


def check_render_content(
    page_html: str, plan: StoryPlan, hero: HeroContent, beat_visuals: list[BeatVisual],
    narration: list[SceneNarration],
) -> list[RenderIssue]:
    """The full content-level static pass -- every check, one call.

    `check_payoff_closes` is deliberately NOT included here (see its own
    docstring) -- two separate live runs against the same real source both
    showed it flagging a genuinely valid "bridge to Part 2" ending whose
    exact wording simply varies each time H regenerates it, which a
    mechanical word-match can't reliably follow. Rather than keep chasing
    a threshold to fit one observed run (the same anti-pattern already
    ruled out for ERR-010), it's kept available and tested for future
    refinement, but not wired into the hard gate."""
    return (
        check_renderer_compat(page_html)
        + check_reader_standalone_word_count(page_html)
        + check_every_scene_has_prose(beat_visuals)
        + check_component_slots_filled(beat_visuals)
        + check_hero_states_problem(hero, plan)
        + check_deictic_resolution(plan, narration)
    )
