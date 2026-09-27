"""Shorts contracts (plan §20.5) — kept separate from long-form planning models.

A short derives the parent's KNOWLEDGE, never its STORY SHAPE (plan §20).
Nothing here inherits Archetype from planning/models.py on purpose.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MicroArc = Literal[
    "contradiction_resolution", "problem_fix", "before_after", "question_answer",
    "prediction_explanation", "myth_correction", "mini_derivation",
]
ShortGoal = Literal["DISCOVERY", "BRIDGE", "SERIES"]
BridgeMode = Literal["PLATFORM_LINK", "ONSCREEN", "SPOKEN", "NONE"]


class HookEvent(BaseModel):
    """The interesting thing must HAPPEN in 0-3s; a visual can carry it before narration (plan §20.4)."""

    narration: str | None = None
    visual: str | None = None
    starts_at_seconds: float = Field(default=0.0, ge=0.0, le=3.0)
    tension: str = ""


class ShortsCandidate(BaseModel):
    """One beat-derived candidate, ranked by multi-factor judgement, not knowledge gain alone (plan §20.6)."""

    beat_ids: list[str]
    insight: str
    hook_material: str = ""
    micro_arc_suggestion: MicroArc | None = None
    prerequisites: list[str] = Field(default_factory=list)
    visual_object: str = ""
    bridge_question: str = ""
    scores: dict[str, float] = Field(default_factory=dict)  # e.g. intelligibility, hookability, ...


class ShortParent(BaseModel):
    run_id: str
    final_plan_hash: str
    source_beat_ids: list[str] = Field(default_factory=list)
    allowed_fact_ids: list[str] = Field(default_factory=list)  # claim_ids + derivations/inferences over them


class ShortBridge(BaseModel):
    mode: BridgeMode = "NONE"
    parent_video_id: str | None = None
    # 2026-09-16, found on review: `narration/short_generator.py`'s own prompt has always
    # told the model ONSCREEN/PLATFORM_LINK mean "the bridge itself will render as
    # on-screen text elsewhere, not spoken" -- but no field anywhere ever captured what
    # that on-screen text actually IS, and `html_synth/vertical_assembler.py` never
    # rendered `bridge` at all. A short assigned either mode shipped with the CTA
    # narration correctly withheld and nothing ever shown in its place -- a silent,
    # complete loss of the one thing that mode exists for. `cta_text` is A2s's own
    # authored short line (<=8 words, same convention as the SPOKEN case); empty for
    # SPOKEN (baked into the narration itself) and NONE (nothing to show).
    cta_text: str = ""


class ShortVisual(BaseModel):
    dominant_object: str = ""
    states: list[str] = Field(default_factory=list)
    safe_zones: list[str] = Field(default_factory=list)  # plan §20.9 vertical-safe composition


class ShortNarration(BaseModel):
    # 2026-09-15: target_duration_seconds le lowered 60.0 -> 55.0, word_band lowered
    # 120-165 -> 90-115 -- confirmed live: 4 of 5 real shorts measured 61.7-76.4s against
    # the then-60s hard cap despite fitting the old (120, 165) band at an assumed ~167
    # words/minute. Back-computing from the worst case (165 words measuring 76.4s)
    # implied real edge-tts speech lands closer to ~130 words/minute, not 167.
    #
    # 2026-09-16: hard cap itself raised 60s -> 120s (user decision, verification/hard/
    # shorts.py's MAX_MEASURED_SHORT_SECONDS) -- the tight 60s budget was itself a real
    # contributing factor to several failures beyond direct duration overruns, since
    # `setup` had to fit BOTH "minimum context" AND its per-micro_arc required beat
    # (Phase 20) in the same tiny word allowance as everything else. Bounds recalibrated
    # against the same ~130wpm real-speech rate, scaled to the new 120s cap, with the same
    # real-margin-below-the-hard-cap philosophy as before (95s target * 130wpm ~= 206
    # words, near the new word_band's own top; 110s ceiling leaves 10s margin below 120s).
    target_duration_seconds: float = Field(default=95.0, ge=60.0, le=110.0)
    word_band: tuple[int, int] = (160, 210)  # a real ceiling now -- see narration/short_generator.py


class ShortPlan(BaseModel):
    """A2s's output (plan §20.5). Parent linkage is required for a derived short;
    the spoken bridge is not — sometimes the strongest ending is the payoff."""

    parent: ShortParent | None = None  # required for derived; None only for a standalone short
    title: str = ""  # plan §20.6/§20.10: A2s's design output, checked for title~hook~payoff alignment
    goal: ShortGoal = "DISCOVERY"
    central_insight: str
    micro_arc: MicroArc
    hook: HookEvent
    setup: str = ""  # minimum_context
    # 2026-09-25: STORY_IMPROVEMENT_PLAN.md Phase 30 P1 item 2. `setup` used to carry BOTH
    # "minimum context" and, for a `problem_fix` micro_arc, the arc's own required naive-
    # attempt beat -- overloaded, with nothing forcing the second half to actually be
    # populated. Confirmed live: 3 of 4 real `problem_fix` shorts shipped a `setup` that
    # was a bare rhetorical question, silently skipping the naive attempt this TASK_PROMPT
    # already explicitly requires ("if you cannot name that specific failed attempt... this
    # candidate is NOT a problem_fix short"). A dedicated field lets `plan_shorts()` check
    # the requirement deterministically instead of hoping a free-text field complied.
    # Required (non-empty) when `micro_arc == "problem_fix"`; left blank for every other arc.
    naive_attempt: str = ""
    mechanism: str = ""
    payoff_central: str = ""
    micro_payoffs: list[str] = Field(default_factory=list)
    bridge: ShortBridge = Field(default_factory=ShortBridge)
    visual: ShortVisual = Field(default_factory=ShortVisual)
    narration: ShortNarration = Field(default_factory=ShortNarration)
