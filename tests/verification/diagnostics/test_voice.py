"""Tests for verification/diagnostics/voice.py -- D* voice diagnostic (plan §10.4, §11.3, V1D)."""
from narration.models import SceneNarration, SentenceNarration
from verification.diagnostics import voice as voice_diagnostic
from verification.diagnostics.voice import check_voice
from voice.fingerprint import MetricBand, VoiceFingerprint


def sentence(text) -> SentenceNarration:
    return SentenceNarration(text=text, sentence_type="transition")


def _wide_open_fingerprint() -> VoiceFingerprint:
    return VoiceFingerprint(bands={
        "burstiness": MetricBand(low=0.0, high=999.0),
        "contractions_per100w": MetricBand(low=0.0, high=999.0),
        "you_per100w": MetricBand(low=0.0, high=999.0),
        "we_per100w": MetricBand(low=0.0, high=999.0),
        "causal_per100w": MetricBand(low=0.0, high=999.0),
    })


def _impossible_fingerprint() -> VoiceFingerprint:
    return VoiceFingerprint(bands={
        "burstiness": MetricBand(low=100.0, high=200.0),
        "contractions_per100w": MetricBand(low=100.0, high=200.0),
        "you_per100w": MetricBand(low=100.0, high=200.0),
        "we_per100w": MetricBand(low=100.0, high=200.0),
        "causal_per100w": MetricBand(low=100.0, high=200.0),
    })


def _narration(n_sentences: int = 20) -> list[SceneNarration]:
    text = "This is a normal sentence with a reasonable number of words in it."
    return [SceneNarration(scene_id="s1", sentences=[sentence(text) for _ in range(n_sentences)])]


def test_check_voice_within_the_fitted_bands_is_green(monkeypatch):
    monkeypatch.setattr(voice_diagnostic, "load_fitted_fingerprint", _wide_open_fingerprint)
    result = check_voice(_narration())
    assert result.dimension == "voice"
    assert result.band == "GREEN"


def test_check_voice_outside_the_fitted_bands_is_amber_never_red(monkeypatch):
    """A fitted corpus this small (6 documents) never licenses an
    automatic RED -- see voice/fingerprint.py's own docstring."""
    monkeypatch.setattr(voice_diagnostic, "load_fitted_fingerprint", _impossible_fingerprint)
    result = check_voice(_narration())
    assert result.band == "AMBER"


def test_check_voice_too_little_text_is_green_not_a_crash(monkeypatch):
    monkeypatch.setattr(voice_diagnostic, "load_fitted_fingerprint", _impossible_fingerprint)
    result = check_voice(_narration(n_sentences=1))
    assert result.band == "GREEN"


def test_check_voice_empty_narration_does_not_crash(monkeypatch):
    monkeypatch.setattr(voice_diagnostic, "load_fitted_fingerprint", _impossible_fingerprint)
    result = check_voice([])
    assert result.band == "GREEN"


def test_check_voice_uses_the_real_checked_in_fingerprint_by_default():
    """No monkeypatch -- confirms the real config file loads and produces
    a usable result end to end."""
    result = check_voice(_narration())
    assert result.dimension == "voice"
    assert result.band in ("GREEN", "AMBER")
