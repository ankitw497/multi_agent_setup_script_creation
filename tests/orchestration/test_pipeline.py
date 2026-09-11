"""Tests for orchestration/pipeline.py -- the bounded revision loop (plan §8, §14, §15).

Uses a schema-dispatching FakeAgent so each of the three shared agent
identities (story_lead/narration_lead/review_lead) can serve multiple
passes (A2+A2b+A3, B1+B2, CM+C1+C2b) the way the real pipeline shares them.
"""
from facts.models import AssumptionLedger, Claim
from narration.generator import GeneratedNarration
from orchestration.pipeline import PipelineAgents, run_story_and_narration_loop
from planning.models import (
    CTAContract, EndingContract, HookContract, StoryBeat, StoryPlan, StoryStructure, TitleContract,
)
from planning.scene_expander import BeatSceneExpansion
from review.claim_mapper import ClaimMapperOutput
from review.cold_hook_critic import ColdHookCritique, ColdHookVerdict
from review.grounding_verifier import GroundingReview
from review.story_critic import StoryCritique


class FakeAgent:
    def __init__(self, responses_by_schema: dict):
        self._queues = {k: list(v) for k, v in responses_by_schema.items()}
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["schema"]
        return self._queues[schema].pop(0)


def make_plan(scene_words=70, n_scenes=24, source_units=None, archetype="build") -> StoryPlan:
    source_units = source_units if source_units is not None else ["u1"]
    from planning.models import ScenePlan

    # Scenes distributed across all three beats (not all dumped on B01) so
    # the retention/CTA/pacing diagnostics (plan §10.2, §10.3) see a
    # realistic timing shape too, not just a plan that happens to pass the
    # word-count hard check. B01 (hook, ALWAYS just 1 scene -- a real hook
    # must land its tension within ~30s per plan §10.2 regardless of total
    # video length, see verification/diagnostics/pacing.py) + B02 (early
    # mini-payoff, hosts the CTA at a real ~20-40% mark) + B03 (the bulk of
    # the remaining content).
    b1_n = 1
    b2_n = min(4, max(1, n_scenes // 6))
    b3_n = max(0, n_scenes - b1_n - b2_n)
    scene_plan = (
        [ScenePlan(scene_id=f"s{i}", beat_id="B01", word_budget=scene_words) for i in range(b1_n)]
        + [ScenePlan(scene_id=f"s{i}", beat_id="B02", word_budget=scene_words) for i in range(b1_n, b1_n + b2_n)]
        + [ScenePlan(scene_id=f"s{i}", beat_id="B03", word_budget=scene_words) for i in range(b1_n + b2_n, n_scenes)]
    )

    return StoryPlan(
        archetype=archetype, selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="understand how attention retrieves context"),
        hook=HookContract(viewer_problem="x", tension="y", promise="you will understand how attention retrieves context"),
        cta=CTAContract(primary_after_beat="B02"),  # not the first beat -- see check_cta_placement
        ending=EndingContract(resolve_hook="now you understand how attention retrieves context end to end",
                               compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=source_units,
                          archetype_stage="desired_capability", forward_driver="x", new_information=True),
               StoryBeat(beat_id="B02", purpose="x", source_unit_ids=source_units,
                          archetype_stage="problem_to_solution_pair", forward_driver="y", payoff=True),
               StoryBeat(beat_id="B03", purpose="x", source_unit_ids=source_units,
                          archetype_stage="assembled_system", forward_driver="z", new_information=True)],
        scene_plan=scene_plan,
    )


def make_empty_narration_response(n=1) -> GeneratedNarration:
    return GeneratedNarration(scenes=[{"scene_id": f"s{i}", "sentences": []} for i in range(n)])


