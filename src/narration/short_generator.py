"""B1 (short rhythm profile) -- short narration first draft (Narration Lead / Sonnet, subscription lane) (plan §20.7, §20.8).

Same voice IDENTITY as long-form, a different RHYTHM: shorts have no
narrative oxygen for a recap, a takeaway paragraph, or a reserved
subscribe slot (plan §20.4) -- the long-form 22-word-sentence median is
almost certainly wrong at short-form length, so this gets its own short
prompt rather than reusing narration/generator.py's.

Narrated as four fixed segments (hook/setup/mechanism/payoff), matching
ShortPlan's own shape -- not a scene_plan the way long-form has one,
since a short (up to 120s, 2026-09-16) doesn't need scene-level planning
granularity.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from planning.shorts_models import ShortPlan

from .factual_invariants import NARRATION_FACTUAL_INVARIANTS
from .models import SceneNarration, SentenceNarration, SentenceType

# 2026-09-16 (found on review, self-inconsistency): this was 167 (long-form's own
# assumption) even after `word_band` was recalibrated against confirmed real edge-tts
# evidence (~130wpm -- planning/shorts_models.py's own comment on ShortNarration) --
# `est_seconds` computed from this constant fed the CHEAP pre-TTS duration gate
# (verification/hard/shorts.py::check_duration_estimate), so that gate was silently
# ~28% optimistic (167/130) the whole time this session, real TTS being the only thing
# that ever caught the difference. Long-form's own rhythm (22-word-sentence median) is
# a different, slower cadence than the short punchy sentences this module's own
# docstring says shorts are written in -- there was never good reason to share the
# same constant.
PLANNING_WPM = 130

TASK_PROMPT = """\
Write the spoken narration for this short, one continuous piece across
four segments: hook, setup, mechanism, payoff. No recap, no takeaway
paragraph, and no UNPROMPTED subscribe ask invented on your own -- the
ONLY place a follow-up line ever belongs is the exact `bridge.mode`-gated
case in the `payoff` segment instructions below; never add one anywhere
else, and never skip it there when `bridge.mode` requires it. Write for
listening, short punchy sentences more than long-form's, concrete verbs,
causal connectors used as seasoning, not a default template -- let most
sentences open plainly with no connector at all, and never lean on the
same rhetorical device (e.g. a "not X, but Y" contrast) more than once in
a script this short; a repeated tell is far more noticeable at 90 seconds
than at 15 minutes.

