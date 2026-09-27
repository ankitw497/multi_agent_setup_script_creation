"""Tests for editing/targeted_rewrite.py -- B2 (plan §8, §15).

Real gap found 2026-09-10: TARGETED_REWRITE was a no-op -- the orchestrator
just logged the intent and re-verified the same narration unchanged. These
tests prove the scoping contract: only named scenes are touched, everything
else survives byte-for-byte, and every finding type (rewrite_beats,
technical_fixes, delete_or_compress) actually reaches the model.
"""
from editing.models import DeleteOrCompress, RevisionPlan, RewriteBeat, RewriteScene, TechnicalFix
from editing.targeted_rewrite import B2_BATCH_SIZE, apply_targeted_rewrite
from facts.models import Claim
from narration.generator import GeneratedNarration
from narration.models import SceneNarration, SentenceNarration
from planning.models import (
    CTAContract, EndingContract, HookContract, RunningExample, ScenePlan, StoryBeat, StoryPlan,
    TitleContract,
)


def make_plan(**overrides) -> StoryPlan:
    base = dict(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"]),
               StoryBeat(beat_id="B02", purpose="y", source_unit_ids=["u2"])],
        scene_plan=[
            ScenePlan(scene_id="s1", beat_id="B01", word_budget=40),
            ScenePlan(scene_id="s2", beat_id="B01", word_budget=40),
            ScenePlan(scene_id="s3", beat_id="B02", word_budget=40),
        ],
    )
    base.update(overrides)
    return StoryPlan(**base)


def make_narration() -> list[SceneNarration]:
    return [
        SceneNarration(scene_id="s1", sentences=[SentenceNarration(text="original one", sentence_type="transition")]),
        SceneNarration(scene_id="s2", sentences=[SentenceNarration(text="original two", sentence_type="transition")]),
        SceneNarration(scene_id="s3", sentences=[SentenceNarration(text="original three", sentence_type="transition")]),
    ]


class FakeNarrationLead:
    def __init__(self, response: GeneratedNarration):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_nothing_named_returns_narration_completely_unchanged():
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    revision_plan = RevisionPlan(run_id="r")  # nothing named at all

    result = apply_targeted_rewrite(make_plan(), make_narration(), [], revision_plan, narration_lead)

    assert result == make_narration()
    assert narration_lead.calls == []  # no call made -- nothing to rewrite


def test_only_the_named_beats_scenes_are_sent_to_the_model():
    """rewrite_beats names B01 -- only s1 and s2 (B01's scenes) should be
    sent, never s3 (B02's scene)."""
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[
        {"scene_id": "s1", "sentences": [{"text": "rewritten one", "sentence_type": "transition"}]},
        {"scene_id": "s2", "sentences": [{"text": "rewritten two", "sentence_type": "transition"}]},
    ]))
    revision_plan = RevisionPlan(run_id="r", rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="tighten")])

    apply_targeted_rewrite(make_plan(), make_narration(), [], revision_plan, narration_lead)

    sent_scene_ids = {s["scene_id"] for s in narration_lead.calls[0]["payload"]["scenes"]}
    assert sent_scene_ids == {"s1", "s2"}


def test_uses_a_300s_timeout_matching_b1s_own_full_narration_call():
    """Real bug confirmed live, twice (2026-09-14): a full-beat rewrite_beats
    payload (multiple scenes' worth of claims, not just one scene) can take
    longer than 180s -- both attempts crashed with a subprocess timeout,
    even after ERR-050 made a timeout retryable, since every retry hit the
    same too-short ceiling. Must match narration/generator.py's B1
    timeout_s=300 for the same reason -- a full-scale Sonnet call routinely
    needs this long."""
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    revision_plan = RevisionPlan(run_id="r", rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="tighten")])

    apply_targeted_rewrite(make_plan(), make_narration(), [], revision_plan, narration_lead)

    assert narration_lead.calls[0]["timeout_s"] == 300


def test_untouched_scenes_survive_byte_for_byte():
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[
        {"scene_id": "s1", "sentences": [{"text": "rewritten one", "sentence_type": "transition"}]},
    ]))
    revision_plan = RevisionPlan(run_id="r", rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="fix s1 only")])
    original = make_narration()

    result = apply_targeted_rewrite(make_plan(), original, [], revision_plan, narration_lead)

    result_by_id = {s.scene_id: s for s in result}
    assert result_by_id["s1"].sentences[0].text == "rewritten one"
    assert result_by_id["s2"] == original[1]  # untouched
    assert result_by_id["s3"] == original[2]  # untouched


