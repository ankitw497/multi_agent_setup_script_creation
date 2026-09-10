"""S2c -- normalize, dedupe, link numbers to claims (plan §6.3, §8, §9 traceability). No LLM.

normalize_number() is the traceability primitive plan §9 names explicitly:
"175B" <-> "175 billion" <-> "175,000,000,000" must compare equal under
normalization, or a genuinely invented statistic slips past unnoticed.
"""
from __future__ import annotations

import re

from .models import Claim, NumericClaim

_WORD_SCALE = {"billion": 1e9, "million": 1e6, "thousand": 1e3}
_LETTER_SCALE = {"b": 1e9, "m": 1e6, "k": 1e3}

_WORD_SUFFIX_RE = re.compile(r"^([\d.]+)\s*(billion|million|thousand)\b")
_LETTER_SUFFIX_RE = re.compile(r"^([\d.]+)([bmk])\b")
_BARE_NUMBER_RE = re.compile(r"^([\d.]+)")


def normalize_number(raw: str) -> float | None:
    """Canonical magnitude for a number mention, regardless of how it's written.

    "175B", "175 billion", and "175,000,000,000" all normalize to 1.75e11.
    A bare "175 GB" normalizes to 175 (the byte-unit is not a magnitude word
    for this purpose -- that distinction belongs to unit-aware verification,
    not number normalization).
    """
    s = raw.strip().lower().replace(",", "")
    if not s:
        return None

    m = _WORD_SUFFIX_RE.match(s)
    if m:
        return float(m.group(1)) * _WORD_SCALE[m.group(2)]

    m = _LETTER_SUFFIX_RE.match(s)
    if m:
        return float(m.group(1)) * _LETTER_SCALE[m.group(2)]

    m = _BARE_NUMBER_RE.match(s)
    if m:
        return float(m.group(1))

    return None


def _normalize_claim_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def dedupe_claims(claims: list[Claim]) -> tuple[list[Claim], list[str]]:
    """Drops near-duplicate claims (identical text after whitespace/case
    normalization), keeping the first occurrence's id. Returns
    (deduped_claims, dropped_claim_ids) -- nothing is silently discarded
    without being reported."""
    seen: dict[str, Claim] = {}
    dropped: list[str] = []
    for claim in claims:
        key = _normalize_claim_text(claim.claim)
        if key in seen:
            dropped.append(claim.claim_id)
            continue
        seen[key] = claim
    return list(seen.values()), dropped


def link_numeric_claims(
    claims: list[Claim], numeric_claims: list[NumericClaim], tolerance: float = 1e-6,
) -> list[NumericClaim]:
    """For each NumericClaim with no claim_id yet, find a Claim whose `numbers`
    list contains a raw mention that normalizes to the same magnitude as the
    numeric claim's own computed product, and link them. A NumericClaim with
    no match keeps claim_id=None -- it's still usable by the deterministic
    verifier, just not yet tied to a specific semantic assertion.
    """
    linked: list[NumericClaim] = []
    for nc in numeric_claims:
        if nc.claim_id is not None:
            linked.append(nc)
            continue

        computed = 1.0
        for v in nc.variables.values():
            computed *= v

        match_id: str | None = None
        for claim in claims:
            for raw_number in claim.numbers:
                normalized = normalize_number(raw_number)
                if normalized is not None and _close(normalized, computed, tolerance):
                    match_id = claim.claim_id
                    break
            if match_id:
                break

        linked.append(nc.model_copy(update={"claim_id": match_id}))
    return linked


def _close(a: float, b: float, tolerance: float) -> bool:
    if b == 0:
        return abs(a - b) < tolerance
    return abs(a - b) / abs(b) <= tolerance
