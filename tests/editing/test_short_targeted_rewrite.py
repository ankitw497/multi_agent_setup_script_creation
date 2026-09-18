"""Tests for editing/short_targeted_rewrite.py -- B2s (2026-09-15).

Mirrors editing/test_targeted_rewrite.py's own scoping-contract tests (long-form's B2),
scaled down for a short's 4 fixed segments and single-issue-list input (no RevisionPlan --
review/short_critic.py's own CritiqueIssue.scene_ids/recommended_intent already is the plan).
"""
from editing.short_targeted_rewrite import ShortTargetedRewrite, apply_short_targeted_rewrite
from narration.models import SceneNarration, SentenceNarration
from planning.shorts_models import HookEvent, ShortBridge, ShortParent, ShortPlan
from review.models import CritiqueIssue


class FakeNarrationLead:
    def __init__(self, response: ShortTargetedRewrite):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_plan(**overrides) -> ShortPlan:
    base = dict(
        parent=ShortParent(run_id="r1", final_plan_hash="sha256:x", source_beat_ids=["B01"], allowed_fact_ids=["C001"]),
        title="Why scaling matters", central_insight="scaling keeps softmax stable",
        micro_arc="problem_fix", hook=HookEvent(narration="scores blow up", starts_at_seconds=1.0),
        payoff_central="scaling fixes it", bridge=ShortBridge(mode="NONE"),
    )
    base.update(overrides)
    return ShortPlan(**base)


def make_narration() -> list[SceneNarration]:
    return [
        SceneNarration(scene_id="hook", sentences=[SentenceNarration(text="hook text", sentence_type="transition")]),
        SceneNarration(scene_id="setup", sentences=[SentenceNarration(text="setup text", sentence_type="transition")]),
        SceneNarration(scene_id="mechanism", sentences=[SentenceNarration(text="mechanism text", sentence_type="technical_assertion")]),
        SceneNarration(scene_id="payoff", sentences=[SentenceNarration(text="payoff text", sentence_type="payoff")]),
    ]


def make_issue(scene_ids, intent="fix it", issue_id="I1", category="ending") -> CritiqueIssue:
    return CritiqueIssue(
        issue_id=issue_id, severity="critical", category=category, layer="NARRATION",
        problem="x", why_it_matters="y", recommended_intent=intent, repair_owner="narration_lead",
        scene_ids=scene_ids,
    )


def test_no_critical_issues_returns_narration_completely_unchanged():
    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[]))
    result = apply_short_targeted_rewrite(make_plan(), make_narration(), [], [], narration_lead)
    assert result == make_narration()
    assert narration_lead.calls == []


def test_an_issue_with_no_scene_ids_is_a_no_op():
    """review/short_critic.py's own prompt now requires scene_ids -- but a response
    that still omits them (schema default []) must not crash or make a wasted call."""
    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[]))
    issues = [make_issue(scene_ids=[])]
    result = apply_short_targeted_rewrite(make_plan(), make_narration(), [], issues, narration_lead)
    assert result == make_narration()
    assert narration_lead.calls == []


def test_duplicate_scene_ids_in_narration_are_a_no_op_not_a_silent_collision():
    """2026-09-17 (found on review): scene_by_id/rewritten_by_id are both keyed purely by
    scene_id -- if narration already has a duplicate (the exact malformed shape
    verification/hard/shorts.py::check_segment_completeness flags as a non-rewritable hard
    failure) and a critical issue independently names that same segment, this used to proceed
    anyway: the rewrite prompt silently lost one duplicate's content, and the merge loop
    overwrote BOTH duplicates with identical text, leaving the real duplicate-segment defect
    in place while claiming to have fixed the named issue. Must bail out instead."""
    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[
        {"segment": "mechanism", "sentences": [{"text": "new mechanism", "sentence_type": "technical_assertion"}]},
    ]))
    duplicated = make_narration() + [
        SceneNarration(scene_id="mechanism", sentences=[SentenceNarration(text="second mechanism", sentence_type="technical_assertion")]),
    ]
    issues = [make_issue(scene_ids=["mechanism"])]
    result = apply_short_targeted_rewrite(make_plan(), duplicated, [], issues, narration_lead)
    assert result == duplicated
    assert narration_lead.calls == []


