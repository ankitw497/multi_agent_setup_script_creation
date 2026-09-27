"""Tests for verification/diagnostics/pacing.py -- D* (plan §10.2, V2 Phase 2)."""
from facts.models import Claim
from planning.models import (
    CTAContract, EndingContract, HookContract, ScenePlan, StoryBeat, StoryPlan, TitleContract,
)
from verification.diagnostics.pacing import (
    check_beat_airtime_outliers, check_hook_tension_pacing, check_payoff_beat_ratio,
    check_recap_bloat, check_time_to_primary_payoff,
)


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
        StoryBeat(beat_id="B00", purpose="hook", source_unit_ids=["u0"]),  # excluded: it's the hook
        StoryBeat(beat_id="B01", purpose="x", source_unit_ids=["u1"]),  # 1 claim, huge budget
        StoryBeat(beat_id="B02", purpose="x", source_unit_ids=["u2"]),
        StoryBeat(beat_id="B03", purpose="x", source_unit_ids=["u3"]),
        StoryBeat(beat_id="B04", purpose="x", source_unit_ids=["u4"]),
    ]
    scenes = [
        ScenePlan(scene_id="s0", beat_id="B00", word_budget=60),
        *[ScenePlan(scene_id=f"s1{i}", beat_id="B01", word_budget=100) for i in range(6)],  # 600 words total
        ScenePlan(scene_id="s2", beat_id="B02", word_budget=60),
        ScenePlan(scene_id="s3", beat_id="B03", word_budget=60),
        ScenePlan(scene_id="s4", beat_id="B04", word_budget=60),
    ]
    claims = [make_claim("C0", "u0"), *[make_claim(f"C{i}", f"u{i}") for i in range(1, 5)]]

    result = check_beat_airtime_outliers(make_plan(beats, scenes), claims)

    assert result.band == "AMBER"
    assert "B01" in result.evidence


def test_the_first_beat_is_excluded_from_the_distribution_entirely_even_as_an_outlier():
    """STORY_IMPROVEMENT_PLAN.md Phase 23 item "B1 (hook) measured at 0.5x median airtime":
    investigated against plan §10.2's own design intent (a hook is deliberately brief, not a
    proportional tour of its claims) -- confirmed as by-design, not a defect. The first beat
    (the hook, by construction) must never be flagged, AND must not skew the median other
    beats are judged against."""
    beats = [
        StoryBeat(beat_id="B01", purpose="hook", source_unit_ids=["u1"]),  # tiny budget, would be a huge outlier
        StoryBeat(beat_id="B02", purpose="x", source_unit_ids=["u2"]),
        StoryBeat(beat_id="B03", purpose="x", source_unit_ids=["u3"]),
        StoryBeat(beat_id="B04", purpose="x", source_unit_ids=["u4"]),
    ]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=30),  # 1 claim, 30 words -- far below the others
        ScenePlan(scene_id="s2", beat_id="B02", word_budget=100),
        ScenePlan(scene_id="s3", beat_id="B03", word_budget=100),
        ScenePlan(scene_id="s4", beat_id="B04", word_budget=100),
    ]
    claims = [make_claim(f"C{i}", f"u{i}") for i in range(1, 5)]

    result = check_beat_airtime_outliers(make_plan(beats, scenes), claims)

    assert result.band == "GREEN"
    assert "B01" not in result.evidence


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


def test_a_callback_beat_reusing_earlier_source_units_is_not_double_counted():
    """STORY_IMPROVEMENT_PLAN.md Phase 32 P1: a deliberate callback/synthesis beat whose
    source_unit_ids overlap EARLIER beats' (e.g. unifying two mechanisms already taught)
    used to have those units' claims counted again in its own denominator, deflating its
    words-per-claim ratio and falsely flagging it as an airtime outlier for doing exactly
    what a callback should -- fewer new words because the claims aren't new. Confirmed
    live on a real cross-attention beat whose source_unit_ids overlapped two earlier
    beats' and scored 0.29x median purely from this double-count.

    B04 here reuses B02's and B03's source units entirely (zero genuinely NEW claims) --
    it must be excluded from the distribution the same way a beat with zero claims
    already is, never scored (and never crash) on claims that were already spent."""
    beats = [
        StoryBeat(beat_id="B01", purpose="hook", source_unit_ids=["u0"]),
        StoryBeat(beat_id="B02", purpose="x", source_unit_ids=["u2"]),
        StoryBeat(beat_id="B03", purpose="x", source_unit_ids=["u3"]),
        StoryBeat(beat_id="B04", purpose="x", source_unit_ids=["u4"]),
        StoryBeat(beat_id="B05", purpose="callback, unifies B02+B03", source_unit_ids=["u2", "u3"]),
    ]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=60),
        *[ScenePlan(scene_id=f"s2{i}", beat_id="B02", word_budget=60) for i in range(3)],  # 180w / 3 claims
        *[ScenePlan(scene_id=f"s3{i}", beat_id="B03", word_budget=60) for i in range(3)],  # 180w / 3 claims
        *[ScenePlan(scene_id=f"s4{i}", beat_id="B04", word_budget=60) for i in range(3)],  # 180w / 3 claims
        ScenePlan(scene_id="s5", beat_id="B05", word_budget=45),  # small, deliberately -- a callback needs less
    ]
    claims = [
        *[make_claim(f"C2{i}", "u2") for i in range(3)],
        *[make_claim(f"C3{i}", "u3") for i in range(3)],
        *[make_claim(f"C4{i}", "u4") for i in range(3)],
    ]

    result = check_beat_airtime_outliers(make_plan(beats, scenes), claims)

    assert result.band == "GREEN"
    assert "B05" not in result.evidence


