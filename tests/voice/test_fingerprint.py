"""Tests for voice/fingerprint.py -- real, corpus-fitted voice bands (plan §11.2, V1D)."""
from voice.fingerprint import (
    MAX_PLAUSIBLE_WORDS_PER_SENTENCE, MetricBand, VoiceFingerprint, clean_transcript,
    compute_metrics, fit_fingerprint, load_fitted_fingerprint, score_against_fingerprint,
)

REAL_SENTENCE = "This is a normal sentence with a reasonable number of words in it."


def _valid_document(n_sentences: int = 20) -> str:
    return " ".join([REAL_SENTENCE] * n_sentences)


def test_clean_transcript_strips_timestamp_lines_and_bracket_tags():
    raw = "0:01\n[Music]\nHello there. This is the real content. [Applause]\n1:23:45\nMore content follows."
    cleaned = clean_transcript(raw)
    assert "0:01" not in cleaned
    assert "[Music]" not in cleaned
    assert "[Applause]" not in cleaned
    assert "Hello there." in cleaned
    assert "More content follows." in cleaned


def test_compute_metrics_returns_none_for_degenerate_auto_caption_dump():
    """A raw auto-caption dump with almost no sentence-ending punctuation
    produces one giant "sentence" -- must be excluded, not silently
    fingerprinted (real finding, 2026-09-11: 4 of 10 real transcripts were
    exactly this)."""
    corrupted = " ".join(["word"] * 2000) + "."
    assert compute_metrics(corrupted) is None


def test_compute_metrics_returns_none_for_too_little_text():
    assert compute_metrics("Just one short sentence.") is None


def test_compute_metrics_returns_real_values_for_a_valid_document():
    metrics = compute_metrics(_valid_document())
    assert metrics is not None
    assert set(metrics) == {
        "burstiness", "contractions_per100w", "you_per100w", "we_per100w", "causal_per100w",
    }
    assert metrics["burstiness"] >= 0.0


def test_compute_metrics_counts_contractions_you_we_and_causal_words():
    text = " ".join([
        "You know we're onto something here because the results are clear.",
        "We've tested this many times and you can see the pattern every time.",
        "So the causal link is obvious, which means the effect is real.",
    ] * 4)
    metrics = compute_metrics(text)
    assert metrics is not None
    assert metrics["contractions_per100w"] > 0
    assert metrics["you_per100w"] > 0
    assert metrics["we_per100w"] > 0
    assert metrics["causal_per100w"] > 0


def test_fit_fingerprint_excludes_degenerate_documents_and_records_them():
    labelled = {
        "good_1.txt": _valid_document(),
        "good_2.txt": _valid_document(n_sentences=25),
        "corrupted.txt": " ".join(["word"] * 2000) + ".",
    }
    fingerprint = fit_fingerprint(labelled)
    assert fingerprint.n_documents == 2
    assert fingerprint.excluded_documents == ["corrupted.txt"]
    assert set(fingerprint.bands) == {
        "burstiness", "contractions_per100w", "you_per100w", "we_per100w", "causal_per100w",
    }


def test_fit_fingerprint_with_no_valid_documents_produces_empty_bands():
    fingerprint = fit_fingerprint({"corrupted.txt": " ".join(["word"] * 2000) + "."})
    assert fingerprint.n_documents == 0
    assert fingerprint.bands == {}


def test_score_against_fingerprint_within_every_band_is_green():
    fingerprint = VoiceFingerprint(bands={
        "burstiness": MetricBand(low=0.0, high=999.0),
        "contractions_per100w": MetricBand(low=0.0, high=999.0),
        "you_per100w": MetricBand(low=0.0, high=999.0),
        "we_per100w": MetricBand(low=0.0, high=999.0),
        "causal_per100w": MetricBand(low=0.0, high=999.0),
    })
    result = score_against_fingerprint(_valid_document(), fingerprint)
    assert result.dimension == "voice"
    assert result.band == "GREEN"


def test_score_against_fingerprint_outside_a_band_is_amber_never_red():
    fingerprint = VoiceFingerprint(bands={
        "burstiness": MetricBand(low=100.0, high=200.0),
        "contractions_per100w": MetricBand(low=100.0, high=200.0),
        "you_per100w": MetricBand(low=100.0, high=200.0),
        "we_per100w": MetricBand(low=100.0, high=200.0),
        "causal_per100w": MetricBand(low=100.0, high=200.0),
    })
    result = score_against_fingerprint(_valid_document(), fingerprint)
    assert result.band == "AMBER"
    assert "outside" in result.evidence


def test_score_against_fingerprint_too_little_text_is_green_not_a_crash():
    fingerprint = VoiceFingerprint(bands={"burstiness": MetricBand(low=100.0, high=200.0)})
    result = score_against_fingerprint("Too short.", fingerprint)
    assert result.band == "GREEN"
    assert "too little text" in result.evidence


def test_load_fitted_fingerprint_reads_the_checked_in_config():
    """This is what production code actually calls -- must never depend on
    docs/corpus/ (gitignored) being present at runtime."""
    fingerprint = load_fitted_fingerprint()
    assert fingerprint.n_documents == 6
    assert set(fingerprint.excluded_documents) == {
        "video_2.txt", "video_6.txt", "video_7.txt", "video_10.txt",
    }
    assert set(fingerprint.bands) == {
        "burstiness", "contractions_per100w", "you_per100w", "we_per100w", "causal_per100w",
    }
    for band in fingerprint.bands.values():
        assert band.low <= band.high
