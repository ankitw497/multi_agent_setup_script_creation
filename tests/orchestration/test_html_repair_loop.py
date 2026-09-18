"""Tests for orchestration/html_pipeline.py's synthesize_and_repair_video_html
(plan §13, §15, V1C).

The static/rendered CHECK FUNCTIONS themselves are already thoroughly
tested elsewhere (tests/verification/hard/); these tests monkeypatch them
to return a prescribed sequence of RenderIssue lists instead of using a
real fixture, so they exercise the LOOP's control flow (which beat gets
repaired, when it stops, how degradation is recorded) in isolation --
matching the same "test the wiring, not re-verify already-tested checks"
approach used for orchestration/run_pipeline.py's own tests. No real
Playwright/Gemini call here; the real end-to-end proof is the live e2e
run logged in ERROR_LOG.md.
"""
import builtins

import orchestration.html_pipeline as html_pipeline_module
from facts.models import Claim
from html_synth.synthesizer import BeatVisual, HeroContent
from llm.budget import BudgetCounter, DEFAULT_TIERS
from narration.models import SceneNarration, SentenceNarration
from orchestration.html_pipeline import MAX_HTML_REPAIRS, synthesize_and_repair_video_html
from planning.models import (
    CTAContract, EndingContract, HookContract, ScenePlan, StoryBeat, StoryPlan, TitleContract,
)
from review.visual_critic import VisualCritique
from verification.hard.render import RenderIssue


class FakeAgent:
    def __init__(self, responses_by_schema: dict):
        self._queues = {k: list(v) for k, v in responses_by_schema.items()}
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["schema"]
        return self._queues[schema].pop(0)


class FakeCheckQueue:
    """Returns each queued issue list in order, one per call; the last
    entry repeats forever once exhausted (so a "never clears" test doesn't
    need to enumerate MAX_HTML_REPAIRS+1 identical entries by hand)."""

    def __init__(self, issue_lists: list[list[RenderIssue]]):
        self._lists = issue_lists
        self.call_count = 0

    def __call__(self, *args, **kwargs):
        i = min(self.call_count, len(self._lists) - 1)
        self.call_count += 1
        return list(self._lists[i])


def make_plan() -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[
            StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"]),
            StoryBeat(beat_id="B02", purpose="y", source_unit_ids=["u2"]),
        ],
        scene_plan=[ScenePlan(scene_id="s1", beat_id="B01"), ScenePlan(scene_id="s2", beat_id="B02")],
    )


def make_narration() -> list[SceneNarration]:
    return [
        SceneNarration(scene_id="s1", sentences=[SentenceNarration(text="hi", sentence_type="transition")]),
        SceneNarration(scene_id="s2", sentences=[SentenceNarration(text="bye", sentence_type="transition")]),
    ]


def make_budget() -> BudgetCounter:
    return BudgetCounter(tier=DEFAULT_TIERS["longform"])


def make_agent() -> FakeAgent:
    return FakeAgent({
        HeroContent: [HeroContent(badge="b", title="t", subtitle="s")] * 5,
        BeatVisual: [
            BeatVisual(beat_id="B01", heading="First", scenes=[{"scene_id": "s1", "screen_prose": "p1"}]),
            BeatVisual(beat_id="B02", heading="Second", scenes=[{"scene_id": "s2", "screen_prose": "p2"}]),
        ] * 5,
    })


def _patch_static_clean(monkeypatch, issue_lists: list[list[RenderIssue]] | None = None):
    monkeypatch.setattr(
        html_pipeline_module, "check_render_static",
        FakeCheckQueue(issue_lists if issue_lists is not None else [[]]),
    )
    monkeypatch.setattr(html_pipeline_module, "check_render_content", lambda *a, **k: [])


