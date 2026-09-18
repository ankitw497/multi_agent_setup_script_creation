"""Tests for orchestration/html_pipeline.py -- H + HV static (plan §12, §13)."""
from facts.models import Claim
from html_synth.synthesizer import BeatVisual, HeroContent
from narration.models import SceneNarration, SentenceNarration
from orchestration.html_pipeline import synthesize_video_html
from planning.models import (
    CTAContract, EndingContract, HookContract, ScenePlan, StoryBeat, StoryPlan, TitleContract,
)


class FakeAgent:
    def __init__(self, responses_by_schema: dict):
        self._queues = {k: list(v) for k, v in responses_by_schema.items()}
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["schema"]
        return self._queues[schema].pop(0)


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
        scene_plan=[
            ScenePlan(scene_id="s1", beat_id="B01"), ScenePlan(scene_id="s2", beat_id="B02"),
        ],
    )


def make_narration() -> list[SceneNarration]:
    return [
        SceneNarration(scene_id="s1", sentences=[SentenceNarration(text="hi", sentence_type="transition")]),
        SceneNarration(scene_id="s2", sentences=[SentenceNarration(text="bye", sentence_type="transition")]),
    ]


def make_agent() -> FakeAgent:
    return FakeAgent({
        HeroContent: [HeroContent(badge="b", title="t", subtitle="s")],
        BeatVisual: [
            BeatVisual(beat_id="B01", heading="First", scenes=[{"scene_id": "s1", "screen_prose": "p1"}]),
            BeatVisual(beat_id="B02", heading="Second", scenes=[{"scene_id": "s2", "screen_prose": "p2"}]),
        ],
    })


def test_calls_hero_once_and_one_beat_visual_per_beat():
    agent = make_agent()
    synthesize_video_html(make_plan(), make_narration(), [], agent)
    hero_calls = [c for c in agent.calls if c["mode"] == "HERO"]
    beat_calls = [c for c in agent.calls if c["mode"] == "BEAT_VISUAL"]
    assert len(hero_calls) == 1
    assert len(beat_calls) == 2


def test_visual_variety_diagnostic_reaches_the_result():
    """PIPELINE_AUDIT_2026-09-17.md (visual monotony): confirms the wiring, not the
    diagnostic's own logic (covered in tests/verification/diagnostics/test_visual_variety.py)
    -- this fixture's own 2 different components (implicit no-component scenes) must not
    crash, and the field must actually be populated, not left at its default None."""
    agent = make_agent()
    result = synthesize_video_html(make_plan(), make_narration(), [], agent)
    assert result.visual_variety is not None
    assert result.visual_variety.dimension == "render.consecutive_component_repetition"


def test_produces_a_structurally_clean_result_on_well_formed_input():
    """This fixture is deliberately minimal (2 tiny scenes) -- it proves
    wiring correctness (valid DOM, hash matches, traceability), not the
    content-richness checks (renderer_compat, word-count band, etc), which
    a fixture this small could never pass. See the dedicated fully-realistic
    test below for that."""
    agent = make_agent()
    result = synthesize_video_html(make_plan(), make_narration(), [], agent)
    from verification.hard.render import check_render_static

    static_issues = check_render_static(result.video_script_html, result.page_html, make_narration(), [])
    assert static_issues == []
    assert "First" in result.video_script_html
    assert "Second" in result.video_script_html


def test_produces_a_fully_clean_result_including_content_checks():
    """A realistic-sized fixture (3 beats, real prose, hero/payoff aligned
    with the plan) proving the content-level checks (renderer_compat,
    reader-standalone word count, hero/payoff alignment, prose-per-scene)
    can genuinely all pass together, not just the structural ones."""
    plan = StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="a token alone has no context", tension="ambiguous meaning", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="attention retrieves context via query key value",
                               capstone_payoff="you can now explain self-attention end to end", viewer_can_now="do x"),
        beats=[
            StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"]),
            StoryBeat(beat_id="B02", purpose="y", source_unit_ids=["u2"]),
            StoryBeat(beat_id="B03", purpose="z", source_unit_ids=["u3"]),
        ],
        scene_plan=[
            ScenePlan(scene_id="s1", beat_id="B01"), ScenePlan(scene_id="s2", beat_id="B02"),
            ScenePlan(scene_id="s3", beat_id="B03"),
        ],
    )
    narration = [
        SceneNarration(scene_id="s1", sentences=[SentenceNarration(text="hi", sentence_type="transition")]),
        SceneNarration(scene_id="s2", sentences=[SentenceNarration(text="mid", sentence_type="transition")]),
        SceneNarration(scene_id="s3", sentences=[SentenceNarration(text="bye", sentence_type="transition")]),
    ]
    long_prose = " ".join(["word"] * 750)  # 3 * 750 = 2250+ visible words total, clears both bands
    agent = FakeAgent({
        HeroContent: [HeroContent(badge="b", title="A token has no context",
                                    subtitle="Why a token alone can't resolve its own meaning.")],
        BeatVisual: [
            BeatVisual(beat_id="B01", heading="First", scenes=[{"scene_id": "s1", "screen_prose": long_prose}]),
            BeatVisual(beat_id="B02", heading="Second", scenes=[{"scene_id": "s2", "screen_prose": long_prose}]),
            BeatVisual(beat_id="B03", heading="Third", scenes=[{
                "scene_id": "s3",
                "screen_prose": long_prose + " attention retrieves context via query key value and you can now explain self-attention end to end",
            }]),
        ],
    })

    result = synthesize_video_html(plan, narration, [], agent)
    assert result.render_issues == []


def test_a_missing_scene_is_caught_by_render_issues():
    agent = FakeAgent({
        HeroContent: [HeroContent()],
        BeatVisual: [
            BeatVisual(beat_id="B01", heading="First", scenes=[{"scene_id": "s1", "screen_prose": "p1"}]),
            BeatVisual(beat_id="B02", heading="Second", scenes=[]),  # s2 never rendered
        ],
    })
    result = synthesize_video_html(make_plan(), make_narration(), [], agent)
    assert any(i.code == "scene_missing_from_dom" for i in result.render_issues)


def test_claims_are_scoped_per_beat_across_the_whole_plan():
    agent = make_agent()
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="for beat 1", type="mechanism"),
        Claim(claim_id="C002", source_unit="u2", claim="for beat 2", type="mechanism"),
    ]
    synthesize_video_html(make_plan(), make_narration(), claims, agent)
    beat_calls = [c for c in agent.calls if c["mode"] == "BEAT_VISUAL"]
    assert {c["claim_id"] for c in beat_calls[0]["payload"]["available_claims"]} == {"C001"}
    assert {c["claim_id"] for c in beat_calls[1]["payload"]["available_claims"]} == {"C002"}
