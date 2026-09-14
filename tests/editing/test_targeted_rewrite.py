"""Tests for editing/targeted_rewrite.py -- B2 (plan §8, §15).

Real gap found 2026-09-10: TARGETED_REWRITE was a no-op -- the orchestrator
just logged the intent and re-verified the same narration unchanged. These
tests prove the scoping contract: only named scenes are touched, everything
else survives byte-for-byte, and every finding type (rewrite_beats,
technical_fixes, delete_or_compress) actually reaches the model.
"""
from editing.models import DeleteOrCompress, RevisionPlan, RewriteBeat, RewriteScene, TechnicalFix
from editing.targeted_rewrite import apply_targeted_rewrite
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
