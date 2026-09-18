"""Tests for verification/diagnostics/compactness.py -- STORY_IMPROVEMENT_PLAN.md Phase 23
"Compact writing" section."""
from narration.models import SceneNarration, SentenceNarration
from verification.diagnostics.compactness import check_sentence_density


def make_narration(*texts: str) -> list[SceneNarration]:
    return [SceneNarration(
        scene_id="s1",
        sentences=[SentenceNarration(text=t, sentence_type="explanatory_inference") for t in texts],
    )]


def test_empty_narration_is_green():
    result = check_sentence_density([])
    assert result.band == "GREEN"
    assert result.value == 0


def test_short_sentences_are_green():
    result = check_sentence_density(make_narration("This is short.", "So is this one."))
    assert result.band == "GREEN"


def test_a_long_sentence_with_no_clause_link_is_green():
    """Length alone isn't the signal -- a long single-idea sentence (e.g. one with a long
    list of nouns but no clause-joining structure) shouldn't be flagged."""
    long_single_idea = "The " + " ".join(f"word{i}" for i in range(60)) + " ends here."
    assert len(long_single_idea.split()) >= 50
    result = check_sentence_density(make_narration(long_single_idea))
    assert result.band == "GREEN"


def test_the_real_confirmed_pattern_is_amber():
    """The real, live-confirmed case (B5_s03/B6_s02/B12_s02): a 60-62 word sentence
    stacking cause + consequence + a numeric example in one breath, joined with 'because'."""
    real_shape = (
        "The model applies a softmax over the raw attention scores because without "
        "normalization the values could range anywhere from negative infinity to positive "
        "infinity, and that would make it impossible to compare how much attention each of "
        "the twelve tokens in the sequence actually receives relative to the other eleven"
    )
    assert len(real_shape.split()) >= 50
    result = check_sentence_density(make_narration(real_shape))
    assert result.band == "AMBER"


def test_semicolon_counts_as_a_clause_link():
    text = ("The gradient vanishes across many layers during backpropagation in a very deep "
            "recurrent network trained on long sequences of text with dozens of timesteps "
            "between the input and the loss; this is exactly the reason architectures like "
            "LSTMs were invented, to preserve long-range dependencies across those same "
            "dozens of timesteps without the signal decaying to nothing")
    assert len(text.split()) >= 50
    result = check_sentence_density(make_narration(text))
    assert result.band == "AMBER"


def test_never_returns_red():
    """Advisory only, matching check_voice's own permanent AMBER-cap precedent -- a
    length+clause-count heuristic is real but coarse, so it must never itself trigger the
    forced-revision escalation a validated RED would."""
    texts = [
        ("Sentence number " + str(i) + " stacks a cause and a consequence in one breath, "
         "because that is exactly the confirmed real pattern found across this channel's own "
         "scripts, and it also adds a numeric example of forty two percent for good measure "
         "right here at the very end of this one, just to make the point unmistakably clear")
        for i in range(5)
    ]
    result = check_sentence_density(make_narration(*texts))
    assert result.band == "AMBER"


def test_evidence_names_the_scene_and_word_count():
    real_shape = (
        "The model applies a softmax over the raw attention scores because without "
        "normalization the values could range anywhere from negative infinity to positive "
        "infinity, and that would make it impossible to compare how much attention each of "
        "the twelve tokens in the sequence actually receives relative to the other eleven"
    )
    result = check_sentence_density(make_narration(real_shape))
    assert "s1" in result.evidence
    assert result.dimension == "compactness.sentence_density"


def test_blank_sentences_are_skipped_not_counted():
    result = check_sentence_density(make_narration("", "   ", "Short one."))
    assert result.band == "GREEN"
    assert "of 1" in result.evidence  # only the one non-blank sentence counts toward the total