def make_structure(archetype="build") -> StoryStructure:
    """The A2 (structure-only) fake response since the ERR-010/ERR-023 split
    -- same title/hook/cta/ending/beats shape as make_plan(), minus
    scene_plan, which is now a separate per-beat pass (see
    make_good_expansions/make_bad_expansions below)."""
    return StoryStructure(
        archetype=archetype, selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="understand how attention retrieves context"),
        hook=HookContract(viewer_problem="x", tension="y", promise="you will understand how attention retrieves context"),
        cta=CTAContract(primary_after_beat="B02"),
        ending=EndingContract(resolve_hook="now you understand how attention retrieves context end to end",
                               compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"],
                          archetype_stage="desired_capability", forward_driver="x", new_information=True),
               StoryBeat(beat_id="B02", purpose="x", source_unit_ids=["u1"],
                          archetype_stage="problem_to_solution_pair", forward_driver="y", payoff=True),
               StoryBeat(beat_id="B03", purpose="x", source_unit_ids=["u1"],
                          archetype_stage="assembled_system", forward_driver="z", new_information=True)],
    )


def _expansion(n_scenes, word_budget) -> BeatSceneExpansion:
    return BeatSceneExpansion(scenes=[
        {"narrative_beat": "teaching", "visual_description": "x", "word_budget": word_budget}
        for _ in range(n_scenes)
    ])


def make_good_expansions() -> list[BeatSceneExpansion]:
    """One response per beat in make_structure()'s order (B01, B02, B03):
    1+4+19=24 scenes * 70 words = 1680 words total, within tolerance of the
    ~1670-word target for a 600s video. B01 (the hook) is a single ~70-word
    scene (~25s) so the pacing diagnostic (plan §10.2's "tension reached
    inside ~30s") reads GREEN, not RED. Asymmetric otherwise (not an even
    8/8/8) so the CTA -- hosted on B02 in make_structure() -- lands at a
    real ~21% mark for the CTA-position diagnostic (plan §10.3's 20-40%
    band), not ~67% the way an even split would put it."""
    return [_expansion(1, 70), _expansion(4, 70), _expansion(19, 70)]


def make_bad_expansions() -> list[BeatSceneExpansion]:
    """The exact real defect this whole split fixes, replayed as a fake
    response: 2 scenes * 30 words * 3 beats = 180 words, wildly short of
    the ~1670-word target -- used to test the exhaustion path still works
    correctly if a beat expansion call is itself still bad."""
    return [_expansion(2, 30), _expansion(2, 30), _expansion(2, 30)]


def make_agents(story_lead_responses=None, narration_responses=None, review_responses=None, worker_responses=None) -> PipelineAgents:
    story_lead = FakeAgent({
        StoryPlan: (story_lead_responses or {}).get(StoryPlan, []),
        StoryStructure: (story_lead_responses or {}).get(StoryStructure, []),
        BeatSceneExpansion: (story_lead_responses or {}).get(BeatSceneExpansion, []),
        __import__("editing.models", fromlist=["RevisionPlan"]).RevisionPlan: (story_lead_responses or {}).get("RevisionPlan", []),
    })
    narration_lead = FakeAgent({GeneratedNarration: narration_responses or []})
    review_lead = FakeAgent({
        StoryCritique: (review_responses or {}).get("c1", []),
        GroundingReview: (review_responses or {}).get("c2b", []),
        ColdHookCritique: (review_responses or {}).get("cold_hook", []),
    })
    cm_agent = FakeAgent({ClaimMapperOutput: (review_responses or {}).get("cm", [])})
    # A clean, non-flagged verdict every time -- the cold-hook cascade
    # (Phase 8.2) then never escalates to review_lead, so existing tests
    # don't need to know about it unless they're testing it directly.
    # Queued generously (20) since it's called once per review cycle and
    # the loop's own bound (MAX_STORY_REPLANS + MAX_MAJOR_REVISIONS) is
    # small but this avoids ever running out across any test's cycles.
    worker = FakeAgent({ColdHookVerdict: worker_responses or [ColdHookVerdict() for _ in range(20)]})
    return PipelineAgents(story_lead=story_lead, narration_lead=narration_lead,
                           review_lead=review_lead, cm_agent=cm_agent, worker=worker)


def make_budget():
    from llm.budget import BudgetCounter, DEFAULT_TIERS
    return BudgetCounter(tier=DEFAULT_TIERS["longform"])


