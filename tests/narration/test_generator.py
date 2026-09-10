"""Tests for narration/generator.py -- B1 (plan §5, §8, §11.4)."""
from facts.models import Claim
from narration.generator import GeneratedNarration, generate_narration
from planning.models import (
    CTAContract, EndingContract, HookContract, ScenePlan, StoryBeat, StoryPlan, TitleContract,
)


def make_plan() -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="learn why", central_question="why?",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[StoryBeat(beat_id="B01", purpose="intro", source_unit_ids=["u1"])],
        scene_plan=[ScenePlan(scene_id="s1", beat_id="B01", word_budget=60, narrative_job="open the loop")],
    )


class FakeNarrationLead:
    def __init__(self, response: GeneratedNarration):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_only_claims_from_the_scenes_own_beat_are_offered():
    """A scene must only see claims from ITS beat's source units -- not the
    whole registry -- matching context isolation (plan §5's beat.source_unit_ids
    linkage)."""
    plan = make_plan()
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="in scope", type="mechanism"),
        Claim(claim_id="C002", source_unit="u2", claim="out of scope", type="mechanism"),
    ]
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[{"scene_id": "s1", "sentences": []}]))

    generate_narration(plan, claims, narration_lead)

    payload = narration_lead.calls[0]["payload"]
    offered_ids = {c["claim_id"] for c in payload["scenes"][0]["available_claims"]}
    assert offered_ids == {"C001"}


def test_maps_generated_sentences_into_scene_narration():
    plan = make_plan()
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[{
        "scene_id": "s1",
        "sentences": [
            {"text": "That creates a new problem.", "sentence_type": "technical_assertion", "claim_refs": ["C001"]},
            {"text": "So what do we do?", "sentence_type": "question"},
        ],
    }]))

    result = generate_narration(plan, [], narration_lead)

    assert len(result) == 1
    assert result[0].scene_id == "s1"
    assert len(result[0].sentences) == 2
    assert result[0].sentences[0].claim_refs == ["C001"]
    assert result[0].sentences[0].grounding_required is False  # CM's job, not B1's


def test_estimates_seconds_from_word_count_at_167_wpm():
    plan = make_plan()
    text = " ".join(["word"] * 167)  # exactly 167 words -> 60s at 167 wpm
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[
        {"scene_id": "s1", "sentences": [{"text": text, "sentence_type": "technical_assertion"}]},
    ]))

    result = generate_narration(plan, [], narration_lead)
    assert result[0].est_seconds == 60.0


def test_a_scene_with_no_matching_beat_gets_an_empty_claim_list():
    plan = make_plan()
    plan.scene_plan.append(ScenePlan(scene_id="orphan", beat_id="NO_SUCH_BEAT", word_budget=50))
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))

    generate_narration(plan, [], narration_lead)
    payload = narration_lead.calls[0]["payload"]
    orphan = next(s for s in payload["scenes"] if s["scene_id"] == "orphan")
    assert orphan["available_claims"] == []


def test_passes_hook_cta_and_ending_context_to_the_writer():
    plan = make_plan()
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    generate_narration(plan, [], narration_lead)
    payload = narration_lead.calls[0]["payload"]
    assert payload["hook"]["tension"] == "y"
    assert payload["cta"]["primary_after_beat"] == "B01"
    assert payload["ending"]["viewer_can_now"] == "do x"


def test_uses_a_longer_timeout_for_this_potentially_large_call():
    """The real batching timeout finding (S2b) applies here too -- a full
    narration draft over many scenes is a large generation."""
    plan = make_plan()
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    generate_narration(plan, [], narration_lead)
    assert narration_lead.calls[0]["timeout_s"] == 300
