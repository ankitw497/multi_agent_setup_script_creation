"""C2b -- grounding completeness + fidelity (Review Lead / Gemini strong) (plan §5.1, §9 Appendix G #3).

CM accelerates grounding; C2b owns completeness. It receives the raw
narration, CM's own output, and the verified fact set -- and does NOT
trust CM's coverage. Two genuine judgement calls no deterministic check
can make:

1. Completeness: did CM miss a factual proposition CM marked
   grounding_required=False (or never touched)?
2. Fidelity: does a grounded sentence actually say what its cited claim
   says, or has paraphrasing drifted the meaning (e.g. "grows with
   tokens" silently becoming "grows quadratically with tokens")?

STORY_IMPROVEMENT_PLAN.md Phase 10: C2b used to return only a sparse
`CritiqueIssue[]` -- "no issue" was indistinguishable from "every sentence
was actually checked." It now returns one dense `GroundingVerdict` per
sentence (keyed by the same stable `sentence_id` CM uses), with coverage
enforced the same fail-closed way as CM. `grounding_verdicts_to_issues()`
derives the same kind of `CritiqueIssue`s callers relied on before, so
routing elsewhere (A3/aggregation) doesn't need to change shape.
"""
from __future__ import annotations

import random

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from llm.budget import BudgetCounter
from llm.concurrency import run_concurrently
from narration.models import SceneNarration, stamp_sentence_ids

from .models import CritiqueIssue, ReviewCoverageError

TASK_PROMPT = """\
You are independently checking grounding for a narration draft. Do not
trust the `grounding_required`/`grounding_refs` already attached to each
sentence -- another pass produced those, and your job is to catch what it
missed, not confirm it.

You MUST return exactly one verdict, keyed by `sentence_id`, for EVERY
sentence given -- never omit one, even a sentence that is obviously fine.
A verdict is your positive record that this sentence was actually checked,
not just a place to report a problem.

For every sentence, decide:
- `factual`: does it actually make a checkable factual proposition (a
  transition, a question, an analogy with no factual content is NOT
  factual, regardless of what it was marked upstream)?
- If `factual` is true:
  - `supported`: does at least one claim in the verified registry actually
    back this specific sentence? A sentence marked grounding_required=false
    upstream that you determine IS factual and IS supported by a real
    claim should still get `supported=true` -- you are recording the truth,
    not just confirming the earlier label.
  - `verified_claim_ids`: every claim id that actually supports it (empty
    if none do, even if one was cited).
  - `qualifier_preserved`: false if the cited claim only holds under a
    stated condition/assumption (its `required_qualifiers`) and the
    sentence drops that condition, stating it as an unconditional fact --
    also false for an absolute motivation/limitation claim ("X can only
    ever do one thing") when the cited claim's actual assertion is
    narrower or conditional.
  - `scope_preserved`: false if the cited claim's `scope` is
    MODEL_SPECIFIC, EXAMPLE_SPECIFIC, or IMPLEMENTATION_DEPENDENT and the
    sentence states it as if it were universal to every version of the
    underlying general idea.
  - `violation_code`: a short code for the specific problem found, beyond
    what `qualifier_preserved`/`scope_preserved` already capture --
    STORY_IMPROVEMENT_PLAN.md Phase 13's two technical-overclaim patterns
    belong here:
      - "soft_stated_as_hard": the claim describes a soft, weighted, or
        probabilistic mechanism, but the sentence narrates a graded
        contribution as if it were a single discrete/hard selection.
      - "partial_contribution_overstated": the claim attributes an outcome
        to several components acting together, but the sentence credits
        one component or step with fully causing or resolving it alone.
    Use null when none of these apply.
  - `explanation`: a one-sentence account of the problem, or null if none.
- If `factual` is false, leave the remaining fields at their defaults --
  there is nothing else to check.

The classic failure this exists to catch: a sentence changes "grows with
tokens" to "grows quadratically with tokens" while still citing the same
claim -- same claim id, different meaning. That is a fidelity failure
(`violation_code="meaning_drifted"`), not a grounding success.
"""


