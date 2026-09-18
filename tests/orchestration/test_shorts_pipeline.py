"""Tests for orchestration/shorts_pipeline.py -- the V1A-S short run (plan §20.7).

Gained a bounded, single-attempt targeted-rewrite cycle (B2s) 2026-09-15 -- see module
docstring for why. Uses a schema-dispatching FakeAgent, same pattern as the long-form
pipeline tests.
"""
import json

import pytest

from editing.short_targeted_rewrite import ShortTargetedRewrite
from narration.models import SceneNarration, SentenceNarration
from narration.short_generator import GeneratedShortNarration
from orchestration.shorts_pipeline import ShortRunResult, ShortsPipelineAgents, run_short, save_short_debug
from planning.shorts_models import HookEvent, ShortParent, ShortPlan
from review.claim_mapper import ClaimMapperOutput
from review.cold_hook_critic import ColdHookCritique, ColdHookVerdict
from review.grounding_verifier import GroundingReview
from review.short_critic import ShortCritique


class FakeAgent:
    def __init__(self, responses_by_schema: dict):
        self._queues = {k: list(v) for k, v in responses_by_schema.items()}
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["schema"]
        return self._queues[schema].pop(0)


def make_plan(**overrides) -> ShortPlan:
    base = dict(
        parent=ShortParent(run_id="r1", final_plan_hash="sha256:x", source_beat_ids=["B01"], allowed_fact_ids=["C001"]),
        title="Why attention needs scaling", central_insight="scaling keeps softmax stable",
        micro_arc="problem_fix",
        hook=HookEvent(narration="scores blow up without scaling", starts_at_seconds=1.0),
        payoff_central="scaling by sqrt(d_k) keeps attention scores stable",
    )
    base.update(overrides)
    return ShortPlan(**base)


def make_narration_response() -> GeneratedShortNarration:
    # "mechanism" padded to land the total within the 160-210 word advisory
    # band (raised 2026-09-16 alongside the 60s -> 120s duration cap) -- a
    # real fixture, not a diagnostic-triggering minimal stub, so "clean"
    # tests actually land on a clean PASS, not a word-count PASS_WARN.
    mechanism_text = " ".join(["word"] * 150)
    return GeneratedShortNarration(segments=[
        {"segment": "hook", "sentences": [{"text": "scores blow up without scaling", "sentence_type": "transition"}]},
        {"segment": "setup", "sentences": [{"text": "context sentence here", "sentence_type": "transition"}]},
        {"segment": "mechanism", "sentences": [{"text": mechanism_text, "sentence_type": "technical_assertion"}]},
        {"segment": "payoff", "sentences": [{"text": "scaling by sqrt(d_k) keeps scores stable", "sentence_type": "payoff"}]},
    ])


# make_narration_response()'s four segments, one sentence each -- Phase 10's coverage
# invariant means CM/C2b must return a verdict for every one of these by default, not an
# empty response, or every test using the default agents would raise ReviewCoverageError.
_DEFAULT_SEGMENT_IDS = ("hook", "setup", "mechanism", "payoff")


def _clean_cm_response() -> ClaimMapperOutput:
    return ClaimMapperOutput(sentences=[
        {"sentence_id": f"{seg}:0", "scene_id": seg, "sentence_index": 0, "factual_status": "NON_FACTUAL"}
        for seg in _DEFAULT_SEGMENT_IDS
    ])


def _clean_c2b_response() -> GroundingReview:
    return GroundingReview(verdicts=[{"sentence_id": f"{seg}:0", "factual": False} for seg in _DEFAULT_SEGMENT_IDS])


