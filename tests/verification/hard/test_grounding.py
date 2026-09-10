"""Tests for verification/hard/grounding.py -- the §5.1 policy, mechanically enforced."""
from facts.models import Claim
from narration.models import SceneNarration, SentenceNarration
from verification.hard.grounding import check_grounding_policy, check_numeric_fidelity


def make_claim(claim_id, status, importance="SUPPORTING", claim="x") -> Claim:
    return Claim(claim_id=claim_id, source_unit="u1", claim=claim, type="mechanism",
                 verification_status=status, importance=importance)


def make_sentence(text="x", grounding_required=True, grounding_refs=None) -> SentenceNarration:
    return SentenceNarration(text=text, sentence_type="technical_assertion",
                              grounding_required=grounding_required, grounding_refs=grounding_refs or [])


def scene(scene_id, sentences) -> SceneNarration:
    return SceneNarration(scene_id=scene_id, sentences=sentences)


def test_verified_claim_is_always_allowed():
    claims = [make_claim("C001", "VERIFIED")]
    narration = [scene("s1", [make_sentence(grounding_refs=["C001"])])]
    assert check_grounding_policy(narration, claims) == []


def test_context_dependent_claim_is_allowed_regardless_of_hedge():
    claims = [make_claim("C001", "CONTEXT_DEPENDENT")]
    narration = [scene("s1", [make_sentence("no hedge here", grounding_refs=["C001"])])]
    assert check_grounding_policy(narration, claims) == []


def test_rejected_claim_is_never_allowed():
    claims = [make_claim("C001", "REJECTED")]
    narration = [scene("s1", [make_sentence(grounding_refs=["C001"])])]
    violations = check_grounding_policy(narration, claims)
    assert len(violations) == 1
    assert violations[0].code == "grounding_policy_violation"
    assert "REJECTED" in violations[0].detail


def test_unverified_core_claim_is_never_allowed_even_with_a_hedge():
    claims = [make_claim("C001", "UNVERIFIED", importance="CORE")]
    narration = [scene("s1", [make_sentence("this is approximately true", grounding_refs=["C001"])])]
    violations = check_grounding_policy(narration, claims)
    assert len(violations) == 1
    assert "importance='CORE'" in violations[0].detail


def test_unverified_supporting_claim_is_never_allowed():
    claims = [make_claim("C001", "UNVERIFIED", importance="SUPPORTING")]
    narration = [scene("s1", [make_sentence("approximately true", grounding_refs=["C001"])])]
    assert len(check_grounding_policy(narration, claims)) == 1


def test_unverified_optional_claim_requires_a_hedge():
    claims = [make_claim("C001", "UNVERIFIED", importance="OPTIONAL")]
    unhedged = [scene("s1", [make_sentence("this is definitely true", grounding_refs=["C001"])])]
    assert len(check_grounding_policy(unhedged, claims)) == 1

    hedged = [scene("s1", [make_sentence("this is typically true", grounding_refs=["C001"])])]
    assert check_grounding_policy(hedged, claims) == []


def test_ungrounded_factual_sentence_with_no_refs_is_flagged():
    narration = [scene("s1", [make_sentence(grounding_required=True, grounding_refs=[])])]
    violations = check_grounding_policy(narration, [])
    assert violations[0].code == "ungrounded_factual_sentence"


def test_sentence_not_requiring_grounding_is_never_checked():
    narration = [scene("s1", [make_sentence(grounding_required=False, grounding_refs=[])])]
    assert check_grounding_policy(narration, []) == []


def test_grounding_ref_to_unknown_claim_is_flagged():
    narration = [scene("s1", [make_sentence(grounding_refs=["GHOST"])])]
    violations = check_grounding_policy(narration, [])
    assert violations[0].code == "grounding_ref_unknown_claim"


def test_unverified_optional_claim_in_the_hook_is_still_forbidden():
    """Always: UNVERIFIED never in the hook or ending, no matter the hedge (plan §5.1)."""
    claims = [make_claim("C001", "UNVERIFIED", importance="OPTIONAL")]
    narration = [scene("hook_scene", [make_sentence("approximately true", grounding_refs=["C001"])])]

    violations = check_grounding_policy(narration, claims, hook_scene_ids={"hook_scene"})
    assert any(v.code == "unverified_in_hook_or_ending" for v in violations)


def test_unverified_optional_claim_outside_hook_and_ending_is_fine_when_hedged():
    claims = [make_claim("C001", "UNVERIFIED", importance="OPTIONAL")]
    narration = [scene("s1", [make_sentence("approximately true", grounding_refs=["C001"])])]
    assert check_grounding_policy(narration, claims, hook_scene_ids={"hook_scene"}) == []


def test_a_clean_multi_scene_narration_has_no_violations():
    claims = [make_claim("C001", "VERIFIED"), make_claim("C002", "CONTEXT_DEPENDENT")]
    narration = [
        scene("s1", [make_sentence(grounding_refs=["C001"]), make_sentence(grounding_required=False)]),
        scene("s2", [make_sentence(grounding_refs=["C002"])]),
    ]
    assert check_grounding_policy(narration, claims) == []


# ---- numeric fidelity -------------------------------------------------------

def test_matching_number_is_clean():
    claims = [make_claim("C001", "VERIFIED", claim="the model has 175 billion parameters")]
    narration = [scene("s1", [make_sentence("it has 175B parameters", grounding_refs=["C001"])])]
    assert check_numeric_fidelity(narration, claims) == []


def test_number_written_differently_but_equal_is_clean():
    """The exact plan §9 traceability example, run in reverse: "175B" and
    "175 billion" must compare EQUAL, not be flagged as drift."""
    claims = [make_claim("C001", "VERIFIED", claim="175,000,000,000 parameters")]
    narration = [scene("s1", [make_sentence("175 billion parameters", grounding_refs=["C001"])])]
    assert check_numeric_fidelity(narration, claims) == []


def test_small_rounding_is_tolerated():
    """Narration is allowed to round a precise figure for speech."""
    claims = [make_claim("C001", "VERIFIED", claim="40.4M saved tensors")]
    narration = [scene("s1", [make_sentence("roughly 40M saved tensors", grounding_refs=["C001"])])]
    assert check_numeric_fidelity(narration, claims) == []


def test_genuine_drift_is_flagged():
    """A real fabrication/drift case: the sentence claims a completely
    different magnitude than the claim it cites."""
    claims = [make_claim("C001", "VERIFIED", claim="175 billion parameters")]
    narration = [scene("s1", [make_sentence("175 million parameters", grounding_refs=["C001"])])]
    violations = check_numeric_fidelity(narration, claims)
    assert len(violations) == 1
    assert violations[0].code == "numeric_drift"


def test_sentence_with_no_numbers_is_not_checked():
    claims = [make_claim("C001", "VERIFIED", claim="175 billion parameters")]
    narration = [scene("s1", [make_sentence("it has many parameters", grounding_refs=["C001"])])]
    assert check_numeric_fidelity(narration, claims) == []


def test_claim_with_no_numbers_is_not_checked():
    """The cited claim makes no numeric assertion itself -- nothing to compare."""
    claims = [make_claim("C001", "VERIFIED", claim="attention retrieves context")]
    narration = [scene("s1", [make_sentence("it has 175 billion parameters", grounding_refs=["C001"])])]
    assert check_numeric_fidelity(narration, claims) == []


def test_ungrounded_sentence_is_not_checked():
    claims = [make_claim("C001", "VERIFIED", claim="175 billion parameters")]
    narration = [scene("s1", [make_sentence("175 million parameters", grounding_required=False)])]
    assert check_numeric_fidelity(narration, claims) == []
