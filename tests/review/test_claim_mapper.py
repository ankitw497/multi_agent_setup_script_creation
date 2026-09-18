"""Tests for review/claim_mapper.py -- CM (plan §5.1, STORY_IMPROVEMENT_PLAN.md Phase 10)."""
import threading

import pytest

from facts.models import Claim
from narration.models import SceneNarration, SentenceNarration
from review.claim_mapper import CM_BATCH_SIZE, ClaimMapperOutput, map_claims
from review.models import ReviewCoverageError


class FakeReviewLead:
    """Pass a single response (reused for every call) or a list (matched to whichever
    call actually requests that exact set of sentence_ids) -- the list form is what
    exercises Phase 10's batching. 2026-09-15: batches now dispatch concurrently
    (llm/concurrency.py), so responses can no longer be matched by call ORDER (thread
    scheduling doesn't guarantee submission order) -- matched by request CONTENT instead,
    and `calls` recording is lock-protected since multiple threads append concurrently."""

    def __init__(self, response):
        self._queue = list(response) if isinstance(response, list) else None
        self._single = None if isinstance(response, list) else response
        self.calls = []
        self._lock = threading.Lock()

    def run(self, **kwargs):
        with self._lock:
            call_index = len(self.calls)
            self.calls.append(kwargs)
        if self._queue is not None:
            # Prefer an exact content match (needed when 2+ batches genuinely dispatch
            # concurrently -- thread scheduling doesn't preserve submission order, so a
            # fixed position can't be trusted there). Fall back to position when no
            # response's ids match exactly -- some tests deliberately queue a partial/
            # incomplete response (to test missing-verdict handling), which by
            # definition can't content-match; those calls are made sequentially
            # (one real batch, then one retry), so position is unambiguous there.
            requested_ids = {s["sentence_id"] for s in kwargs["payload"]["sentences"]}
            for candidate in self._queue:
                if {m.sentence_id for m in candidate.sentences} == requested_ids:
                    return candidate
            return self._queue[call_index]
        return self._single


def make_scene(scene_id: str, sentences: list[tuple[str, str]]) -> SceneNarration:
    return SceneNarration(
        scene_id=scene_id,
        sentences=[SentenceNarration(text=t, sentence_type=st) for t, st in sentences],
    )


def test_writer_sentence_type_is_never_sent_to_the_mapper():
    """The whole point of CM: it must not see the writer's own label, or it
    could anchor on it instead of judging independently (plan §5.1)."""
    narration = [make_scene("s1", [("Weights are like a shared apartment.", "analogy")])]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[
        {"sentence_id": "s1:0", "scene_id": "s1", "sentence_index": 0, "factual_status": "NON_FACTUAL"},
    ]))

    map_claims(narration, [], review_lead, budget=None)

    payload = review_lead.calls[0]["payload"]
    assert set(payload["sentences"][0].keys()) == {"sentence_id", "scene_id", "sentence_index", "text"}
    assert "sentence_type" not in payload["sentences"][0]


def test_marks_grounding_required_regardless_of_the_writers_label():
    """A sentence labelled "analogy" by the writer can still be marked
    grounding_required by CM -- the two fields are independent."""
    narration = [make_scene("s1", [("A fact hiding as an analogy.", "analogy")])]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[
        {"sentence_id": "s1:0", "scene_id": "s1", "sentence_index": 0,
         "factual_status": "FACTUAL", "grounding_refs": ["C001"]},
    ]))

    result = map_claims(narration, [], review_lead, budget=None)

    sentence = result[0].sentences[0]
    assert sentence.sentence_type == "analogy"  # writer's label untouched
    assert sentence.grounding_required is True  # CM's independent judgement
    assert sentence.grounding_refs == ["C001"]
    assert sentence.sentence_id == "s1:0"  # stamped defensively


def test_a_transition_with_no_factual_content_stays_ungrounded():
    narration = [make_scene("s1", [("That's the strange part.", "transition")])]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[
        {"sentence_id": "s1:0", "scene_id": "s1", "sentence_index": 0, "factual_status": "NON_FACTUAL"},
    ]))

    result = map_claims(narration, [], review_lead, budget=None)
    assert result[0].sentences[0].grounding_required is False


def test_uncertain_is_treated_as_grounding_required_not_dropped():
    """Phase 10 §4.2: CM should say UNCERTAIN rather than guess NON_FACTUAL --
    and an uncertain sentence must still be routed on for a real check, not
    silently treated as clean."""
    narration = [make_scene("s1", [("A borderline sentence.", "transition")])]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[
        {"sentence_id": "s1:0", "scene_id": "s1", "sentence_index": 0, "factual_status": "UNCERTAIN"},
    ]))

    result = map_claims(narration, [], review_lead, budget=None)
    assert result[0].sentences[0].grounding_required is True


