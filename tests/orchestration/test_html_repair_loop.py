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
