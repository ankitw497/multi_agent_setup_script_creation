"""Extraction profile protocol (plan §6.1).

A profile scores its own confidence against a parsed document and, if
chosen, turns it into SourceUnits. Profiles never execute JS and never
guess at structure the DOM doesn't actually have — a low-confidence match
is supposed to lose to the generic fallback, not be forced.
"""
from __future__ import annotations

import re
from typing import Protocol

from bs4 import BeautifulSoup

from facts.models import SourceUnit

# Shared unit-bearing number sweep, reused by every profile (and the generic
# fallback) so number detection doesn't drift between them.
_NUMBER_RE = re.compile(
    r"\d[\d,.]*\s*(?:%|GB|MB|KB|TB|B|bytes?|billion|million|thousand|x|×|"
    r"ms|s|GHz|MHz|layers?|tokens?|bits?|params?|parameters?|heads?|"
    r"dimensions?|dims?)\b",
    re.IGNORECASE,
)


def sweep_numbers(text: str) -> list[str]:
    return [m.group(0) for m in _NUMBER_RE.finditer(text)]


def visible_text(tag) -> str:
    """Text of a tag with script/style stripped and whitespace collapsed."""
    for bad in tag.find_all(["script", "style"]):
        bad.decompose()
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()


def extract_pipeline_steps(container) -> list[dict]:
    """`.pipeline-step` (timestamp + title + guidance) is a real component of
    this markup family -- found both inside numbered sections and, in one
    real source, entirely inside a footer that chrome-stripping used to
    delete outright (a real bug found 2026-09-10: it happened to hold the
    single most decisive piece of story-planning evidence in the document,
    an author's own "Problem -> Mini payoff -> new problem" production
    notes, silently discarded before any archetype decision ever saw it).

    Returns [{"timestamp", "title", "text"}, ...] in document order.
    """
    steps = []
    for step in container.select(".pipeline-step"):
        dot = step.select_one(".pipeline-dot")
        title_el = step.select_one(".pipeline-content h4, .pipeline-content h3")
        body_el = step.select_one(".pipeline-content p")
        steps.append({
            "timestamp": visible_text(dot) if dot else "",
            "title": visible_text(title_el) if title_el else "",
            "text": visible_text(body_el) if body_el else "",
        })
    return steps


class ExtractionProfile(Protocol):
    name: str

    def confidence(self, soup: BeautifulSoup) -> float:
        """0.0-1.0: how confidently this profile's markers are present."""
        ...

    def extract(self, soup: BeautifulSoup) -> list[SourceUnit]:
        """Only called on the winning profile."""
        ...
