"""Tests for review/grounding_verifier.py -- C2b (plan §5.1, Appendix G #3,
STORY_IMPROVEMENT_PLAN.md Phase 10)."""
import random
import threading

import pytest

from narration.models import SceneNarration, SentenceNarration
from review.grounding_verifier import (
    C2B_BATCH_SIZE, GroundingReview, GroundingVerdict, apply_grounding_metadata_repairs,
    grounding_verdicts_to_issues, verify_grounding,
)
from review.models import ReviewCoverageError


def scene(scene_id, sentences) -> SceneNarration:
    return SceneNarration(scene_id=scene_id, sentences=sentences)


class FakeReviewLead:
    """Pass a single response (reused for every call) or a list (matched to whichever
    call actually requests that exact set of sentence_ids) -- the list form is what
    exercises batching. 2026-09-15: batches now dispatch concurrently
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
                if {v.sentence_id for v in candidate.verdicts} == requested_ids:
                    return candidate
            return self._queue[call_index]
        return self._single


def test_cms_own_grounding_labels_are_sent_but_not_trusted_by_construction():
    """C2b receives what CM decided (so it can check completeness against
    it) -- the code doesn't hide it, but the prompt explicitly says not to
    trust it. This test confirms the data is at least visible to check."""
    narration = [scene("s1", [
        SentenceNarration(text="x", sentence_type="transition", grounding_required=False, grounding_refs=[]),
    ])]
    review_lead = FakeReviewLead(GroundingReview(verdicts=[{"sentence_id": "s1:0", "factual": False}]))

    verify_grounding(narration, [], review_lead, budget=None)

    sent = review_lead.calls[0]["payload"]["sentences"][0]
    assert sent["grounding_required"] is False


def test_a_missing_verdict_fails_closed_not_silently_clean():
    """The confirmed real bug this phase fixes: C2b used to return only a
    sparse issues list, so "no issue" was indistinguishable from "every
    sentence was actually checked." Now it must cover every sentence or raise."""
    narration = [scene("s1", [
        SentenceNarration(text="Attention scales by the square root of d_k.", sentence_type="transition"),
        SentenceNarration(text="A plain transition.", sentence_type="transition"),
    ])]
    review_lead = FakeReviewLead(GroundingReview(verdicts=[{"sentence_id": "s1:0", "factual": True}]))
    # s1:1 missing entirely -- and from the retry too, since FakeReviewLead reuses this
    # same single response for every call.

    with pytest.raises(ReviewCoverageError, match="s1:1"):
        verify_grounding(narration, [], review_lead, budget=None)

    assert len(review_lead.calls) == 2  # initial batch + one retry for the missing sentence


def test_a_missing_verdict_recovered_by_the_retry_never_raises():
    """STORY_IMPROVEMENT_PLAN.md Phase 10 follow-up: confirmed live (2026-09-15) -- same
    residual gap as CM's own retry (review/claim_mapper.py) -- even a bounded batch can
    still drop a single entry. A retry with just the missing sentence(s) must resolve an
    isolated miss without failing the whole call."""
    narration = [scene("s1", [
        SentenceNarration(text="Attention scales by the square root of d_k.", sentence_type="transition"),
        SentenceNarration(text="A plain transition.", sentence_type="transition"),
    ])]
    initial = GroundingReview(verdicts=[{"sentence_id": "s1:0", "factual": True, "supported": True}])
    retry = GroundingReview(verdicts=[{"sentence_id": "s1:1", "factual": False}])
    review_lead = FakeReviewLead([initial, retry])

    verdicts = verify_grounding(narration, [], review_lead, budget=None)

    assert len(review_lead.calls) == 2
    assert {v.sentence_id for v in verdicts} == {"s1:0", "s1:1"}


