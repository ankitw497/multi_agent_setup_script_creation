"""Round-trip tests for planning/models.py (plan §5, §9, §10.2, §5.2, §5.3)."""
import pytest
from pydantic import ValidationError

from planning.models import (
    ArchetypeSpec, CTAContract, EndingContract, HookContract, MiniPayoff,
    ScenePlan, SemanticObject, SourceBrief, StoryBeat, StoryPlan, SeriesLedger, TitleContract,
)

from tests.conftest import roundtrip, roundtrip_fixture


def test_archetype_spec_roundtrips_core_vs_optional_roles():
    """This is the data behind the §9 structural hard gate: core roles are
    required, optional roles are diagnostics only."""
    spec = roundtrip(
        ArchetypeSpec,
        {
            "archetype": "mystery",
            "core_roles": ["expectation", "contradiction", "mechanism", "resolution"],
            "optional_roles": ["suspects", "investigation_steps"],
            "driver": "unanswered cause",
        },
    )
    assert "suspects" not in spec.core_roles


def test_archetype_literal_excludes_auto():
    """StoryPlan.archetype (and ArchetypeSpec.archetype) can never be "auto" —
    enforced at the TYPE level, not just at runtime (plan §9)."""
    with pytest.raises(ValidationError):
        ArchetypeSpec(archetype="auto", core_roles=[], driver="")


def test_title_contract_roundtrips():
    roundtrip(TitleContract, {"candidates": ["A", "B"], "chosen": "A", "promise": "you'll know why"})


def test_hook_contract_roundtrips():
    roundtrip(
        HookContract,
        {"viewer_problem": "x", "tension": "y", "promise": "z", "open_loop": "w",
         "must_not_reveal_yet": ["the mechanism"]},
    )


def test_cta_contract_defaults_match_feedback_md():
    """Default intent is VALUE_LINKED per feedback.md's stated preference (plan §5.2) —
    not a placement-only rule, and never more than 2 CTAs."""
    cta = CTAContract(primary_after_beat="B03")
    assert cta.intent == "VALUE_LINKED"
    assert cta.max_ctas == 2
    assert cta.end_after_final_payoff is True


def test_cta_contract_rejects_more_than_two():
    with pytest.raises(ValidationError):
        CTAContract(primary_after_beat="B03", max_ctas=3)


def test_mini_payoff_roundtrips():
    roundtrip(MiniPayoff, {"after_beat": "B03", "payoff": "x", "opens": "y"})


def test_ending_contract_roundtrips():
    roundtrip(
        EndingContract,
        {"resolve_hook": "a", "compressed_mental_model": "b", "capstone_payoff": "c",
         "viewer_can_now": "diagnose the failure", "next_video_bridge": None},
    )


def test_story_beat_allows_blank_archetype_role():
    """Blank archetype_role is valid (design doc §14) — not every scene must
    instantiate a named archetype stage."""
    beat = roundtrip(
        StoryBeat,
        {"beat_id": "B02", "purpose": "supportive exposition", "source_unit_ids": []},
    )
    assert beat.archetype_role == ""


def test_story_beat_uses_observable_fields_not_a_numeric_energy_score():
    """Appendix G #10: energy was removed as a hard signal in favor of these
    observable fields — none of them is a 1-10 pseudo-precise score."""
    beat = StoryBeat(beat_id="B03", purpose="reveal the fix")
    assert beat.question_progress == "none"
    assert beat.concept_density in ("low", "medium", "high")
    assert not hasattr(beat, "energy")


def test_scene_plan_word_budget_bounds():
    """40-80 target, 30-100 hard (plan §9)."""
    with pytest.raises(ValidationError):
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=200)
    ScenePlan(scene_id="s1", beat_id="B01", word_budget=95)  # inside the hard bound


def test_semantic_object_roundtrips():
    roundtrip(SemanticObject, {"semantic_object_id": "attention_matrix", "continuity": "transforms"})


def test_story_plan_roundtrips_full_nested_structure():
    plan = roundtrip_fixture(StoryPlan, "planning", "StoryPlan")
    assert plan.archetype == "build"
    assert len(plan.beats) == 2
    assert plan.hook.must_not_reveal_yet == ["the exact scaling formula"]
    assert plan.cta.intent == "VALUE_LINKED"


def test_source_brief_roundtrips():
    brief = roundtrip_fixture(SourceBrief, "planning", "SourceBrief")
    assert brief.novelty_statement  # plan §9 Learning gate requires this be non-empty


def test_series_ledger_roundtrips_and_tracks_shorts_by_video():
    ledger = roundtrip_fixture(SeriesLedger, "planning", "SeriesLedger")
    assert ledger.shorts_by_video["video-1.1"] == ["short-1.1a", "short-1.1b"]
