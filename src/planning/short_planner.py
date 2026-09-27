"""A2s -- short story planner (Story Lead / GPT mini) (plan §20.6).

Selects the top `shorts.count` candidates from SC's shortlist (default 3;
fewer if fewer are genuinely self-contained -- must not pad to the count)
and designs each as its own ShortPlan. `parent` linkage (`final_plan_hash`,
`allowed_fact_ids`) is deliberately NOT the model's job -- it's exact
bookkeeping computed in Python from the selected candidate's own
`beat_ids`, the same "arithmetic is deterministic, not model-voted"
principle applied to fact-set scoping (plan §9's Factual gate: a derived
short may not introduce a fact outside its allowed set).
"""
from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from llm.budget import BudgetCounter
from planning.models import StoryPlan

from .shorts_models import (
    HookEvent, MicroArc, ShortBridge, ShortGoal, ShortNarration, ShortParent, ShortPlan,
    ShortsCandidate, ShortVisual,
)

DEFAULT_SHORTS_COUNT = 3  # plan §20.6: a ceiling, not a quota

TASK_PROMPT = """\
From the candidate shortlist below, select up to `shorts_count` candidates
that would genuinely make strong, self-contained shorts -- fewer is fine
and expected if fewer are genuinely self-contained; never pad the count
with a weak candidate just to fill it. Candidate quality is multi-factor,
not knowledge gain alone: instant intelligibility, hookability, surprise
or contrast, self-containedness, low prerequisite burden, visual
singularity, payoff strength, relevance, bridge potential. The best
long-form insight is often a poor short; a side observation is sometimes
the strongest one.

Design each selected candidate as its own short:
- `title`: a SHORT title (3-8 words, a real title, never a full sentence
  copied verbatim from the hook or payoff) that still REUSES 2-3 actual
  concrete words or phrases from the hook event, the central payoff,
  `central_insight`, OR `visual.states`/`visual.dominant_object` -- not
  just a thematically-related abstract label. A title checked mechanically
  for shared words against those four; an
  abstract technical label ("Pronoun Resolution in Language Models") that
  never says any of their own concrete words fails that check even when
  it's thematically on-topic -- but copying an entire sentence verbatim
  ("With d_k = 128, a score like 12.5 is typical...") isn't a title
  either. Pull 2-3 real words FROM their concrete language into a short,
  punchy phrase -- don't paraphrase away from them, and don't just quote
  them wholesale.
  A third failure mode, distinct from both above: a title built ENTIRELY
  from technical/jargon terminology that appears in `central_insight` but
  never in the hook's own concrete language also fails this check, even
  though it looks specific rather than vague. Confirmed live: a title
  "Permutation Equivariance Limitation" for a hook about shuffling "token
  cards" shared almost no words with either the hook or its own payoff --
  reach into the HOOK's concrete language too, not just `central_insight`'s
  technical framing.
  A fourth, related failure (2026-09-25, Phase 30 P1 item 3): this
  recurred even when the title DID pass the mechanical word-overlap check
  -- a real title "Self-Attention and Permutation" pulled its words
  straight from `central_insight`'s own abstract framing, while the SAME
  short's `visual.states` held a genuinely concrete, memorable anchor
  (two contrasted example sentences) the title never touched at all,
  because `visual` wasn't even in the reuse pool. Prefer pulling from the
  single most concrete, surprising detail actually available -- a specific
  example, number, or named object -- over a topic label, even when the
  topic label would pass the word-overlap check on a technicality. When
  `visual.states`/`dominant_object` holds a real concrete example, it is
  usually the stronger source to pull from than `central_insight`'s own
  abstract restatement of the same idea.
  This check matches EXACT words, never a different grammatical form of
  the same root (no stemming) -- "equivariant" and "Equivariance" count as
  completely different words even though a person reads them as the same
  concept. When you pull a word from the hook/payoff/`central_insight`,
  reuse the SAME form it already appears in there, not a noun/verb/
  adjective variant of it.
- `goal`: DISCOVERY (new-viewer reach), BRIDGE (payoff opens onto the
  parent's larger question), or SERIES (recognisably one piece of a
  larger series) -- pick whichever this candidate genuinely serves best.
  Each candidate already carries its own `bridge_question` from the earlier
  candidate-finder pass -- when it's non-empty, that IS a real, already-
  judged signal this candidate has bridge potential; do not silently ignore
  it just because this prompt's own instructions focus on the fields below.
  DISCOVERY is the safe default this pass reaches for even when a
  candidate's own payoff (or its own non-empty `bridge_question`) genuinely
  opens onto the parent's larger question or clearly belongs to a
  recognisable series -- confirmed live: a full batch landed 100% DISCOVERY
  when at least one candidate's payoff (e.g. "so what happens to the OTHER
  heads?") plainly invited BRIDGE or SERIES.
  Before defaulting a candidate to DISCOVERY, ask honestly whether its own
  payoff already gestures at a bigger question or a next piece -- all three
  goals grow the channel, but differently (plan §20.1), and a batch that
  never varies has quietly given up two of the three growth levers.
- `central_insight`: the ONE thing this short teaches.
- `micro_arc`: contradiction_resolution / problem_fix / before_after /
  question_answer / prediction_explanation / myth_correction /
  mini_derivation -- may differ from the candidate's own suggestion if a
  different arc fits better. Whichever you choose, `setup` (or
  `mechanism` for `mini_derivation` only) MUST actually contain the real,
  source-grounded content that arc requires, or the narration pass
  downstream has nothing true to narrate and either invents something
  ungrounded or silently drops the requirement:
  - `contradiction_resolution`: `setup` states two facts from the source
    that genuinely conflict or are in tension.
  - `problem_fix`: fill in the dedicated `naive_attempt` field (NOT `setup`
    -- see below) with a real naive/intuitive attempt (grounded in the
    source, not invented) and state that it fails or falls short there --
    distinct from just stating the problem. `problem_fix` is the arc this
    pass defaults to reaching for even when it doesn't fit -- do NOT pick
    it just because a candidate has a problem-then-mechanism shape (almost
    every candidate does). Pick it ONLY when the source material gives you
    a genuine, nameable naive/intuitive attempt that actually fails -- not
    merely "the problem" restated. If you cannot name that specific failed
    attempt as a concrete sentence right now, this candidate is NOT a
    `problem_fix` short -- use `before_after` or `mini_derivation` instead,
    which fit a plain problem-then-mechanism shape without requiring a
    failed attempt at all, and leave `naive_attempt` blank. Confirmed live
    (STORY_IMPROVEMENT_PLAN.md Phase 30 P1 item 2): 3 of 4 real `problem_fix`
    shorts shipped with this requirement silently unmet -- `naive_attempt`
    left blank on a `problem_fix` selection now drops the short entirely
    rather than reaching the writer with nothing true to narrate, so an
    empty field here is not a safe default. The naive attempt must be
    something a real practitioner would actually try first, not a strawman
    invented to make the arc fit -- and it must be ENACTED (shown concretely
    failing), not explained away conceptually ("that wouldn't really work
    because...") -- a fabricated or merely-conceptual "fix" reads as
    contrived, the same bar `narration/short_generator.py`'s own writer
    prompt already holds the actual narration to.
  - `before_after`: `setup` states the concrete "before" state.
  - `question_answer`: `setup` poses the actual question explicitly.
  - `prediction_explanation`: `setup` states the specific prediction.
  - `myth_correction`: `setup` names the common myth/misconception itself.
  - `mini_derivation`: `mechanism` walks through one real derivation step.
  If the source material genuinely has nothing to support your chosen
  arc's required beat, choose a different arc rather than forcing it.
- `hook`: the interesting thing happening in the first 0-3 seconds
  (`starts_at_seconds` must be within that window) -- a visual may carry
  it before narration does.
- `setup`: the minimum context needed (should read as roughly a 3-10
  second beat, not a preamble) -- see the micro_arc requirement above for
  what else it must contain. For `problem_fix`, the naive attempt goes in
  `naive_attempt`, not here -- `setup` still carries whatever minimum
  context the naive attempt itself needs to make sense.
- `naive_attempt`: ONLY for `problem_fix` (see above) -- leave blank for
  every other `micro_arc`.
- `mechanism`: ONE mechanism, not a tour of several.
- `payoff_central`: the central payoff; `micro_payoffs` for any smaller
  ones along the way.
- `bridge`: PLATFORM_LINK / ONSCREEN / SPOKEN / NONE -- NONE is a valid
  and often correct choice; do not force a bridge that weakens the ending.
  But NONE for every short in a batch, batch after batch, is its own bias
  in the other direction, and subscribe is explicitly allowed to be earned
  here (plan §20.1: "optional, only after value, <=8 words"). When a
  payoff naturally invites "there's more where this came from" -- a BRIDGE
  goal, or a mechanism that's visibly step one of a larger idea -- a single
  short SPOKEN or ONSCREEN follow line (<=8 words, after the payoff, never
  replacing it) costs the ending nothing and gives a real viewer a real
  next action. Reach for it whenever the payoff genuinely supports it, not
  only when leaving it out would look obviously wrong. When you pick
  ONSCREEN or PLATFORM_LINK, you MUST also fill in `cta_text` with that
  exact short line (<=8 words, e.g. "Part 2 breaks down what's next") --
  it is rendered as on-screen text, not spoken, so an empty `cta_text`
  means nothing is ever shown at all. SPOKEN needs no `cta_text` (the line
  belongs in the narration itself); leave it empty for NONE too.
- `visual`: `dominant_object` (the one concrete thing the short visually
  centers on) is not enough by itself -- `states` MUST also be filled in,
  or the mechanism screen renders as plain text with no diagram at all.
  Give 2-4 short labels (2-4 words each) naming the SEQUENTIAL stages the
  dominant object visibly moves through, matching the mechanism's own
  steps -- e.g. for a scaling short: `["raw scores", "scaled scores",
  "softmax weights"]`; for a masking short: `["unmasked", "masked",
  "zeroed after softmax"]`. This is not optional decoration -- an empty
  `states` list is a real content gap, not a valid "no diagram needed"
  signal. Also give `safe_zones` to keep clear of platform UI overlays.
- `source_beat_ids`: the exact beat id(s) (from the ones given) this
  design is actually built from -- never invent a beat id.

A derived short's every factual claim must trace back to the source
beats' own claims -- never introduce a technical fact the parent content
doesn't already support.
"""