def test_completeness_finding_a_missed_factual_sentence():
    """The core case: CM said false, C2b disagrees and finds it unsupported."""
    narration = [scene("s1", [
        SentenceNarration(text="Attention scales by the square root of d_k.",
                           sentence_type="transition", grounding_required=False),
    ])]
    review_lead = FakeReviewLead(GroundingReview(verdicts=[{
        "sentence_id": "s1:0", "factual": True, "supported": False,
        "violation_code": "cm_missed_factual_claim", "explanation": "CM missed a factual claim about scaling",
    }]))

    verdicts = verify_grounding(narration, [], review_lead, budget=None)
    issues = grounding_verdicts_to_issues(narration, verdicts)
    assert len(issues) == 1
    assert "missed" in issues[0].problem.lower()
    assert issues[0].severity == "critical"  # unsupported is always critical


def test_fidelity_finding_a_claim_that_drifted_during_paraphrase():
    """The real failure class this pass exists for: 'grows with tokens' ->
    'grows quadratically with tokens' -- same claim id, different meaning."""
    narration = [scene("s1", [
        SentenceNarration(text="KV cache grows quadratically with tokens.",
                           sentence_type="technical_assertion", grounding_required=True, grounding_refs=["C001"]),
    ])]
    review_lead = FakeReviewLead(GroundingReview(verdicts=[{
        "sentence_id": "s1:0", "factual": True, "supported": True, "verified_claim_ids": ["C001"],
        "violation_code": "meaning_drifted",
        "explanation": "C001 says KV cache grows linearly, but the sentence claims quadratic growth",
    }]))

    verdicts = verify_grounding(narration, [], review_lead, budget=None)
    issues = grounding_verdicts_to_issues(narration, verdicts)
    assert len(issues) == 1
    assert "linearly" in issues[0].problem
    assert issues[0].severity == "major"  # a named violation_code beyond unsupported/qualifier is major


def test_qualifier_dropped_is_a_critical_issue():
    narration = [scene("s1", [SentenceNarration(text="variance always equals d_k", sentence_type="technical_assertion")])]
    review_lead = FakeReviewLead(GroundingReview(verdicts=[{
        "sentence_id": "s1:0", "factual": True, "supported": True, "qualifier_preserved": False,
        "explanation": "the claim only holds under simplifying assumptions",
    }]))

    verdicts = verify_grounding(narration, [], review_lead, budget=None)
    issues = grounding_verdicts_to_issues(narration, verdicts)
    assert len(issues) == 1
    assert issues[0].severity == "critical"


def test_scope_broadened_is_a_major_issue():
    narration = [scene("s1", [SentenceNarration(text="every model does this", sentence_type="technical_assertion")])]
    review_lead = FakeReviewLead(GroundingReview(verdicts=[{
        "sentence_id": "s1:0", "factual": True, "supported": True, "scope_preserved": False,
    }]))

    verdicts = verify_grounding(narration, [], review_lead, budget=None)
    issues = grounding_verdicts_to_issues(narration, verdicts)
    assert len(issues) == 1
    assert issues[0].severity == "major"


def test_recommended_intent_is_specific_to_which_violation_actually_fired():
    """2026-09-16, found on review: `recommended_intent` used to be one fixed
    three-option sentence ("ground..., restore..., or narrow...") regardless of which
    of the three actually applied. Harmless for long-form (A3 synthesizes a fresh
    instruction before any rewrite sees it), but shorts' B2s
    (editing/short_targeted_rewrite.py) sends `recommended_intent` to the rewrite
    verbatim, with no intermediate step -- a vague instruction there means the rewrite
    doesn't know which of the three to actually do."""
    from review.grounding_verifier import GroundingVerdict

    narration = [scene("s1", [SentenceNarration(text="x", sentence_type="technical_assertion")])]

    unsupported = grounding_verdicts_to_issues(narration, [
        GroundingVerdict(sentence_id="s1:0", factual=True, supported=False),
    ])[0]
    qualifier_dropped = grounding_verdicts_to_issues(narration, [
        GroundingVerdict(sentence_id="s1:0", factual=True, supported=True, qualifier_preserved=False),
    ])[0]
    scope_broadened = grounding_verdicts_to_issues(narration, [
        GroundingVerdict(sentence_id="s1:0", factual=True, supported=True, scope_preserved=False),
    ])[0]

    intents = {unsupported.recommended_intent, qualifier_dropped.recommended_intent, scope_broadened.recommended_intent}
    assert len(intents) == 3  # all three distinct, none is the old generic catch-all
    assert "cite a real claim" in unsupported.recommended_intent
    assert "restore the cited claim's own" in qualifier_dropped.recommended_intent
    assert "narrow this back" in scope_broadened.recommended_intent


