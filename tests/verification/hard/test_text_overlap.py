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


def test_min_length_default_still_excludes_short_words():
    """Every existing caller of content_words() relies on the default -- must be unchanged."""
    assert content_words("q k v attention") == {"attention"}


def test_min_length_override_admits_short_technical_shorthand():
    """Phase 32 P1: a technical title legitimately reuses short shorthand (Q, K, V) that
    the default silently erased -- confirmed live as the actual reason two real titles from
    two different models both scored as failing to reflect their own must_cover items.
    Only callers that explicitly opt in (a lower min_length) get this behavior; the default
    is unchanged (see test above), so no other overlap check's behavior shifts."""
    assert content_words("q k v attention", min_length=1) == {"q", "k", "v", "attention"}
