"""Tests for verification/diagnostics/voice.py -- D* PROVISIONAL (plan §10.4, §11.3)."""
from narration.models import SceneNarration, SentenceNarration
from verification.diagnostics.voice import check_burstiness


def sentence(text) -> SentenceNarration:
    return SentenceNarration(text=text, sentence_type="transition")


def test_varied_sentence_lengths_is_green():
    narration = [SceneNarration(scene_id="s1", sentences=[
        sentence("Short."),
        sentence("A medium length sentence right here."),
        sentence("This one runs quite a bit longer with several more clauses stitched together."),
    ])]
    result = check_burstiness(narration)
    assert result.band == "GREEN"


def test_uniform_sentence_lengths_is_amber_never_red():
    """Monotone rhythm is a real tell, but this is a provisional, unfitted
    heuristic -- it must never escalate to RED (see module docstring)."""
    narration = [SceneNarration(scene_id="s1", sentences=[
        sentence("one two three four five"),
        sentence("six seven eight nine ten"),
        sentence("more words here right now"),
    ])]
    result = check_burstiness(narration)
    assert result.band in ("GREEN", "AMBER")
    assert result.band != "RED"


def test_too_few_sentences_defaults_to_green():
    narration = [SceneNarration(scene_id="s1", sentences=[sentence("just one sentence")])]
    result = check_burstiness(narration)
    assert result.band == "GREEN"


def test_empty_narration_does_not_crash():
    result = check_burstiness([])
    assert result.band == "GREEN"
