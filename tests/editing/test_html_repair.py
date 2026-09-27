"""Tests for editing/html_repair.py -- H REPAIR (plan §13, §15, V1C)."""
from editing.html_repair import beats_to_repair, repair_beat_visual, repair_hero
from facts.models import Claim
from html_synth.synthesizer import BeatVisual, HeroContent
from narration.models import SceneNarration, SentenceNarration
from planning.models import (
    CTAContract, EndingContract, HookContract, RunningExample, ScenePlan, StoryBeat, StoryPlan, TitleContract,
)
from verification.hard.render import RenderIssue


def make_plan() -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[
            StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"], archetype_role="mechanism"),
            StoryBeat(beat_id="B02", purpose="y", source_unit_ids=["u2"], archetype_role="payoff"),
        ],
        scene_plan=[
            ScenePlan(scene_id="s1", beat_id="B01", word_budget=40, visual_description="x"),
            ScenePlan(scene_id="s2", beat_id="B01", word_budget=40, visual_description="y"),
            ScenePlan(scene_id="s3", beat_id="B02", word_budget=40, visual_description="z"),
        ],
    )


class FakeHtmlAuthor:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


# ---- beats_to_repair ----

def test_flagged_scenes_map_to_their_own_beat():
    plan = make_plan()
    result = beats_to_repair(plan, {"s1", "s3"})
    assert result == {"B01": ["s1"], "B02": ["s3"]}


def test_multiple_flagged_scenes_in_the_same_beat_are_grouped():
    plan = make_plan()
    result = beats_to_repair(plan, {"s1", "s2"})
    assert set(result["B01"]) == {"s1", "s2"}
    assert "B02" not in result


def test_a_scene_id_with_no_matching_scene_is_set_aside_not_dropped_silently():
    """A "hero" sentinel or a page-wide issue has no beat to regenerate --
    beats_to_repair must not invent one or crash."""
    plan = make_plan()
    result = beats_to_repair(plan, {"hero", "s1"})
    assert result == {"B01": ["s1"]}
    assert "hero" not in result


def test_no_flagged_scenes_returns_empty():
    assert beats_to_repair(make_plan(), set()) == {}


# ---- repair_beat_visual ----

def test_repair_beat_visual_passes_render_failures_in_the_payload():
    html_author = FakeHtmlAuthor(BeatVisual(beat_id="B01", heading="h", subheading="s", scenes=[]))
    plan = make_plan()
    beat = plan.beats[0]
    failures = [RenderIssue("rendered_clipping", "text overflows", scene_id="s1")]

    repair_beat_visual(beat, plan, [], html_author, failures)

    sent = html_author.calls[0]["payload"]["render_failures"]
    assert sent == [{"scene_id": "s1", "code": "rendered_clipping", "detail": "text overflows"}]


def test_repair_beat_visual_forces_the_real_beat_id_never_trusts_the_models_own():
    """Real crash, 2026-09-27: the payload never sends beat.beat_id at all, yet BeatVisual's
    schema requires the model to invent one from context. This caller happened to be safe by
    accident (its result is stored keyed by the outer loop's own known-good beat_id), but the
    returned object itself must still carry the real id, not whatever the model guessed."""
    html_author = FakeHtmlAuthor(BeatVisual(beat_id="some_other_guessed_id", heading="h", scenes=[]))
    plan = make_plan()

    result = repair_beat_visual(plan.beats[0], plan, [], html_author, [])

    assert result.beat_id == "B01"


def test_repair_beat_visual_uses_pass_id_h_and_repair_mode():
    html_author = FakeHtmlAuthor(BeatVisual(beat_id="B01", heading="h", subheading="s", scenes=[]))
    plan = make_plan()

    repair_beat_visual(plan.beats[0], plan, [], html_author, [])

    assert html_author.calls[0]["pass_id"] == "H"
    assert html_author.calls[0]["mode"] == "BEAT_VISUAL_REPAIR"
    assert html_author.calls[0]["schema"] is BeatVisual


def test_repair_beat_visual_only_offers_claims_from_this_beats_own_source_units():
    html_author = FakeHtmlAuthor(BeatVisual(beat_id="B01", heading="h", subheading="s", scenes=[]))
    plan = make_plan()
    claims = [
        Claim(claim_id="C1", source_unit="u1", claim="from B01", type="definition"),
        Claim(claim_id="C2", source_unit="u2", claim="from B02", type="definition"),
    ]

    repair_beat_visual(plan.beats[0], plan, claims, html_author, [])

    sent_claim_ids = {c["claim_id"] for c in html_author.calls[0]["payload"]["available_claims"]}
    assert sent_claim_ids == {"C1"}


