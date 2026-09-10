"""Story planning contracts (plan §5, §9, §10.2, §5.2, §5.3).

ArchetypeSpec is the core-vs-optional-roles data behind the §9 structural
hard gate. StoryPlan is what A2 produces; everything in it (hook, CTA,
beats, ending) is planned before narration exists (design doc's core
principle — narration is the final creative surface over a validated
story graph, not the other way around).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# The six resolved archetypes. Note this Literal deliberately excludes "auto" —
# `story.archetype` (the config input, which may be "auto") lives outside this
# contract set; StoryPlan.archetype is always a RESOLVED archetype (plan §9:
# "archetype unresolved (auto)" is a hard-gate failure, enforced here at the
# type level rather than only at runtime).
Archetype = Literal["mystery", "build", "experiment", "derivation", "foundation", "framework"]

NarrativeBeat = Literal["hook", "teaching", "escalation", "reveal", "close"]
Engine = Literal["remotion", "manim"]
VisualImportance = Literal["low", "medium", "high", "hero"]
CTAIntent = Literal["VALUE_LINKED", "SERIES_LINKED", "CHANNEL_PROMISE", "MINIMAL"]
Continuity = Literal["continues_from_previous", "new", "transforms"]
QuestionProgress = Literal["none", "partial_answer", "resolved"]
ConceptDensity = Literal["low", "medium", "high"]


class ArchetypeSpec(BaseModel):
    """Core (hard-gated) vs optional (diagnostic) roles for one archetype (plan §9).

    Loaded from config/archetypes.yaml in practice; the model lives here so
    the planner and the hard-gate validator share one shape.
    """

    archetype: Archetype
    core_roles: list[str]
    optional_roles: list[str] = Field(default_factory=list)
    driver: str  # e.g. "unanswered cause" for mystery (plan §10.2)


class ReplanFeedback(BaseModel):
    """What made the previous A2 attempt get rejected, given back on replan so
    A2 doesn't just retry blind with identical inputs (a real gap found
    2026-09-10: the replan call used to rerun plan_story() with the exact
    same source_brief/claims/source_units and nothing else, so a second
    wrong answer was just as likely as a corrected one)."""

    previous_archetype: str
    critique_issues: list[dict] = Field(default_factory=list)  # severity/category/problem/recommended_intent
    structural_issues: list[dict] = Field(default_factory=list)  # code/detail


class SourceBrief(BaseModel):
    """What A1 establishes about the source before any story shape is chosen (plan §5)."""

    topic: str
    core_question: str
    viewer_problem: str
    central_insight: str
    prerequisites: list[str] = Field(default_factory=list)
    key_concepts: list[str] = Field(default_factory=list)
    concept_dependencies: list[str] = Field(default_factory=list)
    likely_confusions: list[str] = Field(default_factory=list)
    source_constraints: list[str] = Field(default_factory=list)
    visual_opportunities: list[str] = Field(default_factory=list)
    novelty_statement: str = ""  # plan §9 Learning gate: what this audience doesn't already know


class TitleContract(BaseModel):
    candidates: list[str] = Field(default_factory=list)
    chosen: str
    promise: str  # must be contained in hook.promise (plan §9 promise-chain gate)


class HookContract(BaseModel):
    viewer_problem: str
    tension: str
    promise: str
    open_loop: str = ""
    must_not_reveal_yet: list[str] = Field(default_factory=list)


class CTAContract(BaseModel):
    """The payoff earns the ask (feedback.md; plan §5.2)."""

    max_ctas: int = Field(default=2, ge=0, le=2)
    primary_after_beat: str  # beat_id
    intent: CTAIntent = "VALUE_LINKED"
    end_after_final_payoff: bool = True


class MiniPayoff(BaseModel):
    after_beat: str  # beat_id
    payoff: str
    opens: str | None = None


class EndingContract(BaseModel):
    resolve_hook: str
    compressed_mental_model: str
    capstone_payoff: str
    viewer_can_now: str  # a capability sentence, not a feature description (plan §9)
    next_video_bridge: str | None = None


class StoryBeat(BaseModel):
    """One planning unit (plan §5, §10.2).

    `archetype_role` may be blank — that's valid (design doc §14): not every
    scene has to instantiate a named archetype stage. When it's non-blank,
    the §9 hard gate requires a causal bridge to the previous scene.
    Observable fields (new_information/payoff/visual_mode_change/
    question_progress/concept_density) replace a numeric "energy" score —
    a model's 6-vs-7 energy rating isn't objective; these are (Appendix G).
    """

    beat_id: str
    purpose: str
    archetype_role: str = ""  # blank is valid
    archetype_stage: str = ""  # which ArchetypeSpec core/optional role this instantiates, if any
    source_unit_ids: list[str] = Field(default_factory=list)
    viewer_question_before: str = ""
    answer_or_payoff: str = ""
    next_question: str = ""
    learning_objective: str = ""  # plan §9 Learning gate: every major beat needs one
    forward_driver: str = ""  # plan §10.2: what this beat advances toward the archetype's driver

    beat_function: str = ""  # e.g. "worked_example", "reveal", "setup" (open, not yet closed to an enum)
    new_information: bool = False
    payoff: bool = False
    visual_mode_change: bool = False
    question_progress: QuestionProgress = "none"
    concept_density: ConceptDensity = "medium"


class SemanticObject(BaseModel):
    """Persistent-object continuity across scenes is semantic, not assumed DOM persistence (plan §12)."""

    semantic_object_id: str
    continuity: Continuity = "new"


class ScenePlan(BaseModel):
    scene_id: str
    beat_id: str
    archetype_role: str = ""
    narrative_beat: NarrativeBeat = "teaching"
    engine: Engine = "remotion"
    narrative_job: str = ""
    visual_importance: VisualImportance = "medium"
    visual_description: str = ""
    word_budget: int = Field(default=60, ge=30, le=100)  # plan §9: 40-80 target, 30-100 hard
    components: list[str] = Field(default_factory=list)
    semantic_objects: list[SemanticObject] = Field(default_factory=list)


class StoryPlan(BaseModel):
    """A2's output (plan §5). Everything narration needs is decided here, before prose exists."""

    archetype: Archetype  # never "auto" — see the Archetype type alias note above
    selection_reason: str
    source_evidence: list[str] = Field(default_factory=list)
    rejected_archetypes: dict[str, str] = Field(default_factory=dict)  # archetype -> why not

    story_promise: str
    central_question: str
    question_chain: list[str] = Field(default_factory=list)

    title: TitleContract
    hook: HookContract
    cta: CTAContract
    beats: list[StoryBeat] = Field(default_factory=list)
    mini_payoffs: list[MiniPayoff] = Field(default_factory=list)
    ending: EndingContract
    scene_plan: list[ScenePlan] = Field(default_factory=list)


class SeriesLedger(BaseModel):
    """Cross-video continuity (plan §5.3). One per series, in config/series/<id>.yaml at rest."""

    series_id: str
    shared_assumptions: dict[str, str] = Field(default_factory=dict)
    terms_taught: dict[str, str] = Field(default_factory=dict)  # term -> video id it was taught in
    hooks_used: list[str] = Field(default_factory=list)
    analogies_used: list[str] = Field(default_factory=list)
    viewer_can_now_by_video: dict[str, str] = Field(default_factory=dict)
    shorts_by_video: dict[str, list[str]] = Field(default_factory=dict)  # video id -> short ids
