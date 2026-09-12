"""Tests for planning/scene_expander.py -- A2b (ERR-010/ERR-023 fix)."""
from facts.models import Claim
from llm.budget import BudgetCounter, DEFAULT_TIERS
from planning.models import FormulaStage, RunningExample, StoryBeat, ViewerLedger
from planning.scene_expander import BeatSceneExpansion, expand_beat_scenes


class FakeStoryLead:
    def __init__(self, response: BeatSceneExpansion):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_beat(**overrides) -> StoryBeat:
    base = dict(beat_id="B01", purpose="explain the setup", source_unit_ids=["u1"])
    base.update(overrides)
    return StoryBeat(**base)


def make_budget() -> BudgetCounter:
    return BudgetCounter(tier=DEFAULT_TIERS["longform"])


def make_ledger(**overrides) -> ViewerLedger:
    return ViewerLedger(**overrides)


def test_prompt_instructs_using_a_concrete_illustration_when_a_claim_has_one():
    """Real gap found 2026-09-11 (user-reported): a hook beat's scene
    visual_description stayed a generic paraphrase even though its own
    available_claims included a crisp, literal example (the source's
    "tired" vs "steep" minimal pair) -- the prompt never told this pass to
    prefer the concrete illustration over its own restatement of one."""
    from planning.scene_expander import TASK_PROMPT

    assert "concrete illustration" in TASK_PROMPT


def test_scenes_are_ided_and_tagged_with_the_beat():
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[
        {"narrative_beat": "teaching", "visual_description": "x", "word_budget": 60},
        {"narrative_beat": "reveal", "visual_description": "y", "word_budget": 70},
    ]))
    scenes, _ledger = expand_beat_scenes(make_beat(), 130, [], story_lead, make_budget(), make_ledger())

    assert [s.scene_id for s in scenes] == ["B01_s01", "B01_s02"]
    assert all(s.beat_id == "B01" for s in scenes)
    assert scenes[0].word_budget == 60
    assert scenes[1].narrative_beat == "reveal"


def test_only_claims_from_the_beats_own_source_units_are_offered():
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="in scope", type="mechanism"),
        Claim(claim_id="C002", source_unit="u2", claim="out of scope", type="mechanism"),
    ]
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))
    expand_beat_scenes(make_beat(source_unit_ids=["u1"]), 100, claims, story_lead, make_budget(), make_ledger())

    offered_ids = {c["claim_id"] for c in story_lead.calls[0]["payload"]["available_claims"]}
    assert offered_ids == {"C001"}


def test_target_words_is_passed_through():
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))
    expand_beat_scenes(make_beat(), 240, [], story_lead, make_budget(), make_ledger())
    assert story_lead.calls[0]["payload"]["target_words"] == 240


def test_no_scenes_returned_is_valid_and_produces_an_empty_list():
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))
    scenes, _ledger = expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget(), make_ledger())
    assert scenes == []


def test_uses_pass_id_a2b_and_scene_expansion_mode():
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))
    expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget(), make_ledger())
    call = story_lead.calls[0]
    assert call["pass_id"] == "A2b"
    assert call["mode"] == "SCENE_EXPANSION"


def test_viewer_knows_and_running_example_are_passed_to_the_model():
    ledger = make_ledger(
        viewer_knows=["attention as retrieval"],
        running_example=RunningExample(label="trophy/suitcase", values={"trophy": "9.6"}),
    )
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))
    expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget(), ledger)

    payload = story_lead.calls[0]["payload"]
    assert payload["viewer_knows"] == ["attention as retrieval"]
    assert payload["running_example"]["label"] == "trophy/suitcase"
    assert payload["running_example"]["values"] == {"trophy": "9.6"}


def test_new_concepts_accumulate_into_the_returned_ledger():
    """This is the mechanical fix for cross-scene repetition: a concept a
    beat introduces must be visible to the NEXT beat's expansion call."""
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[
        {"visual_description": "x", "new_concepts": ["Q/K/V roles"]},
        {"visual_description": "y", "new_concepts": ["compatibility score"]},
    ]))
    _scenes, updated_ledger = expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget(), make_ledger())

    assert updated_ledger.viewer_knows == ["Q/K/V roles", "compatibility score"]


def test_new_concepts_do_not_duplicate_already_known_concepts():
    ledger = make_ledger(viewer_knows=["Q/K/V roles"])
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[
        {"visual_description": "x", "new_concepts": ["Q/K/V roles", "scaling"]},
    ]))
    _scenes, updated_ledger = expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget(), ledger)

    assert updated_ledger.viewer_knows == ["Q/K/V roles", "scaling"]


def test_running_example_passes_through_unchanged():
    example = RunningExample(label="trophy/suitcase")
    ledger = make_ledger(running_example=example)
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))
    _scenes, updated_ledger = expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget(), ledger)

    assert updated_ledger.running_example == example


