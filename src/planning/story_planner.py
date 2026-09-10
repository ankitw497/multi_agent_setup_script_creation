"""A2 -- ONE archetype + full story blueprint (Story Lead / GPT strong) (plan §5, §8, §9, §19).

The single most consequential call in the pipeline: title, hook, CTA,
question chain, beats (with forward drivers), mini-payoffs, ending, and a
scene plan -- all decided here, before a word of narration exists (the
design doc's core principle).
"""
from __future__ import annotations

from agents.base import Agent
from facts.models import AssumptionLedger, Claim, SourceUnit
from llm.budget import BudgetCounter

from .archetypes import ALL_ARCHETYPES, load_archetype_specs
from .models import ReplanFeedback, SourceBrief, StoryPlan

TASK_PROMPT = """\
Resolve ONE primary archetype for this source and build its full story
blueprint. Never output "auto" -- you must commit to exactly one of:
mystery, build, experiment, derivation, foundation, framework.

Classification order (plan §19) -- test evidence in this order and only
fall through to the next when the current one is genuinely absent:
1. Is there a real violated expectation / failure investigated? -> mystery
2. Is there a real problem -> fix -> new problem chain? -> build
3. Is there an actual comparison with baselines/results? -> experiment
4. Is the central value produced through a justified equation? -> derivation
5. Is the knowledge mainly dependency-driven? -> foundation
6. Is it genuinely a non-causal collection of useful observations? -> framework

`framework` and `foundation` are the easy defaults to reach for -- rule out
1-4 explicitly before choosing either. Fill `rejected_archetypes` with a
real reason for every archetype you did NOT choose, citing why the source
does not support it (not a vague dismissal).

Every beat needs: `source_unit_ids` listing the ACTUAL source unit ids it
draws from (never leave this empty -- it is what lets narration later know
which claims are relevant, and what lets a downstream check confirm the
source's real content was actually used, not silently dropped); which of
the resolved archetype's CORE roles it instantiates (`archetype_stage`, if
any -- optional roles are allowed but never required); a `forward_driver`
describing what it advances toward the archetype's own driver concept; a
`learning_objective` stating what the viewer can do afterward that they
couldn't before; and the observable fields (`new_information`, `payoff`,
`visual_mode_change`, `question_progress`, `concept_density`) describing
what actually happens in it -- never a numeric "energy" score.

Every source unit given to you should appear in at least one beat's
`source_unit_ids` unless it is genuinely redundant with another -- a source
with 11 real sections should not collapse into 4 beats that only draw on a
handful of them.

The hook must create a knowledge gap, not announce a syllabus -- no "in this
video we will cover X". `must_not_reveal_yet` must list what the hook
deliberately withholds.

The CTA's `intent` should default to VALUE_LINKED (it names the payoff just
earned and the channel's promise) unless there's a clear reason for another
intent. `primary_after_beat` must be a beat that has a real payoff, not the
first beat that happens to exist.

The ending must resolve the hook's promise, compress the mechanism into a
usable mental model, and state `viewer_can_now` as a capability (diagnose /
predict / build / explain), never a feature list.

Build a `scene_plan` that actually fills the target duration and uses the
source's real depth -- do not under-scope this. At 167 words/minute, the sum
of every scene's `word_budget` should land within about 20% of
`target_duration_seconds / 60 * 167` words. Work backward from that: for a
600-second (10-minute) target, that is roughly 1,670 words, which typically
means 20-30 scenes at 40-80 words each -- NOT 4-6 scenes. A beat is a story
unit, not a scene budget; a single beat routinely spans several scenes when
the source has that much real content to cover (a beat about deriving an
equation, for instance, usually needs a scene for the setup, one for each
real step, and one for the payoff). Every source unit with real teaching
content should be reflected in at least one scene -- do not silently drop
sections of the source because a smaller scene count felt cleaner.

Each scene needs: a realistic `word_budget` (30-100 hard bounds, 40-80
preferred), a `narrative_beat` (hook/teaching/escalation/reveal/close --
`reveal` should be roughly 1 scene in 4-6, not constant), and a concrete,
single-idea `visual_description`. Leave `components` empty -- that's decided
later by the HTML stage, not here.

Ground everything in the claims and source brief given. Never introduce a
technical claim that isn't backed by the claim registry.

You are also given the actual `source_units` (the source's real content, not
just A1's summary) -- use them to make and cross-check your OWN archetype
call rather than trusting the source brief alone. In particular, if any unit
contains the author's own production notes, storyboard plan, pacing outline,
or similar meta-commentary about how the piece is meant to be built, treat
it as strong direct evidence: it is the author's own account of the
structure, not a pattern you have to infer from the raw material. Weigh it
accordingly against the classification order above.

If `replan_feedback` is present, this is NOT a first attempt -- your
previous plan (archetype: `previous_archetype`) was rejected for the
specific reasons listed in `critique_issues` and `structural_issues`. Do
not silently repeat `previous_archetype` unless you can directly refute
every critique issue that names a better-supported alternative. Every
structural issue must be visibly addressed in this new plan (e.g. if
specific source unit ids were listed as uncovered, this plan's beats must
now actually cover them; if the word budget was short, this plan's scene
count and per-scene budgets must close that gap for real, not nominally).
"""


def _archetype_reference_payload() -> dict:
    return {
        name: {"core_roles": spec.core_roles, "optional_roles": spec.optional_roles, "driver": spec.driver}
        for name, spec in load_archetype_specs().items()
    }


def _claim_payload(claim: Claim) -> dict:
    return {
        "claim_id": claim.claim_id, "claim": claim.claim, "type": claim.type,
        "importance": claim.importance, "verification_status": claim.verification_status,
    }


def _source_unit_payload(unit: SourceUnit) -> dict:
    return {
        "id": unit.id, "heading": unit.heading, "text": unit.text,
        "equations": unit.equations, "callouts": unit.callouts,
        "code": unit.code, "numbers": unit.numbers,
    }


def plan_story(
    source_brief: SourceBrief, claims: list[Claim], ledger: AssumptionLedger,
    story_lead: Agent, budget: BudgetCounter, target_duration_seconds: float,
    source_units: list[SourceUnit],
    archetype_override: str | None = None,
    replan_feedback: ReplanFeedback | None = None,
) -> StoryPlan:
    payload = {
        "source_brief": source_brief.model_dump(),
        "source_units": [_source_unit_payload(u) for u in source_units],
        "claims": [_claim_payload(c) for c in claims],
        "assumption_ledger": ledger.model_dump(exclude_none=True),
        "target_duration_seconds": target_duration_seconds,
        "planning_wpm": 167,
        "archetype_reference": _archetype_reference_payload(),
        "archetype_override": archetype_override,  # None means "auto": classify freely
        "replan_feedback": replan_feedback.model_dump() if replan_feedback else None,
    }
    plan = story_lead.run(
        pass_id="A2", mode="PLAN", task_prompt=TASK_PROMPT,
        payload=payload, schema=StoryPlan, budget=budget, estimated_usd=0.15,
    )
    if archetype_override and plan.archetype != archetype_override:
        raise ValueError(
            f"A2 returned archetype {plan.archetype!r} but the run pinned "
            f"{archetype_override!r} -- fixed-archetype mode must not switch archetypes (plan §6)"
        )
    return plan
