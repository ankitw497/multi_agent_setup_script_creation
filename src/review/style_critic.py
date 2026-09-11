"""C5 -- style critic (flash-tier Gemini) (plan §8, §11.5).

Conditional by design: the pipeline diagram (plan §8) only calls this when
a voice diagnostic band is AMBER/RED, so a clean voice signal costs
nothing. Diagnoses tells that mark narration as model-written (plan
§11.1), never rewrites -- repair goes to B4 humanize, which is out of this
scope (guarding humanize's output against drift with the fitted voice
corpus is separate follow-up work; see verification/diagnostics/voice.py).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import Agent
from llm.budget import BudgetCounter
from narration.models import SceneNarration

from .models import CritiqueIssue

TASK_PROMPT = """\
Read this narration draft for tells that mark it as model-written rather
than human-written: uniform sentence rhythm with no real variation,
hedging padding ("it's worth noting", "in essence", "it's important to
understand"), reflexive three-item lists, overly balanced "on one hand /
on the other hand" framing, generic connective tissue ("moving on to...",
"next, let's discuss..."), or a lecture-y tone with no person behind it.

Do not rewrite -- name the specific recurring pattern, where it shows up
(scene_ids), and what must change (recommended_intent: a description of
the pattern to break, never replacement prose). Use category="repetition"
unless another category fits better, layer="VOICE", and
repair_owner="narration_lead". Only raise a real, repeated pattern -- a
single acceptable sentence is not evidence of a tell.
"""


class StyleCritique(BaseModel):
    issues: list[CritiqueIssue] = Field(default_factory=list)


def _scene_payload(scene: SceneNarration) -> dict:
    return {"scene_id": scene.scene_id, "text": " ".join(s.text for s in scene.sentences)}


def critique_style(
    narration: list[SceneNarration], review_agent: Agent, budget: BudgetCounter,
) -> list[CritiqueIssue]:
    payload = {"narration": [_scene_payload(s) for s in narration]}
    critique = review_agent.run(
        pass_id="C5", mode="STYLE_CRITIC", task_prompt=TASK_PROMPT,
        payload=payload, schema=StyleCritique, budget=budget, estimated_usd=0.02, timeout_s=120,
    )
    return critique.issues
