"""Generic fallback — heading-driven segmentation (plan §6.1, §6.4 Tier C).

Always "matches" at a low, fixed confidence so it never wins over a real
profile but is always available as the last resort for genuinely rough
HTML with none of the known markup families.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from facts.models import SourceUnit

from .base import sweep_numbers, visible_text

GENERIC_CONFIDENCE = 0.3


class GenericProfile:
    name = "generic"

    def confidence(self, soup: BeautifulSoup) -> float:
        return GENERIC_CONFIDENCE if soup.find(["h1", "h2", "h3"]) else 0.1

    def extract(self, soup: BeautifulSoup) -> list[SourceUnit]:
        headings = soup.find_all(["h1", "h2", "h3"])
        units: list[SourceUnit] = []

        if not headings:
            # No headings at all: the whole body is one unit. Tier C source
            # coverage (plan §6.4) will have to work with whatever this holds.
            body = soup.body or soup
            text = visible_text(body)
            return [
                SourceUnit(
                    id="unit_1", heading="", level=1, text=text,
                    numbers=sweep_numbers(text), dom_path="body",
                    structure_confidence=0.1,
                )
            ]

        for i, heading in enumerate(headings, start=1):
            level = int(heading.name[1])
            heading_text = visible_text(heading)

            # Collect sibling content until the next heading of this level or shallower.
            parts = []
            for sib in heading.find_next_siblings():
                if sib.name in ("h1", "h2", "h3") and int(sib.name[1]) <= level:
                    break
                parts.append(visible_text(sib))
            text = " ".join(p for p in parts if p)

            code = [c.get_text("\n") for c in heading.find_all_next(["pre", "code"], limit=5)]

            units.append(
                SourceUnit(
                    id=f"unit_{i}",
                    heading=heading_text,
                    level=level,
                    text=text,
                    numbers=sweep_numbers(text),
                    code=code[:1] if code else [],
                    dom_path=f"{heading.name}:nth-of-type({i})",
                    structure_confidence=GENERIC_CONFIDENCE,
                )
            )
        return units
