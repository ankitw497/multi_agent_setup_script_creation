"""Tests for review/grounding_verifier.py -- C2b (plan §5.1, Appendix G #3)."""
from narration.models import SceneNarration, SentenceNarration
from review.grounding_verifier import GroundingReview, verify_grounding


def scene(scene_id, sentences) -> SceneNarration:
    return SceneNarration(scene_id=scene_id, sentences=sentences)


class FakeReviewLead:
    def __init__(self, response: GroundingReview):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_cms_own_grounding_labels_are_sent_but_not_trusted_by_construction():
    """C2b receives what CM decided (so it can check completeness against
    it) -- the code doesn't hide it, but the prompt explicitly says not to
    trust it. This test confirms the data is at least visible to check."""
    narration = [scene("s1", [
        SentenceNarration(text="x", sentence_type="transition", grounding_required=False, grounding_refs=[]),
    ])]
    review_lead = FakeReviewLead(GroundingReview(issues=[]))

    verify_grounding(narration, [], review_lead, budget=None)

    sent = review_lead.calls[0]["payload"]["sentences"][0]
    assert sent["grounding_required"] is False


def test_completeness_finding_a_missed_factual_sentence():
    """The core case: CM said false, C2b disagrees and raises it."""
    narration = [scene("s1", [
        SentenceNarration(text="Attention scales by the square root of d_k.",
                           sentence_type="transition", grounding_required=False),
    ])]
    review_lead = FakeReviewLead(GroundingReview(issues=[{
        "issue_id": "I001", "severity": "major", "category": "hook", "layer": "NARRATION",
        "scene_ids": ["s1"], "problem": "CM missed a factual claim about scaling",
        "why_it_matters": "an ungrounded technical claim slipped through",
        "recommended_intent": "ground this sentence to a claim or remove the assertion",
        "repair_owner": "narration_lead",
    }]))

    issues = verify_grounding(narration, [], review_lead, budget=None)
    assert len(issues) == 1
    assert "missed" in issues[0].problem.lower()


def test_fidelity_finding_a_claim_that_drifted_during_paraphrase():
    """The real failure class this pass exists for: 'grows with tokens' ->
    'grows quadratically with tokens' -- same claim id, different meaning."""
    narration = [scene("s1", [
        SentenceNarration(text="KV cache grows quadratically with tokens.",
                           sentence_type="technical_assertion", grounding_required=True, grounding_refs=["C001"]),
    ])]
    review_lead = FakeReviewLead(GroundingReview(issues=[{
        "issue_id": "I001", "severity": "critical", "category": "clarity", "layer": "TECHNICAL",
        "scene_ids": ["s1"],
        "problem": "C001 says KV cache grows linearly, but the sentence claims quadratic growth",
        "why_it_matters": "this contradicts the verified claim while still citing it as support",
        "recommended_intent": "correct to linear growth or remove the claim reference",
        "repair_owner": "narration_lead",
    }]))

    issues = verify_grounding(narration, [], review_lead, budget=None)
    assert issues[0].severity == "critical"
    assert "linearly" in issues[0].problem


def test_no_issues_is_a_valid_clean_result():
    review_lead = FakeReviewLead(GroundingReview(issues=[]))
    assert verify_grounding([], [], review_lead, budget=None) == []


def test_uses_pass_id_c2b_and_ground_narration_mode():
    review_lead = FakeReviewLead(GroundingReview(issues=[]))
    verify_grounding([], [], review_lead, budget=None)
    call = review_lead.calls[0]
    assert call["pass_id"] == "C2b"
    assert call["mode"] == "GROUND_NARRATION"
