"""Tests for planning/short_planner.py -- A2s (plan §20.6)."""
from facts.models import Claim
from planning.models import (
    CTAContract, EndingContract, HookContract, StoryBeat, StoryPlan, TitleContract,
)
from planning.short_planner import TASK_PROMPT, ShortPlanSelection, check_bridge_selection_defaulted, plan_shorts
from planning.shorts_models import ShortsCandidate


class FakeStoryLead:
    def __init__(self, response: ShortPlanSelection):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


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
    )


def make_candidates() -> list[ShortsCandidate]:
    return [ShortsCandidate(beat_ids=["B01"], insight="x")]


def make_budget():
    from llm.budget import BudgetCounter, DEFAULT_TIERS
    return BudgetCounter(tier=DEFAULT_TIERS["short"])


def make_draft(**overrides) -> dict:
    base = dict(
        title="t", goal="DISCOVERY", central_insight="x", micro_arc="problem_fix",
        hook={"starts_at_seconds": 1.0}, source_beat_ids=["B01"],
    )
    base.update(overrides)
    return base


def test_no_candidates_short_circuits_with_no_call():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[]))
    plans = plan_shorts([], make_plan(), [], story_lead, make_budget(), run_id="r1")
    assert plans == []
    assert story_lead.calls == []


def test_builds_parent_linkage_from_source_beat_ids():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[make_draft()]))
    claims = [Claim(claim_id="C001", source_unit="u1", claim="x", type="mechanism")]

    plans = plan_shorts(make_candidates(), make_plan(), claims, story_lead, make_budget(), run_id="r1")

    assert len(plans) == 1
    assert plans[0].parent.run_id == "r1"
    assert plans[0].parent.source_beat_ids == ["B01"]
    assert plans[0].parent.allowed_fact_ids == ["C001"]
    assert plans[0].parent.final_plan_hash.startswith("sha256:")


def test_only_claims_from_the_selected_beats_source_units_are_allowed():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[make_draft(source_beat_ids=["B01"])]))
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="in scope", type="mechanism"),
        Claim(claim_id="C002", source_unit="u2", claim="out of scope", type="mechanism"),
    ]
    plans = plan_shorts(make_candidates(), make_plan(), claims, story_lead, make_budget(), run_id="r1")
    assert plans[0].parent.allowed_fact_ids == ["C001"]


def test_a_draft_naming_an_unknown_beat_id_is_dropped():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[make_draft(source_beat_ids=["B99"])]))
    plans = plan_shorts(make_candidates(), make_plan(), [], story_lead, make_budget(), run_id="r1")
    assert plans == []


def test_never_returns_more_than_shorts_count():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[make_draft(), make_draft(), make_draft()]))
    plans = plan_shorts(make_candidates(), make_plan(), [], story_lead, make_budget(), run_id="r1", shorts_count=2)
    assert len(plans) == 2


def test_fewer_than_the_count_is_valid_never_padded():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[make_draft()]))
    plans = plan_shorts(make_candidates(), make_plan(), [], story_lead, make_budget(), run_id="r1", shorts_count=3)
    assert len(plans) == 1


def test_uses_pass_id_a2s_and_short_planner_mode():
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[]))
    plan_shorts(make_candidates(), make_plan(), [], story_lead, make_budget(), run_id="r1")
    call = story_lead.calls[0]
    assert call["pass_id"] == "A2s"
    assert call["mode"] == "SHORT_PLANNER"


def test_prompt_requires_the_title_to_reuse_actual_hook_or_payoff_words():
    """2026-09-15: confirmed live -- verification/hard/shorts.py's title_hook_mismatch/
    title_payoff_mismatch (a literal word-overlap check) kept failing because A2s was told
    to match the hook/payoff "semantically," while the check itself only ever counts shared
    literal words -- titles like "Pronoun Resolution in Language Models" are thematically
    on-topic but share zero words with a concrete hook sentence."""
    assert "REUSES 2-3 actual" in TASK_PROMPT
    assert "never a full sentence" in TASK_PROMPT


def test_prompt_requires_setup_to_carry_each_micro_arcs_own_required_content():
    """2026-09-15: confirmed live -- narration/short_generator.py's own prompt already told
    B1s what each micro_arc structurally requires, but A2s (which actually knows the source
    claims) was never told to make sure `setup`/`mechanism` contain that content -- so B1s
    was handed a `setup` field with nothing to narrate the required beat from."""
    from planning.shorts_models import MicroArc

    for arc in MicroArc.__args__:
        assert arc in TASK_PROMPT, f"{arc!r} has no setup-content requirement in the A2s prompt"


def test_prompt_tells_a2s_not_to_default_to_problem_fix_without_a_real_failed_attempt():
    """2026-09-15: confirmed live -- 4 of 5 real shorts declared problem_fix but never
    stated a real failed attempt, across two separate rounds of strengthened prompting
    on the NARRATION side. Root cause traced one level up: A2s reaches for problem_fix
    by default for any problem-then-mechanism candidate (nearly all of them), whether
    or not the source material actually supports a nameable failed attempt."""
    assert "defaults to reaching for even when it doesn't fit" in TASK_PROMPT


