"""Tests for narration/generator.py -- B1 (plan §5, §8, §11.4)."""
from facts.models import Claim
from narration.generator import GeneratedNarration, generate_narration
from planning.models import (
    CTAContract, EndingContract, HookContract, RunningExample, ScenePlan, StoryBeat, StoryPlan,
    TitleContract,
)


def make_plan(**overrides) -> StoryPlan:
    base = dict(
        archetype="build", selection_reason="x", story_promise="learn why", central_question="why?",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[StoryBeat(beat_id="B01", purpose="intro", source_unit_ids=["u1"])],
        scene_plan=[ScenePlan(scene_id="s1", beat_id="B01", word_budget=60, narrative_job="open the loop")],
    )
    base.update(overrides)
    return StoryPlan(**base)


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
    assert payload["cta"]["final_enabled"] is True  # default
    assert payload["ending"]["viewer_can_now"] == "do x"


def test_final_enabled_false_reaches_the_payload():
    """STORY_IMPROVEMENT_PLAN.md Phase 12: the planner's own CTA ownership
    decision must reach the writer -- a video that wants a clean ending
    with no CTA-adjacent language at all sets this explicitly."""
    plan = make_plan(cta=CTAContract(primary_after_beat="B01", final_enabled=False))
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    generate_narration(plan, [], narration_lead)
    payload = narration_lead.calls[0]["payload"]
    assert payload["cta"]["final_enabled"] is False


def test_prompt_no_longer_lets_the_final_scene_auto_qualify_as_the_cta_scene():
    """The confirmed real bug this phase fixes: the old prompt let ANY final
    scene become a full CTA scene regardless of plan.cta.primary_after_beat,
    letting the narrator invent an ask the planner never placed."""
    from narration.generator import TASK_PROMPT

    assert "or is\n  the final scene" not in TASK_PROMPT
    assert "or is the final scene" not in TASK_PROMPT
    assert "ONLY when it matches" in TASK_PROMPT
    assert "final_enabled" in TASK_PROMPT


def test_uses_a_longer_timeout_for_this_potentially_large_call():
    """The real batching timeout finding (S2b) applies here too -- a full
    narration draft over many scenes is a large generation. Raised 300 -> 600
    (2026-09-17): the final live-verify run hit `claude -p timed out after 300s`
    at this exact call site twice in a row (a fresh run and its resume), each
    time after all 3 of claude_cli.py's own retries were exhausted -- real,
    repeated evidence the default was too tight for this call's actual size,
    not a one-off network blip."""
    plan = make_plan()
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    generate_narration(plan, [], narration_lead)
    assert narration_lead.calls[0]["timeout_s"] == 600


def test_passes_scene_function_new_concepts_and_must_not_repeat_per_scene():
    """V2 narrative-continuity fix (STORY_IMPROVEMENT_PLAN.md Phase 1): the
    writer must see each scene's causal-continuity metadata, not just its
    narrative_job, so it knows when to compress instead of re-explain."""
    plan = make_plan(scene_plan=[
        ScenePlan(
            scene_id="s1", beat_id="B01", word_budget=60, narrative_job="open the loop",
            scene_function="derivation", new_concepts=["scaling"], must_not_repeat=["Q/K/V roles"],
        ),
    ])
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    generate_narration(plan, [], narration_lead)

    scene_payload = narration_lead.calls[0]["payload"]["scenes"][0]
    assert scene_payload["scene_function"] == "derivation"
    assert scene_payload["new_concepts"] == ["scaling"]
    assert scene_payload["must_not_repeat"] == ["Q/K/V roles"]


def test_mechanism_scope_reaches_the_scene_payload():
    """Phase 7 #3 (mechanism scope): a recap scene needs to know the
    current recorded scope of a conditional mechanism so it doesn't state
    it as an unconditional, universal fact."""
    plan = make_plan(scene_plan=[
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=60, mechanism_scope={"causal_mask_required": True}),
    ])
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    generate_narration(plan, [], narration_lead)

    scene_payload = narration_lead.calls[0]["payload"]["scenes"][0]
    assert scene_payload["mechanism_scope"] == {"causal_mask_required": True}


def test_prompt_instructs_confirming_already_previewed_exact_values():
    from narration.generator import TASK_PROMPT
    assert "CONFIRMING" in TASK_PROMPT


def test_prompt_instructs_stating_mechanism_scope_correctly_in_a_recap():
    from narration.generator import TASK_PROMPT
    assert "mechanism_scope" in TASK_PROMPT


def test_prompt_warns_against_overusing_causal_connectors_and_repeated_rhetorical_devices():
    """STORY_IMPROVEMENT_PLAN.md Phase 23, found live: a real generated script measured
    causal_per100w=1.93 (target 0.44-1.61) and independently read as repeating the "not X,
    but Y" construction 6+ times -- the prompt's own voice instruction named causal
    connectors as a desired feature with no guidance capping their frequency or warning
    against a repeated device becoming a tell."""
    from narration.generator import TASK_PROMPT

    assert "seasoning, not a default sentence template" in TASK_PROMPT
    assert "not X, but Y" in TASK_PROMPT