def _block_playwright(monkeypatch):
    """Simulates "playwright not installed" regardless of what's actually
    installed in this environment -- blocks the exact module name
    html_pipeline.py's function-local imports use."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "verification.hard.render_rendered":
            raise ImportError("simulated: playwright not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_one_repair_resolves_a_static_failure(monkeypatch):
    """B02's scene never rendered on the first static check; the second
    (post-repair) check comes back clean."""
    _block_playwright(monkeypatch)
    _patch_static_clean(monkeypatch, [
        [RenderIssue("scene_missing_from_dom", "s2 never rendered", scene_id="s2")],
        [],
    ])
    agent = make_agent()
    visual_auditor = FakeAgent({VisualCritique: []})

    result = synthesize_and_repair_video_html(make_plan(), make_narration(), [], agent, visual_auditor, make_budget())

    repair_calls = [c for c in agent.calls if c["mode"] == "BEAT_VISUAL_REPAIR"]
    assert len(repair_calls) == 1
    assert result.repairs_used == 1
    assert result.render_issues == []


def test_repair_only_touches_the_beat_that_actually_failed(monkeypatch):
    _block_playwright(monkeypatch)
    _patch_static_clean(monkeypatch, [
        [RenderIssue("scene_missing_from_dom", "s2 never rendered", scene_id="s2")],
        [],
    ])
    agent = make_agent()
    visual_auditor = FakeAgent({VisualCritique: []})

    synthesize_and_repair_video_html(make_plan(), make_narration(), [], agent, visual_auditor, make_budget())

    repair_calls = [c for c in agent.calls if c["mode"] == "BEAT_VISUAL_REPAIR"]
    assert repair_calls[0]["payload"]["render_failures"] == [
        {"scene_id": "s2", "code": "scene_missing_from_dom", "detail": "s2 never rendered"}
    ]


def test_hero_scoped_failures_route_to_hero_repair_not_a_beat(monkeypatch):
    _block_playwright(monkeypatch)
    _patch_static_clean(monkeypatch, [
        [RenderIssue("hero_does_not_state_the_problem", "mismatch", scene_id="hero")],
        [],
    ])
    agent = make_agent()
    visual_auditor = FakeAgent({VisualCritique: []})

    result = synthesize_and_repair_video_html(make_plan(), make_narration(), [], agent, visual_auditor, make_budget())

    assert any(c["mode"] == "HERO_REPAIR" for c in agent.calls)
    assert not any(c["mode"] == "BEAT_VISUAL_REPAIR" for c in agent.calls)
    assert result.repairs_used == 1


def test_failures_that_never_clear_stop_at_the_repair_budget_not_infinitely(monkeypatch):
    """B02 is broken on every single attempt -- the loop must terminate at
    MAX_HTML_REPAIRS, not loop forever, and report the failure honestly."""
    _block_playwright(monkeypatch)
    _patch_static_clean(monkeypatch, [
        [RenderIssue("scene_missing_from_dom", "s2 never rendered", scene_id="s2")],
    ])  # FakeCheckQueue repeats this last (and only) entry forever
    agent = make_agent()
    visual_auditor = FakeAgent({VisualCritique: []})

    result = synthesize_and_repair_video_html(make_plan(), make_narration(), [], agent, visual_auditor, make_budget())

    assert result.repairs_used == MAX_HTML_REPAIRS
    assert any(i.code == "scene_missing_from_dom" for i in result.render_issues)


def test_a_page_wide_issue_with_no_scene_id_is_never_repaired_and_surfaces_honestly(monkeypatch):
    """A real design-token bug (e.g. contrast baked into the CSS) has no
    scene to regenerate -- must not loop, must not silently vanish."""
    _block_playwright(monkeypatch)
    _patch_static_clean(monkeypatch, [
        [RenderIssue("renderer_compat_too_few_words", "not enough content", scene_id=None)],
    ])
    agent = make_agent()
    visual_auditor = FakeAgent({VisualCritique: []})

    result = synthesize_and_repair_video_html(make_plan(), make_narration(), [], agent, visual_auditor, make_budget())

    assert result.repairs_used == 0
    assert any(i.code == "renderer_compat_too_few_words" for i in result.render_issues)
    assert not any(c["mode"] in ("BEAT_VISUAL_REPAIR", "HERO_REPAIR") for c in agent.calls)


def test_playwright_unavailable_is_recorded_as_a_visible_degradation_and_skips_c3(monkeypatch):
    _block_playwright(monkeypatch)
    _patch_static_clean(monkeypatch)
    agent = make_agent()
    visual_auditor = FakeAgent({VisualCritique: []})

    result = synthesize_and_repair_video_html(make_plan(), make_narration(), [], agent, visual_auditor, make_budget())

    assert any("playwright not installed" in d for d in result.degraded_capabilities)
    assert not any(c["mode"] == "VISUAL_AUDITOR" for c in visual_auditor.calls)


def test_entity_consistency_diagnostic_is_populated_on_the_result(monkeypatch):
    """STORY_IMPROVEMENT_PLAN.md Phase 6 item #20: confirms
    synthesize_and_repair_video_html() actually computes and attaches the
    entity-consistency diagnostic, not just that the check function works
    in isolation (already covered by test_entity_consistency.py)."""
    from planning.models import RunningExample

    _patch_static_clean(monkeypatch)
    _block_playwright(monkeypatch)
    agent = make_agent()
    visual_auditor = FakeAgent({VisualCritique: []})

    plan = make_plan()
    plan.running_example = RunningExample(label="cat/stairs", values={"cat": "9.6"})

    result = synthesize_and_repair_video_html(plan, make_narration(), [], agent, visual_auditor, make_budget())

    assert result.entity_consistency is not None
    assert result.entity_consistency.band == "GREEN"  # make_agent()'s screen_prose has no quoted entities at all


def test_formula_stage_regression_is_a_real_static_issue_that_drives_a_repair(monkeypatch):
    """STORY_IMPROVEMENT_PLAN.md Phase 6 item 7: a scene claiming a
    registered formula stage whose rendered content is missing that
    stage's own form is a real static RenderIssue, wired into the same
    static-check loop as check_render_static/check_render_content --
    confirms it actually drives a beat repair, not just that the check
    function itself returns the right value in isolation."""
    from planning.models import FormulaStage

    monkeypatch.setattr(html_pipeline_module, "check_render_static", lambda *a, **k: [])
    monkeypatch.setattr(html_pipeline_module, "check_render_content", lambda *a, **k: [])
    _block_playwright(monkeypatch)
    agent = FakeAgent({
        HeroContent: [HeroContent(badge="b", title="t", subtitle="s")] * 5,
        BeatVisual: [
            # First pass: B02's card is missing the registered scaled form.
            BeatVisual(beat_id="B01", heading="First", scenes=[{"scene_id": "s1", "screen_prose": "raw: QK^T"}]),
            BeatVisual(beat_id="B02", heading="Second", scenes=[{"scene_id": "s2", "screen_prose": "regressed form"}]),
            # Repair pass: B02 now carries the correct scaled form.
            BeatVisual(beat_id="B02", heading="Second", scenes=[{"scene_id": "s2", "screen_prose": "QK^T / sqrt(d_k)"}]),
        ],
    })

    plan = make_plan()
    plan.formula_stages = [
        FormulaStage(stage_id="raw_score", expression="QK^T"),
        FormulaStage(stage_id="scaled_score", expression="QK^T / sqrt(d_k)"),
    ]
    plan.scene_plan[0].formula_stage_id = "raw_score"
    plan.scene_plan[1].formula_stage_id = "scaled_score"

    result = synthesize_and_repair_video_html(plan, make_narration(), [], agent, agent, make_budget())

    assert result.repairs_used == 1
    assert result.render_issues == []


def test_c3_payload_carries_scene_function_must_not_repeat_and_running_example(monkeypatch):
    """STORY_IMPROVEMENT_PLAN.md Phase 6 (BUG-4): C3 is the only place H's
    screen prose gets any repetition/overclaim check at all -- confirms
    the plan's own ledger fields actually reach its payload, not just
    that visual_critic.py's own function signature accepts them."""
    from planning.models import RunningExample

    _patch_static_clean(monkeypatch)
    monkeypatch.setattr("verification.hard.render_rendered.run_rendered_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        "verification.hard.render_rendered.capture_scene_screenshots",
        lambda *a, **k: {"s1": "data:image/jpeg;base64,AAAA"},
    )
    agent = make_agent()
    visual_auditor = FakeAgent({VisualCritique: [VisualCritique(issues=[])]})

    plan = make_plan()
    plan.scene_plan[0].scene_function = "derivation"
    plan.scene_plan[0].must_not_repeat = ["Q/K/V roles"]
    plan.running_example = RunningExample(label="trophy/suitcase", values={"trophy": "9.6"})

    synthesize_and_repair_video_html(plan, make_narration(), [], agent, visual_auditor, make_budget())

    c3_call = next(c for c in visual_auditor.calls if c["mode"] == "VISUAL_AUDITOR")
    sent = next(s for s in c3_call["payload"]["scenes"] if s["scene_id"] == "s1")
    assert sent["scene_function"] == "derivation"
    assert sent["must_not_repeat"] == ["Q/K/V roles"]
    assert sent["running_example"]["label"] == "trophy/suitcase"


