"""The Evidence Broker (plan §6.5) -- an orchestration component, not an agent.

Fulfils C2a's EvidenceRequests. V1A scope: SOURCE and CALCULATION evidence
(handled directly in facts/verify.py) plus EXTERNAL_REFERENCE from a
curated local config/references/ directory -- simple keyword overlap
against filenames and content, no embeddings, no web (that's V1B). An
unfulfilled request leaves the claim UNVERIFIED; this is never treated as
a failure of the broker, only as "no local evidence exists yet."
"""
from __future__ import annotations

import re
from pathlib import Path

from .models import EvidenceRequest, VerificationEvidence

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _score(request_words: set[str], candidate_words: set[str]) -> float:
    if not request_words:
        return 0.0
    return len(request_words & candidate_words) / len(request_words)


def fulfil_evidence_requests(
    requests: list[EvidenceRequest], references_dir: Path, min_score: float = 0.3,
) -> dict[str, VerificationEvidence]:
    """One best-matching local reference file per request, if any clears
    `min_score` word-overlap with the request's own text. Returns a dict
    keyed by claim_id; requests with no match simply don't appear in it."""
    references_dir = Path(references_dir)
    if not references_dir.exists():
        return {}

    ref_files = [p for p in references_dir.iterdir() if p.is_file() and not p.name.startswith(".")]
    if not ref_files:
        return {}

    fulfilled: dict[str, VerificationEvidence] = {}
    for request in requests:
        request_words = _words(f"{request.what_would_settle_it} {' '.join(request.suggested_sources)}")
        best_file, best_score = None, 0.0

        for ref_file in ref_files:
            content = ref_file.read_text(errors="ignore")
            candidate_words = _words(f"{ref_file.stem} {content[:2000]}")
            score = _score(request_words, candidate_words)
            if score > best_score:
                best_file, best_score = ref_file, score

        if best_file is not None and best_score >= min_score:
            excerpt = best_file.read_text(errors="ignore")[:500]
            fulfilled[request.claim_id] = VerificationEvidence(
                kind="EXTERNAL_REFERENCE", ref=str(best_file.name), excerpt=excerpt,
                verdict=f"matched local reference (word-overlap score {best_score:.2f})",
            )

    return fulfilled