def make_agents(review_responses=None, cold_hook_haiku=None, rewrite_responses=None) -> ShortsPipelineAgents:
    responses = review_responses or {}
    # x2 defaults (2026-09-16, same reasoning as ColdHookVerdict below): a grounding-policy
    # violation is now a real critical CritiqueIssue (see shorts_pipeline.py's
    # `_grounding_violation_to_issue`), so any test with one now triggers a real
    # targeted-rewrite cycle -- a second clean response must be available for the
    # re-review, even for tests that never override these schemas themselves.
    review_agent = FakeAgent({
        ClaimMapperOutput: responses.get("cm", [_clean_cm_response()]),
        GroundingReview: responses.get("c2b", [_clean_c2b_response(), _clean_c2b_response()]),
        ShortCritique: responses.get("c1s", [ShortCritique(issues=[]), ShortCritique(issues=[])]),
        ColdHookCritique: responses.get("c4s_gemini", [ColdHookCritique(issues=[]), ColdHookCritique(issues=[])]),
    })
    clean_cold_hook = cold_hook_haiku or ColdHookVerdict(flagged=False, confidence="high")
    worker = FakeAgent({
        GeneratedShortNarration: [make_narration_response()],
        # x2 (2026-09-15): a targeted-rewrite cycle re-runs the full review block,
        # including C4s -- tests exercising a rewrite need a second response available.
        ColdHookVerdict: [clean_cold_hook, clean_cold_hook],
    })
    narration_lead_schemas = {GeneratedShortNarration: [make_narration_response()]}
    if rewrite_responses is not None:
        narration_lead_schemas[ShortTargetedRewrite] = rewrite_responses
    narration_lead = FakeAgent(narration_lead_schemas)
    return ShortsPipelineAgents(narration_lead=narration_lead, worker=worker, review_agent=review_agent)


def make_budget():
    from llm.budget import BudgetCounter, DEFAULT_TIERS
    return BudgetCounter(tier=DEFAULT_TIERS["short"])


def test_a_clean_short_passes():
    agents = make_agents()
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    assert result.final_status == "PASS"
    assert result.hard_failures == []


def test_missing_parent_reference_fails():
    agents = make_agents()
    result = run_short(make_plan(parent=None), [], agents, make_budget(), require_parent=True, enable_tts_preview=False)
    assert result.final_status == "FAIL"
    assert any("missing_parent_reference" in f for f in result.hard_failures)


def test_missing_parent_is_fine_for_a_standalone_short():
    agents = make_agents()
    result = run_short(make_plan(parent=None), [], agents, make_budget(), require_parent=False, enable_tts_preview=False)
    assert result.final_status == "PASS"


def test_critical_micro_arc_issue_becomes_a_hard_failure():
    critical_issue = {
        "issue_id": "I1", "severity": "critical", "category": "micro_arc", "layer": "STORY",
        "problem": "no real fix shown", "why_it_matters": "x", "recommended_intent": "add the fix",
        "repair_owner": "story_lead",
    }
    agents = make_agents(review_responses={"c1s": [ShortCritique(issues=[critical_issue])]})
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    assert result.final_status == "FAIL"
    assert any("micro_arc" in f for f in result.hard_failures)


def _critical_issue(scene_ids, intent="fix it", issue_id="I1", category="ending"):
    return {
        "issue_id": issue_id, "severity": "critical", "category": category, "layer": "NARRATION",
        "problem": "x", "why_it_matters": "y", "recommended_intent": intent,
        "repair_owner": "narration_lead", "scene_ids": scene_ids,
    }


def make_rewrite_response(segment="payoff", text="a genuinely new closing line") -> ShortTargetedRewrite:
    return ShortTargetedRewrite(segments=[{"segment": segment, "sentences": [{"text": text, "sentence_type": "payoff"}]}])


def test_a_critical_issue_with_scene_ids_triggers_exactly_one_targeted_rewrite():
    """2026-09-15: the bounded B2s revision cycle -- a critical issue naming a real
    scene_id must trigger exactly one targeted rewrite attempt, and a clean re-review
    afterward must land on PASS with the rewrite counted."""
    agents = make_agents(
        review_responses={
            "c1s": [ShortCritique(issues=[_critical_issue(["payoff"])]), ShortCritique(issues=[])],
            "cm": [_clean_cm_response(), _clean_cm_response()],
            "c2b": [_clean_c2b_response(), _clean_c2b_response()],
        },
        rewrite_responses=[make_rewrite_response()],
    )
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)

    assert result.revisions_used == 1
    assert result.final_status == "PASS"
    rewrite_call = next(c for c in agents.narration_lead.calls if c["pass_id"] == "B2s")
    touched = rewrite_call["payload"]["segments_to_rewrite"]
    assert len(touched) == 1
    assert touched[0]["segment"] == "payoff"
    assert touched[0]["problems_to_fix"] == ["fix it"]
    rewritten_payoff = next(s for s in result.narration if s.scene_id == "payoff")
    assert rewritten_payoff.sentences[0].text == "a genuinely new closing line"