def test_c3_payload_carries_required_qualifiers_from_the_scenes_own_beat(monkeypatch):
    """STORY_IMPROVEMENT_PLAN.md Phase 10 follow-up: confirmed live gap (2026-09-15) -- a
    qualifier C2b flags as dropped from spoken narration was independently, silently
    reproduced in H's own screen prose too, and nothing checked that side at all. C3 now
    gets the same beat-scoped required_qualifiers H itself receives."""
    _patch_static_clean(monkeypatch)
    monkeypatch.setattr("verification.hard.render_rendered.run_rendered_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        "verification.hard.render_rendered.capture_scene_screenshots",
        lambda *a, **k: {"s1": "data:image/jpeg;base64,AAAA"},
    )
    agent = make_agent()
    visual_auditor = FakeAgent({VisualCritique: [VisualCritique(issues=[])]})
    claims = [Claim(
        claim_id="C1", source_unit="u1", claim="reaching forward works", type="mechanism",
        required_qualifiers=["only for unmasked/bidirectional attention"],
    )]

    synthesize_and_repair_video_html(make_plan(), make_narration(), claims, agent, visual_auditor, make_budget())

    c3_call = next(c for c in visual_auditor.calls if c["mode"] == "VISUAL_AUDITOR")
    sent = next(s for s in c3_call["payload"]["scenes"] if s["scene_id"] == "s1")
    assert sent["required_qualifiers"] == ["only for unmasked/bidirectional attention"]