def test_a_missing_verdict_fails_closed_instead_of_being_silently_ungrounded():
    """The confirmed real bug this phase fixes: a sentence CM's response omits
    a verdict for used to silently keep grounding_required=False, indistinguishable
    from a genuinely clean check. It must now raise instead, only after a retry
    for the missing sentence(s) also comes back incomplete."""
    narration = [make_scene("s1", [("x", "technical_assertion"), ("y", "transition")])]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[
        {"sentence_id": "s1:0", "scene_id": "s1", "sentence_index": 0, "factual_status": "FACTUAL"},
        # s1:1 missing from the response entirely -- and from the retry response too,
        # since FakeReviewLead reuses this same single response for every call.
    ]))

    with pytest.raises(ReviewCoverageError, match="s1:1"):
        map_claims(narration, [], review_lead, budget=None)

    assert len(review_lead.calls) == 2  # initial batch + one retry for the missing sentence


def test_a_missing_verdict_recovered_by_the_retry_never_raises():
    """STORY_IMPROVEMENT_PLAN.md Phase 10 follow-up: confirmed live (2026-09-15) -- even a
    bounded ~20-sentence batch can still drop a single entry (a real run missed 1/57
    sentences with batching already in place). A retry with just the missing sentence(s)
    must resolve an isolated miss without failing the whole call."""
    narration = [make_scene("s1", [("x", "technical_assertion"), ("y", "transition")])]
    initial = ClaimMapperOutput(sentences=[
        {"sentence_id": "s1:0", "scene_id": "s1", "sentence_index": 0, "factual_status": "FACTUAL"},
        # s1:1 missing from the initial batch
    ])
    retry = ClaimMapperOutput(sentences=[
        {"sentence_id": "s1:1", "scene_id": "s1", "sentence_index": 1, "factual_status": "NON_FACTUAL"},
    ])
    review_lead = FakeReviewLead([initial, retry])

    result = map_claims(narration, [], review_lead, budget=None)

    assert len(review_lead.calls) == 2
    assert review_lead.calls[1]["payload"]["sentences"] == [
        {"sentence_id": "s1:1", "scene_id": "s1", "sentence_index": 1, "text": "y"},
    ]
    assert result[0].sentences[0].grounding_required is True  # s1:0, unaffected
    assert result[0].sentences[1].grounding_required is False  # s1:1, recovered by the retry


def test_maps_across_multiple_scenes_correctly_by_scene_id_and_index():
    narration = [
        make_scene("s1", [("a", "technical_assertion")]),
        make_scene("s2", [("b", "technical_assertion")]),
    ]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[
        {"sentence_id": "s1:0", "scene_id": "s1", "sentence_index": 0,
         "factual_status": "FACTUAL", "grounding_refs": ["C001"]},
        {"sentence_id": "s2:0", "scene_id": "s2", "sentence_index": 0,
         "factual_status": "FACTUAL", "grounding_refs": ["C002"]},
    ]))

    result = map_claims(narration, [], review_lead, budget=None)
    assert result[0].sentences[0].grounding_refs == ["C001"]
    assert result[1].sentences[0].grounding_refs == ["C002"]


def test_registry_sent_is_claim_id_and_text_only():
    narration = [make_scene("s1", [("x", "technical_assertion")])]
    claims = [Claim(claim_id="C001", source_unit="u1", claim="attention scales by sqrt(d_k)", type="mechanism")]
    review_lead = FakeReviewLead(ClaimMapperOutput(sentences=[
        {"sentence_id": "s1:0", "scene_id": "s1", "sentence_index": 0, "factual_status": "NON_FACTUAL"},
    ]))

    map_claims(narration, claims, review_lead, budget=None)

    registry = review_lead.calls[0]["payload"]["claim_registry"]
    assert registry == [{"claim_id": "C001", "claim": "attention scales by sqrt(d_k)"}]


def test_more_sentences_than_the_batch_size_are_split_across_multiple_calls():
    """Phase 10 §4.4: don't map the whole script in one giant structured
    output -- bound each call's size to lower truncation risk."""
    n = CM_BATCH_SIZE + 5
    narration = [make_scene("s1", [(f"sentence {i}", "technical_assertion") for i in range(n)])]
    batch1 = ClaimMapperOutput(sentences=[
        {"sentence_id": f"s1:{i}", "scene_id": "s1", "sentence_index": i, "factual_status": "NON_FACTUAL"}
        for i in range(CM_BATCH_SIZE)
    ])
    batch2 = ClaimMapperOutput(sentences=[
        {"sentence_id": f"s1:{i}", "scene_id": "s1", "sentence_index": i, "factual_status": "NON_FACTUAL"}
        for i in range(CM_BATCH_SIZE, n)
    ])
    review_lead = FakeReviewLead([batch1, batch2])

    result = map_claims(narration, [], review_lead, budget=None)

    # 2026-09-15: batches dispatch concurrently (llm/concurrency.py) -- `calls` order
    # reflects thread scheduling, not submission order, so assert on the multiset of
    # sizes rather than a specific position.
    assert len(review_lead.calls) == 2
    assert sorted(len(c["payload"]["sentences"]) for c in review_lead.calls) == sorted([CM_BATCH_SIZE, n - CM_BATCH_SIZE])
    assert len(result[0].sentences) == n