def test_a_clean_verdict_produces_no_issue():
    narration = [scene("s1", [SentenceNarration(text="a transition", sentence_type="transition")])]
    review_lead = FakeReviewLead(GroundingReview(verdicts=[{"sentence_id": "s1:0", "factual": False}]))

    verdicts = verify_grounding(narration, [], review_lead, budget=None)
    assert grounding_verdicts_to_issues(narration, verdicts) == []


def test_uses_pass_id_c2b_and_ground_narration_mode():
    narration = [scene("s1", [SentenceNarration(text="x", sentence_type="transition")])]
    review_lead = FakeReviewLead(GroundingReview(verdicts=[{"sentence_id": "s1:0", "factual": False}]))
    verify_grounding(narration, [], review_lead, budget=None)
    call = review_lead.calls[0]
    assert call["pass_id"] == "C2b"
    assert call["mode"] == "GROUND_NARRATION"


def test_no_sentences_skips_the_call_entirely():
    review_lead = FakeReviewLead(GroundingReview(verdicts=[]))
    assert verify_grounding([], [], review_lead, budget=None) == []
    assert review_lead.calls == []


def test_metadata_repair_corrects_a_cm_false_negative_without_flagging_it():
    """Phase 10 §5.3: CM says grounding_required=False, C2b independently
    confirms the sentence IS factual and IS actually supported -- this is a
    CM mistake, not a narration defect, so it must be patched in the
    narration directly and must NOT produce a critique issue (which would
    trigger an unnecessary A3/B2 rewrite)."""
    narration = [scene("s1", [
        SentenceNarration(text="Every query compares against every key.",
                           sentence_type="explanatory_inference", grounding_required=False, claim_refs=["C074"]),
    ])]
    review_lead = FakeReviewLead(GroundingReview(verdicts=[{
        "sentence_id": "s1:0", "factual": True, "supported": True, "verified_claim_ids": ["C074"],
    }]))

    verdicts = verify_grounding(narration, [], review_lead, budget=None)
    repaired = apply_grounding_metadata_repairs(narration, verdicts)

    assert repaired[0].sentences[0].grounding_required is True
    assert repaired[0].sentences[0].grounding_refs == ["C074"]
    assert grounding_verdicts_to_issues(narration, verdicts) == []


def test_metadata_repair_leaves_a_real_problem_alone():
    """The repair path only ever moves False -> True on C2b's own confirmation --
    it must never touch a sentence C2b flags as a real defect."""
    narration = [scene("s1", [
        SentenceNarration(text="the highest score is selected", sentence_type="technical_assertion",
                           grounding_required=True, grounding_refs=["C001"]),
    ])]
    review_lead = FakeReviewLead(GroundingReview(verdicts=[{
        "sentence_id": "s1:0", "factual": True, "supported": False, "violation_code": "soft_stated_as_hard",
    }]))

    verdicts = verify_grounding(narration, [], review_lead, budget=None)
    repaired = apply_grounding_metadata_repairs(narration, verdicts)

    assert repaired[0].sentences[0].grounding_refs == ["C001"]  # untouched
    assert len(grounding_verdicts_to_issues(narration, verdicts)) == 1


