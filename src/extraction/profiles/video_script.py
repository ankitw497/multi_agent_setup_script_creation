"""Family B — the "video-script" markup profile (plan §6.1).

Matches sources like docs/corpus/raw_inputs and docs/corpus/sample_outputs:
`id="hero-story"`, `.sec-wrap`/`.sec-alt` wrappers, `.section-title`/
`.section-sub`, `.callout callout-<variant>` (a HYPHENATED compound class —
this is the opposite convention from the guide profile's space-separated
`.callout info`), `.step-item`/`.step-num`, `.defbox`.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from facts.models import SourceUnit

from .base import sweep_numbers, visible_text


class VideoScriptProfile:
    name = "video_script"

    def confidence(self, soup: BeautifulSoup) -> float:
        wrappers = soup.select(".sec-wrap, .sec-alt")
        if not wrappers:
            return 0.0
        markers = {
            "hero_story": len(soup.select("#hero-story")),
            "section_title": len(soup.select(".section-title")),
            "hyphenated_callout": len(soup.select(
                '[class*="callout-info"], [class*="callout-warn"], '
                '[class*="callout-success"], [class*="callout-danger"], '
                '[class*="callout-neutral"]'
            )),
            "step_item": len(soup.select(".step-item")),
            "defbox": len(soup.select(".defbox")),
        }
        score = 0.0
        score += 0.3 if wrappers else 0.0
        score += 0.25 if markers["hero_story"] >= 1 else 0.0
        score += 0.2 if markers["section_title"] >= 1 else 0.0
        score += 0.15 if markers["hyphenated_callout"] >= 1 else 0.0
        score += 0.1 if markers["step_item"] >= 1 or markers["defbox"] >= 1 else 0.0
        return min(score, 1.0)

    def extract(self, soup: BeautifulSoup) -> list[SourceUnit]:
        confidence = self.confidence(soup)
        units: list[SourceUnit] = []

        for level, wrap in enumerate(soup.select(".sec-wrap, .sec-alt"), start=1):
            wrap_id = wrap.get("id") or f"wrap_{level}"
            title_el = wrap.select_one(".section-title") or wrap.find(["h1", "h2", "h3"])
            heading = visible_text(title_el) if title_el else ""

            text = " ".join(visible_text(p) for p in wrap.select("p, .subsection-body"))
            callouts = [visible_text(c) for c in wrap.select(".callout")]
            code = [c.get_text("\n") for c in wrap.select("pre, code")]
            numbers = sweep_numbers(text + " " + " ".join(callouts))

            units.append(
                SourceUnit(
                    id=wrap_id,
                    heading=heading,
                    level=min(level, 6),
                    text=text,
                    equations=[],
                    diagrams=[],
                    callouts=callouts,
                    code=code,
                    numbers=numbers,
                    js_literals=[],
                    dom_path=f"#{wrap_id}",
                    structure_confidence=confidence,
                )
            )
        return units
