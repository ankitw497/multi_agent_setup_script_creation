"""Tests for voice/tts_preview.py -- V1C's shorts measured-duration gate.

edge-tts is a real, free, keyless network call (no API key, no billing) --
still marked `integration` per this project's own convention for anything
that hits a real external service, so the default fast suite never makes
a network call by accident.
"""
import pytest

from voice.tts_preview import EDGE_TTS_VOICE, synthesize_narration_preview


@pytest.mark.integration
def test_synthesizes_real_audio_and_measures_a_plausible_duration():
    text = "This is a short test sentence to measure real spoken duration."
    result = synthesize_narration_preview(text)

    assert len(result.audio_bytes) > 1000  # a real MP3, not an empty/error response
    # ~11 words at a natural speaking pace should land well under 10s and
    # comfortably over 1s -- a wide, false-positive-averse sanity band, not
    # a precise timing assertion (real TTS pacing varies).
    assert 1.0 < result.measured_duration_seconds < 10.0


@pytest.mark.integration
def test_longer_text_measures_a_longer_duration():
    """Confirms the measurement actually reflects the text, not a constant."""
    short_result = synthesize_narration_preview("One short sentence.")
    long_text = " ".join(["This is a much longer piece of narration text."] * 8)
    long_result = synthesize_narration_preview(long_text)

    assert long_result.measured_duration_seconds > short_result.measured_duration_seconds


@pytest.mark.integration
def test_uses_the_prabhat_voice_by_default():
    """Locks in the specific voice choice (user decision, 2026-09-11) --
    a regression here would silently change the channel's narrated voice."""
    assert EDGE_TTS_VOICE == "en-IN-PrabhatNeural"
    result = synthesize_narration_preview("Voice check.")
    assert len(result.audio_bytes) > 0
