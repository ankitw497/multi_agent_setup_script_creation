"""Tests for review/claim_mapper.py -- CM (plan §5.1)."""
from facts.models import Claim
from narration.models import SceneNarration, SentenceNarration
from review.claim_mapper import ClaimMapperOutput, map_claims


class FakeReviewLead:
    def __init__(self, response: ClaimMapperOutput):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_scene(scene_id: str, sentences: list[tuple[str, str]]) -> SceneNarration:
    return SceneNarration(
        scene_id=scene_id,
        sentences=[SentenceNarration(text=t, sentence_type=st) for t, st in sentences],
    )


def test_writer_sentence_type_is_never_sent_to_the_mapper():
    """The whole point of CM: it must not see the writer's own label, or it
    could anchor on it instead of judging independently (plan §5.1)."""
    narration = [make_scene("s1", [("Weights are like a shared apartment.", "analogy")])]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[]))

    map_claims(narration, [], review_lead, budget=None)

    payload = review_lead.calls[0]["payload"]
    assert set(payload["sentences"][0].keys()) == {"scene_id", "sentence_index", "text"}
    assert "sentence_type" not in payload["sentences"][0]


def test_marks_grounding_required_regardless_of_the_writers_label():
    """A sentence labelled "analogy" by the writer can still be marked
    grounding_required by CM -- the two fields are independent."""
    narration = [make_scene("s1", [("A fact hiding as an analogy.", "analogy")])]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[
        {"scene_id": "s1", "sentence_index": 0, "grounding_required": True, "grounding_refs": ["C001"]},
    ]))

    result = map_claims(narration, [], review_lead, budget=None)

    sentence = result[0].sentences[0]
    assert sentence.sentence_type == "analogy"  # writer's label untouched
    assert sentence.grounding_required is True  # CM's independent judgement
    assert sentence.grounding_refs == ["C001"]


def test_a_transition_with_no_factual_content_stays_ungrounded():
    narration = [make_scene("s1", [("That's the strange part.", "transition")])]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[
        {"scene_id": "s1", "sentence_index": 0, "grounding_required": False, "grounding_refs": []},
    ]))

    result = map_claims(narration, [], review_lead, budget=None)
    assert result[0].sentences[0].grounding_required is False


def test_a_sentence_the_model_never_returned_a_verdict_for_is_left_untouched_not_guessed():
    narration = [make_scene("s1", [("x", "technical_assertion"), ("y", "transition")])]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[
        {"scene_id": "s1", "sentence_index": 0, "grounding_required": True, "grounding_refs": []},
        # sentence_index 1 missing from the response entirely
    ]))

    result = map_claims(narration, [], review_lead, budget=None)
    assert result[0].sentences[0].grounding_required is True
    assert result[0].sentences[1].grounding_required is False  # default, never guessed True


def test_maps_across_multiple_scenes_correctly_by_scene_id_and_index():
    narration = [
        make_scene("s1", [("a", "technical_assertion")]),
        make_scene("s2", [("b", "technical_assertion")]),
    ]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[
        {"scene_id": "s1", "sentence_index": 0, "grounding_required": True, "grounding_refs": ["C001"]},
        {"scene_id": "s2", "sentence_index": 0, "grounding_required": True, "grounding_refs": ["C002"]},
    ]))

    result = map_claims(narration, [], review_lead, budget=None)
    assert result[0].sentences[0].grounding_refs == ["C001"]
    assert result[1].sentences[0].grounding_refs == ["C002"]


def test_registry_sent_is_claim_id_and_text_only():
    narration = [make_scene("s1", [("x", "technical_assertion")])]
    claims = [Claim(claim_id="C001", source_unit="u1", claim="attention scales by sqrt(d_k)", type="mechanism")]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[]))

    map_claims(narration, claims, review_lead, budget=None)

    registry = review_lead.calls[0]["payload"]["claim_registry"]
    assert registry == [{"claim_id": "C001", "claim": "attention scales by sqrt(d_k)"}]