def test_non_structural_c3_findings_are_captured_not_silently_dropped(monkeypatch):
    """Real gap found 2026-09-11: C3's ordinary content critique (anything
    not critical+RENDERER+html_author) used to be computed and then
    discarded -- never returned, never reported anywhere."""
    _patch_static_clean(monkeypatch)
    monkeypatch.setattr("verification.hard.render_rendered.run_rendered_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        "verification.hard.render_rendered.capture_scene_screenshots",
        lambda *a, **k: {"s1": "data:image/jpeg;base64,AAAA"},
    )
    agent = make_agent()
    repetition_issue = {
        "issue_id": "V1", "severity": "major", "category": "repetition", "layer": "NARRATION",
        "scene_ids": ["s1"], "problem": "re-explains an already-taught concept", "why_it_matters": "y",
        "recommended_intent": "compress it", "repair_owner": "html_author",
    }
    visual_auditor = FakeAgent({VisualCritique: [VisualCritique(issues=[repetition_issue])]})

    result = synthesize_and_repair_video_html(make_plan(), make_narration(), [], agent, visual_auditor, make_budget())

    assert len(result.visual_critique_issues) == 1
    assert result.visual_critique_issues[0].category == "repetition"
    # Not structural (not RENDERER/html_author+critical) -- must not have
    # triggered a repair or been folded into render_issues.
    assert result.repairs_used == 0
    assert result.render_issues == []


