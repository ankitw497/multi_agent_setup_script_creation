"""S0 — deterministic HTML extraction (plan §6, §8, §17 V1A).

parse_html() is the single entry point: pick the best-matching profile
(or fall back to generic heading-driven segmentation), extract SourceUnits,
and separately run every inline <script> through the Acorn literal
extractor. Nothing here calls a model — this stage is 100% deterministic,
which is what makes it cacheable and free to re-run.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from facts.models import SourceUnit

from .js_literal_extractor import LiteralExtractionResult, extract_literals_from_scripts
from .profiles import ALL_PROFILES, FALLBACK_PROFILE
from .profiles.base import extract_pipeline_steps, sweep_numbers, visible_text

# Chrome that carries no story content — stripped before any profile sees the
# document, so nav text/link labels never leak into a SourceUnit's prose.
_CHROME_SELECTORS = [
    "nav", "#prog", ".nav-main", ".nav-brand", ".nav-links", ".nav-link",
    ".page-footer", ".hdivider",
]
# NOTE: deliberately NOT a bare "footer" tag selector. This design system
# uses <footer> for content elements too (.diagram-caption, .math-block
# both render as <footer> tags) -- a blanket "footer" selector silently
# deleted them. Found by running against a real source (project/
# attention_series/input/video-01-*.html), not assumed from markup lists.
#
# .page-footer itself IS mostly chrome (nav-adjacent captions), but on that
# same real source it also held "Production notes" -- see
# _extract_production_notes(), which runs BEFORE this strip and pulls that
# content out as its own SourceUnit so _strip_chrome() only discards the rest.

MIN_PROFILE_CONFIDENCE = 0.4


@dataclass
class ExtractionResult:
    units: list[SourceUnit]
    profile_name: str
    profile_confidence: float
    source_hash: str
    js_literals: dict = field(default_factory=dict)
    js_rejected: list = field(default_factory=list)
    js_parse_ok: bool = True


def _content_hash(html: str) -> str:
    return "sha256:" + hashlib.sha256(html.encode("utf-8")).hexdigest()


def _inline_script_texts(soup: BeautifulSoup) -> list[str]:
    """Scripts with no `src` — external libraries (KaTeX, etc.) are never parsed here."""
    return [tag.string or tag.get_text() for tag in soup.find_all("script") if not tag.get("src")]


def _strip_chrome(soup: BeautifulSoup) -> None:
    for selector in _CHROME_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()


def _extract_production_notes(soup: BeautifulSoup) -> SourceUnit | None:
    """`.page-footer` is stripped as chrome (see _CHROME_SELECTORS), but on at
    least one real source it holds the author's own "Production notes" — a
    timestamped .pipeline-step plan (Problem -> Mini payoff -> new problem ->
    ...) that is itself direct evidence of the intended story archetype. A
    real bug (found 2026-09-10): this was being silently discarded before A1/
    A2 ever saw it, and A2 then had to guess the archetype blind. Must run on
    the UNSTRIPPED soup, before _strip_chrome() removes .page-footer.
    """
    footer = soup.select_one(".page-footer")
    if footer is None:
        return None
    steps = extract_pipeline_steps(footer)
    if not steps:
        return None

    heading_el = footer.select_one(".content h3") or footer.find(["h2", "h3"])
    heading = visible_text(heading_el) if heading_el else "Production notes"
    text = " ".join(f"[{s['timestamp']}] {s['title']}: {s['text']}" for s in steps if s["title"] or s["text"])

    return SourceUnit(
        id="production_notes",
        heading=heading,
        level=1,
        text=text,
        kind="PRODUCTION_META",  # STORY_IMPROVEMENT_PLAN.md Phase 11 -- author's own storyboard
        # intent, not a technical assertion about the subject matter; S2b must never extract a
        # Claim from this unit (see facts/claim_extract.py).
        callouts=[f"{s['title']} ({s['timestamp']})" for s in steps if s["title"]],
        dom_path=".page-footer .pipeline",
        structure_confidence=1.0,
    )


def _extract_hero_hook(soup: BeautifulSoup) -> SourceUnit | None:
    """`<header class="hero">` sits BEFORE any `<section class="section">` in
    the document, so every profile's `section.select("section.section")` walk
    is structurally blind to it -- the same gap `_extract_production_notes`
    already fixed for `.page-footer`, mirrored here for the header. Real bug
    found 2026-09-11 (user-reported: the generated hook was generic/abstract
    while the source's own hook used a concrete minimal-pair example -- "the
    cat couldn't climb the stairs because it was too tired" vs "...too
    steep"). That example was never missing from the SOURCE, only from
    every SourceUnit ever built from it -- A1/A2 had no way to ground a
    concrete hook in content they were never given.
    """
    hero = soup.select_one("header.hero")
    if hero is None:
        return None
    heading_el = hero.find(["h1", "h2"])
    heading = visible_text(heading_el) if heading_el else ""
    body_el = hero.select_one(".hero-sub")
    text = visible_text(body_el) if body_el else visible_text(hero)
    if not text:
        return None
    return SourceUnit(
        id=hero.get("id") or "hook",
        heading=heading,
        level=1,
        text=text,
        numbers=sweep_numbers(text),
        dom_path="header.hero",
        structure_confidence=1.0,
    )


def parse_html(path: str | Path) -> ExtractionResult:
    html = Path(path).read_text(encoding="utf-8")
    return parse_html_string(html)


def parse_html_string(html: str) -> ExtractionResult:
    source_hash = _content_hash(html)

    # Pass 1: collect inline script text BEFORE anything is stripped.
    raw_soup = BeautifulSoup(html, "lxml")
    script_texts = _inline_script_texts(raw_soup)
    js_result: LiteralExtractionResult = extract_literals_from_scripts(script_texts)

    # Pass 2: a fresh soup, chrome and scripts removed, for profile matching + extraction.
    # Production notes must be pulled BEFORE chrome-stripping removes .page-footer.
    soup = BeautifulSoup(html, "lxml")
    hero_hook = _extract_hero_hook(soup)
    production_notes = _extract_production_notes(soup)
    _strip_chrome(soup)

    scored = [(profile, profile.confidence(soup)) for profile in ALL_PROFILES]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    best_profile, best_confidence = scored[0] if scored else (None, 0.0)

    if best_profile is None or best_confidence < MIN_PROFILE_CONFIDENCE:
        chosen_profile = FALLBACK_PROFILE
        chosen_confidence = chosen_profile.confidence(soup)
    else:
        chosen_profile = best_profile
        chosen_confidence = best_confidence

    units = chosen_profile.extract(soup)
    if hero_hook is not None:
        units.insert(0, hero_hook)
    if production_notes is not None:
        units.append(production_notes)

    return ExtractionResult(
        units=units,
        profile_name=chosen_profile.name,
        profile_confidence=chosen_confidence,
        source_hash=source_hash,
        js_literals=js_result.literals,
        js_rejected=[r.__dict__ for r in js_result.rejected],
        js_parse_ok=js_result.parse_ok,
    )
