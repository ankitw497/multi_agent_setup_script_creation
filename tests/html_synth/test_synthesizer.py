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


def test_prompt_does_not_discourage_using_diagram_or_math_components():
    """Real regression found live 2026-09-14: the original wording for the
    fix above ("a component with even one slot left blank... is worse than
    not choosing a component at all") measurably made H avoid diagram_card/
    math_block altogether -- a real run went from 6 diagram-card + 3
    math-block components to ZERO of either, comparing before/after this
    session's prompt changes on the same real source. The requirement
    (fill every slot) must not read as "the safe choice is no component"."""
    from html_synth.synthesizer import TASK_PROMPT

    lowered = TASK_PROMPT.lower()
    assert "worse than not choosing a component" not in lowered
    assert "math_block" in TASK_PROMPT or "diagram_card" in TASK_PROMPT


def test_prompt_is_visual_first_but_never_allows_blank_screen_prose():
    """STORY_IMPROVEMENT_PLAN.md Phase 14: the lighter prompt-level rebalancing (minimum
    text needed, not "1-3 sentences of article prose") must not contradict the existing
    hard gate (`verification/hard/render.py::check_every_scene_has_prose`) that a
    component/diagram is never a substitute for real screen text."""
    from html_synth.synthesizer import TASK_PROMPT

    assert "minimum" in TASK_PROMPT.lower()
    assert "never blank" in TASK_PROMPT.lower()
    assert "1-3 sentences of article prose" not in TASK_PROMPT


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
        "required_formula_stage": None,
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


def test_scene_with_no_formula_stage_id_gets_a_null_required_formula_stage():
    plan = make_plan()
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h", scenes=[{"scene_id": "s1"}]))

    synthesize_beat_visual(plan.beats[0], plan, [], agent)

    assert agent.calls[0]["payload"]["scenes"][0]["required_formula_stage"] is None


def test_scenes_own_formula_stage_reaches_the_beat_visual_payload():
    """2026-09-24: H used to never see formula_stages/formula_stage_id at all --
    verification/hard/formula_consistency.py checks the rendered content for this
    verbatim afterward, but nothing ever told H what it needed. Confirms the SAME
    "most advanced stage reached so far" that check computes now reaches the payload."""
    from planning.models import FormulaStage

    plan = make_plan()
    plan.formula_stages = [
        FormulaStage(stage_id="raw", expression="QK^T", values={"cat": "1.2"}),
        FormulaStage(stage_id="scaled", expression="QK^T / sqrt(d_k)", values={"cat": "0.4"}),
    ]
    plan.scene_plan = [
        ScenePlan(scene_id="s1", beat_id="B01", visual_description="x", formula_stage_id="scaled"),
    ]
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h", scenes=[{"scene_id": "s1"}]))

    synthesize_beat_visual(plan.beats[0], plan, [], agent)

    required = agent.calls[0]["payload"]["scenes"][0]["required_formula_stage"]
    assert required == {"stage_id": "scaled", "expression": "QK^T / sqrt(d_k)", "values": {"cat": "0.4"}}


def test_a_later_scene_still_requires_the_most_advanced_stage_even_if_its_own_tag_is_earlier():
    """Matches formula_consistency.py's own algorithm exactly: once a later stage has been
    reached anywhere in scene_plan order, an earlier-tagged scene appearing after it must
    still carry the MOST ADVANCED form, never regress to its own tag's simpler one."""
    from planning.models import FormulaStage

    plan = make_plan()
    plan.formula_stages = [
        FormulaStage(stage_id="raw", expression="QK^T", values={}),
        FormulaStage(stage_id="scaled", expression="QK^T / sqrt(d_k)", values={}),
    ]
    plan.scene_plan = [
        ScenePlan(scene_id="s1", beat_id="B01", visual_description="x", formula_stage_id="scaled"),
        ScenePlan(scene_id="s2", beat_id="B01", visual_description="x", formula_stage_id="raw"),
    ]
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h", scenes=[{"scene_id": "s1"}, {"scene_id": "s2"}]))

    synthesize_beat_visual(plan.beats[0], plan, [], agent)

    scenes = agent.calls[0]["payload"]["scenes"]
    assert scenes[1]["required_formula_stage"]["stage_id"] == "scaled"