def test_a_critical_narration_owned_visual_mismatch_blocks_promotion(monkeypatch):
    """STORY_IMPROVEMENT_PLAN.md Phase 8.6: a CRITICAL visual_mismatch
    whose own repair_owner is narration_lead means C3 judged this a
    genuine factual contradiction, not a rendering break -- H-repair
    cannot fix it (it only ever regenerates screen prose/component data,
    never the underlying facts), so it must surface as a real, blocking
    render_issue instead of being silently absorbed into
    visual_critique_issues with no consequence."""
    _patch_static_clean(monkeypatch)
    monkeypatch.setattr("verification.hard.render_rendered.run_rendered_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        "verification.hard.render_rendered.capture_scene_screenshots",
        lambda *a, **k: {"s1": "data:image/jpeg;base64,AAAA"},
    )
    agent = make_agent()
    contradiction_issue = {
        "issue_id": "V1", "severity": "critical", "category": "visual_mismatch", "layer": "VISUAL",
        "scene_ids": ["s1"], "problem": "screen shows a different example than the narration describes",
        "why_it_matters": "y", "recommended_intent": "fix the narration to match", "repair_owner": "narration_lead",
    }
    visual_auditor = FakeAgent({VisualCritique: [VisualCritique(issues=[contradiction_issue])]})

    result = synthesize_and_repair_video_html(make_plan(), make_narration(), [], agent, visual_auditor, make_budget())

    assert result.repairs_used == 0  # never attempted -- H-repair cannot fix a narration-owned finding
    assert any(i.code == "c3_narration_level_finding" for i in result.render_issues)
    assert len(result.visual_critique_issues) == 1  # still visible in the full list too


def test_a_major_narration_owned_visual_mismatch_does_not_block_promotion(monkeypatch):
    """Only CRITICAL narration-owned findings block -- the ordinary
    major/minor content-critique case (the common one) must keep behaving
    exactly as before this fix."""
    _patch_static_clean(monkeypatch)
    monkeypatch.setattr("verification.hard.render_rendered.run_rendered_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        "verification.hard.render_rendered.capture_scene_screenshots",
        lambda *a, **k: {"s1": "data:image/jpeg;base64,AAAA"},
    )
    agent = make_agent()
    ordinary_issue = {
        "issue_id": "V1", "severity": "major", "category": "visual_mismatch", "layer": "VISUAL",
        "scene_ids": ["s1"], "problem": "visual weight is off", "why_it_matters": "y",
        "recommended_intent": "reconsider the component choice", "repair_owner": "narration_lead",
    }
    visual_auditor = FakeAgent({VisualCritique: [VisualCritique(issues=[ordinary_issue])]})

    result = synthesize_and_repair_video_html(make_plan(), make_narration(), [], agent, visual_auditor, make_budget())

    assert result.render_issues == []


def test_enable_rendered_checks_false_is_an_explicit_opt_out_not_a_degradation(monkeypatch):
    """Turning rendered checks off on purpose is not the same as them
    being unavailable -- only a genuinely missing capability degrades."""
    _patch_static_clean(monkeypatch)
    agent = make_agent()
    visual_auditor = FakeAgent({VisualCritique: []})

    result = synthesize_and_repair_video_html(
        make_plan(), make_narration(), [], agent, visual_auditor, make_budget(),
        enable_rendered_checks=False,
    )

    assert result.degraded_capabilities == []
    assert not any(c["mode"] == "VISUAL_AUDITOR" for c in visual_auditor.calls)


def test_claims_are_still_scoped_per_beat_during_a_repair(monkeypatch):
    _block_playwright(monkeypatch)
    _patch_static_clean(monkeypatch, [
        [RenderIssue("scene_missing_from_dom", "s2 never rendered", scene_id="s2")],
        [],
    ])
    agent = make_agent()
    visual_auditor = FakeAgent({VisualCritique: []})
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="for beat 1", type="mechanism"),
        Claim(claim_id="C002", source_unit="u2", claim="for beat 2", type="mechanism"),
    ]

    synthesize_and_repair_video_html(make_plan(), make_narration(), claims, agent, visual_auditor, make_budget())

    repair_call = next(c for c in agent.calls if c["mode"] == "BEAT_VISUAL_REPAIR")
    assert {c["claim_id"] for c in repair_call["payload"]["available_claims"]} == {"C002"}


