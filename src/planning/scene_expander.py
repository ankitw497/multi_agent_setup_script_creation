"""A2b -- per-beat scene expansion (Story Lead) (plan §5, §9).

The other half of the ERR-010/ERR-023 fix: `beat_word_budget.py` computes
each beat's own word target deterministically; this pass asks one small,
well-scoped call per beat to hit ITS OWN target -- a few hundred words
across 2-6 scenes is an aggregate an LLM can actually satisfy reliably,
unlike the full 20-30-scene, ~1670-word system-wide sum A2 used to be
asked for in one shot.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from facts.models import Claim
from llm.budget import BudgetCounter
from planning.models import NarrativeBeat, ScenePlan, StoryBeat

TASK_PROMPT = """\
Break this ONE beat into concrete scenes whose word_budgets together land
within about 15% of `target_words` -- no more, no less. If `target_words`
is large enough to need it, use multiple scenes rather than cramming
everything into one overloaded scene; a beat covering real source depth
should usually become 2-6 scenes, not always exactly one.

Each scene needs: a realistic word_budget (30-100 hard bounds, 40-80
preferred), a narrative_beat (hook/teaching/escalation/reveal/close --
`reveal` should be used sparingly, not for every scene), and a concrete,
single-idea visual_description that follows from the beat's own
`purpose`, `forward_driver`, and `archetype_role` -- the scene must feel
caused by what came before it. Ground everything in the `available_claims`
given; never introduce a technical claim outside that registry. When an
available claim already IS a concrete illustration (an actual example, a
specific sentence pair, a real number) rather than an abstract statement,
the `visual_description` for the scene grounded in it must reference that
concrete illustration directly -- do not compress a claim like "changing
X to Y flips the answer" into a vaguer restatement like "context matters
for meaning."
"""


class ExpandedScene(BaseModel):
    narrative_beat: NarrativeBeat = "teaching"
    visual_description: str = ""
    word_budget: int = Field(ge=30, le=100, default=60)


class BeatSceneExpansion(BaseModel):
    scenes: list[ExpandedScene] = Field(default_factory=list)


def _claim_payload(claim: Claim) -> dict:
    return {"claim_id": claim.claim_id, "claim": claim.claim, "importance": claim.importance}


def expand_beat_scenes(
    beat: StoryBeat, target_words: int, claims: list[Claim], story_lead: Agent,
    budget: BudgetCounter,
) -> list[ScenePlan]:
    beat_claims = [c for c in claims if c.source_unit in set(beat.source_unit_ids)]
    payload = {
        "beat_id": beat.beat_id, "purpose": beat.purpose, "archetype_role": beat.archetype_role,
        "forward_driver": beat.forward_driver, "learning_objective": beat.learning_objective,
        "target_words": target_words,
        "available_claims": [_claim_payload(c) for c in beat_claims],
    }
    result = story_lead.run(
        pass_id="A2b", mode="SCENE_EXPANSION", task_prompt=TASK_PROMPT,
        payload=payload, schema=BeatSceneExpansion, budget=budget, estimated_usd=0.03,
    )
    return [
        ScenePlan(
            scene_id=f"{beat.beat_id}_s{i:02d}", beat_id=beat.beat_id,
            archetype_role=beat.archetype_role, narrative_beat=s.narrative_beat,
            narrative_job=beat.purpose, visual_description=s.visual_description,
            word_budget=s.word_budget,
        )
        for i, s in enumerate(result.scenes, start=1)
    ]
