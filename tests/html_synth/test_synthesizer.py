"""Tests for html_synth/synthesizer.py -- H (plan §12)."""
from facts.models import Claim
from html_synth.synthesizer import BeatVisual, HeroContent, synthesize_beat_visual, synthesize_hero
from narration.models import SceneNarration, SentenceNarration
from planning.models import (
    CTAContract, EndingContract, HookContract, RunningExample, ScenePlan, StoryBeat, StoryPlan, TitleContract,
)


class FakeAgent:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_plan() -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="understand scaling"),
        hook=HookContract(viewer_problem="x", tension="scores blow up", promise="you'll understand scaling"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[StoryBeat(beat_id="B01", purpose="explain scaling", archetype_role="mechanism", source_unit_ids=["u1"])],
        scene_plan=[ScenePlan(scene_id="s1", beat_id="B01", visual_description="score distribution widening")],
    )


def test_synthesize_hero_returns_badge_title_subtitle():
    agent = FakeAgent(HeroContent(badge="Series X", title="Why Scores Explode", subtitle="sub"))
    hero = synthesize_hero(make_plan(), agent)
    assert hero.badge == "Series X"
    assert hero.title == "Why Scores Explode"


def test_hero_prompt_never_reuses_narration_verbatim_instruction():
    from html_synth.synthesizer import HERO_TASK_PROMPT
    assert "never reuse" in HERO_TASK_PROMPT.lower()


def test_prompt_instructs_plain_notation_never_latex():
    """Real bug found live 2026-09-12: a gpt-5.6-sol-planned video's
    visual_description carried real LaTeX (\\frac{}{}, \\operatorname{})
    which H echoed verbatim into on-screen math-block-equation content --
    the page loads no LaTeX renderer, so it showed as literal broken text."""
    from html_synth.synthesizer import TASK_PROMPT

    assert "LaTeX" in TASK_PROMPT
    assert "plain" in TASK_PROMPT.lower()


def test_prompt_instructs_filling_every_component_slot():
    """The other real bug found on the same live run (and confirmed present
    regardless of story_lead model): a chosen component left some of its
    own slots blank, rendering as a visibly empty box."""
    from html_synth.synthesizer import TASK_PROMPT

    assert "blank" in TASK_PROMPT.lower()
    assert "EVERY slot" in TASK_PROMPT


def test_prompt_has_no_stray_control_characters_from_unescaped_backslashes():
    """Regression guard for a bug in THIS session's own fix: writing a raw
    LaTeX example like \\frac/\\right/\\top directly into a normal (non-raw)
    triple-quoted Python string silently turns \\f/\\r/\\t into a real
    form-feed/carriage-return/tab character instead of the two literal
    characters intended -- confirmed to actually happen (caught by a
    SyntaxWarning) before being fixed with doubled backslashes."""
    from html_synth.synthesizer import TASK_PROMPT

    for control_char in ("\x0c", "\r", "\t"):
        assert control_char not in TASK_PROMPT


def test_synthesize_beat_visual_scopes_scenes_to_the_beat():
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h", scenes=[{"scene_id": "s1"}]))
    synthesize_beat_visual(make_plan().beats[0], make_plan(), [], agent)
    payload = agent.calls[0]["payload"]
    assert payload["scenes"] == [{
        "scene_id": "s1", "visual_description": "score distribution widening", "narration_text": "",
    }]


def test_running_example_reaches_the_hero_payload():
    plan = make_plan()
    plan.running_example = RunningExample(label="trophy/suitcase", values={"trophy": "9.6"})
    agent = FakeAgent(HeroContent(badge="b", title="t", subtitle="s"))

    synthesize_hero(plan, agent)

    payload = agent.calls[0]["payload"]
    assert payload["running_example"]["label"] == "trophy/suitcase"
    assert payload["running_example"]["values"] == {"trophy": "9.6"}


def test_running_example_reaches_the_beat_visual_payload():
    plan = make_plan()
    plan.running_example = RunningExample(label="trophy/suitcase", values={"trophy": "9.6"})
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h", scenes=[{"scene_id": "s1"}]))

    synthesize_beat_visual(plan.beats[0], plan, [], agent)

    payload = agent.calls[0]["payload"]
    assert payload["running_example"]["label"] == "trophy/suitcase"


def test_scenes_own_actual_narration_text_reaches_the_beat_visual_payload():
    """Phase 6 (BUG-5): H used to only see visual_description (written
    before narration existed) -- confirms it now sees what was ACTUALLY
    narrated for each scene."""
    plan = make_plan()
    narration = [SceneNarration(scene_id="s1", sentences=[
        SentenceNarration(text="the score gap narrows here", sentence_type="technical_assertion"),
    ])]
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h", scenes=[{"scene_id": "s1"}]))

    synthesize_beat_visual(plan.beats[0], plan, [], agent, narration)

    sent_scene = agent.calls[0]["payload"]["scenes"][0]
    assert sent_scene["narration_text"] == "the score gap narrows here"


def test_no_narration_given_defaults_to_an_empty_narration_text():
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h", scenes=[{"scene_id": "s1"}]))
    synthesize_beat_visual(make_plan().beats[0], make_plan(), [], agent)
    assert agent.calls[0]["payload"]["scenes"][0]["narration_text"] == ""


def test_prompt_instructs_illustrating_what_was_actually_narrated():
    from html_synth.synthesizer import TASK_PROMPT
    assert "narration_text" in TASK_PROMPT
    assert "running_example" in TASK_PROMPT


def test_hero_prompt_instructs_reusing_the_running_example():
    from html_synth.synthesizer import HERO_TASK_PROMPT
    assert "running_example" in HERO_TASK_PROMPT


def test_only_claims_from_the_beats_source_units_are_offered():
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h"))
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="in scope", type="mechanism"),
        Claim(claim_id="C002", source_unit="u2", claim="out of scope", type="mechanism"),
    ]
    synthesize_beat_visual(make_plan().beats[0], make_plan(), claims, agent)
    offered = {c["claim_id"] for c in agent.calls[0]["payload"]["available_claims"]}
    assert offered == {"C001"}


def test_allowed_components_matches_the_beats_archetype_role():
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h"))
    synthesize_beat_visual(make_plan().beats[0], make_plan(), [], agent)
    payload = agent.calls[0]["payload"]
    assert "math_block" in payload["allowed_components"]  # mechanism role


def test_component_slots_are_given_for_every_allowed_component():
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h"))
    synthesize_beat_visual(make_plan().beats[0], make_plan(), [], agent)
    payload = agent.calls[0]["payload"]
    for cid in payload["allowed_components"]:
        assert cid in payload["component_slots"]


def test_blank_archetype_role_falls_back_to_observations():
    plan = make_plan()
    plan.beats[0].archetype_role = ""
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h"))
    synthesize_beat_visual(plan.beats[0], plan, [], agent)
    payload = agent.calls[0]["payload"]
    assert set(payload["allowed_components"]) >= {"grid_3", "defbox"}


def test_uses_pass_id_h_for_both_calls():
    hero_agent = FakeAgent(HeroContent())
    synthesize_hero(make_plan(), hero_agent)
    assert hero_agent.calls[0]["pass_id"] == "H"
    assert hero_agent.calls[0]["mode"] == "HERO"

    beat_agent = FakeAgent(BeatVisual(beat_id="B01", heading="h"))
    synthesize_beat_visual(make_plan().beats[0], make_plan(), [], beat_agent)
    assert beat_agent.calls[0]["pass_id"] == "H"
    assert beat_agent.calls[0]["mode"] == "BEAT_VISUAL"
