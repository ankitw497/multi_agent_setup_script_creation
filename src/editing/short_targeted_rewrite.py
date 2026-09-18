"""B2s -- bounded targeted rewrite for shorts (Narration Lead / Sonnet, subscription lane).

2026-09-15, built on real evidence, not speculation: `orchestration/shorts_pipeline.py`'s
own module docstring pre-committed to this exact escalation -- "A bounded rewrite loop for
shorts can be added later if real runs show it's needed, the same way the long-form loop
only grew a revision cycle after real failures demonstrated one was necessary." Six live
verification rounds later, two failure categories (`micro_arc`/naive-attempt, `ending`
repetition-or-recap) kept resurfacing in new shapes after each prompt-only fix closed the
previous one -- the same signature that made long-form outgrow pure prompting (ERR-022
through ERR-026). This is that evidence.

Deliberately much smaller than long-form's A3+B2 pair:
- No separate "A3" planning call -- C1s's own `CritiqueIssue.recommended_intent` +
  `scene_ids` (required by review/short_critic.py's own prompt, added alongside this) are
  already the plan; a short has no archetype-dispute complexity, no replan-vs-rewrite
  choice, no beat structure to reason about. There's nothing left for a planner to decide.
- No plan-level fix at all -- a short's `ShortPlan` (title, micro_arc, hook/setup/mechanism/
  payoff summaries from A2s) is never touched here, only its SPOKEN narration. No real run
  has ever shown a plan-level defect that a narration rewrite couldn't reach; if one shows
  up, that's the trigger to extend this, not a reason to build it now.
- Bounded to exactly ONE attempt (`MAX_SHORT_REVISIONS` in orchestration/shorts_pipeline.py)
  -- a short is cheap enough that a second full regeneration (a fresh SC/A2s/B1s cycle on
  the next run) is a better use of a persistent miss than an unbounded in-run loop.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from narration.factual_invariants import NARRATION_FACTUAL_INVARIANTS
from narration.models import SceneNarration, SentenceNarration, SentenceType
from planning.shorts_models import ShortPlan
from review.models import CritiqueIssue

PLANNING_WPM = 130  # matches narration/short_generator.py's own -- see that constant's comment

TASK_PROMPT = """\
A critique already identified specific problems with named segments of
this short's narration. Rewrite ONLY the segments listed below, each
with the exact problem(s) found and what must change -- do not touch any
segment not listed, and do not expand scope beyond what each finding
actually asks for.

Common patterns worth naming explicitly, since they're the ones a rewrite
most often needs to fix:
- A payoff that verbatim-repeats (or barely paraphrases) a sentence
  already spoken in `mechanism` is not a payoff -- it must state the NEXT
  idea (the consequence, the "so what," the thing now true because of the
  mechanism), never restate what was just said.