def test_prompt_requires_visual_states_not_just_dominant_object():
    """2026-09-16: confirmed live -- visual.states was empty in 5 of 5 real shorts
    across a full run, silently disabling the mechanism screen's flow diagram this
    whole time (html_synth/vertical_assembler.py only draws one when states is
    non-empty). The old prompt text ("the dominant object, its states, and safe
    zones") never explained what a "state" actually is, unlike every other field --
    A2s reliably filled dominant_object (self-explanatory) but never states."""
    assert "MUST also be filled in" in TASK_PROMPT
    assert "not optional decoration" in TASK_PROMPT


def test_prompt_warns_against_defaulting_every_short_to_discovery():
    """2026-09-16, user-reported: a real batch of 5 landed 100% goal=DISCOVERY and
    100% bridge=NONE -- none of the 5 shorts in that run gave a viewer any reason to
    subscribe or return to the parent video. DISCOVERY/NONE are individually valid
    choices, but a batch that never varies quietly forfeits BRIDGE/SERIES entirely."""
    assert "100% DISCOVERY" in TASK_PROMPT
    assert "two of the three growth levers" in TASK_PROMPT


def test_prompt_encourages_a_real_follow_line_when_the_payoff_supports_it():
    assert "there's more where this came from" in TASK_PROMPT
    assert "<=8 words" in TASK_PROMPT


def test_prompt_requires_cta_text_for_onscreen_and_platform_link_bridges():
    """2026-09-16, found on review: ONSCREEN/PLATFORM_LINK explicitly mean the bridge
    renders as on-screen text rather than spoken narration, but there was no field
    anywhere to capture what that text actually says, and no renderer for it either --
    a short assigned either mode shipped with a silently missing CTA. The schema now
    has `ShortBridge.cta_text`; this prompt must tell A2s to actually fill it in."""
    assert "cta_text" in TASK_PROMPT
    assert "nothing is ever shown at all" in TASK_PROMPT


def test_prompt_tells_a2s_to_actually_use_the_candidates_own_bridge_question():
    """2026-09-16, found on review: `planning/candidate_finder.py`'s SC prompt spends a
    real LLM call producing `bridge_question` specifically to flag bridge potential
    ("the larger question this candidate's payoff could naturally open onto... for a
    BRIDGE-goal short later") -- but the full candidate (bridge_question included) was
    only ever handed to A2s as raw JSON payload, never once named in A2s's own prompt.
    The one upstream signal purpose-built to fix the live 100%-DISCOVERY bias was being
    silently discarded downstream."""
    assert "bridge_question" in TASK_PROMPT
    assert "do not silently ignore" in TASK_PROMPT


# --- check_bridge_selection_defaulted (STORY_IMPROVEMENT_PLAN.md Phase 23 continuation) -----


def make_candidate(bridge_question="") -> ShortsCandidate:
    return ShortsCandidate(beat_ids=["B01"], insight="x", bridge_question=bridge_question)


def make_all_discovery_none_plans(n=1):
    story_lead = FakeStoryLead(ShortPlanSelection(shorts=[make_draft() for _ in range(n)]))
    return plan_shorts(
        [make_candidate() for _ in range(n)], make_plan(), [], story_lead, make_budget(), run_id="r1",
        shorts_count=n,
    )


def test_no_note_when_the_selection_already_varied():
    plans = make_all_discovery_none_plans(1)
    plans[0].goal = "BRIDGE"

    assert check_bridge_selection_defaulted([make_candidate(bridge_question="q")], plans) is None


def test_no_note_when_no_candidate_ever_had_a_real_bridge_signal():
    plans = make_all_discovery_none_plans(1)

    assert check_bridge_selection_defaulted([make_candidate(bridge_question="")], plans) is None


def test_note_when_all_discovery_none_but_a_real_signal_was_available():
    """The real, live-confirmed scenario: ERR-072's own prompt nudge showed 0% variation
    across two full verification rounds (10 shorts) despite real bridge_question signals
    existing in the candidate shortlist."""
    plans = make_all_discovery_none_plans(1)

    note = check_bridge_selection_defaulted([make_candidate(bridge_question="what about multi-head?")], plans)

    assert note is not None
    assert "1 of 1 candidates had a real bridge_question" in note


def test_does_not_override_the_models_own_selection():
    """This is a visibility check, not a gate -- the returned plans are never mutated."""
    plans = make_all_discovery_none_plans(1)
    original_goal = plans[0].goal

    check_bridge_selection_defaulted([make_candidate(bridge_question="q")], plans)

    assert plans[0].goal == original_goal


def test_prompt_warns_against_a_jargon_only_title_sharing_no_hook_words():
    """2026-09-16: confirmed live -- a title "Permutation Equivariance Limitation" shared
    almost no words with its own hook (about shuffling "token cards") or payoff, failing
    title_hook_mismatch/title_payoff_mismatch despite being specific rather than vague.
    The existing prompt only warned against "too vague" and "too verbatim" titles, not a
    title built entirely from central_insight's technical framing with nothing pulled from
    the hook's own concrete language."""
    assert "shared almost no words with either the hook" in TASK_PROMPT


def test_prompt_warns_that_the_word_overlap_check_does_not_stem():
    """verification/hard/text_overlap.py::overlap() matches exact tokens only -- a title
    reusing a different grammatical form of the same word (e.g. "Equivariance" for a hook
    that says "equivariant") scores zero overlap for that word even though a human reader
    sees the same concept."""
    assert "no stemming" in TASK_PROMPT
    assert "reuse the SAME form" in TASK_PROMPT


def test_no_note_for_an_empty_plans_list():
    assert check_bridge_selection_defaulted([make_candidate(bridge_question="q")], []) is None