STAY WITHIN `word_band` (min, max) TOTAL WORDS, summed across all four
segments combined -- treat the max as a real ceiling, not a soft
suggestion. Real synthesized speech reliably runs SLOWER than a casual
seconds-based guess would predict; a script that reads fine in your head
against `target_duration_seconds` can measure well past it once actually
spoken. When in doubt, cut a sentence rather than approach the top of the
band -- there is real room in this budget (up to 120 seconds); use it to
give the required content (the arc's own beat, the mechanism, the payoff)
its own real sentence, never to pad with restatement or filler.

`micro_arc` is a MANDATORY structural shape, not flavor text -- MOST
narration drafts fail because they slide into a generic "here's the
problem, here's the mechanism that fixes it" shape regardless of which
arc was actually assigned. That generic shape is WRONG for 6 of these 7
arcs. Before writing, identify which segment (`setup` or `mechanism`)
carries YOUR arc's own required extra beat below, and write that beat as
its own explicit sentence -- not implied, not skipped:

- `contradiction_resolution`: the `setup` segment MUST state two facts
  that genuinely conflict, in tension with each other, BEFORE `mechanism`
  resolves it. If your setup only states one fact, this arc is not
  satisfied -- add the second, conflicting one.
- `problem_fix`: the `setup` segment MUST describe a naive, intuitive
  first attempt at fixing the problem, AND say that it fails or falls
  short -- as its own sentence, distinct from stating the problem itself.
  Only THEN does `mechanism` introduce the real fix. Writing "here's the
  problem" followed immediately by "here's the fix" -- with no failed
  attempt in between -- is THE single most common miss on this pass and
  does not satisfy `problem_fix`; if you cannot state a concrete failed
  attempt, this is not actually a `problem_fix` short.
  The naive attempt must be something a real practitioner would actually try first,
  not a strawman invented to make the arc fit -- confirmed live: a fabricated "fix"
  that isn't a real, recognizable first instinct reads as contrived, and an attempt
  that gets explained away conceptually ("that wouldn't really work because...") is
  not the same as ENACTING a failed attempt and showing the concrete way it falls short.
  Confirmed live across multiple shorts, in multiple runs, about completely different
  topics: a "The real fix ___" sentence -- regardless of which verb follows ("is,"
  "works," "scales," or any other predicate) -- the TEMPLATE is the tell, not any one
  specific verb -- has become a DEFAULT opener for the exact moment `mechanism`
  introduces the actual solution. A viewer who watches more than one of this channel's
  shorts will notice the same opening line reused across unrelated videos -- vary how you make this transition every time (e.g. name the mechanism directly,
  state what changes, or ask what the fix would need to do) rather than
  reaching for this phrase, in any of its forms, by default.
- `before_after`: `setup` MUST describe the concrete "before" state as
  its own sentence; `mechanism` then shows the concrete "after" state,
  with the mechanism itself as the pivot between them.
- `question_answer`: `setup` MUST pose the actual question as an explicit
  question, not an implied one, before `mechanism` answers it.
- `prediction_explanation`: `setup` MUST state a specific prediction or
  expected outcome as its own sentence before `mechanism` explains why it
  happens.
- `myth_correction`: `setup` MUST explicitly name the common myth or
  misconception, as a sentence a viewer would recognize believing, before
  `mechanism` corrects it -- correcting something never named isn't a
  correction a viewer can follow.
- `mini_derivation`: `mechanism` MUST walk through one real derivation
  step (an actual computation or logical move) -- not a restated goal
  dressed up as a step.

Only `mini_derivation` places its required beat in `mechanism`; every
other arc's required extra beat belongs in `setup`, distinct from the
plain problem/context statement `setup` already carries.

State that required beat as ONE tight sentence (roughly 15-20 words), not a
paragraph -- confirmed live across multiple shorts, multiple runs, that
this instruction alone does not stop the overrun: `setup` segments still
ran 1.1x-2.4x their own diagnostic target even when the required beat WAS
technically "one sentence." The actual failure shape is JUSTIFYING the
beat instead of just stating it -- e.g. explaining in detail WHY the naive
attempt seemed reasonable, walking through HOW it fails step by step, or
building up to a question with its own supporting reasoning first. State
the naive attempt, state that it fails (or state the contradiction/myth/
prediction), and stop -- the WHY belongs in `mechanism`, not `setup`. If
your one sentence needs a clause explaining its own reasoning, it is
carrying `mechanism`'s job, not `setup`'s. `setup`'s job is still "the
minimum context needed to make the hook click" -- the required beat is an
ADDITION to that job, not a license to expand it into its own
mini-explanation.

- `hook` segment: the interesting thing HAPPENS here, in the first 0-3
  seconds worth of words -- do not explain it yet, just create the tension
  the `hook` event describes. NEVER leave this segment empty. If `hook.
  narration` is blank (a visual-only hook design), you still MUST write a
  short spoken line here -- describe the concrete moment the visual
  shows, or voice the tension it creates. A short with no spoken words in
  its first 3 seconds is broken; `hook.visual` carries the image, not an
  excuse to stay silent. NEVER open on a technical term or jargon
  ("saturated softmax", "d_k scaling") before the viewer has any reason to
  care what it means, and NEVER open by flatly stating the outcome/fact as
  settled -- that gives the answer away before any tension exists. Open on
  the concrete moment, number, or contrast itself; save the technical name
  for `setup`/`mechanism`, once the viewer already wants to know it.
- `setup` segment: the minimum context needed to make the hook click --
  a concrete failure, number, or contrast, not a preamble.
- `mechanism` segment: explain the ONE mechanism -- do not tour several.
  If `micro_payoffs` (given below) is non-empty, weave them in HERE, as
  brief intermediate wins along the way to the central payoff -- never save
  them up and list them at the end. A payoff segment that lands
  `payoff_central` and THEN works through leftover `micro_payoffs` reads
  as exactly the recap/reserved-outro this format has no room for (a short
  has one ending, not a sequence of them after the real one).
- `payoff` segment: land the central payoff FIRST, then handle `bridge.mode`:
  - NONE: stop right there -- the payoff itself is the ending, never add a
    subscribe ask.
  - SPOKEN: you MUST add one short final sentence naming the follow-up
    action out loud (e.g. "Follow for the next piece of this mechanism" /
    "Part 2 breaks down what comes next -- follow so you don't miss it").
    This is a REQUIRED sentence, not optional -- a payoff segment with no
    such line when `bridge.mode` is SPOKEN is incomplete, the single most
    common miss on this pass.
  - ONSCREEN: the spoken payoff still ends cleanly on its own (the bridge
    itself will render as on-screen text elsewhere, not spoken) -- do not
    also speak a redundant bridge line.
  - PLATFORM_LINK: same as ONSCREEN -- the link lives in the platform UI,
    not the spoken track.

Ground every technical_assertion/source_paraphrase sentence in a real
claim from the registry given -- cite it in `claim_refs`. Never introduce
a technical claim that is not in the claim registry; a derived short's
claims are already scoped to what the parent verified.

""" + NARRATION_FACTUAL_INVARIANTS


class GeneratedSentence(BaseModel):
    text: str
    sentence_type: SentenceType
    claim_refs: list[str] = Field(default_factory=list)


class GeneratedSegment(BaseModel):
    # Literal, not a bare str (2026-09-15 defensive fix, found on static review -- not yet
    # observed live): downstream code finds segments by exact scene_id match ("hook",
    # "setup", ...) -- an unconstrained str let a typo'd or invented segment name silently
    # produce a "missing" hook/setup/etc. everywhere that matching happens, rather than a
    # clear validation error at the one place it actually occurred.
    segment: Literal["hook", "setup", "mechanism", "payoff"]
    sentences: list[GeneratedSentence] = Field(default_factory=list)


class GeneratedShortNarration(BaseModel):
    segments: list[GeneratedSegment] = Field(default_factory=list)


def _claim_payload(claim: Claim) -> dict:
    return {"claim_id": claim.claim_id, "claim": claim.claim, "verification_status": claim.verification_status}


def generate_short_narration(
    plan: ShortPlan, claims: list[Claim], narration_lead: Agent,
) -> list[SceneNarration]:
    allowed_ids = set(plan.parent.allowed_fact_ids) if plan.parent else {c.claim_id for c in claims}
    scoped_claims = [c for c in claims if c.claim_id in allowed_ids]

    payload = {
        "central_insight": plan.central_insight, "micro_arc": plan.micro_arc,
        "hook": plan.hook.model_dump(), "setup": plan.setup, "mechanism": plan.mechanism,
        "payoff_central": plan.payoff_central, "micro_payoffs": plan.micro_payoffs,
        "bridge": plan.bridge.model_dump(), "target_duration_seconds": plan.narration.target_duration_seconds,
        # word_band (2026-09-15): existed on ShortNarration since before this pass was
        # written but was never actually sent to the model -- confirmed live as a real
        # cause of duration overruns (measured TTS audio running well past the 60s hard
        # cap) with only a vague "45-60 seconds" phrase to go on.
        "word_band": list(plan.narration.word_band),
        "available_claims": [_claim_payload(c) for c in scoped_claims],
    }
    generated = narration_lead.run(
        pass_id="B1s", mode="SHORT_FIRST_DRAFT", task_prompt=TASK_PROMPT,
        payload=payload, schema=GeneratedShortNarration, timeout_s=180,
    )

    result: list[SceneNarration] = []
    for segment in generated.segments:
        sentences = [
            SentenceNarration(text=s.text, sentence_type=s.sentence_type, claim_refs=s.claim_refs)
            for s in segment.sentences
        ]
        word_count = sum(len(s.text.split()) for s in sentences)
        result.append(SceneNarration(
            scene_id=segment.segment, sentences=sentences, est_seconds=word_count / PLANNING_WPM * 60,
        ))
    return result
