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
    soup = BeautifulSoup(html, "lxml")
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

    return ExtractionResult(
        units=units,
        profile_name=chosen_profile.name,
        profile_confidence=chosen_confidence,
        source_hash=source_hash,
        js_literals=js_result.literals,
        js_rejected=[r.__dict__ for r in js_result.rejected],
        js_parse_ok=js_result.parse_ok,
    )