def test_scene_function_and_must_not_repeat_flow_into_the_scene_plan():
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[
        {"visual_description": "x", "scene_function": "derivation", "must_not_repeat": ["Q/K/V roles"]},
    ]))
    scenes, _ledger = expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget(), make_ledger())

    assert scenes[0].scene_function == "derivation"
    assert scenes[0].must_not_repeat == ["Q/K/V roles"]


def test_neighbor_contract_and_central_question_reach_the_model():
    previous = make_beat(beat_id="B00", purpose="setup", forward_driver="fd0",
                          viewer_question_before="why?", next_question="what next?")
    next_ = make_beat(beat_id="B02", purpose="payoff", forward_driver="fd2",
                       viewer_question_before="how?", next_question="")
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))

    expand_beat_scenes(
        make_beat(), 100, [], story_lead, make_budget(), make_ledger(),
        previous_beat=previous, next_beat=next_, central_question="how does it work?",
    )

    payload = story_lead.calls[0]["payload"]
    assert payload["central_question"] == "how does it work?"
    assert payload["neighbor_contract"]["previous_beat"]["purpose"] == "setup"
    assert payload["neighbor_contract"]["previous_beat"]["next_question"] == "what next?"
    assert payload["neighbor_contract"]["next_beat"]["purpose"] == "payoff"


def test_neighbor_contract_is_null_at_either_end_of_the_video():
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))
    expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget(), make_ledger())

    payload = story_lead.calls[0]["payload"]
    assert payload["neighbor_contract"]["previous_beat"] is None
    assert payload["neighbor_contract"]["next_beat"] is None
    assert payload["central_question"] == ""


def test_prompt_instructs_not_preempting_the_next_beats_open_question():
    from planning.scene_expander import TASK_PROMPT

    assert "neighbor_contract" in TASK_PROMPT
    assert "next_beat" in TASK_PROMPT


def test_prompt_instructs_plain_notation_never_latex_in_visual_description():
    """Real bug found live 2026-09-12: A2b (gpt-5.6-sol on this run) wrote
    visual_description using real LaTeX (\\frac{}{}, \\operatorname{}),
    which H echoed verbatim -- the page loads no LaTeX renderer, so it
    rendered as literal broken text."""
    from planning.scene_expander import TASK_PROMPT

    assert "LaTeX" in TASK_PROMPT
    assert "plain" in TASK_PROMPT.lower()


def test_prompt_has_no_stray_control_characters_from_unescaped_backslashes():
    """Regression guard for a bug in THIS session's own fix: a raw LaTeX
    example like \\frac/\\right/\\top written directly into a normal
    (non-raw) triple-quoted Python string silently turns \\f/\\r/\\t into a
    real form-feed/carriage-return/tab character -- confirmed to actually
    happen (caught by a SyntaxWarning) before being fixed with doubled
    backslashes."""
    from planning.scene_expander import TASK_PROMPT

    for control_char in ("\x0c", "\r", "\t"):
        assert control_char not in TASK_PROMPT


def test_formula_stages_are_passed_to_the_model():
    ledger = make_ledger(formula_stages=[FormulaStage(stage_id="raw_score", expression="QK^T")])
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))
    expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget(), ledger)

    payload = story_lead.calls[0]["payload"]
    assert payload["formula_stages"] == [{"stage_id": "raw_score", "expression": "QK^T", "values": {}}]


def test_formula_stage_id_flows_into_the_scene_plan():
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[
        {"visual_description": "x", "formula_stage_id": "scaled_score"},
    ]))
    scenes, _ledger = expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget(), make_ledger())

    assert scenes[0].formula_stage_id == "scaled_score"


def test_formula_stages_pass_through_unchanged_in_the_returned_ledger():
    stages = [FormulaStage(stage_id="raw_score", expression="QK^T")]
    ledger = make_ledger(formula_stages=stages)
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))
    _scenes, updated_ledger = expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget(), ledger)

    assert updated_ledger.formula_stages == stages


def test_prompt_has_no_hardcoded_topic_vocabulary():
    """Overfitting guard (user-flagged, STORY_IMPROVEMENT_PLAN.md): this
    prompt runs once per beat for EVERY future video regardless of topic --
    an earlier draft baked in attention/Q-K-V-specific example text, which
    would have been irrelevant (and potentially biasing) boilerplate for a
    video about an unrelated subject."""
    from planning.scene_expander import TASK_PROMPT

    lowered = TASK_PROMPT.lower()
    for term in ("q/k/v", "softmax", "multi-head", "q asks", "k matches", "v carries"):
        assert term not in lowered, f"found topic-specific term {term!r} in a generic per-video prompt"
