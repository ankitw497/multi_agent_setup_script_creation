"""voice/fingerprint.py -- real, corpus-fitted voice bands (plan §11.2, V1D).

Replaces `verification/diagnostics/voice.py`'s provisional single-dimension
placeholder (capped at AMBER, never RED, an unfitted stdev threshold) with
bands actually fitted against `docs/corpus/transcripts/` -- real,
human-narrated technical YouTube scripts, the closest real reference this
project has for "does this sound like a real person talking," not a
generic prose corpus.

Promotes `tools/voice_fit.py`'s prototype metrics into production, with
one real fix the prototype didn't have: `compute_metrics()` returns `None`
for text that can't be reliably sentence-segmented (raw, unedited
auto-caption transcripts with almost no punctuation) instead of silently
producing a degenerate "one giant sentence" fingerprint. Found live
2026-09-11: 4 of the 10 real transcripts in the corpus are exactly this --
auto-caption dumps with 1-2 real sentence breaks across thousands of
words, which would have badly skewed every fitted band (one such file
alone reports a "sentence" 5,249 words long). The remaining 6 are real,
clean, edited transcripts and are what this module actually fits against.
"""
from __future__ import annotations

import re
import statistics
from pathlib import Path

from pydantic import BaseModel, Field

from config.loader import load_yaml
from review.models import Band, DiagnosticResult

_CONTRACTION_RE = re.compile(r"\b\w+'(?:s|t|re|ve|ll|d|m)\b", re.IGNORECASE)
_YOU_RE = re.compile(r"\byou\b|\byour\b|\byou're\b", re.IGNORECASE)
_WE_RE = re.compile(r"\bwe\b|\bour\b|\bwe're\b|\bwe've\b", re.IGNORECASE)
_CAUSAL_RE = re.compile(
    r"\b(because|so|therefore|but|which means|that means|since|thus|as a result|which is why)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"“])')
_TIMESTAMP_LINE_RE = re.compile(r"^\s*\d+:\d+(:\d+)?\s*$", re.MULTILINE)
_BRACKET_TAG_RE = re.compile(r"\[[^\]]{0,80}\]")

# A real transcript with essentially no sentence-ending punctuation (raw,
# unedited auto-captions) produces a degenerate "one giant sentence"
# fingerprint -- excluded from fitting, not silently included. Real valid
# transcripts in this corpus land at 16-32 words/sentence; the corrupted
# ones land at 899-5249 words for their one "sentence" -- not a close call,
# no risk of this threshold accidentally excluding real short-sentence prose.
MAX_PLAUSIBLE_WORDS_PER_SENTENCE = 100.0
MIN_WORDS_TO_FIT = 100


def clean_transcript(raw: str) -> str:
    """Strips YouTube-style timestamp lines and [music]/[applause] tags --
    the same cleanup `tools/voice_fit.py`'s prototype already used."""
    without_timestamps = _TIMESTAMP_LINE_RE.sub("", raw)
    without_tags = _BRACKET_TAG_RE.sub(" ", without_timestamps)
    return re.sub(r"\s+", " ", without_tags).strip()


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]


def compute_metrics(text: str) -> dict[str, float] | None:
    """Five metrics chosen from the prototype's 15 for real, meaningful
    spread across the valid reference transcripts (dropped: hedge/notjust
    rates, which sit at ~0 across every real document in this corpus and
    would fit into a band so narrow it flags constantly on noise; p10/p90/
    pct_under6/longest_similar_run, which duplicate what stdev/burstiness
    already capture more simply).

    Returns None when the text can't be reliably sentence-segmented (see
    module docstring) -- callers must treat that as "couldn't measure,"
    never as a default/zero fingerprint.
    """
    sentences = _sentences(text)
    lengths = [len(s.split()) for s in sentences]
    words = sum(lengths)
    if not lengths or words < MIN_WORDS_TO_FIT:
        return None
    if words / len(lengths) > MAX_PLAUSIBLE_WORDS_PER_SENTENCE:
        return None

    mean_len = statistics.mean(lengths)
    stdev = statistics.pstdev(lengths) if len(lengths) > 1 else 0.0

    def per100w(n: int) -> float:
        return 100.0 * n / words

    return {
        "burstiness": stdev / mean_len if mean_len else 0.0,
        "contractions_per100w": per100w(len(_CONTRACTION_RE.findall(text))),
        "you_per100w": per100w(len(_YOU_RE.findall(text))),
        "we_per100w": per100w(len(_WE_RE.findall(text))),
        "causal_per100w": per100w(len(_CAUSAL_RE.findall(text))),
    }