def test_technical_fix_names_the_exact_scene_and_claim():
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[
        {"scene_id": "s3", "sentences": [{"text": "corrected", "sentence_type": "technical_assertion", "claim_refs": ["C001"]}]},
    ]))
    revision_plan = RevisionPlan(run_id="r", technical_fixes=[
        TechnicalFix(scene_id="s3", claim_id="C001", required_change="use the verified figure, not the draft one"),
    ])

    apply_targeted_rewrite(make_plan(), make_narration(), [], revision_plan, narration_lead)

    payload_scene = narration_lead.calls[0]["payload"]["scenes"][0]
    assert payload_scene["scene_id"] == "s3"
    assert "C001" in payload_scene["required_intent"]
    assert "verified figure" in payload_scene["required_intent"]


def test_delete_or_compress_reaches_the_model_without_touching_scene_plan():
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[
        {"scene_id": "s2", "sentences": [{"text": "brief bridge", "sentence_type": "transition"}]},
    ]))
    revision_plan = RevisionPlan(run_id="r", delete_or_compress=[
        DeleteOrCompress(scene_id="s2", reason="redundant with s1"),
    ])
    plan = make_plan()

    result = apply_targeted_rewrite(plan, make_narration(), [], revision_plan, narration_lead)

    assert "redundant with s1" in narration_lead.calls[0]["payload"]["scenes"][0]["required_intent"]
    assert [s.scene_id for s in result] == ["s1", "s2", "s3"]  # scene_plan/narration shape unchanged
    assert len(plan.scene_plan) == 3  # never structurally deleted


def test_preserve_list_is_passed_through():
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[
        {"scene_id": "s1", "sentences": [{"text": "x", "sentence_type": "transition"}]},
    ]))
    revision_plan = RevisionPlan(
        run_id="r", preserve=["s2", "s3", "the ending"],
        rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="y")],
    )

    apply_targeted_rewrite(make_plan(), make_narration(), [], revision_plan, narration_lead)

    assert narration_lead.calls[0]["payload"]["preserve"] == ["s2", "s3", "the ending"]


def test_uses_pass_id_b2_and_targeted_rewrite_mode():
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    revision_plan = RevisionPlan(run_id="r", rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="y")])

    apply_targeted_rewrite(make_plan(), make_narration(), [], revision_plan, narration_lead)

    call = narration_lead.calls[0]
    assert call["pass_id"] == "B2"
    assert call["mode"] == "TARGETED_REWRITE"


def test_scene_function_new_concepts_and_must_not_repeat_reach_a_rewrite():
    """BUG-1 fix (STORY_IMPROVEMENT_PLAN.md Phase 8.1): a rewritten scene
    must still carry the Viewer Knowledge Ledger fields B1 already gets --
    otherwise a targeted rewrite can silently reintroduce a repetition the
    original draft correctly avoided."""
    plan = make_plan(scene_plan=[
        ScenePlan(
            scene_id="s1", beat_id="B01", word_budget=40,
            scene_function="derivation", new_concepts=["scaling"], must_not_repeat=["Q/K/V roles"],
        ),
        ScenePlan(scene_id="s2", beat_id="B01", word_budget=40),
        ScenePlan(scene_id="s3", beat_id="B02", word_budget=40),
    ])
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[
        {"scene_id": "s1", "sentences": [{"text": "rewritten", "sentence_type": "transition"}]},
    ]))
    revision_plan = RevisionPlan(run_id="r", rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="tighten")])

    apply_targeted_rewrite(plan, make_narration(), [], revision_plan, narration_lead)

    payload_scene = next(s for s in narration_lead.calls[0]["payload"]["scenes"] if s["scene_id"] == "s1")
    assert payload_scene["scene_function"] == "derivation"
    assert payload_scene["new_concepts"] == ["scaling"]
    assert payload_scene["must_not_repeat"] == ["Q/K/V roles"]


def test_running_example_reaches_a_rewrite():
    plan = make_plan(running_example=RunningExample(label="trophy/suitcase", values={"trophy": "9.6"}))
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[
        {"scene_id": "s1", "sentences": [{"text": "x", "sentence_type": "transition"}]},
    ]))
    revision_plan = RevisionPlan(run_id="r", rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="y")])

    apply_targeted_rewrite(plan, make_narration(), [], revision_plan, narration_lead)

    payload = narration_lead.calls[0]["payload"]
    assert payload["running_example"]["label"] == "trophy/suitcase"
    assert payload["running_example"]["values"] == {"trophy": "9.6"}


