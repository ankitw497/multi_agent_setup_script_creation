"""Tests for verification/hard/text_overlap.py -- the shared word-overlap heuristic."""
from verification.hard.text_overlap import content_words, overlap


def test_identical_text_has_full_overlap():
    assert overlap("understand how attention works", "understand how attention works") == 1.0


def test_completely_unrelated_text_has_no_overlap():
    assert overlap("why cats land on their feet", "how transformers process language") == 0.0


def test_containment_style_not_symmetric_similarity():
    """A short phrase substantively contained in a longer one should score
    high even though the longer text has many more unrelated words."""
    short = "attention retrieves context"
    long = "you will learn exactly how attention retrieves context for every token in a sequence"
    assert overlap(short, long) == 1.0


def test_stopwords_are_excluded():
    assert content_words("the a of to and") == set()


def test_short_words_are_excluded():
    assert content_words("it is a to") == set()  # all length <= 2 or stopwords


def test_empty_text_has_zero_overlap():
    assert overlap("", "something real") == 0.0
    assert overlap("something real", "") == 0.0