def test_an_issue_with_no_scene_ids_cannot_trigger_a_rewrite():
    """review/short_critic.py's own prompt now requires scene_ids -- but a response
    that still omits them (schema default []) must be a no-op, not a crash, and must
    not spend a revision attempt on nothing actionable."""
    agents = make_agents(review_responses={"c1s": [ShortCritique(issues=[_critical_issue([])])]})
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)

    assert result.revisions_used == 0
    assert result.final_status == "FAIL"
    assert not any(c["pass_id"] == "B2s" for c in agents.narration_lead.calls)


def make_overlong_narration_response() -> GeneratedShortNarration:
    """~350 words total (well over MAX_SHORT_SECONDS=122s at PLANNING_WPM=130) -- all in
    `mechanism` so it's unambiguously the longest segment."""
    mechanism_text = " ".join(["word"] * 330)
    return GeneratedShortNarration(segments=[
        {"segment": "hook", "sentences": [{"text": "scores blow up without scaling", "sentence_type": "transition"}]},
        {"segment": "setup", "sentences": [{"text": "context sentence here", "sentence_type": "transition"}]},
        {"segment": "mechanism", "sentences": [{"text": mechanism_text, "sentence_type": "technical_assertion"}]},
        {"segment": "payoff", "sentences": [{"text": "scaling by sqrt(d_k) keeps scores stable", "sentence_type": "payoff"}]},
    ])


def test_a_duration_overrun_now_triggers_a_targeted_rewrite():
    """PIPELINE_AUDIT_2026-09-17.md finding #4: before this fix, a short that passed every
    critic cleanly but simply ran too long could never attempt a rewrite at all -- none of
    check_short_structure's ShortHardIssues ever reached the B2s trigger. duration_estimate_
    exceeds_max is now converted into a rewritable CritiqueIssue targeting the longest
    segment (mechanism, here), same as a real critique issue would."""
    agents = make_agents(
        review_responses={"cm": [_clean_cm_response(), _clean_cm_response()], "c2b": [_clean_c2b_response(), _clean_c2b_response()]},
        rewrite_responses=[make_rewrite_response(segment="mechanism", text="a much shorter fix")],
    )
    agents.narration_lead._queues[GeneratedShortNarration] = [make_overlong_narration_response()]

    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)

    assert result.revisions_used == 1
    rewrite_call = next(c for c in agents.narration_lead.calls if c["pass_id"] == "B2s")
    touched = rewrite_call["payload"]["segments_to_rewrite"]
    assert len(touched) == 1
    assert touched[0]["segment"] == "mechanism"
    # the duration failure is still reported once (from `hard`, not double-counted via
    # the converted CritiqueIssue also landing in `critique_issues`)
    assert sum("duration_estimate_exceeds_max" in f for f in result.hard_failures) <= 1


def test_a_plan_level_hard_issue_never_triggers_a_rewrite():
    """title_hook_mismatch/title_payoff_mismatch/no_central_insight/missing_parent_reference
    are PLAN-level defects -- no narration rewrite can fix a bad title or a missing parent,
    so these must never be converted into a rewrite target (PIPELINE_AUDIT_2026-09-17.md
    finding #4's own scope: only rewritable_hard_codes are eligible)."""
    agents = make_agents()
    result = run_short(make_plan(parent=None), [], agents, make_budget(), require_parent=True, enable_tts_preview=False)

    assert result.final_status == "FAIL"
    assert any("missing_parent_reference" in f for f in result.hard_failures)
    assert not any(c["pass_id"] == "B2s" for c in agents.narration_lead.calls)