def test_prompt_instructs_including_the_required_formula_stage_verbatim():
    from html_synth.synthesizer import TASK_PROMPT
    assert "required_formula_stage" in TASK_PROMPT
    assert "VERBATIM" in TASK_PROMPT


def test_beat_screen_text_word_budget_reaches_the_payload_and_sums_to_the_target():
    """2026-09-24: confirmed live a denser, more complete narration (Opus 5.5 story_lead)
    pushed the rendered page's word count over verification/hard/render.py's own band --
    H previously had zero numeric awareness of that ceiling. Confirms each beat now gets
    its own real share of it, proportional to scene count, summing to the target."""
    from html_synth.synthesizer import _SCREEN_TEXT_TARGET_WORDS

    plan = make_plan()
    plan.beats.append(StoryBeat(beat_id="B02", purpose="y", archetype_role="payoff", source_unit_ids=["u2"]))
    plan.scene_plan += [
        ScenePlan(scene_id="s2", beat_id="B02", visual_description="x"),
        ScenePlan(scene_id="s3", beat_id="B02", visual_description="x"),
    ]
    agent_b1 = FakeAgent(BeatVisual(beat_id="B01", heading="h", scenes=[{"scene_id": "s1"}]))
    agent_b2 = FakeAgent(BeatVisual(beat_id="B02", heading="h", scenes=[{"scene_id": "s2"}, {"scene_id": "s3"}]))

    synthesize_beat_visual(plan.beats[0], plan, [], agent_b1)
    synthesize_beat_visual(plan.beats[1], plan, [], agent_b2)

    b1_budget = agent_b1.calls[0]["payload"]["beat_screen_text_word_budget"]
    b2_budget = agent_b2.calls[0]["payload"]["beat_screen_text_word_budget"]
    assert b1_budget is not None and b2_budget is not None
    assert b1_budget + b2_budget == _SCREEN_TEXT_TARGET_WORDS
    assert b2_budget > b1_budget  # B02 has 2 scenes vs B01's 1 -- proportionally more


def test_beat_screen_text_word_budget_never_exceeds_the_target_even_with_a_20_word_floor():
    """Real bug found live, 2026-09-27 audit: `allocated_so_far` used to accumulate the
    pre-clamp `words` value, not the actual (possibly floor-boosted) allocation returned
    for each beat. Whenever a non-last beat's proportional share rounds below the 20-word
    floor, that shortfall was never charged against the running total, so the last beat's
    "absorb the remainder" share silently absorbed too much and the SUM exceeded
    _SCREEN_TEXT_TARGET_WORDS -- exactly the guardrail this function exists to provide.

    Two 1-scene beats sandwiched between two 150-scene beats (total_scenes=302): each
    1-scene beat's raw share is 2600*1/302=8.6 -- well below the 20-word floor, clamped up
    by +11.4 each (22 total). The old, buggy bookkeeping let the last beat's remainder
    silently absorb that whole 22-word overshoot; verified by hand, the buggy version
    summed to 2622, the fixed version must sum to exactly 2600."""
    from html_synth.synthesizer import _SCREEN_TEXT_TARGET_WORDS, _screen_text_word_budget_by_beat

    plan = make_plan()
    plan.beats = [
        StoryBeat(beat_id="A", purpose="a", archetype_role="hook", source_unit_ids=["u1"]),
        StoryBeat(beat_id="B", purpose="b", archetype_role="mechanism", source_unit_ids=["u2"]),
        StoryBeat(beat_id="C", purpose="c", archetype_role="mechanism", source_unit_ids=["u3"]),
        StoryBeat(beat_id="LAST", purpose="d", archetype_role="payoff", source_unit_ids=["u4"]),
    ]
    plan.scene_plan = (
        [ScenePlan(scene_id=f"a{i}", beat_id="A", visual_description="x") for i in range(150)]
        + [ScenePlan(scene_id="b0", beat_id="B", visual_description="x")]
        + [ScenePlan(scene_id="c0", beat_id="C", visual_description="x")]
        + [ScenePlan(scene_id=f"last{i}", beat_id="LAST", visual_description="x") for i in range(150)]
    )

    allocations = _screen_text_word_budget_by_beat(plan)

    assert allocations["B"] == 20 and allocations["C"] == 20  # floor-clamped, as expected
    assert sum(allocations.values()) == _SCREEN_TEXT_TARGET_WORDS