def test_a_clean_plan_passes_with_no_revision_calls():
    plan = make_plan()
    agents = make_agents(
        narration_responses=[make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[])],
        },
    )
    result = run_story_and_narration_loop(
        source_brief=__import__("planning.models", fromlist=["SourceBrief"]).SourceBrief(
            topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=plan,
    )
    assert result.final_status == "PASS"
    assert result.story_replans_used == 0
    assert result.major_revisions_used == 0
    assert agents.story_lead.calls == []  # A3/A2 never called -- nothing needed fixing


def test_a_bad_plan_gets_replanned_and_then_passes():
    """The exact real scenario found live: a structurally deficient plan
    (word budget too low) gets caught, A3 calls for a replan, and a second,
    clean plan is generated and passes. Since ERR-010/ERR-023's split, the
    replan's StoryPlan is assembled from a StoryStructure call plus one
    BeatSceneExpansion call per beat -- never returned verbatim by a single
    agent call -- so this checks content, not object identity."""
    from editing.models import RevisionPlan

    bad_plan = make_plan(scene_words=30, n_scenes=2)  # ~20 words vs ~1670 target

    agents = make_agents(
        story_lead_responses={
            StoryStructure: [make_structure()], BeatSceneExpansion: make_good_expansions(),
            "RevisionPlan": [RevisionPlan(run_id="r", story_replan_required=True)],
        },
        narration_responses=[make_empty_narration_response(), make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    result = run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=bad_plan,
    )
    assert result.final_status == "PASS"
    assert result.story_replans_used == 1
    assert result.plan.archetype == "build"
    assert len(result.plan.scene_plan) == 24  # 8 scenes * 3 beats, from make_good_expansions()


def test_replan_budget_exhaustion_fails_rather_than_looping_forever():
    """MAX_STORY_REPLANS=1 -- a second consecutive bad plan must FAIL, not
    keep replanning indefinitely."""
    from editing.models import RevisionPlan

    bad_plan_1 = make_plan(scene_words=30, n_scenes=2)

    agents = make_agents(
        story_lead_responses={
            StoryStructure: [make_structure()], BeatSceneExpansion: make_bad_expansions(),
            "RevisionPlan": [RevisionPlan(run_id="r", story_replan_required=True)] * 2,
        },
        narration_responses=[make_empty_narration_response(), make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[])] * 2,
            "c1": [StoryCritique(issues=[])] * 2,
            "c2b": [GroundingReview(issues=[])] * 2,
        },
    )
    from planning.models import SourceBrief

    result = run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=bad_plan_1,
    )
    assert result.final_status == "FAIL"
    assert result.story_replans_used == 1  # never exceeds the bound
    assert any("replan budget exhausted" in line for line in result.log)