def test_more_sentences_than_the_batch_size_are_split_across_multiple_calls():
    """Phase 10 (extended after a live run confirmed C2b needs the same fix CM already
    had): a single oversized call is exactly what let a real C2b response come back with
    16 of 58 verdicts silently missing -- bounding call size lowers that risk."""
    n = C2B_BATCH_SIZE + 5
    narration = [scene("s1", [SentenceNarration(text=f"sentence {i}", sentence_type="transition") for i in range(n)])]
    batch1 = GroundingReview(verdicts=[{"sentence_id": f"s1:{i}", "factual": False} for i in range(C2B_BATCH_SIZE)])
    batch2 = GroundingReview(verdicts=[{"sentence_id": f"s1:{i}", "factual": False} for i in range(C2B_BATCH_SIZE, n)])
    review_lead = FakeReviewLead([batch1, batch2])

    verdicts = verify_grounding(narration, [], review_lead, budget=None)

    # 2026-09-15: batches dispatch concurrently (llm/concurrency.py) -- `calls` order
    # reflects thread scheduling, not submission order, so assert on the multiset of
    # sizes rather than a specific position.
    assert len(review_lead.calls) == 2
    assert sorted(len(c["payload"]["sentences"]) for c in review_lead.calls) == sorted([C2B_BATCH_SIZE, n - C2B_BATCH_SIZE])
    assert len(verdicts) == n


def test_soft_stated_as_hard_is_a_major_issue():
    """STORY_IMPROVEMENT_PLAN.md Phase 13: the generic technical-overclaim checks moved
    here from C1 -- hard-selection language for a claim that's actually soft/weighted."""
    narration = [scene("s1", [SentenceNarration(text="the highest-scoring option is selected",
                                                 sentence_type="technical_assertion")])]
    review_lead = FakeReviewLead(GroundingReview(verdicts=[{
        "sentence_id": "s1:0", "factual": True, "supported": True,
        "violation_code": "soft_stated_as_hard", "explanation": "the claim describes a weighted contribution",
    }]))

    verdicts = verify_grounding(narration, [], review_lead, budget=None)
    issues = grounding_verdicts_to_issues(narration, verdicts)
    assert len(issues) == 1
    assert issues[0].severity == "major"


def test_partial_contribution_overstated_is_a_major_issue():
    narration = [scene("s1", [SentenceNarration(text="this one component causes the entire outcome",
                                                 sentence_type="technical_assertion")])]
    review_lead = FakeReviewLead(GroundingReview(verdicts=[{
        "sentence_id": "s1:0", "factual": True, "supported": True,
        "violation_code": "partial_contribution_overstated",
    }]))

    verdicts = verify_grounding(narration, [], review_lead, budget=None)
    issues = grounding_verdicts_to_issues(narration, verdicts)
    assert len(issues) == 1
    assert issues[0].severity == "major"


def test_prompt_covers_the_technical_overclaim_patterns_moved_from_c1():
    from review.grounding_verifier import TASK_PROMPT

    assert "soft_stated_as_hard" in TASK_PROMPT
    assert "partial_contribution_overstated" in TASK_PROMPT


# --- STORY_IMPROVEMENT_PLAN.md Phase 22 (2026-09-16): escalation-gating ---------------------


def test_a_clean_flash_pass_never_calls_the_escalation_agent():
    narration = [scene("s1", [SentenceNarration(text="x", sentence_type="transition")])]
    flash = FakeReviewLead(GroundingReview(verdicts=[{"sentence_id": "s1:0", "factual": False}]))
    strong = FakeReviewLead(GroundingReview(verdicts=[]))

    verify_grounding(narration, [], flash, budget=None, escalate_to=strong)

    assert strong.calls == []


def test_an_unsupported_verdict_is_escalated_and_the_escalated_verdict_wins():
    narration = [scene("s1", [SentenceNarration(text="a real claim", sentence_type="technical_assertion")])]
    flash = FakeReviewLead(GroundingReview(verdicts=[
        {"sentence_id": "s1:0", "factual": True, "supported": False},
    ]))
    strong = FakeReviewLead(GroundingReview(verdicts=[
        {"sentence_id": "s1:0", "factual": True, "supported": True, "verified_claim_ids": ["C001"]},
    ]))

    verdicts = verify_grounding(narration, [], flash, budget=None, escalate_to=strong)

    assert len(strong.calls) == 1
    assert strong.calls[0]["payload"]["sentences"][0]["sentence_id"] == "s1:0"
    assert verdicts[0].supported is True  # the strong tier's own opinion wins, not flash's
    assert verdicts[0].verified_claim_ids == ["C001"]