class ShortPlanDraft(BaseModel):
    """A2s's actual output -- everything in a ShortPlan except `parent`,
    which Python assembles afterward from `source_beat_ids` (see module
    docstring)."""

    title: str = ""
    goal: ShortGoal = "DISCOVERY"
    central_insight: str
    micro_arc: MicroArc
    hook: HookEvent
    setup: str = ""
    naive_attempt: str = ""  # required (non-empty) when micro_arc == "problem_fix"
    mechanism: str = ""
    payoff_central: str = ""
    micro_payoffs: list[str] = Field(default_factory=list)
    bridge: ShortBridge = Field(default_factory=ShortBridge)
    visual: ShortVisual = Field(default_factory=ShortVisual)
    narration: ShortNarration = Field(default_factory=ShortNarration)
    source_beat_ids: list[str] = Field(default_factory=list)


class ShortPlanSelection(BaseModel):
    shorts: list[ShortPlanDraft] = Field(default_factory=list)


def _candidate_payload(candidate: ShortsCandidate) -> dict:
    return candidate.model_dump()


def _plan_hash(plan: StoryPlan) -> str:
    return "sha256:" + hashlib.sha256(plan.model_dump_json().encode("utf-8")).hexdigest()


def plan_shorts(
    candidates: list[ShortsCandidate], plan: StoryPlan, claims: list[Claim],
    story_lead: Agent, budget: BudgetCounter, run_id: str,
    shorts_count: int = DEFAULT_SHORTS_COUNT,
) -> list[ShortPlan]:
    if not candidates:
        return []

    known_beat_ids = {b.beat_id for b in plan.beats}
    payload = {
        "candidates": [_candidate_payload(c) for c in candidates],
        "shorts_count": shorts_count,
        "known_beat_ids": sorted(known_beat_ids),
    }
    selection = story_lead.run(
        pass_id="A2s", mode="SHORT_PLANNER", task_prompt=TASK_PROMPT,
        payload=payload, schema=ShortPlanSelection, budget=budget, estimated_usd=0.04,
    )

    final_plan_hash = _plan_hash(plan)
    claims_by_source_unit: dict[str, list[str]] = {}
    for c in claims:
        claims_by_source_unit.setdefault(c.source_unit, []).append(c.claim_id)

    plans: list[ShortPlan] = []
    for draft in selection.shorts[:shorts_count]:
        source_beat_ids = [bid for bid in draft.source_beat_ids if bid in known_beat_ids]
        if not source_beat_ids:
            continue  # every referenced beat was invalid -- nothing real to scope this short to
        # 2026-09-25 (Phase 30 P1 item 2): a `problem_fix` selection with no `naive_attempt`
        # violates this module's own TASK_PROMPT ("if you cannot name that specific failed
        # attempt... this candidate is NOT a problem_fix short") -- confirmed live 3 of 4
        # real cases shipped anyway. Drop it here, deterministically, rather than send the
        # writer a setup with nothing true to enact -- same "arithmetic is deterministic,
        # not model-voted" precedent as the invalid-beat check just above.
        if draft.micro_arc == "problem_fix" and not draft.naive_attempt.strip():
            continue
        source_unit_ids = {
            uid for bid in source_beat_ids for uid in next(b for b in plan.beats if b.beat_id == bid).source_unit_ids
        }
        allowed_fact_ids = sorted({cid for uid in source_unit_ids for cid in claims_by_source_unit.get(uid, [])})

        plans.append(ShortPlan(
            parent=ShortParent(
                run_id=run_id, final_plan_hash=final_plan_hash,
                source_beat_ids=source_beat_ids, allowed_fact_ids=allowed_fact_ids,
            ),
            title=draft.title, goal=draft.goal, central_insight=draft.central_insight,
            micro_arc=draft.micro_arc, hook=draft.hook, setup=draft.setup,
            naive_attempt=draft.naive_attempt,
            mechanism=draft.mechanism, payoff_central=draft.payoff_central,
            micro_payoffs=draft.micro_payoffs, bridge=draft.bridge,
            visual=draft.visual, narration=draft.narration,
        ))
    return plans