def test_prompt_instructs_respecting_the_beat_screen_text_word_budget():
    from html_synth.synthesizer import TASK_PROMPT
    assert "beat_screen_text_word_budget" in TASK_PROMPT


def test_no_narration_given_defaults_to_an_empty_narration_text():
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h", scenes=[{"scene_id": "s1"}]))
    synthesize_beat_visual(make_plan().beats[0], make_plan(), [], agent)
    assert agent.calls[0]["payload"]["scenes"][0]["narration_text"] == ""


def test_prompt_instructs_illustrating_what_was_actually_narrated():
    from html_synth.synthesizer import TASK_PROMPT
    assert "narration_text" in TASK_PROMPT
    assert "running_example" in TASK_PROMPT


def test_archetype_and_beat_question_fields_reach_the_beat_visual_payload():
    """STORY_IMPROVEMENT_PLAN.md Phase 31 item 2: previously never sent to H at all --
    needed so a mystery/build-archetype heading can read as the next beat of an
    unfolding investigation instead of a topic label."""
    plan = make_plan()
    plan.beats[0].viewer_question_before = "why does it point to cat?"
    plan.beats[0].answer_or_payoff = "it retrieves from context"
    plan.beats[0].next_question = "what happens with more words?"
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h", scenes=[{"scene_id": "s1"}]))

    synthesize_beat_visual(plan.beats[0], plan, [], agent)

    payload = agent.calls[0]["payload"]
    assert payload["archetype"] == "build"
    assert payload["viewer_question_before"] == "why does it point to cat?"
    assert payload["answer_or_payoff"] == "it retrieves from context"
    assert payload["next_question"] == "what happens with more words?"


def test_prompt_instructs_sustained_narrative_headings_for_mystery_and_build():
    from html_synth.synthesizer import TASK_PROMPT
    assert "mystery" in TASK_PROMPT and "`build`" in TASK_PROMPT
    assert "viewer_question_before" in TASK_PROMPT
    assert "honest, correct choice" in TASK_PROMPT


def test_prompt_describes_the_three_new_components():
    """STORY_IMPROVEMENT_PLAN.md Phase 31 item 3."""
    from html_synth.synthesizer import TASK_PROMPT
    assert "`suspect_board`" in TASK_PROMPT
    assert "`solution_grid`" in TASK_PROMPT
    assert "`case_card`" in TASK_PROMPT


def test_hero_prompt_instructs_reusing_the_running_example():
    from html_synth.synthesizer import HERO_TASK_PROMPT
    assert "running_example" in HERO_TASK_PROMPT


def test_beat_visual_beat_id_is_forced_from_the_input_never_trusted_from_the_model():
    """Real crash, 2026-09-27: the payload never sends beat.beat_id at all, yet BeatVisual's
    schema requires the model to invent one from context -- confirmed live, a real plan's
    beat "B1_hook" came back from H with a different self-chosen beat_id, and
    html_pipeline.py's `beat_visual_by_id[b.beat_id] for b in plan.beats` (keyed off the
    model's own field) raised KeyError. This had silently worked by luck on every run that
    never needed a repair pass."""
    agent = FakeAgent(BeatVisual(beat_id="some_other_guessed_id", heading="h"))

    result = synthesize_beat_visual(make_plan().beats[0], make_plan(), [], agent)

    assert result.beat_id == "B01"