class MetricBand(BaseModel):
    low: float
    high: float


class VoiceFingerprint(BaseModel):
    """GREEN bands fitted from real corpus documents (plan §11.2) --
    padded around the observed min/max so a genuinely different but still
    human-sounding real document isn't flagged just for sitting at the
    edge of a 6-document sample."""

    bands: dict[str, MetricBand] = Field(default_factory=dict)
    n_documents: int = 0
    excluded_documents: list[str] = Field(default_factory=list)


def fit_fingerprint(labelled_texts: dict[str, str], pad_fraction: float = 0.15) -> VoiceFingerprint:
    """`labelled_texts`: {label: raw_text} (e.g. {"video_1.txt": "..."})
    -- already `clean_transcript()`-ed by the caller. Documents that fail
    `compute_metrics()` (degenerate segmentation) are recorded in
    `excluded_documents`, never silently dropped without a trace.
    """
    all_metrics: list[dict[str, float]] = []
    excluded: list[str] = []

    for label, text in labelled_texts.items():
        metrics = compute_metrics(text)
        if metrics is None:
            excluded.append(label)
        else:
            all_metrics.append(metrics)

    bands: dict[str, MetricBand] = {}
    if all_metrics:
        for key in all_metrics[0]:
            values = [m[key] for m in all_metrics]
            low, high = min(values), max(values)
            spread = high - low
            pad = spread * pad_fraction if spread > 0 else max(high * 0.2, 0.05)
            bands[key] = MetricBand(low=max(0.0, low - pad), high=high + pad)

    return VoiceFingerprint(bands=bands, n_documents=len(all_metrics), excluded_documents=excluded)


def fit_fingerprint_from_corpus_dir(corpus_dir: Path) -> VoiceFingerprint:
    labelled_texts = {
        path.name: clean_transcript(path.read_text())
        for path in sorted(corpus_dir.glob("*.txt"))
    }
    return fit_fingerprint(labelled_texts)


def load_fitted_fingerprint() -> VoiceFingerprint:
    """Loads the checked-in `config/voice_fingerprint.yaml` -- the fitted
    RESULT of a one-time local run of `fit_fingerprint_from_corpus_dir()`
    against `docs/corpus/transcripts/`, which is gitignored and must never
    be a runtime dependency (see module docstring). This is what production
    code (`verification/diagnostics/voice.py`) actually calls.
    """
    raw = load_yaml("voice_fingerprint.yaml")
    bands = {key: MetricBand(**value) for key, value in raw["bands"].items()}
    fitted_from = raw.get("fitted_from", {})
    return VoiceFingerprint(
        bands=bands,
        n_documents=fitted_from.get("n_documents", 0),
        excluded_documents=fitted_from.get("excluded_documents", []),
    )


def score_against_fingerprint(narration_text: str, fingerprint: VoiceFingerprint) -> DiagnosticResult:
    """ONE combined `voice` diagnostic (not one per metric) -- matches the
    existing convention of one band gating C5, and avoids over-weighting
    voice relative to other dimensions in `compute_final_status`'s
    across-dimension RED count. Reports every off-band metric in
    `evidence` for transparency, even though only the worst band is
    returned.
    """
    metrics = compute_metrics(narration_text)
    if metrics is None:
        return DiagnosticResult(
            dimension="voice", band="GREEN",
            evidence="too little text (or no real sentence structure) to measure voice",
        )

    off_band: list[str] = []
    worst: Band = "GREEN"
    for key, value in metrics.items():
        band_range = fingerprint.bands.get(key)
        if band_range is None:
            continue
        if band_range.low <= value <= band_range.high:
            continue
        off_band.append(f"{key}={value:.2f} outside {band_range.low:.2f}-{band_range.high:.2f}")
        worst = "AMBER"  # a fitted corpus this small (6 documents) never licenses an automatic RED --
        # see check_voice()'s own docstring for why RED needs a human-reviewed floor first.

    evidence = "; ".join(off_band) if off_band else "within the fitted voice bands"
    return DiagnosticResult(dimension="voice", band=worst, evidence=evidence)