def test_only_the_named_segment_is_sent_for_rewrite():
    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[
        {"segment": "payoff", "sentences": [{"text": "new payoff", "sentence_type": "payoff"}]},
    ]))
    issues = [make_issue(scene_ids=["payoff"], intent="stop repeating the mechanism's line")]

    apply_short_targeted_rewrite(make_plan(), make_narration(), [], issues, narration_lead)

    payload = narration_lead.calls[0]["payload"]
    touched = {s["segment"] for s in payload["segments_to_rewrite"]}
    assert touched == {"payoff"}
    payoff_payload = payload["segments_to_rewrite"][0]
    assert payoff_payload["problems_to_fix"] == ["stop repeating the mechanism's line"]
    neighbor_ids = {s["segment"] for s in payload["untouched_neighbor_segments"]}
    assert neighbor_ids == {"hook", "setup", "mechanism"}


def test_an_extra_segment_the_model_returned_but_was_never_requested_is_ignored():
    """PIPELINE_AUDIT_2026-09-17.md finding: this module's own docstring/prompt promise
    "Rewrite ONLY the segments listed... do not touch any segment not listed" was never
    actually enforced in code -- the merge applied whatever the model returned
    unconditionally. If the model "helpfully" also rewrites mechanism when only payoff was
    requested, that extra rewrite must be silently discarded, not applied."""
    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[
        {"segment": "payoff", "sentences": [{"text": "new payoff", "sentence_type": "payoff"}]},
        {"segment": "mechanism", "sentences": [{"text": "an uninvited rewrite", "sentence_type": "technical_assertion"}]},
    ]))
    original = make_narration()
    issues = [make_issue(scene_ids=["payoff"])]  # only payoff was ever requested

    result = apply_short_targeted_rewrite(make_plan(), original, [], issues, narration_lead)

    result_by_id = {s.scene_id: s for s in result}
    assert result_by_id["payoff"].sentences[0].text == "new payoff"  # the requested rewrite still applies
    assert result_by_id["mechanism"] == original[2]  # the uninvited one is discarded, untouched byte-for-byte


def test_untouched_segments_survive_byte_for_byte():
    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[
        {"segment": "payoff", "sentences": [{"text": "new payoff", "sentence_type": "payoff"}]},
    ]))
    original = make_narration()
    issues = [make_issue(scene_ids=["payoff"])]

    result = apply_short_targeted_rewrite(make_plan(), original, [], issues, narration_lead)

    result_by_id = {s.scene_id: s for s in result}
    assert result_by_id["hook"] == original[0]
    assert result_by_id["setup"] == original[1]
    assert result_by_id["mechanism"] == original[2]
    assert result_by_id["payoff"].sentences[0].text == "new payoff"


def test_multiple_issues_on_the_same_segment_combine_into_one_problems_list():
    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[]))
    issues = [
        make_issue(scene_ids=["setup"], intent="add the naive attempt", issue_id="I1"),
        make_issue(scene_ids=["setup"], intent="tighten to under 10 seconds", issue_id="I2"),
    ]

    apply_short_targeted_rewrite(make_plan(), make_narration(), [], issues, narration_lead)

    payload_scene = narration_lead.calls[0]["payload"]["segments_to_rewrite"][0]
    assert payload_scene["problems_to_fix"] == ["add the naive attempt", "tighten to under 10 seconds"]


def test_an_issue_naming_multiple_segments_touches_all_of_them():
    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[]))
    issues = [make_issue(scene_ids=["setup", "mechanism"], intent="split the two mechanisms apart")]

    apply_short_targeted_rewrite(make_plan(), make_narration(), [], issues, narration_lead)

    touched = {s["segment"] for s in narration_lead.calls[0]["payload"]["segments_to_rewrite"]}
    assert touched == {"setup", "mechanism"}


def test_a_segment_named_that_doesnt_exist_in_narration_is_skipped_gracefully():
    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[]))
    issues = [make_issue(scene_ids=["nonexistent_segment"])]

    result = apply_short_targeted_rewrite(make_plan(), make_narration(), [], issues, narration_lead)

    assert result == make_narration()
    assert narration_lead.calls == []


