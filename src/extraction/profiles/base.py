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


class ExtractionProfile(Protocol):
    name: str

    def confidence(self, soup: BeautifulSoup) -> float:
        """0.0-1.0: how confidently this profile's markers are present."""
        ...

    def extract(self, soup: BeautifulSoup) -> list[SourceUnit]:
        """Only called on the winning profile."""
        ...