class GroundingVerdict(BaseModel):
    sentence_id: str
    factual: bool = False
    supported: bool = True
    verified_claim_ids: list[str] = Field(default_factory=list)
    qualifier_preserved: bool = True
    scope_preserved: bool = True
    violation_code: str | None = None
    explanation: str | None = None


class GroundingReview(BaseModel):
    verdicts: list[GroundingVerdict] = Field(default_factory=list)


# Bounds the size of a single C2b structured output -- the exact same rationale as CM's
# CM_BATCH_SIZE (review/claim_mapper.py). Added after a live run confirmed C2b needs it too:
# a single 58-sentence call returned only 42 verdicts (16 silently missing), correctly caught
# by the fail-closed coverage check rather than a truncated response being trusted, but the
# fix that actually lets the run PROCEED is shrinking the call, same as CM's own history.
C2B_BATCH_SIZE = 20


def _sentence_payload(sentence_id: str, scene_id: str, index: int, sentence) -> dict:
    return {
        "sentence_id": sentence_id, "scene_id": scene_id, "sentence_index": index, "text": sentence.text,
        "grounding_required": sentence.grounding_required, "grounding_refs": sentence.grounding_refs,
    }


def _claim_payload(claim: Claim) -> dict:
    return {
        "claim_id": claim.claim_id, "claim": claim.claim, "verification_status": claim.verification_status,
        "scope": claim.scope, "required_qualifiers": claim.required_qualifiers,
    }


def _call_c2b(
    batch: list[tuple[str, int, object]], claim_registry_payload: list[dict],
    review_lead: Agent, budget: BudgetCounter,
) -> GroundingReview:
    payload = {
        "sentences": [_sentence_payload(sentence.sentence_id, scene_id, i, sentence) for scene_id, i, sentence in batch],
        "verified_claims": claim_registry_payload,
    }
    return review_lead.run(
        pass_id="C2b", mode="GROUND_NARRATION", task_prompt=TASK_PROMPT,
        payload=payload, schema=GroundingReview, budget=budget, estimated_usd=0.06, timeout_s=180,
    )


def _run_c2b_pass(
    sentences: list[tuple[str, int, object]], claim_registry_payload: list[dict],
    review_lead: Agent, budget: BudgetCounter, label: str,
) -> dict[str, GroundingVerdict]:
    """Dispatch `sentences` through `review_lead` in `C2B_BATCH_SIZE` chunks (concurrently),
    retry once with just whatever's missing, then fail closed -- the exact same pattern
    `verify_grounding` always used for its one and only pass, extracted (2026-09-16, Phase
    22 escalation-gating) so the escalation pass below gets the identical coverage guarantee
    instead of a second, weaker one. `label` is just for the `ReviewCoverageError` message,
    so a coverage gap in the escalation pass isn't mistaken for one in the main pass."""
    batches = [sentences[i:i + C2B_BATCH_SIZE] for i in range(0, len(sentences), C2B_BATCH_SIZE)]
    results = run_concurrently([
        (lambda b=batch: _call_c2b(b, claim_registry_payload, review_lead, budget)) for batch in batches
    ])
    verdicts_by_id: dict[str, GroundingVerdict] = {}
    for review in results:
        for v in review.verdicts:
            verdicts_by_id[v.sentence_id] = v

    all_sentence_ids = {sentence.sentence_id for _, _, sentence in sentences}
    missing_ids = all_sentence_ids - verdicts_by_id.keys()
    if missing_ids:
        # STORY_IMPROVEMENT_PLAN.md Phase 10 follow-up: confirmed live (2026-09-15) -- same
        # residual gap as CM's own retry (review/claim_mapper.py) -- even a bounded batch can
        # still drop a single entry. One small retry with just the missing sentences resolves
        # an isolated, likely-stochastic miss without paying to redo whole batches.
        retry_batch = [(scene_id, i, sentence) for scene_id, i, sentence in sentences if sentence.sentence_id in missing_ids]
        retried = _call_c2b(retry_batch, claim_registry_payload, review_lead, budget)
        for v in retried.verdicts:
            verdicts_by_id[v.sentence_id] = v
        missing_ids = all_sentence_ids - verdicts_by_id.keys()

    if missing_ids:
        missing = sorted(missing_ids)
        raise ReviewCoverageError(
            f"C2b ({label}) did not return a verdict for {len(missing)}/{len(all_sentence_ids)} "
            f"sentence(s) even after one retry: {missing[:10]}{'...' if len(missing) > 10 else ''}"
        )
    return verdicts_by_id