def test_no_critical_issues_means_no_rewrite_is_attempted():
    agents = make_agents()  # default: clean c1s response
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)

    assert result.revisions_used == 0
    assert not any(c["pass_id"] == "B2s" for c in agents.narration_lead.calls)


def test_a_rewrite_that_makes_things_worse_is_reverted_but_still_counts_as_used():
    """Mirrors orchestration/pipeline.py's own long-form precedent (Phase 8.5): a
    rewrite that regresses must not become the accepted state, but the attempt itself
    still consumes the bounded budget -- it was tried, not skipped."""
    worse_issue = _critical_issue(["payoff"], intent="fix it", issue_id="I1")
    even_worse = [worse_issue, _critical_issue(["mechanism"], intent="also fix this", issue_id="I2")]
    agents = make_agents(
        review_responses={
            "c1s": [ShortCritique(issues=[worse_issue]), ShortCritique(issues=even_worse)],
            "cm": [_clean_cm_response(), _clean_cm_response()],
            "c2b": [_clean_c2b_response(), _clean_c2b_response()],
        },
        rewrite_responses=[make_rewrite_response()],
    )
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)

    assert result.revisions_used == 1
    assert any("also fix this" not in f for f in result.hard_failures)  # kept the ORIGINAL (1-issue) failures
    assert sum("critical/ending" in f for f in result.hard_failures) == 1  # not the 2-issue rewritten version
    # the narration itself is the ORIGINAL, not the (reverted) rewritten text
    payoff = next(s for s in result.narration if s.scene_id == "payoff")
    assert payoff.sentences[0].text == "scaling by sqrt(d_k) keeps scores stable"


def test_a_second_revision_is_never_attempted_even_if_still_failing():
    """MAX_SHORT_REVISIONS=1 -- bounded, not a loop until clean."""
    agents = make_agents(
        review_responses={
            "c1s": [ShortCritique(issues=[_critical_issue(["payoff"])])] * 2,
            "cm": [_clean_cm_response(), _clean_cm_response()],
            "c2b": [_clean_c2b_response(), _clean_c2b_response()],
        },
        rewrite_responses=[make_rewrite_response()],
    )
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)

    assert result.revisions_used == 1
    assert result.final_status == "FAIL"  # still failing after the one bounded attempt
    assert sum(1 for c in agents.narration_lead.calls if c["pass_id"] == "B2s") == 1


def test_the_plans_own_bridge_mode_reaches_c1s():
    """2026-09-15: confirmed live -- 5 of 5 real shorts got a critical RESERVED_OUTRO
    finding even when bridge.mode=SPOKEN correctly required the follow-up line
    narration/short_generator.py's own prompt added. C1s never received bridge_mode at
    all before this fix, so it couldn't tell a required line from an unprompted one."""
    from planning.shorts_models import ShortBridge

    agents = make_agents()
    run_short(make_plan(bridge=ShortBridge(mode="SPOKEN")), [], agents, make_budget(), enable_tts_preview=False)
    c1s_call = next(c for c in agents.review_agent.calls if c["pass_id"] == "C1s")
    assert c1s_call["payload"]["bridge_mode"] == "SPOKEN"


def test_major_cold_hook_issue_does_not_force_a_hard_failure():
    """Cold-hook findings are feedback, not a mechanical hard gate (plan §20.10's
    hard list never mentions cold-hook strength)."""
    agents = make_agents(
        cold_hook_haiku=ColdHookVerdict(flagged=True, confidence="high"),
        review_responses={"c4s_gemini": [ColdHookCritique(issues=[{
            "issue_id": "I1", "severity": "major", "category": "hook", "layer": "STORY",
            "problem": "generic opening", "why_it_matters": "x", "recommended_intent": "make it specific",
            "repair_owner": "story_lead",
        }])]},
    )
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    assert result.final_status == "PASS"
    assert len(result.issues) == 1


def test_clean_cold_hook_never_escalates():
    agents = make_agents(cold_hook_haiku=ColdHookVerdict(flagged=False, confidence="high"))
    run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    # ColdHookCritique schema registered but never popped -- confirms no escalation call
    # happened. x2 in the queue (2026-09-16) is just the default's own rewrite-cycle
    # headroom (see make_agents) -- what matters here is neither entry was consumed.
    assert agents.review_agent._queues[ColdHookCritique] == [ColdHookCritique(issues=[]), ColdHookCritique(issues=[])]


