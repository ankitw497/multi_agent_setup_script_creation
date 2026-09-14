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
# V2 narrative-continuity fix: distinguishes a scene's storytelling function so
# narration knows how much to say about a concept it touches -- "preview" (a
# one-line mention before it's taught), "derivation" (builds on something
# already taught, referenced not re-explained), "recap" (deliberate
# compression of prior material), or "standard" (a normal first explanation).
# See STORY_IMPROVEMENT_PLAN.md Phase 1.
SceneFunction = Literal["preview", "derivation", "recap", "standard"]


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


class RunningExample(BaseModel):
    """The one concrete illustration a video anchors on and reuses across
    scenes (V2 narrative-continuity fix, STORY_IMPROVEMENT_PLAN.md Phase 1)
    -- set once during A2 from the same concrete illustration the hook
    prompt already extracts, then threaded unchanged through A2b and into
    B1 so later scenes reuse the same named objects/values instead of each
    scene rebuilding its own example from scratch."""

    label: str = ""
    description: str = ""
    values: dict[str, str] = Field(default_factory=dict)  # named quantities/objects, e.g. {"item_a": "9.6", "item_b": "2.4"}


class FormulaStage(BaseModel):
    """One stage in a formula/expression the source builds up progressively
    across beats (e.g. a raw score -> a scaled score -> a normalized form
    -> a final output) -- STORY_IMPROVEMENT_PLAN.md Phase 6 item 7.
    Registered once during A2, in derivation order; most videos have none
    of these (empty list is the normal case) -- only set when the source
    actually centers on an expression that evolves stage by stage, the
    same "typed formula-state object" the confirmed B8 regression bug
    (a later equation card silently dropping an already-derived term)
    showed was needed."""

    stage_id: str
    expression: str  # the exact symbolic form for this stage, e.g. "QK^T / sqrt(d_k)"
    values: dict[str, str] = Field(default_factory=dict)  # this stage's own worked numbers, e.g. {"cat": "1.7"} --
    # distinct from an earlier/later stage's numbers for the SAME named quantities (raw vs. scaled scores are
    # different numbers, never the same dict reused across stages)


class ViewerLedger(BaseModel):
    """Transient accumulator threaded through A2b's per-beat loop
    (`planning/story_planner.py`) -- not persisted on `StoryPlan` itself.
    Each beat's `expand_beat_scenes()` call receives the ledger built from
    every prior beat's `new_concepts` and returns an updated one; this is
    what lets a later beat know a concept was already taught, instead of
    each beat being expanded in total isolation (the mechanical cause of
    cross-scene repetition -- see STORY_IMPROVEMENT_PLAN.md's "Why")."""

    viewer_knows: list[str] = Field(default_factory=list)  # concept labels already taught
    running_example: RunningExample = Field(default_factory=RunningExample)
    formula_stages: list[FormulaStage] = Field(default_factory=list)  # set once by A2, never mutated here
    # STORY_IMPROVEMENT_PLAN.md Phase 7 #3 (mechanism scope): a mechanism whose applicability
    # is conditional (e.g. causal masking only applies to autoregressive attention) rather than
    # universal, keyed by a short descriptive flag (e.g. "causal_mask_required"). Empty until a
    # beat's own expansion establishes one; accumulates beat-to-beat like viewer_knows, so a
    # later beat's recap can be checked against the scope as of that point in the video.
    mechanism_scope: dict[str, bool] = Field(default_factory=dict)


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
    scene_function: SceneFunction = "standard"
    new_concepts: list[str] = Field(default_factory=list)  # concept labels this scene introduces for the first time
    must_not_repeat: list[str] = Field(default_factory=list)  # already-taught concepts this scene builds on, never re-derives
    formula_stage_id: str = ""  # which registered FormulaStage (if any) this scene's equation/diagram represents
    # Phase 7 #3: the ViewerLedger.mechanism_scope snapshot as of this scene's own beat --
    # empty until some earlier (or this) beat establishes a conditional mechanism's scope.
    mechanism_scope: dict[str, bool] = Field(default_factory=dict)


class RetentionDeadline(BaseModel):
    """A cumulative-time ceiling for a named `StoryBeat.archetype_role`
    (STORY_IMPROVEMENT_PLAN.md Phase 7 item #1): "the beat instantiating
    this role must be fully covered within `max_seconds` of video start."
    Registered once during A2, only for roles where pacing genuinely
    matters (e.g. the central problem should land within ~30s) -- empty
    list is the normal case and changes no allocation behavior. Fixes the
    confirmed bug where airtime was allocated purely by
    `len(source_unit_ids)`, so a hook citing as many source units as a
    deep-dive section got the same word budget as that section."""

    archetype_role: str
    max_seconds: float


class StoryStructure(BaseModel):
    """A2a's output -- everything about the story EXCEPT its scene-level
    breakdown (plan §5, §9, §19).

    Split out from StoryPlan (2026-09-10, ERR-010/ERR-023) because asking
    one call to both resolve the archetype/beats AND correctly sum a
    20-30-scene word budget against a target duration was reliably
    unreliable at the aggregate math specifically -- real live runs
    returned 5-6 scenes (~500 words) against a ~1670-word target, even
    with explicit calibration instructions. The archetype/structure
    judgement itself was never the problem (A2 resolved `build` correctly
    on every live run tested). See planning/scene_expander.py for A2b,
    which fills in `StoryPlan.scene_plan` afterward, one beat at a time.
    """

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
    running_example: RunningExample = Field(default_factory=RunningExample)  # V2: the one example every scene reuses
    formula_stages: list[FormulaStage] = Field(default_factory=list)  # Phase 6: empty unless the source has an evolving formula
    retention_deadlines: list[RetentionDeadline] = Field(default_factory=list)  # Phase 7: empty unless pacing needs one


class StoryPlan(StoryStructure):
    """A2's full output (plan §5): a StoryStructure plus its scene-level
    breakdown. Everything narration needs is decided here, before prose
    exists."""

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