# ---- check_time_to_primary_payoff (STORY_IMPROVEMENT_PLAN.md Phase 23) --------------------


def test_no_beats_is_red_not_a_crash():
    result = check_time_to_primary_payoff(make_plan([], []), target_duration_seconds=600.0)
    assert result.band == "RED"


def test_no_beat_marked_payoff_is_red():
    beats = [StoryBeat(beat_id="B01", purpose="x"), StoryBeat(beat_id="B02", purpose="y")]
    scenes = [ScenePlan(scene_id="s1", beat_id="B01", word_budget=60)]
    result = check_time_to_primary_payoff(make_plan(beats, scenes), target_duration_seconds=600.0)
    assert result.band == "RED"
    assert "no beat is marked payoff=True" in result.evidence


def test_zero_target_duration_is_red_not_a_zero_division_crash():
    beats = [StoryBeat(beat_id="B01", purpose="x", payoff=True)]
    scenes = [ScenePlan(scene_id="s1", beat_id="B01", word_budget=60)]
    result = check_time_to_primary_payoff(make_plan(beats, scenes), target_duration_seconds=0.0)
    assert result.band == "RED"


def test_payoff_landing_early_is_green():
    beats = [StoryBeat(beat_id="B01", purpose="x", payoff=True), StoryBeat(beat_id="B02", purpose="y")]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=100),
        ScenePlan(scene_id="s2", beat_id="B01", word_budget=100),
        ScenePlan(scene_id="s3", beat_id="B01", word_budget=100),  # 300 words -> 107.8s
        ScenePlan(scene_id="s4", beat_id="B02", word_budget=100),  # after the payoff beat -- must not count
    ]
    result = check_time_to_primary_payoff(make_plan(beats, scenes), target_duration_seconds=600.0)
    assert result.band == "GREEN"  # 107.8/600 = 18%


def test_payoff_landing_at_45_percent_is_amber():
    """The real, live-confirmed case this diagnostic exists for: a full payoff landing
    ~5:00 into an 11-minute video (45.5% of runtime)."""
    beats = [StoryBeat(beat_id=f"B{i:02d}", purpose="x") for i in range(1, 8)]
    beats[-1].payoff = True  # B07 carries the primary payoff
    scenes = [ScenePlan(scene_id=f"s{i}", beat_id=f"B{i:02d}", word_budget=100) for i in range(1, 8)]
    # 7 * 100 = 700 words -> 251.5s; 251.5/600 = 41.9% -- inside the 35-50% AMBER band
    result = check_time_to_primary_payoff(make_plan(beats, scenes), target_duration_seconds=600.0)
    assert result.band == "AMBER"


def test_payoff_landing_late_is_red():
    beats = [StoryBeat(beat_id=f"B{i:02d}", purpose="x") for i in range(1, 11)]
    beats[-1].payoff = True
    scenes = [ScenePlan(scene_id=f"s{i}", beat_id=f"B{i:02d}", word_budget=100) for i in range(1, 11)]
    # 10 * 100 = 1000 words -> 359.3s; 359.3/600 = 59.9% -- past the 50% AMBER ceiling
    result = check_time_to_primary_payoff(make_plan(beats, scenes), target_duration_seconds=600.0)
    assert result.band == "RED"


def test_only_the_first_payoff_beat_counts_not_a_later_one():
    """Mirrors _hook_scene_seconds's own first-occurrence-by-construction pattern --
    the FIRST payoff=True beat is the primary one; a later beat also marked payoff=True
    (e.g. a secondary/mini payoff) must not extend the measured time."""
    beats = [
        StoryBeat(beat_id="B01", purpose="x", payoff=True),
        StoryBeat(beat_id="B02", purpose="y", payoff=True),
    ]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=60),
        ScenePlan(scene_id="s2", beat_id="B02", word_budget=100),
    ]
    result = check_time_to_primary_payoff(make_plan(beats, scenes), target_duration_seconds=600.0)
    assert "B01" in result.evidence
    assert "B02" not in result.evidence