def _needs_escalation(v: GroundingVerdict) -> bool:
    """STORY_IMPROVEMENT_PLAN.md Phase 22: the routine, high-confidence case (not factual, or
    factual and cleanly supported) never needs a second opinion -- only a verdict the cheap
    pass itself flagged as a real problem does. Mirrors `grounding_verdicts_to_issues`'s own
    branching (unsupported / qualifier dropped / scope broadened / a named violation code) --
    the same four signals that already turn into a hard/critical finding are exactly the ones
    worth spending the strong tier's second opinion on before trusting them."""
    if not v.factual:
        return False
    return not v.supported or not v.qualifier_preserved or not v.scope_preserved or v.violation_code is not None


def verify_grounding(
    narration: list[SceneNarration], claims: list[Claim], review_lead: Agent, budget: BudgetCounter,
    escalate_to: Agent | None = None,
) -> list[GroundingVerdict]:
    """`escalate_to` (STORY_IMPROVEMENT_PLAN.md Phase 22, 2026-09-16): when given, `review_lead`
    is treated as the cheap first pass over EVERY sentence (as before) -- but any verdict
    `_needs_escalation` flags gets a second, independent opinion from `escalate_to` (the strong
    tier), which is what actually gets returned for those sentences. A clean flash pass (the
    common case) costs nothing extra; only genuinely flagged sentences ever reach the strong
    tier. `None` (the default) preserves the original single-tier behavior exactly -- shorts'
    own call site passes nothing here on purpose (STORY_IMPROVEMENT_PLAN.md Phase 22's own
    scope note: shorts already runs its whole review stack on flash only, nothing to escalate
    FROM)."""
    narration = stamp_sentence_ids(narration)
    all_sentences = [
        (scene.scene_id, i, sentence) for scene in narration for i, sentence in enumerate(scene.sentences)
    ]
    if not all_sentences:
        return []  # nothing to check -- skip the call entirely, same as CM's batching loop

    claim_registry_payload = [_claim_payload(c) for c in claims]
    # 2026-09-15: same reasoning as review/claim_mapper.py's CM batches -- each C2b batch
    # is independent (a disjoint slice of sentences against the same read-only claim
    # registry), so they run concurrently via llm/concurrency.py to cut wall-clock time.
    # This is the single biggest real driver of a slow review cycle (C2b's dense
    # per-sentence verdicts are the most expensive/verbose structured output in the review
    # block), so it's also the pass most worth parallelizing first.
    verdicts_by_id = _run_c2b_pass(all_sentences, claim_registry_payload, review_lead, budget, label="first pass")

    if escalate_to is not None:
        flagged_ids = {sid for sid, v in verdicts_by_id.items() if _needs_escalation(v)}
        if flagged_ids:
            flagged_sentences = [s for s in all_sentences if s[2].sentence_id in flagged_ids]
            escalated = _run_c2b_pass(flagged_sentences, claim_registry_payload, escalate_to, budget, label="escalation")
            verdicts_by_id.update(escalated)  # the strong tier's own opinion wins outright

    # Stable order (narration order), not response order -- callers shouldn't have to care.
    return [verdicts_by_id[sentence.sentence_id] for _, _, sentence in all_sentences]


class GroundingAuditFinding(BaseModel):
    sentence_id: str
    flash: GroundingVerdict
    pro: GroundingVerdict
    agrees: bool


