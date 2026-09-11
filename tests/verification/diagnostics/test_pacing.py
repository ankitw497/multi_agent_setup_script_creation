"""Tests for verification/diagnostics/pacing.py -- D* (plan §10.2, V2 Phase 2)."""
from facts.models import Claim
from planning.models import (
    CTAContract, EndingContract, HookContract, ScenePlan, StoryBeat, StoryPlan, TitleContract,
)
from verification.diagnostics.pacing import check_beat_airtime_outliers, check_hook_tension_pacing


def make_claim(claim_id, source_unit) -> Claim:
    return Claim(claim_id=claim_id, source_unit=source_unit, claim="x", type="mechanism")


def make_plan(beats, scene_plan) -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat=beats[0].beat_id if beats else "B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=beats, scene_plan=scene_plan,
    )


def test_hook_tagged_scenes_under_30s_is_green():
    beats = [StoryBeat(beat_id="B01", purpose="hook"), StoryBeat(beat_id="B02", purpose="teach")]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", narrative_beat="hook", word_budget=60),  # ~21.6s
        ScenePlan(scene_id="s2", beat_id="B02", narrative_beat="teaching", word_budget=100),
    ]
    result = check_hook_tension_pacing(make_plan(beats, scenes))
    assert result.band == "GREEN"


def test_hook_tagged_scenes_around_45s_is_amber():
    beats = [StoryBeat(beat_id="B01", purpose="hook")]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", narrative_beat="hook", word_budget=100),  # ~35.9s
        ScenePlan(scene_id="s2", beat_id="B01", narrative_beat="hook", word_budget=30),   # +10.8s -> ~46.7s
    ]
    result = check_hook_tension_pacing(make_plan(beats, scenes))
    assert result.band == "AMBER"


def test_hook_tagged_scenes_well_over_60s_is_red():
    beats = [StoryBeat(beat_id="B01", purpose="hook")]
    scenes = [ScenePlan(scene_id="s1", beat_id="B01", narrative_beat="hook", word_budget=100) for _ in range(3)]
    result = check_hook_tension_pacing(make_plan(beats, scenes))
    assert result.band == "RED"


def test_falls_back_to_the_first_beats_scenes_when_nothing_is_tagged_hook():
    """Real data-quality case: A2b never tagged any scene narrative_beat='hook'.
    The first-positioned beat IS the opening by construction -- must not be
    silently treated as zero seconds."""
    beats = [StoryBeat(beat_id="B01", purpose="opening"), StoryBeat(beat_id="B02", purpose="teach")]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", narrative_beat="teaching", word_budget=60),
        ScenePlan(scene_id="s2", beat_id="B02", narrative_beat="teaching", word_budget=100),
    ]
    result = check_hook_tension_pacing(make_plan(beats, scenes))
    assert result.band == "GREEN"
    assert result.value == 21.6


def test_no_beats_and_no_hook_scenes_is_red_not_a_crash():
    result = check_hook_tension_pacing(make_plan([], []))
    assert result.band == "RED"


def test_evidence_names_the_measured_seconds():
    beats = [StoryBeat(beat_id="B01", purpose="hook")]
    scenes = [ScenePlan(scene_id="s1", beat_id="B01", narrative_beat="hook", word_budget=60)]
    result = check_hook_tension_pacing(make_plan(beats, scenes))
    assert "22s" in result.evidence  # 60/167*60 = 21.56... -> "22s" at .0f precision
    assert result.value == 21.6  # the raw value field keeps 1 decimal of precision
    assert result.target == "<= 30s"