def test_evidence_names_the_payoff_beat_and_percentage():
    beats = [StoryBeat(beat_id="B01", purpose="x", payoff=True)]
    scenes = [ScenePlan(scene_id="s1", beat_id="B01", word_budget=60)]
    result = check_time_to_primary_payoff(make_plan(beats, scenes), target_duration_seconds=600.0)
    assert result.dimension == "pacing.time_to_primary_payoff"
    assert "B01" in result.evidence
    assert result.target == "<= 35% of runtime"


# ---- check_payoff_beat_ratio (STORY_IMPROVEMENT_PLAN.md Phase 25 item 2) ------------------


def test_no_beats_is_red_not_a_crash():
    result = check_payoff_beat_ratio(make_plan([], []))
    assert result.band == "RED"


def test_a_single_central_payoff_beat_is_green():
    beats = [StoryBeat(beat_id=f"B{i:02d}", purpose="x") for i in range(1, 11)]
    beats[-1].payoff = True  # 1/10 = 10%
    result = check_payoff_beat_ratio(make_plan(beats, []))
    assert result.band == "GREEN"


def test_the_real_confirmed_regression_is_red():
    """The real, live-confirmed case: a plan marked payoff=True on 10 of 12 beats (83%),
    making the field meaningless for anything anchored to "the first real payoff beat"."""
    beats = [StoryBeat(beat_id=f"B{i:02d}", purpose="x") for i in range(1, 13)]
    for b in beats[2:]:  # 10 of 12, matching the real plan's own ratio exactly
        b.payoff = True
    result = check_payoff_beat_ratio(make_plan(beats, []))
    assert result.band == "RED"
    assert "10/12" in result.evidence


def test_moderate_ratio_is_amber():
    beats = [StoryBeat(beat_id=f"B{i:02d}", purpose="x") for i in range(1, 11)]
    for b in beats[:4]:  # 4/10 = 40%
        b.payoff = True
    result = check_payoff_beat_ratio(make_plan(beats, []))
    assert result.band == "AMBER"


# ---- check_recap_bloat (STORY_IMPROVEMENT_PLAN.md Phase 25 item 5) ------------------------


def test_no_scenes_at_all_is_green_not_a_crash():
    beats = [StoryBeat(beat_id="B01", purpose="x")]
    result = check_recap_bloat(make_plan(beats, []))
    assert result.band == "GREEN"


def test_the_real_confirmed_case_is_amber():
    """The real, live-confirmed case: a real closing beat had 7 of its 9 scenes tagged
    recap with zero new_concepts, re-teaching the mechanism right after the real payoff."""
    beats = [StoryBeat(beat_id="B12", purpose="x")]
    scenes = [
        ScenePlan(scene_id=f"s{i}", beat_id="B12", word_budget=60, scene_function="recap", new_concepts=[])
        for i in range(1, 8)
    ] + [
        ScenePlan(scene_id="s8", beat_id="B12", word_budget=60, scene_function="derivation", new_concepts=["x"]),
        ScenePlan(scene_id="s9", beat_id="B12", word_budget=60, scene_function="derivation", new_concepts=["y"]),
    ]
    result = check_recap_bloat(make_plan(beats, scenes))
    assert result.band == "AMBER"
    assert "B12" in result.evidence
    assert "7/9" in result.evidence


def test_a_recap_scene_with_real_new_concepts_does_not_count_as_pure_recap():
    beats = [StoryBeat(beat_id="B01", purpose="x")]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=60, scene_function="recap", new_concepts=["x"]),
        ScenePlan(scene_id="s2", beat_id="B01", word_budget=60, scene_function="recap", new_concepts=["y"]),
    ]
    result = check_recap_bloat(make_plan(beats, scenes))
    assert result.band == "GREEN"


def test_a_healthy_mostly_derivation_beat_is_green():
    beats = [StoryBeat(beat_id="B01", purpose="x")]
    scenes = [
        ScenePlan(scene_id="s1", beat_id="B01", word_budget=60, scene_function="derivation", new_concepts=["x"]),
        ScenePlan(scene_id="s2", beat_id="B01", word_budget=60, scene_function="recap", new_concepts=[]),
    ]
    result = check_recap_bloat(make_plan(beats, scenes))  # 1/2 = 50%, not > 50% target
    assert result.band == "GREEN"