class GroundingAudit(BaseModel):
    """STORY_IMPROVEMENT_PLAN.md Phase 22, step 2: turns "we assume flash is good enough" into
    "we measured flash is good enough" -- the actual gate for whether step 1's escalation-gating
    is safe to keep running, not a one-time check. `disagreement_rate` is the metric to watch
    (the plan's own §6 interpretation: <1% excellent, 1-3% keep sampling, >3% increase coverage,
    any critical miss investigate before reducing further)."""

    sampled_count: int = 0
    disagreement_count: int = 0
    findings: list[GroundingAuditFinding] = Field(default_factory=list)

    @property
    def disagreement_rate(self) -> float:
        return self.disagreement_count / self.sampled_count if self.sampled_count else 0.0


DEFAULT_AUDIT_SAMPLE_RATE = 0.10  # plan's own suggested starting point (STORY_IMPROVEMENT_PLAN.md Phase 22 §6)


def audit_clean_verdicts(
    narration: list[SceneNarration], claims: list[Claim], verdicts: list[GroundingVerdict],
    escalate_to: Agent, budget: BudgetCounter,
    sample_rate: float = DEFAULT_AUDIT_SAMPLE_RATE, rng: random.Random | None = None,
) -> GroundingAudit:
    """Randomly samples `sample_rate` of the sentences flash called clean (i.e. NOT flagged by
    `_needs_escalation` -- the ones step 1's escalation-gating trusts flash on outright) and
    gets `escalate_to`'s (the strong tier's) own independent opinion on them too, to measure
    how often that trust is actually correct rather than merely assuming it. A "disagreement"
    means the strong tier itself would have flagged a sentence flash called clean -- exactly
    the kind of miss escalation-gating exists to avoid, now made visible instead of silent.

    Deliberately separate from `verify_grounding()` itself: the audit is a measurement, not a
    gate -- it must never change what gets returned to the caller or block a run, only report.
    Call it AFTER `verify_grounding()`, on its own final verdicts, not instead of it."""
    rng = rng or random.Random()
    narration = stamp_sentence_ids(narration)
    all_sentences = [
        (scene.scene_id, i, sentence) for scene in narration for i, sentence in enumerate(scene.sentences)
    ]

    clean_ids = [v.sentence_id for v in verdicts if not _needs_escalation(v)]
    sample_size = round(len(clean_ids) * sample_rate)
    sampled_ids = set(rng.sample(clean_ids, sample_size)) if sample_size else set()
    if not sampled_ids:
        return GroundingAudit()

    flash_by_id = {v.sentence_id: v for v in verdicts if v.sentence_id in sampled_ids}
    claim_registry_payload = [_claim_payload(c) for c in claims]
    sampled_sentences = [s for s in all_sentences if s[2].sentence_id in sampled_ids]
    pro_by_id = _run_c2b_pass(sampled_sentences, claim_registry_payload, escalate_to, budget, label="audit")

    findings = []
    for sid in sorted(sampled_ids):  # stable order for reporting/testing, not a semantic sort
        flash_v, pro_v = flash_by_id[sid], pro_by_id[sid]
        findings.append(GroundingAuditFinding(sentence_id=sid, flash=flash_v, pro=pro_v, agrees=not _needs_escalation(pro_v)))
    disagreement_count = sum(1 for f in findings if not f.agrees)
    return GroundingAudit(sampled_count=len(findings), disagreement_count=disagreement_count, findings=findings)