def test_a_later_beats_hook_tagged_scene_does_not_inflate_the_measurement():
    """BUG-2 (found 2026-09-11 via a real gpt-5.6-sol plan): A2b tags
    narrative_beat="hook" onto the first scene of MANY beats as a
    per-section rhetorical device, not exclusively the video's true
    opening. A real plan had it on 7 different beats and the old
    (pre-fix) implementation summed all of them, reporting 143s for a
    hook that was actually 64s. Only the first beat's own scenes may
    count, regardless of what's tagged elsewhere in the plan."""
    beats = [
        StoryBeat(beat_id="B01", purpose="hook"),
        StoryBeat(beat_id="B02", purpose="teach"),
        StoryBeat(beat_id="B03", purpose="teach more"),
    ]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", narrative_beat="hook", word_budget=60),  # ~21.6s -- the real hook
        ScenePlan(scene_id="s2", beat_id="B02", narrative_beat="teaching", word_budget=100),
        # A2b also tagged this LATER beat's opening scene "hook" -- a per-section device,
        # not the video's true opening. Must not be added to the measurement.
        ScenePlan(scene_id="s3", beat_id="B03", narrative_beat="hook", word_budget=100),
    ]
    result = check_hook_tension_pacing(make_plan(beats, scenes))
    assert result.band == "GREEN"
    assert result.value == 21.6  # B01's own scene only, not B01 + B03


# ---- check_beat_airtime_outliers (STORY_IMPROVEMENT_PLAN.md Phase 7 item #1) --------------

def test_too_few_beats_with_claims_is_green_not_a_crash():
    beats = [StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"])]
    scenes = [ScenePlan(scene_id="s1", beat_id="B01", word_budget=60)]
    claims = [make_claim("C1", "u1")]
    result = check_beat_airtime_outliers(make_plan(beats, scenes), claims)
    assert result.band == "GREEN"


def test_evenly_allocated_beats_are_green():
    beats = [
        StoryBeat(beat_id=f"B{i:02d}", purpose="x", source_unit_ids=[f"u{i}"]) for i in range(1, 5)
    ]
    scenes = [ScenePlan(scene_id=f"s{i}", beat_id=f"B{i:02d}", word_budget=60) for i in range(1, 5)]
    claims = [make_claim(f"C{i}", f"u{i}") for i in range(1, 5)]
    result = check_beat_airtime_outliers(make_plan(beats, scenes), claims)
    assert result.band == "GREEN"


def test_a_beat_allocated_far_more_than_its_content_density_justifies_is_flagged():
    """The confirmed live bug's shape: a beat gets a large word budget while
    its own claim density doesn't justify it, even though the video's
    total word budget matches its target elsewhere."""
    beats = [
        StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"]),  # 1 claim, huge budget
        StoryBeat(beat_id="B02", purpose="x", source_unit_ids=["u2"]),
        StoryBeat(beat_id="B03", purpose="x", source_unit_ids=["u3"]),
        StoryBeat(beat_id="B04", purpose="x", source_unit_ids=["u4"]),
    ]
    scenes = [
        *[ScenePlan(scene_id=f"s1{i}", beat_id="B01", word_budget=100) for i in range(6)],  # 600 words total
        ScenePlan(scene_id="s2", beat_id="B02", word_budget=60),
        ScenePlan(scene_id="s3", beat_id="B03", word_budget=60),
        ScenePlan(scene_id="s4", beat_id="B04", word_budget=60),
    ]
    claims = [make_claim(f"C{i}", f"u{i}") for i in range(1, 5)]

    result = check_beat_airtime_outliers(make_plan(beats, scenes), claims)

    assert result.band == "AMBER"
    assert "B01" in result.evidence


def test_beats_with_zero_claims_are_excluded_not_treated_as_infinite_ratio():
    beats = [
        StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"]),
        StoryBeat(beat_id="B02", purpose="x", source_unit_ids=["u2"]),
        StoryBeat(beat_id="B03", purpose="x"),  # no source units, no claims at all
    ]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=60),
        ScenePlan(scene_id="s2", beat_id="B02", word_budget=65),
        ScenePlan(scene_id="s3a", beat_id="B03", word_budget=100),  # large, but no claims to compare against
        ScenePlan(scene_id="s3b", beat_id="B03", word_budget=100),
    ]
    claims = [make_claim("C1", "u1"), make_claim("C2", "u2")]

    result = check_beat_airtime_outliers(make_plan(beats, scenes), claims)

    assert result.band == "GREEN"