def test_a2_replan_receives_the_prior_rejection_reason_not_a_blind_retry():
    """Real gap found 2026-09-10: the replan call used to rerun plan_story()
    with the exact same inputs as the first attempt -- A2 never learned WHY
    its plan was rejected. This proves the orchestrator now builds and
    passes a ReplanFeedback carrying the previous archetype, C1's critique,
    and the structural findings into the replan call."""
    from editing.models import RevisionPlan

    bad_plan = make_plan(scene_words=30, n_scenes=2, archetype="foundation")
    archetype_issue = {
        "issue_id": "I1", "severity": "critical", "category": "archetype", "layer": "STORY",
        "problem": "explicit problem->fix chain suggests build",
        "why_it_matters": "x", "recommended_intent": "replan as build", "repair_owner": "story_lead",
    }

    agents = make_agents(
        story_lead_responses={
            StoryStructure: [make_structure(archetype="build")], BeatSceneExpansion: make_good_expansions(),
            "RevisionPlan": [RevisionPlan(run_id="r", story_replan_required=True)],
        },
        narration_responses=[make_empty_narration_response(), make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[archetype_issue]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=bad_plan,
    )

    a2_call = next(c for c in agents.story_lead.calls if c["pass_id"] == "A2")
    feedback = a2_call["payload"]["replan_feedback"]
    assert feedback["previous_archetype"] == "foundation"
    assert feedback["critique_issues"][0]["category"] == "archetype"
    assert feedback["critique_issues"][0]["recommended_intent"] == "replan as build"
    assert any(i["code"] == "word_budget_mismatch" for i in feedback["structural_issues"])


def test_source_units_reach_both_a2_replan_and_c1_critique():
    """Real gap found 2026-09-10: neither A2 nor C1 ever saw the source's
    real content (e.g. an author's own production notes) -- only A1's
    compressed brief. This proves the plumbing carries source_units through
    the orchestrator to both the A2 replan call and the C1 critique call."""
    from editing.models import RevisionPlan
    from facts.models import SourceUnit

    bad_plan = make_plan(scene_words=30, n_scenes=2)
    units = [SourceUnit(id="production_notes", heading="Production notes", text="Problem -> Mini payoff")]

    agents = make_agents(
        story_lead_responses={
            StoryStructure: [make_structure()], BeatSceneExpansion: make_good_expansions(),
            "RevisionPlan": [RevisionPlan(run_id="r", story_replan_required=True)],
        },
        narration_responses=[make_empty_narration_response(), make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(),
        source_units=units, initial_plan=bad_plan,
    )

    a2_call = next(c for c in agents.story_lead.calls if c["pass_id"] == "A2")
    assert a2_call["payload"]["source_units"][0]["id"] == "production_notes"

    c1_call = next(c for c in agents.review_lead.calls if c["pass_id"] == "C1")
    assert c1_call["payload"]["source_units"][0]["id"] == "production_notes"


def _make_plan_with_rejected_archetypes(rejected_archetypes: dict) -> StoryPlan:
    plan = make_plan()
    return plan.model_copy(update={"rejected_archetypes": rejected_archetypes})


def test_legitimate_dismissal_clears_the_only_hard_failure_to_pass():
    """ERR-025's fix: C1 disputing an archetype the plan's own
    rejected_archetypes ALREADY explicitly considered is not new evidence
    -- A3 may dismiss it, and if it was the only hard failure, the run
    should resolve to PASS without ever replanning."""
    from editing.models import DismissedIssue, RevisionPlan

    plan = _make_plan_with_rejected_archetypes({"derivation": "no justified equation found in the source"})
    archetype_issue = {
        "issue_id": "I1", "severity": "critical", "category": "archetype", "layer": "STORY",
        "problem": "the source actually shows a derivation, not a build arc",
        "why_it_matters": "x", "recommended_intent": "replan as derivation", "repair_owner": "story_lead",
    }
    agents = make_agents(
        story_lead_responses={
            "RevisionPlan": [RevisionPlan(
                run_id="r", story_replan_required=False,
                dismissed_issues=[DismissedIssue(issue_id="I1", reason="already ruled out: no justified equation found")],
            )],
        },
        narration_responses=[make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[archetype_issue])],
            "c2b": [GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    result = run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=plan,
    )

    assert result.final_status == "PASS"
    assert result.story_replans_used == 0  # dismissed, not replanned
    assert any("dismissed 1 critique issue" in line for line in result.log)
    # narration_lead only called once (B1) -- no B2/replan triggered by the dismissed issue
    assert len(agents.narration_lead.calls) == 1


def test_illegitimate_dismissal_naming_an_unconsidered_archetype_is_ignored():
    """The safety rail: A3 cannot dismiss a critique naming an archetype
    the plan never actually addressed in rejected_archetypes -- that
    would just be A3 (GPT) overruling C1 (Gemini) on its own say-so,
    defeating the point of an independent critic."""
    from editing.models import DismissedIssue, RevisionPlan

    plan = _make_plan_with_rejected_archetypes({"mystery": "no violated expectation found"})
    archetype_issue = {
        "issue_id": "I1", "severity": "critical", "category": "archetype", "layer": "STORY",
        "problem": "the source actually shows a derivation, not a build arc",  # "derivation" never considered
        "why_it_matters": "x", "recommended_intent": "replan as derivation", "repair_owner": "story_lead",
    }
    agents = make_agents(
        story_lead_responses={
            # Same shape as make_plan()'s known-clean fixture (not
            # "derivation") -- this test is only about the dismissal being
            # ignored, not about simulating a fully correct replan.
            StoryStructure: [make_structure()], BeatSceneExpansion: make_good_expansions(),
            "RevisionPlan": [RevisionPlan(
                run_id="r", story_replan_required=True,
                dismissed_issues=[DismissedIssue(issue_id="I1", reason="A3 just disagrees")],
            )],
        },
        narration_responses=[make_empty_narration_response(), make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[archetype_issue]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    result = run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=plan,
    )

    assert result.story_replans_used == 1  # the dismissal was ignored -- normal replan still happened
    assert any("without adequate grounds" in line for line in result.log)


def test_dismissal_leaves_other_hard_failures_intact():
    """A legitimate dismissal only removes ITS OWN hard-failure line --
    an unrelated structural failure must still force a replan."""
    from editing.models import DismissedIssue, RevisionPlan

    bad_plan = _make_plan_with_rejected_archetypes({"derivation": "no justified equation found"})
    bad_plan = bad_plan.model_copy(update={"scene_plan": [
        s.model_copy(update={"word_budget": 30}) for s in bad_plan.scene_plan[:2]
    ]})  # word_budget_mismatch: ~60 words vs ~1670 target
    archetype_issue = {
        "issue_id": "I1", "severity": "critical", "category": "archetype", "layer": "STORY",
        "problem": "the source actually shows a derivation, not a build arc",
        "why_it_matters": "x", "recommended_intent": "replan as derivation", "repair_owner": "story_lead",
    }
    agents = make_agents(
        story_lead_responses={
            StoryStructure: [make_structure()], BeatSceneExpansion: make_good_expansions(),
            "RevisionPlan": [RevisionPlan(
                run_id="r", story_replan_required=True,
                dismissed_issues=[DismissedIssue(issue_id="I1", reason="already ruled out: no justified equation found")],
            )],
        },
        narration_responses=[make_empty_narration_response(), make_empty_narration_response()],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[archetype_issue]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    result = run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=bad_plan,
    )

    assert any("dismissed 1 critique issue" in line for line in result.log)
    assert result.story_replans_used == 1  # the word_budget_mismatch still forced a replan
    assert result.final_status == "PASS"


def test_a_critical_non_archetype_issue_routes_to_targeted_rewrite_not_replan():
    """A critical issue that ISN'T structural (e.g. a grounding fidelity
    problem) should let A3 choose targeted rewrite over a full replan."""
    from editing.models import RewriteBeat, RevisionPlan

    plan = make_plan()
    critical_issue = {
        "issue_id": "I1", "severity": "critical", "category": "clarity", "layer": "TECHNICAL",
        "problem": "x", "why_it_matters": "y", "recommended_intent": "z", "repair_owner": "narration_lead",
    }
    agents = make_agents(
        story_lead_responses={
            "RevisionPlan": [RevisionPlan(run_id="r", story_replan_required=False,
                                            rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="y")])],
        },
        # Two narration_lead calls now happen: B1's initial draft, then B2's
        # targeted rewrite (real gap fixed 2026-09-10 -- TARGETED_REWRITE used
        # to be a no-op and never called narration_lead a second time at all).
        narration_responses=[make_empty_narration_response(), GeneratedNarration(scenes=[])],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[critical_issue]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    result = run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=plan,
    )
    assert result.final_status == "PASS"
    assert result.major_revisions_used == 1
    assert result.story_replans_used == 0  # replan was never triggered
    assert any("targeted rewrite" in line for line in result.log)


def test_targeted_rewrite_actually_calls_b2_with_the_named_beat_not_a_no_op():
    """Real gap found 2026-09-10: TARGETED_REWRITE used to just log the
    intent and re-verify the same narration -- narration_lead was never
    called a second time at all. This proves the second call actually
    happens and carries the named beat's scope."""
    from editing.models import RewriteBeat, RevisionPlan

    plan = make_plan()
    critical_issue = {
        "issue_id": "I1", "severity": "critical", "category": "clarity", "layer": "TECHNICAL",
        "problem": "x", "why_it_matters": "y", "recommended_intent": "z", "repair_owner": "narration_lead",
    }
    agents = make_agents(
        story_lead_responses={
            "RevisionPlan": [RevisionPlan(run_id="r", story_replan_required=False,
                                            rewrite_beats=[RewriteBeat(beat_id="B01", reason="x", intent="tighten it")])],
        },
        narration_responses=[make_empty_narration_response(), GeneratedNarration(scenes=[])],
        review_responses={
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
            "c1": [StoryCritique(issues=[critical_issue]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
        },
    )
    from planning.models import SourceBrief

    run_story_and_narration_loop(
        source_brief=SourceBrief(topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=plan,
    )

    b2_call = next(c for c in agents.narration_lead.calls if c["pass_id"] == "B2")
    assert b2_call["mode"] == "TARGETED_REWRITE"
    assert all("tighten it" == s["required_intent"] for s in b2_call["payload"]["scenes"])


def test_cold_hook_critic_receives_the_plans_title_and_first_beats_narration():
    """STORY_IMPROVEMENT_PLAN.md Phase 8.2: long-form now runs the same
    cold-hook cascade shorts already had -- confirms the real payload
    (title + first-beat narration/visual) actually reaches it."""
    plan = make_plan()
    agents = make_agents(
        narration_responses=[GeneratedNarration(scenes=[
            {"scene_id": "s0", "sentences": [{"text": "opening line", "sentence_type": "transition"}]},
        ])],
        review_responses={"c1": [StoryCritique(issues=[])], "c2b": [GroundingReview(issues=[])], "cm": [ClaimMapperOutput(sentences=[])]},
    )
    run_story_and_narration_loop(
        source_brief=__import__("planning.models", fromlist=["SourceBrief"]).SourceBrief(
            topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=plan,
    )

    assert len(agents.worker.calls) == 1
    payload = agents.worker.calls[0]["payload"]
    assert payload["title"] == "t"  # plan.title.chosen from make_plan()


def test_cold_hook_uses_c4a_c4b_pass_ids_not_the_shorts_c4s_default():
    plan = make_plan()
    flagged = ColdHookVerdict(clarity="confusing", flagged=True, confidence="high")
    agents = make_agents(
        narration_responses=[make_empty_narration_response()],
        review_responses={
            "c1": [StoryCritique(issues=[])], "c2b": [GroundingReview(issues=[])],
            "cold_hook": [ColdHookCritique(issues=[])], "cm": [ClaimMapperOutput(sentences=[])],
        },
        worker_responses=[flagged],
    )
    run_story_and_narration_loop(
        source_brief=__import__("planning.models", fromlist=["SourceBrief"]).SourceBrief(
            topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=plan,
    )

    assert agents.worker.calls[0]["pass_id"] == "C4a"
    cold_hook_call = next(c for c in agents.review_lead.calls if c["schema"] is ColdHookCritique)
    assert cold_hook_call["pass_id"] == "C4b"


def test_a_flagged_cold_hook_verdict_produces_a_real_issue_in_the_bundle():
    plan = make_plan()
    flagged = ColdHookVerdict(clarity="confusing", flagged=True, confidence="high")
    cold_hook_issue = {
        "issue_id": "ch1", "severity": "major", "category": "hook", "layer": "STORY",
        "problem": "generic opening, no curiosity gap", "why_it_matters": "loses cold viewers immediately",
        "recommended_intent": "open with a specific, concrete tension", "repair_owner": "story_lead",
    }
    agents = make_agents(
        narration_responses=[make_empty_narration_response(), GeneratedNarration(scenes=[])],
        review_responses={
            "c1": [StoryCritique(issues=[]), StoryCritique(issues=[])],
            "c2b": [GroundingReview(issues=[]), GroundingReview(issues=[])],
            "cold_hook": [ColdHookCritique(issues=[cold_hook_issue])],
            "cm": [ClaimMapperOutput(sentences=[]), ClaimMapperOutput(sentences=[])],
        },
        worker_responses=[flagged],
    )
    result = run_story_and_narration_loop(
        source_brief=__import__("planning.models", fromlist=["SourceBrief"]).SourceBrief(
            topic="t", core_question="q", viewer_problem="p", central_insight="i"),
        claims=[], ledger=AssumptionLedger(), all_source_unit_ids=["u1"],
        target_duration_seconds=600.0, agents=agents, budget=make_budget(), initial_plan=plan,
    )

    hook_issues = [i for i in result.review_bundle.issues if i.category == "hook"]
    assert len(hook_issues) == 1
    assert hook_issues[0].problem == "generic opening, no curiosity gap"