def check_bridge_selection_defaulted(candidates: list[ShortsCandidate], plans: list[ShortPlan]) -> str | None:
    """STORY_IMPROVEMENT_PLAN.md Phase 23 continuation, 2026-09-16: ERR-072's own prompt
    nudge (encourage BRIDGE/a follow line when the payoff supports it) has now shown 0%
    variation across two full real verification rounds (v08, v10 -- 10 shorts total) -- real
    evidence a prompt-only nudge alone isn't reliably changing behavior. This does NOT
    override the model's own selection (a real `bridge_question` candidate can legitimately
    lose to a stronger DISCOVERY candidate on other merits, and forcing a worse selection just
    to hit a variety target would be its own mistake) -- it only makes a real, already-
    computed signal VISIBLE when the model's own selection looks like a reflexive default
    rather than a genuine judgement call, the same "measure before gating" discipline Phase
    22's audit mechanism already uses. Returns `None` when there's nothing worth flagging
    (either the selection already varied, or no candidate ever had a real bridge signal to
    weigh in the first place)."""
    if not plans or any(p.goal != "DISCOVERY" or p.bridge.mode != "NONE" for p in plans):
        return None
    with_signal = [c for c in candidates if c.bridge_question.strip()]
    if not with_signal:
        return None
    return (
        f"NOTE: all {len(plans)} selected short(s) landed on goal=DISCOVERY/bridge=NONE, but "
        f"{len(with_signal)} of {len(candidates)} candidates had a real bridge_question -- "
        "worth checking whether this was a genuine judgement call or a reflexive default."
    )