def test_grounding_scope_violation_is_a_hard_failure():
    cm_response = ClaimMapperOutput(sentences=[
        {"sentence_id": f"{seg}:0", "scene_id": seg, "sentence_index": 0, "factual_status": "NON_FACTUAL"}
        for seg in _DEFAULT_SEGMENT_IDS if seg != "payoff"
    ] + [
        {"sentence_id": "payoff:0", "scene_id": "payoff", "sentence_index": 0,
         "factual_status": "FACTUAL", "grounding_refs": ["C999"]},
    ])
    # 2026-09-16: a grounding violation (here: an unknown claim id) is now a real critical
    # CritiqueIssue, so this triggers a real targeted-rewrite cycle -- a second cm response
    # and a (no-op) rewrite response are both needed for the re-review to complete.
    agents = make_agents(
        review_responses={"cm": [cm_response, cm_response]},
        rewrite_responses=[ShortTargetedRewrite(segments=[])],
    )
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    assert result.final_status == "FAIL"
    assert any("claim_outside_allowed_fact_set" in f for f in result.hard_failures)


def test_an_ungrounded_factual_sentence_is_a_hard_failure():
    """2026-09-16: confirmed as a real, undocumented gap -- long-form's own
    `_run_review_block` has always run `check_grounding_policy`, but shorts never did,
    so a sentence CM marked FACTUAL with no grounding_refs at all (a deterministic,
    self-consistency defect the pipeline is supposed to always catch) previously sailed
    through completely unchecked for shorts."""
    cm_response = ClaimMapperOutput(sentences=[
        {"sentence_id": f"{seg}:0", "scene_id": seg, "sentence_index": 0, "factual_status": "NON_FACTUAL"}
        for seg in _DEFAULT_SEGMENT_IDS if seg != "payoff"
    ] + [
        # FACTUAL but no grounding_refs at all -- the exact defect check_grounding_policy exists for.
        {"sentence_id": "payoff:0", "scene_id": "payoff", "sentence_index": 0,
         "factual_status": "FACTUAL", "grounding_refs": []},
    ])
    # x2 + a no-op rewrite response: this is now a critical CritiqueIssue (2026-09-16),
    # which triggers a real targeted-rewrite cycle and its own re-review.
    agents = make_agents(
        review_responses={"cm": [cm_response, cm_response]},
        rewrite_responses=[ShortTargetedRewrite(segments=[])],
    )
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    assert result.final_status == "FAIL"
    assert any("ungrounded_factual_sentence" in f for f in result.hard_failures)
    # The whole point of this fix: this defect must now actually reach the rewrite mechanism.
    assert result.revisions_used == 1


def test_a_drifted_number_against_the_cited_claim_is_a_hard_failure():
    """2026-09-16: same gap as above -- check_numeric_fidelity (a claim says one
    number, the narration cites the same claim but states a different one) was never
    run for shorts either."""
    from facts.models import Claim

    claims = [Claim(
        claim_id="C001", source_unit="u1", claim="scaling divides by 128 dimensions", type="mechanism",
        numbers=["128"], verification_status="VERIFIED",
    )]
    narration_lead = FakeAgent({
        GeneratedShortNarration: [GeneratedShortNarration(segments=[
            {"segment": "hook", "sentences": [{"text": "x", "sentence_type": "transition"}]},
            {"segment": "setup", "sentences": [{"text": "x", "sentence_type": "transition"}]},
            {"segment": "mechanism", "sentences": [
                {"text": "We divide by 256 dimensions to keep the scores stable.", "sentence_type": "technical_assertion", "claim_refs": ["C001"]},
            ]},
            {"segment": "payoff", "sentences": [{"text": "x", "sentence_type": "payoff"}]},
        ])],
        # 2026-09-16: numeric_drift is now a critical CritiqueIssue, triggering a real
        # targeted-rewrite cycle -- a (no-op) rewrite response is needed to complete it.
        ShortTargetedRewrite: [ShortTargetedRewrite(segments=[])],
    })
    cm_response = ClaimMapperOutput(sentences=[
        {"sentence_id": f"{seg}:0", "scene_id": seg, "sentence_index": 0, "factual_status": "NON_FACTUAL"}
        for seg in _DEFAULT_SEGMENT_IDS if seg != "mechanism"
    ] + [
        {"sentence_id": "mechanism:0", "scene_id": "mechanism", "sentence_index": 0,
         "factual_status": "FACTUAL", "grounding_refs": ["C001"]},
    ])
    agents = make_agents(review_responses={"cm": [cm_response, cm_response]})
    agents.narration_lead = narration_lead

    result = run_short(make_plan(), claims, agents, make_budget(), enable_tts_preview=False)

    assert result.final_status == "FAIL"
    assert any("numeric_drift" in f for f in result.hard_failures)