# ---- Phase 15: sequence-level visual review -------------------------------------------

def test_sequence_critique_receives_scenes_in_true_video_order_with_component_ids(monkeypatch):
    """STORY_IMPROVEMENT_PLAN.md Phase 15: the contact sheet must be built in the video's
    real scene order, not `select_scenes_for_visual_audit`'s flagged-first order."""
    from review.visual_sequence_critic import VisualSequenceCritique

    _patch_static_clean(monkeypatch)
    monkeypatch.setattr("verification.hard.render_rendered.run_rendered_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        "verification.hard.render_rendered.capture_scene_screenshots",
        lambda *a, **k: {"s1": "data:image/jpeg;base64,AAAA", "s2": "data:image/jpeg;base64,BBBB"},
    )
    agent = make_agent()
    visual_auditor = FakeAgent({
        VisualCritique: [VisualCritique(issues=[])],
        VisualSequenceCritique: [VisualSequenceCritique(issues=[])],
    })

    synthesize_and_repair_video_html(make_plan(), make_narration(), [], agent, visual_auditor, make_budget())

    seq_call = next(c for c in visual_auditor.calls if c["mode"] == "VISUAL_SEQUENCE_AUDITOR")
    sent = seq_call["payload"]["scenes"]
    assert [s["scene_id"] for s in sent] == ["s1", "s2"]
    assert sent[0]["component_id"] is None  # make_agent()'s BeatVisual scenes carry no component_id


def test_sequence_critique_is_never_a_hard_gate(monkeypatch):
    """Purely reported, never routed into repairs or render_issues -- a compositional
    judgement call, same principle as the ordinary (non-narration-owned) C3 findings."""
    from review.visual_sequence_critic import VisualSequenceCritique

    _patch_static_clean(monkeypatch)
    monkeypatch.setattr("verification.hard.render_rendered.run_rendered_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        "verification.hard.render_rendered.capture_scene_screenshots",
        lambda *a, **k: {"s1": "data:image/jpeg;base64,AAAA", "s2": "data:image/jpeg;base64,BBBB"},
    )
    agent = make_agent()
    layout_issue = {
        "issue_id": "V1", "severity": "major", "category": "visual_mismatch", "layer": "VISUAL",
        "scene_ids": ["s1", "s2"], "problem": "both scenes use card", "why_it_matters": "y",
        "recommended_intent": "vary the layout", "repair_owner": "html_author",
    }
    visual_auditor = FakeAgent({
        VisualCritique: [VisualCritique(issues=[])],
        VisualSequenceCritique: [VisualSequenceCritique(issues=[layout_issue])],
    })

    result = synthesize_and_repair_video_html(make_plan(), make_narration(), [], agent, visual_auditor, make_budget())

    assert len(result.sequence_critique_issues) == 1
    assert result.repairs_used == 0
    assert result.render_issues == []


# ---- Phase 15: bounded late narration repair -------------------------------------------

def _rewritten_narration_response():
    from narration.generator import GeneratedNarration

    return GeneratedNarration(scenes=[{
        "scene_id": "s1", "sentences": [{"text": "the corrected fact", "sentence_type": "technical_assertion"}],
    }])


