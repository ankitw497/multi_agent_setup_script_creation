"""Family A — the "guide" markup profile (plan §6.1).

Matches sources like docs/corpus (visual_guide-style) and
project/attention_series/input/video-01-*: `<section class="section" id=…>`,
`.sec-title`/`.sec-label`, `.diagram-card`, `.math-block`
(+ `.math-block-label`), `.callout <bareword variant>` (space-separated
modifier, e.g. `class="callout info"` — NOT the hyphenated
`callout-info` compound class the video-script profile uses).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from facts.models import SourceUnit

from .base import sweep_numbers, visible_text

_EQUATION_RE = re.compile(r"\$\$.*?\$\$|\\\(.*?\\\)", re.DOTALL)


class GuideProfile:
    name = "guide"

    def confidence(self, soup: BeautifulSoup) -> float:
        sections = soup.select("section.section")
        if not sections:
            return 0.0
        markers = {
            "sections_with_id": sum(1 for s in sections if s.get("id")),
            "sec_title": len(soup.select(".sec-title")),
            "diagram_card": len(soup.select(".diagram-card")),
            "math_block": len(soup.select(".math-block")),
            "callout_bareword": len(soup.select(
                ".callout.info, .callout.good, .callout.warn, .callout.danger"
            )),
        }
        # Every real guide has sections-with-id and sec-title; the rest are
        # bonus signal. Weighted so a file with just sections but none of the
        # guide-specific sub-markers doesn't win over a better-matching profile.
        score = 0.0
        score += 0.4 if markers["sections_with_id"] >= 1 else 0.0
        score += 0.3 if markers["sec_title"] >= 1 else 0.0
        score += 0.15 if markers["diagram_card"] >= 1 else 0.0
        score += 0.15 if markers["callout_bareword"] >= 1 or markers["math_block"] >= 1 else 0.0
        return min(score, 1.0)

    def extract(self, soup: BeautifulSoup) -> list[SourceUnit]:
        confidence = self.confidence(soup)
        units: list[SourceUnit] = []

        for level, section in enumerate(soup.select("section.section"), start=1):
            section_id = section.get("id", f"section_{level}")
            title_el = section.select_one(".sec-title") or section.find(["h1", "h2", "h3"])
            heading = visible_text(title_el) if title_el else ""

            body_paras = section.select(".body-text")
            text = " ".join(visible_text(p) for p in body_paras) if body_paras else visible_text(section)

            diagrams = [visible_text(c) for c in section.select(".diagram-caption")]
            callouts = [visible_text(c) for c in section.select(".callout")]
            code = [c.get_text("\n") for c in section.select(".code-pre, pre, code")]

            equations = []
            for block in section.select(".math-block"):
                raw = block.get_text(" ", strip=False)
                equations.extend(_EQUATION_RE.findall(raw))

            numbers = sweep_numbers(text + " " + " ".join(callouts))

            units.append(
                SourceUnit(
                    id=section_id,
                    heading=heading,
                    level=min(level, 6),
                    text=text,
                    equations=equations,
                    diagrams=diagrams,
                    callouts=callouts,
                    code=code,
                    numbers=numbers,
                    js_literals=[],  # populated separately at the document level (plan §6.2)
                    dom_path=f"section#{section_id}",
                    structure_confidence=confidence,
                )
            )
        return units