def test_prompt_instructs_the_same_scene_function_and_running_example_rules_as_b1():
    from editing.targeted_rewrite import TASK_PROMPT

    assert "scene_function" in TASK_PROMPT
    assert "must_not_repeat" in TASK_PROMPT
    assert "running_example" in TASK_PROMPT


def test_prompt_warns_against_overusing_causal_connectors_and_repeated_devices():
    """STORY_IMPROVEMENT_PLAN.md: confirmed live -- the same causal-connector/repeated-
    device cap shipped to narration/generator.py (B1) was never propagated here (B2, the
    actual rewrite executor both revision cycles used), so 12 sentences opening with
    So/Because/Since and a 6x-repeated "not X, but Y" survived 2 full targeted-rewrite
    cycles into the final emitted script."""
    from editing.targeted_rewrite import TASK_PROMPT

    assert "seasoning, not a default" in TASK_PROMPT
    assert "not X, but Y" in TASK_PROMPT


def test_prompt_names_the_fix_opener_and_sentence_length_variety():
    """2026-09-25, Phase 30 P2 item 7: STORY_IMPROVEMENT_PLAN.md Phase 24 already
    root-caused a real propagation gap -- the connector cap's fix never made it into this
    module, so a revised scene wasn't held to the same repetition/rhythm bar as a first
    draft. Confirms this pass now names "The fix:" specifically and gives the same
    sentence-length-variety guidance generator.py's own first-draft prompt has."""
    from editing.targeted_rewrite import TASK_PROMPT

    assert '"The fix:"' in TASK_PROMPT
    assert "one length per sentence" in TASK_PROMPT


def test_prompt_has_no_hardcoded_topic_vocabulary():
    """Overfitting guard (STORY_IMPROVEMENT_PLAN.md's own Phase 3 precedent):
    this prompt runs on every future video's revision cycles regardless of
    topic -- must not bake in attention/Q-K-V-specific example language."""
    from editing.targeted_rewrite import TASK_PROMPT

    lowered = TASK_PROMPT.lower()
    for term in ("q/k/v", "softmax", "multi-head", "q asks", "k matches", "v carries"):
        assert term not in lowered, f"found topic-specific term {term!r} in a generic per-video prompt"


def test_rewrite_scenes_touches_only_the_named_scene_not_the_whole_beat():
    """STORY_IMPROVEMENT_PLAN.md Phase 8.5: the narrower scene-scoped tool
    must only reach the scenes A3 actually named, never every scene in
    that scene's beat the way rewrite_beats does."""
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[
        {"scene_id": "s1", "sentences": [{"text": "rewritten one", "sentence_type": "transition"}]},
    ]))
    revision_plan = RevisionPlan(run_id="r", rewrite_scenes=[
        RewriteScene(scene_id="s1", reason="repeats s2's explanation", intent="compress to one bridging clause"),
    ])

    apply_targeted_rewrite(make_plan(), make_narration(), [], revision_plan, narration_lead)

    sent_scene_ids = {s["scene_id"] for s in narration_lead.calls[0]["payload"]["scenes"]}
    assert sent_scene_ids == {"s1"}  # not s2, even though both are in beat B01


def test_rewrite_scenes_intent_reaches_the_model():
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    revision_plan = RevisionPlan(run_id="r", rewrite_scenes=[
        RewriteScene(scene_id="s3", reason="x", intent="tighten the transition into this scene"),
    ])

    apply_targeted_rewrite(make_plan(), make_narration(), [], revision_plan, narration_lead)

    payload_scene = narration_lead.calls[0]["payload"]["scenes"][0]
    assert payload_scene["scene_id"] == "s3"
    assert "tighten the transition" in payload_scene["required_intent"]


def test_rewrite_scenes_and_technical_fixes_on_the_same_scene_combine():
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    revision_plan = RevisionPlan(
        run_id="r",
        rewrite_scenes=[RewriteScene(scene_id="s1", reason="x", intent="compress the repetition")],
        technical_fixes=[TechnicalFix(scene_id="s1", claim_id="C001", required_change="use the verified figure")],
    )

    apply_targeted_rewrite(make_plan(), make_narration(), [], revision_plan, narration_lead)

    payload_scene = narration_lead.calls[0]["payload"]["scenes"][0]
    assert "compress the repetition" in payload_scene["required_intent"]
    assert "C001" in payload_scene["required_intent"]


