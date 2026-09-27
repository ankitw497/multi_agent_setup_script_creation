"""Shared word-overlap heuristic (plan §9's promise-chain gate, and every
other hard check that needs to mechanically approximate "are these two
texts about the same thing"). Extracted 2026-09-11 after the identical
logic was independently duplicated in structure.py and shorts.py, and was
about to become a third copy in render.py.

This is genuinely about SEMANTIC relatedness, which a mechanical check can
only approximate -- a word-overlap ratio, not real judgement. Thresholds
are deliberately generous everywhere this is used: false negatives are
fine (an LLM critic can still judge a subtle mismatch); false positives on
legitimate paraphrase would be worse than not having the check at all.
"""
from __future__ import annotations

import re

DEFAULT_OVERLAP_THRESHOLD = 0.15

_STOPWORDS = {
    "a", "an", "the", "to", "of", "and", "or", "in", "on", "for", "with", "this", "that",
    "you", "your", "is", "are", "it", "its", "be", "can", "will", "how", "what", "why",
    "not", "but", "so", "as", "at", "by", "from", "into", "than", "then", "their",
}

_WORD_RE = re.compile(r"[a-z0-9']+")


def content_words(text: str, min_length: int = 3) -> set[str]:
    # min_length is overridable (2026-09-26, Phase 32 P1) -- the default of 3
    # is right for general prose overlap (every other caller), but it silently
    # erases exactly the short technical shorthand a title would reuse (Q, K,
    # V, n2) -- confirmed live: a real title scored 0.8 "unreflected" against
    # its must_cover items purely because every one of those tokens fell below
    # this default, not because the title was actually a poor fit. Callers
    # checking overlap against short technical terms should pass a lower
    # min_length explicitly; the default is unchanged for everyone else.
    words = _WORD_RE.findall(text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) >= min_length}


def overlap(a: str, b: str) -> float:
    """Containment-style overlap (intersection / shorter text's word
    count), not symmetric similarity -- matches how this is used
    everywhere: checking that a SHORT text (a title, a subtitle) is
    substantively contained in a LONGER one (a hook, an ending)."""
    wa, wb = content_words(a), content_words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))