def test_an_unverified_claim_in_the_hook_is_a_hard_failure_even_with_a_hedge():
    """2026-09-16, found on a further review round: `check_grounding_policy`'s own
    `hook_scene_ids`/`ending_scene_ids` params were left at their empty defaults here,
    silently disabling its "UNVERIFIED never in the hook / ... / the ending" rule --
    confirmed the exact same gap exists in both of long-form's own call sites too,
    so this was inherited, not a shorts-specific oversight. An OPTIONAL-importance
    UNVERIFIED claim WITH a hedge is otherwise allowed to be narrated
    (`_claim_allows_narration`) -- but never in the hook or the ending, hedge or not."""
    from facts.models import Claim

    claims = [Claim(
        claim_id="C001", source_unit="u1", claim="scaling roughly follows sqrt(d_k)",
        type="mechanism", importance="OPTIONAL", verification_status="UNVERIFIED",
    )]
    narration_lead = FakeAgent({
        GeneratedShortNarration: [GeneratedShortNarration(segments=[
            {"segment": "hook", "sentences": [
                {"text": "Scores roughly blow up without scaling.", "sentence_type": "transition", "claim_refs": ["C001"]},
            ]},
            {"segment": "setup", "sentences": [{"text": "x", "sentence_type": "transition"}]},
            {"segment": "mechanism", "sentences": [{"text": "x", "sentence_type": "transition"}]},
            {"segment": "payoff", "sentences": [{"text": "x", "sentence_type": "payoff"}]},
        ])],
        # 2026-09-16: unverified_in_hook_or_ending is now a critical CritiqueIssue,
        # triggering a real targeted-rewrite cycle -- a (no-op) rewrite response is
        # needed to complete it.
        ShortTargetedRewrite: [ShortTargetedRewrite(segments=[])],
    })
    cm_response = ClaimMapperOutput(sentences=[
        {"sentence_id": f"{seg}:0", "scene_id": seg, "sentence_index": 0, "factual_status": "NON_FACTUAL"}
        for seg in _DEFAULT_SEGMENT_IDS if seg != "hook"
    ] + [
        {"sentence_id": "hook:0", "scene_id": "hook", "sentence_index": 0,
         "factual_status": "FACTUAL", "grounding_refs": ["C001"]},
    ])
    agents = make_agents(review_responses={"cm": [cm_response, cm_response]})
    agents.narration_lead = narration_lead

    result = run_short(make_plan(), claims, agents, make_budget(), enable_tts_preview=False)

    assert result.final_status == "FAIL"
    assert any("unverified_in_hook_or_ending" in f for f in result.hard_failures)


def test_cm_and_c2b_never_see_a_claim_outside_the_allowed_scope():
    """Real gap found live (2026-09-10): CM was given the FULL claim
    registry, so it could (and did) ground a sentence to a real, correctly-
    classified claim that simply happened to sit outside this short's
    allowed_fact_ids. Fixed by scoping claims BEFORE they ever reach CM/C2b,
    not just detecting the violation after the fact."""
    from facts.models import Claim

    agents = make_agents()
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="in scope", type="mechanism"),
        Claim(claim_id="C999", source_unit="u9", claim="out of scope", type="mechanism"),
    ]
    run_short(make_plan(), claims, agents, make_budget(), enable_tts_preview=False)  # parent.allowed_fact_ids == ["C001"]

    cm_call = agents.review_agent.calls[0]  # CM is always the first review_agent call
    offered_ids = {c["claim_id"] for c in cm_call["payload"]["claim_registry"]}
    assert offered_ids == {"C001"}