def test_only_claims_from_the_beats_source_units_are_offered():
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h"))
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="in scope", type="mechanism"),
        Claim(claim_id="C002", source_unit="u2", claim="out of scope", type="mechanism"),
    ]
    synthesize_beat_visual(make_plan().beats[0], make_plan(), claims, agent)
    offered = {c["claim_id"] for c in agent.calls[0]["payload"]["available_claims"]}
    assert offered == {"C001"}


def test_required_qualifiers_and_scope_reach_the_beat_visual_payload():
    """STORY_IMPROVEMENT_PLAN.md Phase 10 follow-up: confirmed live gap (2026-09-15) -- H's
    screen prose is written independently of narration and can drop a qualifier C2b would
    catch on the narration side, since H never even saw it. Threading required_qualifiers/
    scope into H's own claim payload is the fix."""
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h"))
    claims = [Claim(
        claim_id="C001", source_unit="u1", claim="reaching forward works", type="mechanism",
        scope="MODEL_SPECIFIC", required_qualifiers=["only for unmasked/bidirectional attention"],
    )]
    synthesize_beat_visual(make_plan().beats[0], make_plan(), claims, agent)
    offered = agent.calls[0]["payload"]["available_claims"][0]
    assert offered["required_qualifiers"] == ["only for unmasked/bidirectional attention"]
    assert offered["scope"] == "MODEL_SPECIFIC"


def test_prompt_instructs_preserving_required_qualifiers():
    from html_synth.synthesizer import TASK_PROMPT

    assert "required_qualifiers" in TASK_PROMPT


def test_verification_status_and_importance_reach_the_beat_visual_payload():
    """Phase 32 P0: H used to receive claims with no `verification_status`/`importance` at
    all -- no REJECTED/UNVERIFIED gating for annotated_numbers/component_data, unlike every
    narration-writing pass."""
    agent = FakeAgent(BeatVisual(beat_id="B01", heading="h"))
    claims = [Claim(
        claim_id="C001", source_unit="u1", claim="x", type="mechanism",
        verification_status="UNVERIFIED", importance="OPTIONAL",
    )]
    synthesize_beat_visual(make_plan().beats[0], make_plan(), claims, agent)
    offered = agent.calls[0]["payload"]["available_claims"][0]
    assert offered["verification_status"] == "UNVERIFIED"
    assert offered["importance"] == "OPTIONAL"


def test_prompt_instructs_gating_on_verification_status_and_importance():
    from html_synth.synthesizer import TASK_PROMPT

    assert "REJECTED" in TASK_PROMPT
    assert "UNVERIFIED" in TASK_PROMPT


def test_prompt_warns_against_defaulting_to_diagram_card():
    """Phase 32 P1: confirmed live across two real full pages -- diagram_card (legal
    under nearly every role) was picked in roughly 2 of every 3 components chosen,
    including payoff scenes that never once used solution_grid despite it being offered.
    The prompt used to only explain what the other components are FOR, never warn against
    diagram_card becoming the reflexive safe default."""
    from html_synth.synthesizer import TASK_PROMPT

    assert "reflexive default" in TASK_PROMPT


def test_prompt_documents_metric_tables_flat_row_shape():
    """Found live, 2026-09-27 audit: metric_table's item shape was documented only in a
    YAML comment, never sent to the model at all (component_slots() only returns bare
    slot names) -- a real, reachable gap since metric_table IS offered under the
    'comparison' story_role. A model guessing the same dict-per-item shape every sibling
    component actually uses was a real, plausible failure mode."""
    from html_synth.synthesizer import TASK_PROMPT

    assert "metric_table" in TASK_PROMPT
    assert "flat list" in TASK_PROMPT


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