def apply_grounding_metadata_repairs(
    narration: list[SceneNarration], verdicts: list[GroundingVerdict],
) -> list[SceneNarration]:
    """STORY_IMPROVEMENT_PLAN.md Phase 10 §5.3: when C2b's independent check shows a
    sentence IS actually factual and IS supported by a real verified claim, despite CM
    having mis-tagged it `grounding_required=False`, patch the sentence's grounding
    metadata directly -- this was never a narration defect, so it must never trigger an
    unnecessary A3/B2 rewrite. Only ever moves False -> True using the claim ids C2b
    itself found; a sentence C2b flags as a real problem is left alone here (that's
    `grounding_verdicts_to_issues`'s job, which routes it to an actual rewrite).

    Stamps sentence ids defensively (like `verify_grounding` itself) rather than trusting
    the caller to pass in narration that's already been through `verify_grounding` --
    `verdicts` was necessarily computed against stamped ids, so matching against
    unstamped ones here would silently match nothing."""
    narration = stamp_sentence_ids(narration)
    verdicts_by_id = {v.sentence_id: v for v in verdicts}
    result: list[SceneNarration] = []
    for scene in narration:
        new_sentences = []
        for sentence in scene.sentences:
            v = verdicts_by_id.get(sentence.sentence_id)
            if v is not None and v.factual and v.supported and not sentence.grounding_required:
                new_sentences.append(sentence.model_copy(update={
                    "grounding_required": True,
                    "grounding_refs": v.verified_claim_ids or sentence.grounding_refs,
                }))
            else:
                new_sentences.append(sentence)
        result.append(scene.model_copy(update={"sentences": new_sentences}))
    return result


def grounding_verdicts_to_issues(
    narration: list[SceneNarration], verdicts: list[GroundingVerdict],
) -> list[CritiqueIssue]:
    """Turns C2b's dense per-sentence verdicts into the same kind of
    `CritiqueIssue`s the rest of the pipeline already routes on -- only for
    a real defect (unsupported, meaning drifted, a qualifier dropped, scope
    broadened). A verdict that's clean, or not `factual` at all, produces nothing. Exactly
    one issue per sentence -- `supported`/`qualifier_preserved`/`scope_preserved`/
    `violation_code` are checked in that priority order rather than all independently, since
    a `violation_code` is usually the model's own explanation for whichever structured flag
    it also set false, not a second, distinct defect."""
    narration = stamp_sentence_ids(narration)
    scene_id_by_sentence_id = {s.sentence_id: scene.scene_id for scene in narration for s in scene.sentences}
    issues: list[CritiqueIssue] = []
    for v in verdicts:
        if not v.factual:
            continue
        if not v.supported:
            code, severity, detail = "unsupported", "critical", "no verified claim actually supports this sentence"
            intent = "cite a real claim from the registry that actually supports this exact sentence, or cut the claim entirely if none does"
        elif not v.qualifier_preserved:
            code, severity, detail = "qualifier_dropped", "critical", "a required qualifier was dropped"
            intent = "restore the cited claim's own stated condition/qualifier instead of asserting it unconditionally"
        elif not v.scope_preserved:
            code, severity, detail = "scope_broadened", "major", "a claim's limited scope was stated as universal"
            intent = "narrow this back to the cited claim's own limited scope instead of stating it as universal"
        elif v.violation_code:
            code, severity, detail = v.violation_code, "major", v.explanation or v.violation_code
            intent = v.explanation or f"fix the '{v.violation_code}' problem: {detail}"
        else:
            continue  # clean

        scene_id = scene_id_by_sentence_id.get(v.sentence_id)
        issues.append(CritiqueIssue(
            # `recommended_intent` (2026-09-16, found on review): used to be one fixed
            # three-option sentence regardless of which of the three actually applied --
            # harmless for long-form, where A3 (planning/revision_planner.py) synthesizes
            # a fresh instruction from the whole CritiqueIssue before any rewrite ever sees
            # it, but shorts' B2s (editing/short_targeted_rewrite.py) has no such
            # intermediate step -- its own docstring says `recommended_intent` IS the plan,
            # sent to the rewrite verbatim. A vague three-option instruction there means the
            # rewrite doesn't know WHICH of the three to actually do.
            issue_id=f"c2b_{v.sentence_id}_{code}", severity=severity, category="clarity",
            layer="TECHNICAL", scene_ids=[scene_id] if scene_id else [],
            problem=v.explanation or detail, why_it_matters=detail,
            recommended_intent=intent,
            repair_owner="narration_lead",
        ))
    return issues
