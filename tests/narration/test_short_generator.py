"""Tests for narration/short_generator.py -- B1 short rhythm (plan §20.7, §20.8)."""
from facts.models import Claim
from narration.short_generator import GeneratedShortNarration, generate_short_narration
from planning.shorts_models import HookEvent, ShortParent, ShortPlan


class FakeNarrationLead:
    def __init__(self, response: GeneratedShortNarration):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_plan(**overrides) -> ShortPlan:
    base = dict(
        parent=ShortParent(run_id="r1", final_plan_hash="sha256:x", source_beat_ids=["B01"], allowed_fact_ids=["C001"]),
        central_insight="x", micro_arc="problem_fix", hook=HookEvent(starts_at_seconds=1.0),
    )
    base.update(overrides)
    return ShortPlan(**base)


def test_prompt_requires_a_spoken_bridge_line_when_mode_is_spoken():
    """Real gap found 2026-09-11 (user-reported): a real short with
    `bridge.mode="SPOKEN"` produced a clean payoff with no follow-up/
    subscribe line at all -- the prompt's blanket "no reserved subscribe
    slot" framing evidently outweighed the later conditional instruction.
    Tightened to make the SPOKEN case explicitly REQUIRED and to scope the
    "don't invent one" rule to only the other three modes."""
    from narration.short_generator import TASK_PROMPT

    assert "REQUIRED" in TASK_PROMPT
    assert "SPOKEN" in TASK_PROMPT
    assert "NONE" in TASK_PROMPT


def test_word_band_reaches_the_payload():
    """2026-09-15: confirmed live as a real cause of duration overruns -- `word_band`
    existed on ShortNarration since before this pass was written but was never actually
    sent to the model, which only ever saw a vague "45-60 seconds" phrase."""
    from planning.shorts_models import ShortNarration

    narration_lead = FakeNarrationLead(GeneratedShortNarration(segments=[]))
    generate_short_narration(make_plan(narration=ShortNarration(word_band=(90, 115))), [], narration_lead)
    assert narration_lead.calls[0]["payload"]["word_band"] == [90, 115]


def test_prompt_treats_word_band_as_a_real_ceiling_not_a_soft_suggestion():
    from narration.short_generator import TASK_PROMPT

    assert "word_band" in TASK_PROMPT
    assert "ceiling" in TASK_PROMPT
    assert "SLOWER" in TASK_PROMPT


def test_prompt_warns_against_jargon_first_and_flat_hooks():
    """2026-09-15: confirmed live -- 4 of 5 real shorts had their hook flagged as
    opening on unexplained jargon or flatly stating the outcome before any tension
    existed. The prompt never warned against either pattern before this fix."""
    from narration.short_generator import TASK_PROMPT

    assert "NEVER open on a technical term or jargon" in TASK_PROMPT
    assert "flatly stating the outcome" in TASK_PROMPT


def test_prompt_gives_structural_guidance_for_every_micro_arc_type():
    """2026-09-15: confirmed live -- review/short_critic.py already judges narration
    against each micro_arc's own structural shape (a naive attempt for problem_fix, a
    stated myth for myth_correction, ...), but this generator's own prompt never told
    the model what any of those shapes actually require, for any of the 7 arc types."""
    from planning.shorts_models import MicroArc
    from narration.short_generator import TASK_PROMPT

    for arc in MicroArc.__args__:
        assert arc in TASK_PROMPT, f"{arc!r} has no structural guidance in the B1s prompt"


def test_prompt_requires_the_hook_segment_to_never_be_empty():
    """2026-09-15: confirmed live -- 2 of 5 real shorts had a completely empty hook
    segment when hook.narration was blank (a valid visual-only hook design), which a
    critic then flagged as broken -- a short with no spoken words in its first 3
    seconds. The prompt never said the hook segment must have SOME spoken content
    regardless of which hook field was populated."""
    from narration.short_generator import TASK_PROMPT

    assert "NEVER leave this segment empty" in TASK_PROMPT


def test_prompt_tells_the_model_where_micro_payoffs_belong():
    """2026-09-16, found on review: `micro_payoffs` was already sent to the model in the
    payload (line ~171) but the prompt text itself never mentioned it at all -- a real,
    plausible contributor to the "ending drifts into a recap" failure this pipeline has
    repeatedly had to fight (Phase 20's own motivation), since a model given a list of
    "smaller payoffs" with zero placement guidance could easily tack them onto the end
    after the central payoff instead of weaving them into the mechanism."""
    from narration.short_generator import TASK_PROMPT

    assert "micro_payoffs" in TASK_PROMPT
    assert "weave them in HERE" in TASK_PROMPT
    assert "reserved-outro" in TASK_PROMPT


def test_prompt_warns_against_the_real_fix_template_phrase():
    """STORY_IMPROVEMENT_PLAN.md Phase 23 continuation, 2026-09-16: read 6 real shorts
    across two separate runs (v08, v10) -- 4 of them, all problem_fix arc, use "the real
    fix is/works" as the transition into the mechanism, verbatim or near-verbatim, across
    shorts about completely unrelated topics. A more damaging version of the causal-
    connector/repeated-device fix already shipped, since this repeats ACROSS a channel's
    shorts, not just within one script."""
    from narration.short_generator import TASK_PROMPT

    assert '"The real fix ___"' in TASK_PROMPT
    assert "vary how you make this transition every time" in TASK_PROMPT