def test_a_resolved_late_repair_no_longer_blocks_promotion(monkeypatch):
    """STORY_IMPROVEMENT_PLAN.md Phase 15: the one case nothing else in this architecture
    could otherwise fix -- a genuine screen/narration contradiction. When the bounded
    B2 -> C2b -> H-repair -> C3-recheck cycle actually resolves it (the recheck comes back
    clean), the finding must stop blocking promotion."""
    from narration.generator import GeneratedNarration
    from review.grounding_verifier import GroundingReview

    _patch_static_clean(monkeypatch)
    monkeypatch.setattr("verification.hard.render_rendered.run_rendered_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        "verification.hard.render_rendered.capture_scene_screenshots",
        lambda *a, **k: {"s1": "data:image/jpeg;base64,AAAA"},
    )
    agent = make_agent()
    narration_lead = FakeAgent({GeneratedNarration: [_rewritten_narration_response()]})
    contradiction_issue = {
        "issue_id": "V1", "severity": "critical", "category": "visual_mismatch", "layer": "VISUAL",
        "scene_ids": ["s1"], "problem": "screen shows a different example than the narration describes",
        "why_it_matters": "y", "recommended_intent": "correct the fact", "repair_owner": "narration_lead",
    }
    visual_auditor = FakeAgent({
        VisualCritique: [VisualCritique(issues=[contradiction_issue]), VisualCritique(issues=[])],
        GroundingReview: [GroundingReview(verdicts=[{"sentence_id": "s1:0", "factual": False}])],
    })

    result = synthesize_and_repair_video_html(
        make_plan(), make_narration(), [], agent, visual_auditor, make_budget(), narration_lead=narration_lead,
    )

    assert result.late_narration_repairs_used == 1
    assert not any(i.code == "c3_narration_level_finding" for i in result.render_issues)
    assert "the corrected fact" in result.video_script_html


def test_an_unresolved_late_repair_still_blocks_promotion(monkeypatch):
    """The recheck still finds the same contradiction -- the finding must still block,
    exactly as it did before this bounded attempt existed."""
    from narration.generator import GeneratedNarration
    from review.grounding_verifier import GroundingReview

    _patch_static_clean(monkeypatch)
    monkeypatch.setattr("verification.hard.render_rendered.run_rendered_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        "verification.hard.render_rendered.capture_scene_screenshots",
        lambda *a, **k: {"s1": "data:image/jpeg;base64,AAAA"},
    )
    agent = make_agent()
    narration_lead = FakeAgent({GeneratedNarration: [_rewritten_narration_response()]})
    contradiction_issue = {
        "issue_id": "V1", "severity": "critical", "category": "visual_mismatch", "layer": "VISUAL",
        "scene_ids": ["s1"], "problem": "screen shows a different example than the narration describes",
        "why_it_matters": "y", "recommended_intent": "correct the fact", "repair_owner": "narration_lead",
    }
    still_contradicts_issue = {**contradiction_issue, "issue_id": "V2", "problem": "still doesn't match"}
    visual_auditor = FakeAgent({
        VisualCritique: [VisualCritique(issues=[contradiction_issue]), VisualCritique(issues=[still_contradicts_issue])],
        GroundingReview: [GroundingReview(verdicts=[{"sentence_id": "s1:0", "factual": False}])],
    })

    result = synthesize_and_repair_video_html(
        make_plan(), make_narration(), [], agent, visual_auditor, make_budget(), narration_lead=narration_lead,
    )

    assert result.late_narration_repairs_used == 1
    assert any(i.code == "c3_narration_level_finding" for i in result.render_issues)


def test_without_narration_lead_the_old_blocking_behavior_is_unchanged(monkeypatch):
    """Backward compatibility: narration_lead defaults to None, so every existing caller
    (and test) keeps the pre-Phase-15 behavior -- a narration-owned critical finding blocks,
    with no repair attempt at all."""
    _patch_static_clean(monkeypatch)
    monkeypatch.setattr("verification.hard.render_rendered.run_rendered_checks", lambda *a, **k: [])
    monkeypatch.setattr(
        "verification.hard.render_rendered.capture_scene_screenshots",
        lambda *a, **k: {"s1": "data:image/jpeg;base64,AAAA"},
    )
    agent = make_agent()
    contradiction_issue = {
        "issue_id": "V1", "severity": "critical", "category": "visual_mismatch", "layer": "VISUAL",
        "scene_ids": ["s1"], "problem": "screen shows a different example than the narration describes",
        "why_it_matters": "y", "recommended_intent": "correct the fact", "repair_owner": "narration_lead",
    }
    visual_auditor = FakeAgent({VisualCritique: [VisualCritique(issues=[contradiction_issue])]})

    result = synthesize_and_repair_video_html(make_plan(), make_narration(), [], agent, visual_auditor, make_budget())

    assert result.late_narration_repairs_used == 0
    assert any(i.code == "c3_narration_level_finding" for i in result.render_issues)