def test_prompt_requires_one_idea_per_sentence():
    """STORY_IMPROVEMENT_PLAN.md Phase 23: real 50-62 word sentences found in a generated
    script stacking cause, mechanism, and a numeric example together -- no prior guidance
    against this."""
    from narration.generator import TASK_PROMPT

    assert "exactly ONE idea" in TASK_PROMPT


def test_claim_importance_reaches_the_payload():
    """Real bug found 2026-09-11 (live e2e run): the grounding-policy hard
    gate (verification/hard/grounding.py) requires CORE/SUPPORTING claims
    to be VERIFIED/CONTEXT_DEPENDENT to be narrated at all -- but B1 was
    never given `importance`, so it structurally couldn't have followed
    that rule even if instructed to. A live run produced 61 grounding
    hard failures from exactly this gap."""
    plan = make_plan()
    claims = [Claim(claim_id="C001", source_unit="u1", claim="x", type="mechanism", importance="CORE")]
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[{"scene_id": "s1", "sentences": []}]))

    generate_narration(plan, claims, narration_lead)

    payload = narration_lead.calls[0]["payload"]
    assert payload["scenes"][0]["available_claims"][0]["importance"] == "CORE"


def test_prompt_instructs_the_full_grounding_policy_not_just_verified_phrasing():
    """The other half of the same live bug: the prompt only ever told B1
    how to PHRASE a VERIFIED claim, never what to do with an UNVERIFIED or
    REJECTED one -- so it narrated everything as if verified, matching
    verification/hard/grounding.py's own CORE/SUPPORTING/OPTIONAL/REJECTED
    policy table exactly, which the prompt now must mirror."""
    from narration.generator import TASK_PROMPT

    assert "REJECTED" in TASK_PROMPT
    assert "UNVERIFIED" in TASK_PROMPT
    assert "CONTEXT_DEPENDENT" in TASK_PROMPT
    assert "OPTIONAL" in TASK_PROMPT
    assert "no hedge makes it acceptable" in TASK_PROMPT


def test_prompt_instructs_not_hedging_verified_claims():
    """Real bug confirmed live (STORY_IMPROVEMENT_PLAN.md Phase 3, feedback
    §9): a saved run (runs/v13/drafts/narration_final.json) contains "is
    then believed to pass through a learned output projection" -- verifier-
    style hedging leaking into narration for a claim that was already
    verified. The prompt never told B1 to state verified facts plainly."""
    from narration.generator import TASK_PROMPT

    assert "VERIFIED" in TASK_PROMPT
    assert "is believed to" in TASK_PROMPT


def test_prompt_instructs_the_preview_derivation_recap_distinction():
    from narration.generator import TASK_PROMPT

    assert "scene_function" in TASK_PROMPT
    assert "must_not_repeat" in TASK_PROMPT


def test_prompt_says_a_same_beat_sibling_is_just_as_off_limits_as_another_beat():
    """STORY_IMPROVEMENT_PLAN.md Phase 27 item 2: found live -- a real script re-derived
    the same underlying assumptions across 3 consecutive scenes within ONE beat, even
    though the "don't re-derive a must_not_repeat concept" rule already existed, apparently
    because a sibling scene felt like "still building the same point" rather than a
    genuinely separate prior scene that's off-limits."""
    from narration.generator import TASK_PROMPT

    assert "your OWN earlier scenes in this" in TASK_PROMPT
    assert "not an exception" in TASK_PROMPT


def test_prompt_has_no_hardcoded_topic_vocabulary():
    """Overfitting guard (user-flagged, STORY_IMPROVEMENT_PLAN.md): this
    prompt runs once per full video regardless of topic -- must state its
    overclaim/hedge guidance generically, not via attention/Q-K-V-specific
    examples baked in from the one video this fix was diagnosed against."""
    from narration.generator import TASK_PROMPT

    lowered = TASK_PROMPT.lower()
    for term in ("q/k/v", "softmax", "multi-head", "q asks", "k matches", "v carries"):
        assert term not in lowered, f"found topic-specific term {term!r} in a generic per-video prompt"


def test_passes_the_running_example_to_the_writer():
    plan = make_plan(running_example=RunningExample(label="trophy/suitcase", values={"trophy": "9.6"}))
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    generate_narration(plan, [], narration_lead)

    payload = narration_lead.calls[0]["payload"]
    assert payload["running_example"]["label"] == "trophy/suitcase"
    assert payload["running_example"]["values"] == {"trophy": "9.6"}


def test_prompt_carries_the_shared_factual_invariants():
    """STORY_IMPROVEMENT_PLAN.md Phase 12: one shared fragment, not rules
    B1 alone carries and B2/shorts silently drift out of sync with."""
    from narration.factual_invariants import NARRATION_FACTUAL_INVARIANTS
    from narration.generator import TASK_PROMPT

    assert NARRATION_FACTUAL_INVARIANTS in TASK_PROMPT
    assert "NEVER UPGRADE" in TASK_PROMPT