def test_required_qualifiers_and_scope_reach_the_repair_payload():
    """STORY_IMPROVEMENT_PLAN.md Phase 10 follow-up: same fix as the first H pass -- a repair
    round must not lose the qualifier context either."""
    html_author = FakeHtmlAuthor(BeatVisual(beat_id="B01", heading="h", subheading="s", scenes=[]))
    plan = make_plan()
    claims = [Claim(
        claim_id="C1", source_unit="u1", claim="reaching forward works", type="mechanism",
        scope="MODEL_SPECIFIC", required_qualifiers=["only for unmasked/bidirectional attention"],
    )]

    repair_beat_visual(plan.beats[0], plan, claims, html_author, [])

    offered = html_author.calls[0]["payload"]["available_claims"][0]
    assert offered["required_qualifiers"] == ["only for unmasked/bidirectional attention"]
    assert offered["scope"] == "MODEL_SPECIFIC"


def test_repair_prompt_instructs_preserving_required_qualifiers():
    from editing.html_repair import REPAIR_TASK_PROMPT

    assert "required_qualifiers" in REPAIR_TASK_PROMPT


def test_repair_prompt_bans_latex_same_as_a_first_pass():
    """PIPELINE_AUDIT_2026-09-17.md finding #7: every Agent.run call is stateless (no
    conversation history), so a repair call has zero memory of the first pass's own LaTeX
    ban -- a repair regenerating a beat with a math_block scene for an UNRELATED reason
    (clipping, overflow) could silently reintroduce raw LaTeX while fixing the named issue."""
    from editing.html_repair import REPAIR_TASK_PROMPT

    assert "never LaTeX escape syntax" in REPAIR_TASK_PROMPT
    assert "\\frac{}{}" in REPAIR_TASK_PROMPT


def test_repair_beat_visual_carries_running_example_and_narration_text():
    """Phase 6 (BUG-5): a repair pass must have the same running_example/
    narration_text context as a first H pass, or it could reintroduce the
    exact drift a first pass was fixed to avoid."""
    html_author = FakeHtmlAuthor(BeatVisual(beat_id="B01", heading="h", subheading="s", scenes=[]))
    plan = make_plan()
    plan.running_example = RunningExample(label="trophy/suitcase", values={"trophy": "9.6"})
    narration = [SceneNarration(scene_id="s1", sentences=[
        SentenceNarration(text="actual spoken line", sentence_type="technical_assertion"),
    ])]

    repair_beat_visual(plan.beats[0], plan, [], html_author, [], narration)

    payload = html_author.calls[0]["payload"]
    assert payload["running_example"]["label"] == "trophy/suitcase"
    sent_scene = next(s for s in payload["scenes"] if s["scene_id"] == "s1")
    assert sent_scene["narration_text"] == "actual spoken line"


# ---- repair_hero ----

def test_repair_hero_passes_render_failures_and_uses_repair_mode():
    html_author = FakeHtmlAuthor(HeroContent(badge="b", title="t", subtitle="s"))
    plan = make_plan()
    failures = [RenderIssue("rendered_invisible_required_content", "hero title invisible", scene_id="hero")]

    result = repair_hero(plan, html_author, failures)

    assert result == HeroContent(badge="b", title="t", subtitle="s")
    assert html_author.calls[0]["mode"] == "HERO_REPAIR"
    assert html_author.calls[0]["payload"]["render_failures"] == [
        {"scene_id": "hero", "code": "rendered_invisible_required_content", "detail": "hero title invisible"}
    ]


def test_repair_hero_carries_running_example():
    html_author = FakeHtmlAuthor(HeroContent(badge="b", title="t", subtitle="s"))
    plan = make_plan()
    plan.running_example = RunningExample(label="trophy/suitcase")

    repair_hero(plan, html_author, [])

    assert html_author.calls[0]["payload"]["running_example"]["label"] == "trophy/suitcase"


def test_repair_prompt_is_visual_first_but_never_allows_blank_screen_prose():
    """STORY_IMPROVEMENT_PLAN.md Phase 14: same rebalancing as the first H pass."""
    from editing.html_repair import REPAIR_TASK_PROMPT

    assert "minimum" in REPAIR_TASK_PROMPT.lower()
    assert "never blank" in REPAIR_TASK_PROMPT.lower()
    assert "1-3 sentences of on-screen article prose" not in REPAIR_TASK_PROMPT