def test_uses_pass_id_b2s_and_short_targeted_rewrite_mode():
    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[]))
    issues = [make_issue(scene_ids=["payoff"])]

    apply_short_targeted_rewrite(make_plan(), make_narration(), [], issues, narration_lead)

    call = narration_lead.calls[0]
    assert call["pass_id"] == "B2s"
    assert call["mode"] == "SHORT_TARGETED_REWRITE"


def test_uses_a_300s_timeout_matching_long_forms_own_analogous_rewrite_call():
    """2026-09-18: confirmed live on the final live-verify run -- this exact call timed out
    at the old 120s after all 3 of claude_cli.py's own retries were exhausted. Long-form's
    own analogous rewrite call (editing/targeted_rewrite.py) already sits at 300s for the
    same reason ("a full-scale Sonnet call"); this one was left at a much tighter 120s
    despite doing the same kind of call, just scoped to fewer segments."""
    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[]))
    issues = [make_issue(scene_ids=["payoff"])]

    apply_short_targeted_rewrite(make_plan(), make_narration(), [], issues, narration_lead)

    assert narration_lead.calls[0]["timeout_s"] == 300


def test_bridge_mode_reaches_the_payload():
    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[]))
    issues = [make_issue(scene_ids=["payoff"])]

    apply_short_targeted_rewrite(make_plan(bridge=ShortBridge(mode="SPOKEN")), make_narration(), [], issues, narration_lead)

    assert narration_lead.calls[0]["payload"]["bridge"]["mode"] == "SPOKEN"


def test_prompt_carries_the_shared_factual_invariants():
    from editing.short_targeted_rewrite import TASK_PROMPT
    from narration.factual_invariants import NARRATION_FACTUAL_INVARIANTS

    assert NARRATION_FACTUAL_INVARIANTS in TASK_PROMPT
    assert "NEVER UPGRADE" in TASK_PROMPT


def test_prompt_names_the_recurring_ending_and_hook_failure_patterns():
    """These specific patterns (verbatim repetition, full recap, jargon-first hooks)
    were confirmed live, repeatedly, across 6 verification rounds -- not hypothetical."""
    from editing.short_targeted_rewrite import TASK_PROMPT

    assert "verbatim-repeats" in TASK_PROMPT
    assert "recap" in TASK_PROMPT
    assert "jargon" in TASK_PROMPT


def test_an_invalid_segment_name_is_rejected_not_silently_dropped():
    """2026-09-16, found on review -- the same fix already applied to
    narration/short_generator.py::GeneratedSegment, missed when this module was built
    the next day. An unconstrained str let a typo'd segment name silently fail to
    match any real scene_id, silently dropping the requested fix with no error."""
    import pytest as _pytest

    from editing.short_targeted_rewrite import RewrittenSegment

    with _pytest.raises(Exception):
        RewrittenSegment(segment="mechanisms", sentences=[])  # typo'd, not a real segment


def test_prompt_requires_staying_within_the_overall_word_band():
    """2026-09-16, found on review -- this prompt previously carried NO word-budget
    context at all, unlike the original B1s generation prompt. Confirmed live as a
    real contributor to a rewrite that was "kept, not worse" by hard-failure count yet
    still measured over the duration cap once real TTS ran."""
    from editing.short_targeted_rewrite import TASK_PROMPT

    assert "word_band" in TASK_PROMPT
    assert "untouched_neighbors_word_count" in TASK_PROMPT


def test_word_band_and_neighbor_word_count_reach_the_payload():
    from planning.shorts_models import ShortNarration

    narration_lead = FakeNarrationLead(ShortTargetedRewrite(segments=[]))
    plan = make_plan(narration=ShortNarration(word_band=(160, 210)))
    narration = make_narration()  # hook/setup/mechanism/payoff, 2 words each = 8 total
    issues = [make_issue(scene_ids=["payoff"])]

    apply_short_targeted_rewrite(plan, narration, [], issues, narration_lead)

    payload = narration_lead.calls[0]["payload"]
    assert payload["word_band"] == [160, 210]
    # 3 untouched segments (hook, setup, mechanism) at 2 words each = 6
    assert payload["untouched_neighbors_word_count"] == 6
