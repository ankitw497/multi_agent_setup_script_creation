"""Tests for planning/scene_expander.py -- A2b (ERR-010/ERR-023 fix)."""
from facts.models import Claim
from llm.budget import BudgetCounter, DEFAULT_TIERS
from planning.models import StoryBeat
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
    scenes = expand_beat_scenes(make_beat(), 130, [], story_lead, make_budget())

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
    expand_beat_scenes(make_beat(source_unit_ids=["u1"]), 100, claims, story_lead, make_budget())

    offered_ids = {c["claim_id"] for c in story_lead.calls[0]["payload"]["available_claims"]}
    assert offered_ids == {"C001"}


def test_target_words_is_passed_through():
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))
    expand_beat_scenes(make_beat(), 240, [], story_lead, make_budget())
    assert story_lead.calls[0]["payload"]["target_words"] == 240


def test_no_scenes_returned_is_valid_and_produces_an_empty_list():
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))
    scenes = expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget())
    assert scenes == []


def test_uses_pass_id_a2b_and_scene_expansion_mode():
    story_lead = FakeStoryLead(BeatSceneExpansion(scenes=[]))
    expand_beat_scenes(make_beat(), 100, [], story_lead, make_budget())
    call = story_lead.calls[0]
    assert call["pass_id"] == "A2b"
    assert call["mode"] == "SCENE_EXPANSION"
