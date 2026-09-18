"""D* compact-writing diagnostic (STORY_IMPROVEMENT_PLAN.md Phase 23, "Compact writing"
section): no deterministic check for sentence density/length existed anywhere before this
(confirmed by direct search of `verification/diagnostics/` and `verification/hard/`) --
`narration/generator.py`'s TASK_PROMPT already asks for one idea per sentence, but nothing
measured whether that actually held.

Real examples this calibrates against (found in a live generated script, B5_s03/B6_s02/
B12_s02): 60-62 word single sentences stacking cause + consequence + a numeric example in
one breath. Advisory only, AMBER at most, never RED -- matches `check_voice`'s own permanent
AMBER-cap precedent (a length+clause-count heuristic is a real but coarse signal, not proof a
sentence is actually unclear, so it shouldn't be able to trigger a forced-revision escalation
on its own).
"""
from __future__ import annotations

import re

from narration.models import SceneNarration
from review.models import DiagnosticResult

# Low end of the confirmed real range (50-62 words) -- catches the actual examples found
# without also flagging a merely-long-but-single-idea sentence.
SENTENCE_DENSITY_WORD_THRESHOLD = 50

_CLAUSE_LINK_PATTERN = re.compile(
    r",\s*(and|but|so|or|yet|for|nor|which|because|since|while|though|although)\b", re.IGNORECASE,
)


def _clause_link_count(text: str) -> int:
    """Cheap heuristic, not a real parse (plan's own explicit scope): counts marks that
    typically join two independent (or dependent) clauses -- a comma before a coordinating/
    subordinating conjunction, a semicolon, or a dash used as a clause break. One such mark
    already means the sentence carries 2+ clauses, which is this diagnostic's own threshold
    -- it does not need to distinguish 2 from 3+."""
    count = len(_CLAUSE_LINK_PATTERN.findall(text))
    count += text.count(";")
    count += text.count(" — ") + text.count(" -- ")
    return count


def check_sentence_density(narration: list[SceneNarration]) -> DiagnosticResult:
    flagged: list[tuple[str, int, str]] = []
    total_sentences = 0

    for scene in narration:
        for sentence in scene.sentences:
            text = sentence.text.strip()
            if not text:
                continue
            total_sentences += 1
            words = len(text.split())
            if words >= SENTENCE_DENSITY_WORD_THRESHOLD and _clause_link_count(text) >= 1:
                flagged.append((scene.scene_id, words, text))

    target = f"< {SENTENCE_DENSITY_WORD_THRESHOLD} words OR a single clause"
    if not flagged:
        return DiagnosticResult(
            dimension="compactness.sentence_density", band="GREEN", value=0, target=target,
            evidence=f"no sentence (of {total_sentences}) combines length >= "
                     f"{SENTENCE_DENSITY_WORD_THRESHOLD} words with 2+ independent clauses",
        )

    examples = "; ".join(f"{scene_id} ({words}w): {text[:80]!r}" for scene_id, words, text in flagged[:3])
    return DiagnosticResult(
        dimension="compactness.sentence_density", band="AMBER", value=len(flagged), target=target,
        evidence=f"{len(flagged)}/{total_sentences} sentences run >= {SENTENCE_DENSITY_WORD_THRESHOLD} "
                 f"words with 2+ independent clauses -- e.g. {examples}",
    )
