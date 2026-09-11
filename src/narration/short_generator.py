"""B1 (short rhythm profile) -- short narration first draft (Narration Lead / Sonnet, subscription lane) (plan §20.7, §20.8).

Same voice IDENTITY as long-form, a different RHYTHM: shorts have no
narrative oxygen for a recap, a takeaway paragraph, or a reserved
subscribe slot (plan §20.4) -- the long-form 22-word-sentence median is
almost certainly wrong at 60 seconds, so this gets its own short prompt
rather than reusing narration/generator.py's.

Narrated as four fixed segments (hook/setup/mechanism/payoff), matching
ShortPlan's own shape -- not a scene_plan the way long-form has one,
since a 45-60s short doesn't need scene-level planning granularity.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from planning.shorts_models import ShortPlan

from .models import SceneNarration, SentenceNarration, SentenceType

PLANNING_WPM = 167

TASK_PROMPT = """\
Write the spoken narration for this short, one continuous piece across
four segments: hook, setup, mechanism, payoff. Rhythm for 45-60 seconds,
not a shrunken long-form video: no recap, no takeaway paragraph, and no
UNPROMPTED subscribe ask invented on your own -- the ONLY place a
follow-up line ever belongs is the exact `bridge.mode`-gated case in the
`payoff` segment instructions below; never add one anywhere else, and
never skip it there when `bridge.mode` requires it. Write for listening,
short punchy sentences more than long-form's, concrete verbs, causal
connectors.

- `hook` segment: the interesting thing HAPPENS here, in the first 0-3
  seconds worth of words -- do not explain it yet, just create the tension
  the `hook` event describes.
- `setup` segment: the minimum context needed to make the hook click --
  a concrete failure, number, or contrast, not a preamble.
- `mechanism` segment: explain the ONE mechanism -- do not tour several.
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
"""


class GeneratedSentence(BaseModel):
    text: str
    sentence_type: SentenceType
    claim_refs: list[str] = Field(default_factory=list)


class GeneratedSegment(BaseModel):
    segment: str  # "hook" | "setup" | "mechanism" | "payoff"
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