class FakeNarrationLeadEcho:
    """Rewrites every scene_id present in whatever payload it's called with --
    used to verify chunking/merging across multiple B2 calls without hand-listing
    every scene's response up front."""

    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        scenes = [
            {"scene_id": s["scene_id"], "sentences": [{"text": f"rewritten {s['scene_id']}", "sentence_type": "transition"}]}
            for s in kwargs["payload"]["scenes"]
        ]
        return GeneratedNarration(scenes=scenes)


def test_a_revision_plan_larger_than_one_batch_is_split_across_multiple_calls():
    """ERR-065 (2026-09-15, found live on a gpt-5.6-sol run): a single B2 call
    carrying 16 scenes' worth of claims timed out at the 300s ceiling ERR-051
    had raised. Must chunk into multiple calls of at most B2_BATCH_SIZE scenes
    each, never one unbounded call."""
    scene_count = B2_BATCH_SIZE * 2 + 1  # forces 3 batches: 5, 5, 1
    plan = make_plan(
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"])],
        scene_plan=[ScenePlan(scene_id=f"s{i}", beat_id="B01", word_budget=40) for i in range(scene_count)],
    )
    narration = [
        SceneNarration(scene_id=f"s{i}", sentences=[SentenceNarration(text="original", sentence_type="transition")])
        for i in range(scene_count)
    ]
    narration_lead = FakeNarrationLeadEcho()
    revision_plan = RevisionPlan(run_id="r", rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="tighten")])

    result = apply_targeted_rewrite(plan, narration, [], revision_plan, narration_lead)

    assert len(narration_lead.calls) == 3
    assert [len(c["payload"]["scenes"]) for c in narration_lead.calls] == [B2_BATCH_SIZE, B2_BATCH_SIZE, 1]
    # every scene actually got rewritten, regardless of which batch it landed in
    result_by_id = {s.scene_id: s for s in result}
    for i in range(scene_count):
        assert result_by_id[f"s{i}"].sentences[0].text == f"rewritten s{i}"


def test_a_small_revision_plan_still_makes_exactly_one_call():
    narration_lead = FakeNarrationLeadEcho()
    revision_plan = RevisionPlan(run_id="r", rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="tighten")])

    apply_targeted_rewrite(make_plan(), make_narration(), [], revision_plan, narration_lead)

    assert len(narration_lead.calls) == 1


def test_prompt_carries_the_shared_factual_invariants():
    """STORY_IMPROVEMENT_PLAN.md Phase 12: confirmed real gap -- this prompt
    used to have no hedging/upgrade language at all, so a targeted rewrite
    could reintroduce exactly the overclaim B1 was told to avoid."""
    from editing.targeted_rewrite import TASK_PROMPT
    from narration.factual_invariants import NARRATION_FACTUAL_INVARIANTS

    assert NARRATION_FACTUAL_INVARIANTS in TASK_PROMPT
    assert "NEVER UPGRADE" in TASK_PROMPT


# ---- Phase 32 P0: importance/mechanism_scope/cta/hook reaching B2 -------------------------

def test_claim_importance_reaches_the_payload():
    """A real gap found live 2026-09-26: the shared factual-invariants fragment tells this
    pass to gate narration on `importance` + `verification_status` together, but the claim
    payload used to send only `verification_status` -- structurally impossible to obey."""
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    revision_plan = RevisionPlan(run_id="r", rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="tighten")])
    claims = [Claim(claim_id="C1", source_unit="u1", claim="x", type="mechanism", importance="CORE")]

    apply_targeted_rewrite(make_plan(), make_narration(), claims, revision_plan, narration_lead)

    payload_scene = narration_lead.calls[0]["payload"]["scenes"][0]
    assert payload_scene["available_claims"][0]["importance"] == "CORE"


def test_mechanism_scope_reaches_the_payload():
    plan = make_plan(scene_plan=[
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=40, mechanism_scope={"causal_masking": False}),
        ScenePlan(scene_id="s2", beat_id="B01", word_budget=40),
        ScenePlan(scene_id="s3", beat_id="B02", word_budget=40),
    ])
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    revision_plan = RevisionPlan(run_id="r", rewrite_scenes=[RewriteScene(scene_id="s1", reason="x", intent="fix")])

    apply_targeted_rewrite(plan, make_narration(), [], revision_plan, narration_lead)

    payload_scene = narration_lead.calls[0]["payload"]["scenes"][0]
    assert payload_scene["mechanism_scope"] == {"causal_masking": False}