def test_escalation_only_re_sends_the_flagged_subset_not_every_sentence():
    narration = [scene("s1", [
        SentenceNarration(text="clean", sentence_type="transition"),
        SentenceNarration(text="flagged", sentence_type="technical_assertion"),
    ])]
    flash = FakeReviewLead(GroundingReview(verdicts=[
        {"sentence_id": "s1:0", "factual": False},
        {"sentence_id": "s1:1", "factual": True, "supported": False},
    ]))
    strong = FakeReviewLead(GroundingReview(verdicts=[
        {"sentence_id": "s1:1", "factual": True, "supported": True},
    ]))

    verify_grounding(narration, [], flash, budget=None, escalate_to=strong)

    escalated_ids = {s["sentence_id"] for s in strong.calls[0]["payload"]["sentences"]}
    assert escalated_ids == {"s1:1"}


def test_qualifier_dropped_and_scope_broadened_and_violation_code_all_escalate():
    """Mirrors grounding_verdicts_to_issues's own branching -- the same four signals that
    already turn into a hard/critical finding are exactly the ones worth a second opinion."""
    cases = [
        {"sentence_id": "s1:0", "factual": True, "supported": True, "qualifier_preserved": False},
        {"sentence_id": "s1:0", "factual": True, "supported": True, "scope_preserved": False},
        {"sentence_id": "s1:0", "factual": True, "supported": True, "violation_code": "meaning_drifted"},
    ]
    for verdict in cases:
        narration = [scene("s1", [SentenceNarration(text="x", sentence_type="technical_assertion")])]
        flash = FakeReviewLead(GroundingReview(verdicts=[verdict]))
        strong = FakeReviewLead(GroundingReview(verdicts=[{"sentence_id": "s1:0", "factual": True, "supported": True}]))

        verify_grounding(narration, [], flash, budget=None, escalate_to=strong)

        assert len(strong.calls) == 1, f"expected escalation for {verdict}"


def test_no_escalate_to_preserves_the_original_single_tier_behavior():
    narration = [scene("s1", [SentenceNarration(text="x", sentence_type="technical_assertion")])]
    flash = FakeReviewLead(GroundingReview(verdicts=[{"sentence_id": "s1:0", "factual": True, "supported": False}]))

    verdicts = verify_grounding(narration, [], flash, budget=None)  # no escalate_to at all

    assert verdicts[0].supported is False  # flash's own verdict stands, nothing to escalate to


def test_missing_escalation_verdict_fails_closed_same_as_the_first_pass():
    narration = [scene("s1", [SentenceNarration(text="x", sentence_type="technical_assertion")])]
    flash = FakeReviewLead(GroundingReview(verdicts=[{"sentence_id": "s1:0", "factual": True, "supported": False}]))
    strong = FakeReviewLead(GroundingReview(verdicts=[]))  # never actually answers

    with pytest.raises(ReviewCoverageError, match="escalation"):
        verify_grounding(narration, [], flash, budget=None, escalate_to=strong)


# --- STORY_IMPROVEMENT_PLAN.md Phase 22, step 2 (2026-09-16): the random-audit mechanism ----


def make_verdict(sentence_id, **overrides) -> GroundingVerdict:
    base = dict(sentence_id=sentence_id, factual=True, supported=True)
    base.update(overrides)
    return GroundingVerdict(**base)


def test_zero_sample_rate_never_calls_the_audit_agent():
    from review.grounding_verifier import audit_clean_verdicts

    narration = [scene("s1", [SentenceNarration(text="x", sentence_type="technical_assertion")])]
    verdicts = [make_verdict("s1:0")]
    pro = FakeReviewLead(GroundingReview(verdicts=[]))

    audit = audit_clean_verdicts(narration, [], verdicts, pro, budget=None, sample_rate=0.0)

    assert pro.calls == []
    assert audit.sampled_count == 0
    assert audit.disagreement_rate == 0.0