def test_enable_tts_preview_false_is_an_explicit_opt_out_not_a_degradation():
    agents = make_agents()
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=False)
    assert result.degraded_capabilities == []
    assert result.measured_duration_seconds is None
    assert result.preview_audio is None


def test_a_successful_tts_synthesis_is_used_for_the_duration_gate_not_the_estimate(monkeypatch):
    from voice.tts_preview import TtsPreviewResult

    def fake_synthesize(text, voice=None):
        return TtsPreviewResult(audio_bytes=b"fake-mp3-bytes", measured_duration_seconds=42.0)

    import voice.tts_preview as tts_preview_module
    monkeypatch.setattr(tts_preview_module, "synthesize_narration_preview", fake_synthesize)

    agents = make_agents()
    result = run_short(make_plan(), [], agents, make_budget())

    assert result.measured_duration_seconds == 42.0
    assert result.preview_audio == b"fake-mp3-bytes"
    assert result.degraded_capabilities == []


def test_a_tts_synthesis_failure_degrades_visibly_and_falls_back_to_the_estimate(monkeypatch):
    """A real network/service failure must never crash the run -- it
    degrades visibly (recorded, caps status at PASS_WARN) and falls back
    to the WPM estimate for the duration gate."""
    import voice.tts_preview as tts_preview_module

    def failing_synthesize(text, voice=None):
        raise RuntimeError("simulated: edge-tts service unreachable")

    monkeypatch.setattr(tts_preview_module, "synthesize_narration_preview", failing_synthesize)

    agents = make_agents()
    result = run_short(make_plan(), [], agents, make_budget())

    assert result.measured_duration_seconds is None
    assert result.preview_audio is None
    assert any("synthesis failed" in d for d in result.degraded_capabilities)
    assert result.final_status != "PASS"  # degraded caps at PASS_WARN at best
    # 2026-09-16, found on a live verification run: `degraded_capabilities` silently
    # forced a real short's final_status to PASS_WARN with NOTHING in `result.log` (or,
    # before this fix, in the persisted status.json either) explaining why -- a short
    # that looked like a clean pass except for one AMBER diagnostic was actually PASS_WARN
    # only because TTS synthesis failed and the real duration was never measured.
    assert any("degraded" in line and "synthesis failed" in line for line in result.log)


def test_save_short_debug_writes_status_regardless_of_pass_or_fail(tmp_path):
    """2026-09-15: a real gap -- a FAILed short's own hard_failures/issues/log used to
    exist only in a stdout log line, gone once the process exited. Unlike
    final/shorts/<i>/ (promotion-only), this must be written for every short."""
    from review.models import CritiqueIssue, DiagnosticResult

    result = ShortRunResult(
        plan=make_plan(), narration=[],
        hard_failures=["ungrounded_factual_sentence (s1): x"],
        issues=[CritiqueIssue(
            issue_id="c1s_1", severity="critical", category="micro_arc", layer="STORY",
            problem="x", why_it_matters="y", recommended_intent="z", repair_owner="narration_lead",
        )],
        diagnostics=[DiagnosticResult(dimension="hook_event_latency", band="RED", evidence="4.2s > 3s")],
        final_status="FAIL", log=["A2s: 1 candidate selected", "review: 1 hard failure"],
        degraded_capabilities=["tts_preview: synthesis failed (simulated)"],
    )

    save_short_debug(result, 1, tmp_path)

    status_path = tmp_path / "shorts" / "1" / "status.json"
    assert status_path.exists()
    saved = json.loads(status_path.read_text())
    assert saved["final_status"] == "FAIL"
    assert saved["hard_failures"] == ["ungrounded_factual_sentence (s1): x"]
    assert saved["issues"][0]["issue_id"] == "c1s_1"
    assert saved["diagnostics"][0]["dimension"] == "hook_event_latency"
    assert saved["log"] == ["A2s: 1 candidate selected", "review: 1 hard failure"]
    # 2026-09-16, found on a live verification run: `degraded_capabilities` was computed
    # and could silently force PASS_WARN, but was never persisted here -- a short's own
    # status.json could show PASS_WARN with no critical issues and no RED/AMBER diagnostic
    # explaining it, because the actual reason (a failed TTS measurement) was invisible.
    assert saved["degraded_capabilities"] == ["tts_preview: synthesis failed (simulated)"]


