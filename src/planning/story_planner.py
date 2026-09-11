"""A2 -- ONE archetype + full story blueprint (Story Lead / GPT strong) (plan §5, §8, §9, §19).

The single most consequential call in the pipeline: title, hook, CTA,
question chain, beats (with forward drivers), mini-payoffs, and ending --
all decided here, before a word of narration exists (the design doc's
core principle).

Split into two stages since 2026-09-10 (ERR-010/ERR-023): A2 itself
(this call, `TASK_PROMPT` below) resolves the archetype and full
structure via `StoryStructure`; A2b (`scene_expander.py`) then fills in
`StoryPlan.scene_plan` one beat at a time, using a word target that
`beat_word_budget.py` computes deterministically. Asking one call to also
correctly sum a 20-30-scene word budget against a target duration was
reliably unreliable (a live run returned 5 scenes / ~525 words against a
~1670-word target); each beat's own much smaller target is independently
achievable, and Python's own sum is exact by construction.
"""
from __future__ import annotations

from agents.base import Agent
from facts.models import AssumptionLedger, Claim, SourceUnit
from llm.budget import BudgetCounter

from .archetypes import ALL_ARCHETYPES, load_archetype_specs
from .beat_word_budget import allocate_beat_word_budgets
from .models import ReplanFeedback, SourceBrief, StoryPlan, StoryStructure, ViewerLedger
from .scene_expander import expand_beat_scenes

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
the resolved archetype's CORE roles it instantiates -- put THAT
archetype-specific term (e.g. "justified_step" for derivation,
"problem_to_solution_pair" for build) in `archetype_stage`, if any
(optional roles are allowed but never required).

Separately, ALSO set `archetype_role` to a DIFFERENT, FIXED, generic term
from this exact list, never an archetype-specific one: hook, contradiction,
investigation, problem_fix, mechanism, comparison, derivation, observations,
payoff. This is the ONE vocabulary shared across all six archetypes that
later decides which visual component this beat's scenes are allowed to use
when rendered -- pick whichever term this beat's actual content genuinely
is (a beat walking through how something works is `mechanism`; a beat
contrasting two things is `comparison`; a beat resolving a real failure is
`contradiction`; and so on), regardless of which archetype you resolved.
Concrete worked example -- do not confuse the two fields, they hold
DIFFERENT vocabularies and are almost never the same string:
  archetype = "derivation", this beat justifies one algebraic step
  -> archetype_stage = "justified_step" (derivation's own term)
  -> archetype_role = "mechanism" (the fixed generic term, NOT "justified_step")
Leave `archetype_role` blank only for a beat that is genuinely none of the
nine terms above -- blank should be the rare exception, not most beats,
and never every beat; a mostly-blank plan means every beat will render
with the same generic fallback components regardless of what it actually
covers. Also needed: a `forward_driver`
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
deliberately withholds. If a claim or source unit gives you a concrete,
specific illustration of the hook's tension (an actual example sentence, a
specific number, a named scenario -- not a generic description of the
category of problem), `hook.tension` must USE that concrete illustration
directly, not abstract it into a general statement. "The same word can
mean two different things depending on context" is the kind of vague
restatement to avoid when the source already hands you the literal
sentence pair that proves it -- use the literal example.

If you used a concrete illustration for the hook, ALSO populate
`running_example` with that same illustration, structured for reuse:
`label` (a short name for it), `description` (one sentence), and `values`
(a dict of the concrete named quantities/objects involved, in whatever
shape this source's own illustration actually takes -- named measurements
with their numbers for a numeric example, named entities and the property
that distinguishes them for a qualitative one, named steps and their
outputs for a process). This is the ONE example every later beat's scene
expansion (A2b) and narration will be told to reuse -- do not leave it
blank if the hook has a real concrete illustration, and never invent a
second, different example for the same underlying concept.

If pacing genuinely matters for a specific structural role this archetype
gives one of your beats (e.g. the central problem should be unmistakable
to the viewer within the first 20-40 seconds, or a key mechanism should be
previewed before too much setup accumulates), declare it in
`retention_deadlines` as `{archetype_role, max_seconds}` -- `archetype_role`
must exactly match the value you gave that beat, and `max_seconds` is the
CUMULATIVE runtime (from video start) by which that beat's content should
be fully covered. Leave `retention_deadlines` empty when no beat has this
kind of hard pacing requirement -- most archetypes will not need one, and
this must never be used just to compress every beat evenly.