def test_prompt_names_the_template_as_a_pattern_not_just_two_verbs():
    """STORY_IMPROVEMENT_PLAN.md Phase 25: found live -- v04's short #2 opened with "The
    real fix scales with d_k itself...", surviving the prior fix because it only named
    "is"/"works" as banned verbs. The instruction must name the TEMPLATE, not specific
    verbs, so a different predicate can't slip through the same opener."""
    from narration.short_generator import TASK_PROMPT

    assert "regardless of which verb follows" in TASK_PROMPT
    assert "the TEMPLATE is the tell, not any one" in TASK_PROMPT


def test_prompt_requires_a_real_naive_attempt_not_a_strawman():
    """STORY_IMPROVEMENT_PLAN.md Phase 25: found live -- 2 of 4 v04 problem_fix shorts
    either invented a non-standard "fix" as the naive attempt or explained it away
    conceptually instead of enacting a failed attempt."""
    from narration.short_generator import TASK_PROMPT

    assert "something a real practitioner would actually try first" in TASK_PROMPT
    assert "not the same as ENACTING a" in TASK_PROMPT


def test_prompt_requires_the_required_arc_beat_stated_concisely():
    """STORY_IMPROVEMENT_PLAN.md: found live -- setup segments ran 1.5x-2.5x their own
    diagnostic target (14.8/25.4/30.9/24.5s across 4 different micro_arcs) once the
    per-arc required beat was elaborated instead of stated plainly, directly correlating
    with real FAILs (a missing naive-attempt beat, an ungrounded setup sentence)."""
    from narration.short_generator import TASK_PROMPT

    assert "ONE tight sentence (roughly 15-20 words), not a" in TASK_PROMPT


def test_prompt_names_justification_not_just_length_as_the_real_failure():
    """STORY_IMPROVEMENT_PLAN.md Phase 25: found live -- the prior "one tight sentence"
    instruction alone did not stop the overrun (v04's 4 shorts still ran 1.1x-2.4x
    target). The real failure shape is justifying/explaining the beat, not just its raw
    length."""
    from narration.short_generator import TASK_PROMPT

    assert "the WHY belongs in `mechanism`, not `setup`" in TASK_PROMPT


def test_prompt_warns_against_overusing_causal_connectors_and_repeated_devices():
    """STORY_IMPROVEMENT_PLAN.md Phase 23: the same root cause found in long-form's own
    prompt (causal connectors named as a desired voice feature with no cap) applies here
    too, since shorts share the same narration infrastructure -- and a repeated tell is
    proportionally more noticeable in a 90-second script than a 15-minute one."""
    from narration.short_generator import TASK_PROMPT

    assert "seasoning, not a default template" in TASK_PROMPT
    assert "not X, but Y" in TASK_PROMPT


def test_returns_one_scene_per_segment():
    narration_lead = FakeNarrationLead(GeneratedShortNarration(segments=[
        {"segment": "hook", "sentences": [{"text": "x", "sentence_type": "transition"}]},
        {"segment": "setup", "sentences": []},
        {"segment": "mechanism", "sentences": []},
        {"segment": "payoff", "sentences": []},
    ]))
    result = generate_short_narration(make_plan(), [], narration_lead)
    assert [s.scene_id for s in result] == ["hook", "setup", "mechanism", "payoff"]


def test_only_claims_within_allowed_fact_ids_are_offered():
    narration_lead = FakeNarrationLead(GeneratedShortNarration(segments=[]))
    claims = [
        Claim(claim_id="C001", source_unit="u1", claim="allowed", type="mechanism"),
        Claim(claim_id="C002", source_unit="u1", claim="not allowed", type="mechanism"),
    ]
    generate_short_narration(make_plan(), claims, narration_lead)
    offered = {c["claim_id"] for c in narration_lead.calls[0]["payload"]["available_claims"]}
    assert offered == {"C001"}


def test_no_parent_offers_all_claims():
    narration_lead = FakeNarrationLead(GeneratedShortNarration(segments=[]))
    claims = [Claim(claim_id="C001", source_unit="u1", claim="x", type="mechanism")]
    generate_short_narration(make_plan(parent=None), claims, narration_lead)
    offered = {c["claim_id"] for c in narration_lead.calls[0]["payload"]["available_claims"]}
    assert offered == {"C001"}


def test_uses_pass_id_b1s_and_short_first_draft_mode():
    narration_lead = FakeNarrationLead(GeneratedShortNarration(segments=[]))
    generate_short_narration(make_plan(), [], narration_lead)
    call = narration_lead.calls[0]
    assert call["pass_id"] == "B1s"
    assert call["mode"] == "SHORT_FIRST_DRAFT"


def test_prompt_carries_the_shared_factual_invariants():
    """STORY_IMPROVEMENT_PLAN.md Phase 12: a short's own narrator had no
    hedging/upgrade language at all before this fix."""
    from narration.factual_invariants import NARRATION_FACTUAL_INVARIANTS
    from narration.short_generator import TASK_PROMPT

    assert NARRATION_FACTUAL_INVARIANTS in TASK_PROMPT
    assert "NEVER UPGRADE" in TASK_PROMPT