def test_cta_beat_hook_last_scene_and_true_final_scene_flags():
    """B01 is the hook beat (s1, s2 -- s2 is its LAST scene); B02 is the cta beat (s3, the
    plan's true final scene too). A rewrite touching all three scenes must correctly flag
    exactly one scene for each of the three booleans B2 needs but never received before."""
    plan = make_plan(
        beats=[
            StoryBeat(beat_id="B01", purpose="x", archetype_role="hook", source_unit_ids=["u1"]),
            StoryBeat(beat_id="B02", purpose="y", source_unit_ids=["u2"]),
        ],
        cta=CTAContract(primary_after_beat="B02"),
        scene_plan=[
            ScenePlan(scene_id="s1", beat_id="B01", word_budget=40),
            ScenePlan(scene_id="s2", beat_id="B01", word_budget=40),
            ScenePlan(scene_id="s3", beat_id="B02", word_budget=40),
        ],
    )
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    revision_plan = RevisionPlan(run_id="r", rewrite_scenes=[
        RewriteScene(scene_id="s1", reason="x", intent="fix"),
        RewriteScene(scene_id="s2", reason="x", intent="fix"),
        RewriteScene(scene_id="s3", reason="x", intent="fix"),
    ])

    apply_targeted_rewrite(plan, make_narration(), [], revision_plan, narration_lead)

    by_id = {s["scene_id"]: s for s in narration_lead.calls[0]["payload"]["scenes"]}
    assert by_id["s1"]["is_hook_last_scene"] is False
    assert by_id["s2"]["is_hook_last_scene"] is True
    assert by_id["s3"]["is_hook_last_scene"] is False
    assert by_id["s1"]["is_cta_beat"] is False
    assert by_id["s3"]["is_cta_beat"] is True
    assert by_id["s3"]["is_true_final_scene"] is True
    assert by_id["s1"]["is_true_final_scene"] is False


def test_hook_last_scene_is_found_positionally_even_without_archetype_role_hook():
    """Found live, 2026-09-27: archetype_role is a plain, model-filled string, not a
    Literal -- a beat that IS the hook by construction (the video's very first beat) but
    whose archetype_role the model tagged differently (or left blank) must not silently
    disable this guardrail. Matches pacing.py's own established convention: the FIRST
    beat is the hook, by construction, regardless of its own archetype_role label."""
    plan = make_plan(
        beats=[
            StoryBeat(beat_id="B01", purpose="x", archetype_role="", source_unit_ids=["u1"]),  # no "hook" label
            StoryBeat(beat_id="B02", purpose="y", source_unit_ids=["u2"]),
        ],
        scene_plan=[
            ScenePlan(scene_id="s1", beat_id="B01", word_budget=40),
            ScenePlan(scene_id="s2", beat_id="B01", word_budget=40),
            ScenePlan(scene_id="s3", beat_id="B02", word_budget=40),
        ],
    )
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    revision_plan = RevisionPlan(run_id="r", rewrite_scenes=[RewriteScene(scene_id="s2", reason="x", intent="fix")])

    apply_targeted_rewrite(plan, make_narration(), [], revision_plan, narration_lead)

    payload_scene = narration_lead.calls[0]["payload"]["scenes"][0]
    assert payload_scene["is_hook_last_scene"] is True


def test_cta_and_hook_contracts_reach_the_outer_payload():
    narration_lead = FakeNarrationLead(GeneratedNarration(scenes=[]))
    revision_plan = RevisionPlan(run_id="r", rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="tighten")])

    apply_targeted_rewrite(make_plan(), make_narration(), [], revision_plan, narration_lead)

    payload = narration_lead.calls[0]["payload"]
    assert payload["cta"]["primary_after_beat"] == "B01"
    assert "hook" in payload and "open_loop" in payload["hook"]


def test_prompt_names_cta_hook_and_mechanism_scope_rules():
    from editing.targeted_rewrite import TASK_PROMPT

    assert "is_cta_beat" in TASK_PROMPT
    assert "is_hook_last_scene" in TASK_PROMPT
    assert "mechanism_scope" in TASK_PROMPT