def test_only_clean_verdicts_are_eligible_for_sampling_not_already_flagged_ones():
    """A sentence flash already escalated (step 1) has already gotten a strong-tier opinion --
    auditing it again would double-count, not measure anything new about trusting flash."""
    from review.grounding_verifier import audit_clean_verdicts

    narration = [scene("s1", [
        SentenceNarration(text="clean", sentence_type="transition"),
        SentenceNarration(text="already flagged", sentence_type="technical_assertion"),
    ])]
    verdicts = [make_verdict("s1:0"), make_verdict("s1:1", supported=False)]
    pro = FakeReviewLead(GroundingReview(verdicts=[{"sentence_id": "s1:0", "factual": True, "supported": True}]))

    audit_clean_verdicts(narration, [], verdicts, pro, budget=None, sample_rate=1.0, rng=random.Random(0))

    sampled_ids = {s["sentence_id"] for s in pro.calls[0]["payload"]["sentences"]}
    assert sampled_ids == {"s1:0"}


def test_a_full_sample_rate_with_full_agreement_reports_zero_disagreement():
    from review.grounding_verifier import audit_clean_verdicts

    narration = [scene("s1", [
        SentenceNarration(text="a", sentence_type="transition"),
        SentenceNarration(text="b", sentence_type="transition"),
    ])]
    verdicts = [make_verdict("s1:0"), make_verdict("s1:1")]
    pro = FakeReviewLead(GroundingReview(verdicts=[
        {"sentence_id": "s1:0", "factual": True, "supported": True},
        {"sentence_id": "s1:1", "factual": True, "supported": True},
    ]))

    audit = audit_clean_verdicts(narration, [], verdicts, pro, budget=None, sample_rate=1.0, rng=random.Random(0))

    assert audit.sampled_count == 2
    assert audit.disagreement_count == 0
    assert audit.disagreement_rate == 0.0


def test_a_pro_disagreement_is_counted_and_surfaced_in_findings():
    """The real point of the audit: flash called this clean, but the strong tier would have
    flagged it -- exactly the kind of miss escalation-gating exists to catch."""
    from review.grounding_verifier import audit_clean_verdicts

    narration = [scene("s1", [SentenceNarration(text="x", sentence_type="technical_assertion")])]
    verdicts = [make_verdict("s1:0")]  # flash: clean
    pro = FakeReviewLead(GroundingReview(verdicts=[
        {"sentence_id": "s1:0", "factual": True, "supported": False},  # pro: actually unsupported
    ]))

    audit = audit_clean_verdicts(narration, [], verdicts, pro, budget=None, sample_rate=1.0, rng=random.Random(0))

    assert audit.sampled_count == 1
    assert audit.disagreement_count == 1
    assert audit.disagreement_rate == 1.0
    assert audit.findings[0].agrees is False
    assert audit.findings[0].sentence_id == "s1:0"


def test_sample_size_rounds_to_the_nearest_sentence_count():
    from review.grounding_verifier import audit_clean_verdicts

    narration = [scene("s1", [SentenceNarration(text=f"s{i}", sentence_type="transition") for i in range(10)])]
    verdicts = [make_verdict(f"s1:{i}") for i in range(10)]
    pro = FakeReviewLead(GroundingReview(verdicts=[
        {"sentence_id": f"s1:{i}", "factual": True, "supported": True} for i in range(10)
    ]))

    audit = audit_clean_verdicts(narration, [], verdicts, pro, budget=None, sample_rate=0.10, rng=random.Random(0))

    assert audit.sampled_count == 1  # 10% of 10 clean sentences


def test_audit_coverage_also_fails_closed():
    from review.grounding_verifier import audit_clean_verdicts

    narration = [scene("s1", [SentenceNarration(text="x", sentence_type="technical_assertion")])]
    verdicts = [make_verdict("s1:0")]
    pro = FakeReviewLead(GroundingReview(verdicts=[]))  # never answers

    with pytest.raises(ReviewCoverageError, match="audit"):
        audit_clean_verdicts(narration, [], verdicts, pro, budget=None, sample_rate=1.0, rng=random.Random(0))