If (and only if) the source builds up a mathematical or algorithmic
expression progressively across multiple beats -- a raw form that later
gets refined, scaled, normalized, or combined into a final form -- register
each distinct stage ONCE in `formula_stages`, in the order the source
derives them, each with a short `stage_id` (e.g. "raw_score",
"scaled_score", "output") and its exact symbolic `expression` as the
source states it. If the source works a running numeric example through
these stages, also give each stage its OWN `values` dict for that stage's
actual worked numbers (e.g. `{"item_a": "4.8"}` for an early stage, a
DIFFERENT number for the same named quantity at a later stage once the
source's own transformation has actually been applied to it) -- never
reuse one stage's numbers as another's; if the source
never actually changes the numbers between stages, leave `values` empty
for the later stage rather than restating an unchanged number as if it
were newly computed. Leave `formula_stages` empty for any source that has
no such evolving expression -- most sources will not.

The CTA's `intent` should default to VALUE_LINKED (it names the payoff just
earned and the channel's promise) unless there's a clear reason for another
intent. `primary_after_beat` must be a beat that has a real payoff, not the
first beat that happens to exist.

The ending must resolve the hook's promise, compress the mechanism into a
usable mental model, and state `viewer_can_now` as a capability (diagnose /
predict / build / explain), never a feature list.

Do not produce a scene-by-scene breakdown here -- that is a separate pass
(A2b), given your beats afterward. Focus entirely on getting the
archetype, hook, CTA, beats, and ending right; a beat is a story unit that
will later expand into several scenes when the source has that much real
content to cover, not a single scene itself.

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
structural issue must be visibly addressed in this new plan -- e.g. if
specific source unit ids were listed as uncovered, this plan's beats must
now actually cover them (a word-budget shortfall specifically is handled
by a separate deterministic pass afterward, not something you need to fix
here by adding more beats than the source actually supports).
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
    structure = story_lead.run(
        pass_id="A2", mode="PLAN", task_prompt=TASK_PROMPT,
        payload=payload, schema=StoryStructure, budget=budget, estimated_usd=0.10,
        # No max_tokens override here -- it comes from story_lead's own
        # `default_max_tokens` (config/models.yaml, per alias). A real
        # 2048-token default truncated a full StoryPlan mid-string
        # (2026-09-10, ERR-021) before the scene-plan split existed;
        # `openai_story_strong` (gpt-4o) keeps 4000 there for exactly this
        # reason. A reasoning-capable alias needs its OWN, usually larger,
        # ceiling -- reasoning tokens count against the same budget as the
        # actual output (confirmed 2026-09-11 for gpt-5.6-sol: an unset/
        # default reasoning effort burned the entire ceiling with zero room
        # left for the real StoryStructure). Per-alias config is what lets
        # each model carry the ceiling it actually needs.
    )
    if archetype_override and structure.archetype != archetype_override:
        raise ValueError(
            f"A2 returned archetype {structure.archetype!r} but the run pinned "
            f"{archetype_override!r} -- fixed-archetype mode must not switch archetypes (plan §6)"
        )

    # A2b (ERR-010/ERR-023 fix): each beat's own word target is computed
    # deterministically, then filled by one small, independently-achievable
    # call per beat -- never one call asked to sum the whole plan itself.
    # V2 fix (STORY_IMPROVEMENT_PLAN.md Phase 1): a ViewerLedger threads
    # through this loop beat-to-beat -- each beat's expansion now knows
    # what earlier beats already taught, instead of expanding in isolation
    # (the mechanical cause of cross-scene repetition). No extra LLM call:
    # the loop was already sequential, this just carries state between its
    # existing calls.
    beat_word_budgets = allocate_beat_word_budgets(
        structure.beats, target_duration_seconds, retention_deadlines=structure.retention_deadlines,
    )
    scene_plan = []
    ledger = ViewerLedger(running_example=structure.running_example, formula_stages=structure.formula_stages)
    for i, beat in enumerate(structure.beats):
        target_words = beat_word_budgets.get(beat.beat_id, 0)
        if target_words <= 0:
            continue
        previous_beat = structure.beats[i - 1] if i > 0 else None
        next_beat = structure.beats[i + 1] if i + 1 < len(structure.beats) else None
        beat_scenes, ledger = expand_beat_scenes(
            beat, target_words, claims, story_lead, budget, ledger,
            previous_beat=previous_beat, next_beat=next_beat, central_question=structure.central_question,
        )
        scene_plan.extend(beat_scenes)

    return StoryPlan(**structure.model_dump(exclude={"scene_plan"}), scene_plan=scene_plan)