- A payoff that recaps multiple prior points in summary form ("so first
  X, then Y, then Z...") is a recap, not a landing point -- land on ONE
  final consequence instead.
- A hook that opens on unexplained jargon, or flatly states the outcome
  before any tension exists, isn't a hook -- open on the concrete moment
  or contrast itself, saving the technical name for `setup`/`mechanism`.
- If the fix is "add the missing naive attempt" (`problem_fix`'s own
  requirement), write it as its own explicit sentence in `setup`, grounded
  in a real claim -- not implied, not merged into the problem statement.

Keep the same voice as the original: short punchy sentences, concrete
verbs, causal connectors. A rewritten segment must still fit naturally
against the segments you were NOT asked to touch -- read the current text
of neighboring segments (given below) before rewriting, so the join
doesn't repeat or contradict them. Ground every technical_assertion/
source_paraphrase sentence in a real claim from the registry given.

STAY WITHIN THE OVERALL BUDGET: `word_band` (min, max) is the TOTAL word
ceiling across all four segments, the same one the original draft was
built against -- `untouched_neighbors_word_count` tells you how much of
it the segments you are NOT touching already spend. Your rewritten
segment(s) must not push the total over `word_band`'s own max. A "fix" is
not real progress if it adds enough words to trade one problem for a
measured-duration overrun -- when a fix needs more content (e.g. adding a
missing naive-attempt sentence), cut a less essential clause elsewhere in
the SAME segment to make room, rather than letting the segment grow
unchecked.

""" + NARRATION_FACTUAL_INVARIANTS


class RewrittenSentence(BaseModel):
    text: str
    sentence_type: SentenceType
    claim_refs: list[str] = Field(default_factory=list)


class RewrittenSegment(BaseModel):
    # Literal, not a bare str (2026-09-16, found on review -- the same fix already
    # applied to narration/short_generator.py::GeneratedSegment, missed here when this
    # module was built the next day): an unconstrained str let a typo'd segment name
    # silently fail to match any real scene_id in `rewritten_by_id.get(...)`, which
    # would silently DROP the requested fix (the original, unfixed text survives
    # byte-for-byte) with no error anywhere -- exactly the kind of failure a targeted
    # rewrite exists to prevent, happening invisibly inside the rewrite itself.
    segment: Literal["hook", "setup", "mechanism", "payoff"]
    sentences: list[RewrittenSentence] = Field(default_factory=list)


class ShortTargetedRewrite(BaseModel):
    segments: list[RewrittenSegment] = Field(default_factory=list)


def _claim_payload(claim: Claim) -> dict:
    return {"claim_id": claim.claim_id, "claim": claim.claim, "verification_status": claim.verification_status}


def _touched_segment_intents(critical_issues: list[CritiqueIssue]) -> dict[str, list[str]]:
    """segment -> every recommended_intent naming it. Issues with empty `scene_ids`
    name nothing actionable and are silently skipped -- review/short_critic.py's own
    prompt now requires scene_ids precisely so this isn't the common case."""
    touched: dict[str, list[str]] = {}
    for issue in critical_issues:
        for segment in issue.scene_ids:
            touched.setdefault(segment, []).append(issue.recommended_intent)
    return touched


def apply_short_targeted_rewrite(
    plan: ShortPlan, narration: list[SceneNarration], claims: list[Claim],
    critical_issues: list[CritiqueIssue], narration_lead: Agent,
) -> list[SceneNarration]:
    touched = _touched_segment_intents(critical_issues)
    if not touched:
        return narration  # nothing actionable named -- no-op, same guard as long-form's B2

    # 2026-09-17 (found on review): a duplicate scene_id in `narration` is exactly the
    # malformed-output shape verification/hard/shorts.py::check_segment_completeness exists
    # to catch (a non-rewritable hard failure) -- but if the SAME review round also raises an
    # independent critical CritiqueIssue naming that segment, this function used to proceed
    # anyway: `scene_by_id`/`rewritten_by_id` are both keyed purely by scene_id, so one
    # duplicate's content silently vanished from the rewrite prompt, and the merge loop below
    # then overwrote BOTH duplicates with identical text -- "fixing" the named issue while
    # leaving the actual duplicate-segment defect in place. Bail out the same way the
    # `not touched` case above does; a run in this shape needs a fresh regeneration, not a
    # targeted rewrite that can't even address one segment unambiguously.
    if len({s.scene_id for s in narration}) != len(narration):
        return narration

    scene_by_id = {s.scene_id: s for s in narration}
    segments_payload = []
    for segment, intents in touched.items():
        scene = scene_by_id.get(segment)
        if scene is None:
            continue  # a critique named a segment that doesn't exist in this narration
        segments_payload.append({
            "segment": segment,
            "current_text": " ".join(s.text for s in scene.sentences),
            "problems_to_fix": intents,
        })
    if not segments_payload:
        return narration

    neighbors_payload = [
        {"segment": s.scene_id, "text": " ".join(sent.text for sent in s.sentences)}
        for s in narration if s.scene_id not in touched
    ]
    # 2026-09-16 (found on review): this prompt previously carried NO word-budget
    # context at all, unlike the original B1s generation prompt -- confirmed live as a
    # real contributor to a short whose rewrite was "kept, not worse" by hard-failure
    # count, yet still measured over the duration cap once its real TTS ran, because
    # nothing ever told the rewrite it had a ceiling to respect.
    untouched_neighbors_word_count = sum(
        len(sent.text.split()) for s in narration for sent in s.sentences if s.scene_id not in touched
    )

    payload = {
        "micro_arc": plan.micro_arc, "bridge": plan.bridge.model_dump(),
        "segments_to_rewrite": segments_payload, "untouched_neighbor_segments": neighbors_payload,
        "word_band": list(plan.narration.word_band), "untouched_neighbors_word_count": untouched_neighbors_word_count,
        "available_claims": [_claim_payload(c) for c in claims],
    }
    # timeout_s=300 (2026-09-18, was 120): confirmed live on the final live-verify run --
    # this exact call timed out at 120s after all 3 of claude_cli.py's own retries were
    # exhausted (ERR-082-adjacent finding). Long-form's own analogous rewrite call
    # (editing/targeted_rewrite.py) already sits at 300s for the same reason ("matches B1's
    # own timeout_s=300 -- a full-scale Sonnet call") -- this one was left at a much
    # tighter 120s despite doing the same kind of call, just scoped to fewer segments.
    rewritten = narration_lead.run(
        pass_id="B2s", mode="SHORT_TARGETED_REWRITE", task_prompt=TASK_PROMPT,
        payload=payload, schema=ShortTargetedRewrite, timeout_s=300,
    )
    # PIPELINE_AUDIT_2026-09-17.md finding: filtered to `touched` -- this module's own
    # docstring/prompt promise "Rewrite ONLY the segments listed... do not touch any
    # segment not listed" was never actually enforced in code. If the model "helpfully"
    # also returns a segment that wasn't requested, it must not be silently applied.
    rewritten_by_id = {s.segment: s for s in rewritten.segments if s.segment in touched}

    result: list[SceneNarration] = []
    for scene in narration:
        rs = rewritten_by_id.get(scene.scene_id)
        if rs is None:
            result.append(scene)  # untouched, byte-for-byte
            continue
        sentences = [
            SentenceNarration(text=s.text, sentence_type=s.sentence_type, claim_refs=s.claim_refs)
            for s in rs.sentences
        ]
        word_count = sum(len(s.text.split()) for s in sentences)
        result.append(SceneNarration(
            scene_id=scene.scene_id, sentences=sentences, est_seconds=word_count / PLANNING_WPM * 60,
        ))
    return result