def test_save_short_debug_uses_the_given_index_for_multiple_shorts(tmp_path):
    result = ShortRunResult(
        plan=make_plan(), narration=[], hard_failures=[], issues=[], diagnostics=[], final_status="PASS",
    )
    save_short_debug(result, 3, tmp_path)
    assert (tmp_path / "shorts" / "3" / "status.json").exists()
    assert not (tmp_path / "shorts" / "1" / "status.json").exists()


def test_save_short_debug_writes_html_plan_and_narration_regardless_of_overall_run_status(tmp_path):
    """2026-09-15: confirmed live -- a short can individually PASS_WARN with zero hard
    failures, yet final/shorts/<i>/ (gated on the OVERALL run's combined status, not
    this short's own) never gets written when the unrelated parent long-form run
    FAILed -- so a genuinely passing short was never visible anywhere on disk. These
    files must exist unconditionally, the same way status.json already does."""
    plan = make_plan(title="Why scaling matters")
    narration = [SceneNarration(scene_id="hook", sentences=[SentenceNarration(text="x", sentence_type="transition")])]
    result = ShortRunResult(
        plan=plan, narration=narration, hard_failures=[], issues=[], diagnostics=[], final_status="PASS_WARN",
    )

    save_short_debug(result, 2, tmp_path, short_html="<html>the actual short</html>")

    short_dir = tmp_path / "shorts" / "2"
    assert (short_dir / "short.html").read_text() == "<html>the actual short</html>"
    assert json.loads((short_dir / "plan.json").read_text())["title"] == "Why scaling matters"
    assert json.loads((short_dir / "narration.json").read_text())[0]["scene_id"] == "hook"


def test_major_issue_count_counts_only_major_severity():
    """2026-09-17: parity fix for orchestration/pipeline.py's own `_major_issue_count`
    (Phase 27 item 3) -- shorts share the same CritiqueIssue.severity taxonomy and could
    accrue uncorrected major issues the same way long-form can, but had zero log visibility."""
    from orchestration.shorts_pipeline import _major_issue_count
    from review.models import CritiqueIssue

    def issue(severity, issue_id):
        return CritiqueIssue(
            issue_id=issue_id, severity=severity, category="repetition", layer="VOICE",
            problem="x", why_it_matters="y", recommended_intent="z", repair_owner="narration_lead",
        )

    issues = [issue("major", "i1"), issue("minor", "i2"), issue("major", "i3"), issue("critical", "i4")]
    assert _major_issue_count(issues) == 2


def test_save_short_debug_skips_the_html_file_when_none_given(tmp_path):
    result = ShortRunResult(
        plan=make_plan(), narration=[], hard_failures=[], issues=[], diagnostics=[], final_status="PASS",
    )

    save_short_debug(result, 1, tmp_path)

    assert not (tmp_path / "shorts" / "1" / "short.html").exists()


@pytest.mark.integration
def test_live_tts_preview_produces_real_audio_and_a_measured_duration():
    """The one real end-to-end check: a real short run with the real
    edge-tts call enabled, confirming actual audio and a plausible
    measured duration come back (not just that the wiring calls a mock)."""
    agents = make_agents()
    result = run_short(make_plan(), [], agents, make_budget(), enable_tts_preview=True)

    assert result.degraded_capabilities == []
    assert result.preview_audio is not None
    assert len(result.preview_audio) > 1000
    assert result.measured_duration_seconds is not None
    assert result.measured_duration_seconds > 0
