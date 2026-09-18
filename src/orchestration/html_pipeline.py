"""H + HV (plan §12, §13). `synthesize_video_html` is the V1B single pass:
synthesize, run the static checks, report a failing result rather than
repairing it. `synthesize_and_repair_video_html` (V1C) wraps that with a
bounded repair loop: static checks -> rendered checks (Playwright, when
available) -> C3 visual audit, each round targeting only the beats/hero a
concrete `RenderIssue`/`CritiqueIssue` actually named -- never a model's
own choice of scope, and never routed through A3/`routing.py` (plan §15:
"HTML structural / render -> H REPAIR -- never B2, never a paid model").
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.base import Agent
from editing.html_repair import beats_to_repair, repair_beat_visual, repair_hero
from facts.models import Claim
from html_synth.assembler import synthesize_page
from html_synth.synthesizer import BeatVisual, HeroContent, synthesize_beat_visual, synthesize_hero
from llm.budget import BudgetCounter
from narration.models import SceneNarration
from planning.models import StoryPlan
from review.models import CritiqueIssue, DiagnosticResult
from review.visual_critic import critique_visuals, scene_payload
from review.visual_sample import select_scenes_for_visual_audit
from review.visual_sequence_critic import critique_visual_sequence, sequence_scene_payload
from verification.diagnostics.entity_consistency import check_running_example_entity_consistency
from verification.diagnostics.visual_variety import check_consecutive_component_repetition
from verification.hard.formula_consistency import check_formula_stage_consistency
from verification.hard.render import RenderIssue, check_render_content, check_render_static

MAX_HTML_REPAIRS = 2
# STORY_IMPROVEMENT_PLAN.md Phase 15: a genuine screen/narration factual contradiction C3
# finds (critical, repair_owner=narration_lead) is the ONE case nothing else in this
# architecture can otherwise resolve -- H-repair only ever regenerates screen prose/component
# data, never the underlying fact it represents. Bounded to exactly ONE attempt, total, per
# run (not per finding) -- a narrow, explicit exception to "HTML render issues never route
# through B2" (Phase 8.6's own invariant), never a general reopening of that boundary.
MAX_LATE_NARRATION_REPAIRS = 1


@dataclass
class HtmlSynthesisResult:
    video_script_html: str
    page_html: str
    hero: HeroContent
    beat_visuals: list[BeatVisual]
    render_issues: list[RenderIssue] = field(default_factory=list)
    repairs_used: int = 0
    degraded_capabilities: list[str] = field(default_factory=list)
    # Every C3 finding, not just the structural subset that routes to
    # repair -- STORY_IMPROVEMENT_PLAN.md Phase 6 fix: these used to be
    # computed and then silently discarded (never returned, never
    # reported anywhere) once the structural ones were pulled out.
    visual_critique_issues: list[CritiqueIssue] = field(default_factory=list)
    # AMBER-banded, never a hard gate (Phase 6 item #20) -- a scene quoting an
    # entity that matches neither the plan's locked running_example nor the
    # beat's own claims is a candidate invented example (confirmed live: the
    # dog/park/bone regression), not a confirmed defect -- regex entity
    # extraction from prose isn't reliable enough to promote to a hard gate.
    entity_consistency: DiagnosticResult | None = None
    # STORY_IMPROVEMENT_PLAN.md Phase 15: compositional-monotony findings across the sampled
    # sequence of scenes -- never a hard gate (a layout-rhythm judgement call), reported
    # alongside visual_critique_issues for visibility.
    sequence_critique_issues: list[CritiqueIssue] = field(default_factory=list)
    late_narration_repairs_used: int = 0
    # PIPELINE_AUDIT_2026-09-17.md (visual monotony): a cheap, deterministic, always-
    # available complement to `sequence_critique_issues` above -- that LLM-based check is
    # sampled to whichever scenes have a screenshot (a bounded C3 subset) and gated behind
    # playwright; this runs on every scene, unconditionally, no LLM call needed. Advisory
    # only (AMBER at most), same "layout-rhythm judgement call" reasoning.
    visual_variety: DiagnosticResult | None = None


def synthesize_video_html(
    plan: StoryPlan, narration: list[SceneNarration], claims: list[Claim], html_author: Agent,
) -> HtmlSynthesisResult:
    hero = synthesize_hero(plan, html_author)
    beat_visuals = [synthesize_beat_visual(beat, plan, claims, html_author, narration) for beat in plan.beats]
    video_script_html, page_html = synthesize_page(plan, hero, beat_visuals, narration)
    render_issues = (
        check_render_static(video_script_html, page_html, narration, claims)
        + check_render_content(page_html, plan, hero, beat_visuals, narration)
        + check_formula_stage_consistency(plan, beat_visuals)
    )
    return HtmlSynthesisResult(
        video_script_html=video_script_html, page_html=page_html,
        hero=hero, beat_visuals=beat_visuals, render_issues=render_issues,
        entity_consistency=check_running_example_entity_consistency(plan, beat_visuals, claims),
        visual_variety=check_consecutive_component_repetition(beat_visuals),
    )


def _visual_critique_to_render_issues(issues: list[CritiqueIssue]) -> list[RenderIssue]:
    """Only a genuinely structural finding routes to repair -- the exact,
    Python-checkable signal `visual_critic.py`'s own prompt asks for, never
    a separate yes/no question put to the model."""
    return [
        RenderIssue("c3_structural_finding", issue.problem, scene_id=issue.scene_ids[0])
        for issue in issues
        if issue.severity == "critical" and issue.layer in ("VISUAL", "RENDERER")
        and issue.repair_owner == "html_author" and issue.scene_ids
    ]


def _visual_critique_to_narration_level_issues(issues: list[CritiqueIssue]) -> list[RenderIssue]:
    """STORY_IMPROVEMENT_PLAN.md Phase 8.6: a CRITICAL C3 finding whose own
    `repair_owner` is `narration_lead` means C3 itself judged the fix
    belongs in the spoken narration, not the HTML -- something H-repair
    (which only ever regenerates screen prose/component data, never
    narration) structurally cannot fix. By the time C3 runs, the
    story+narration loop has already finished, so there is no way to feed
    this back into a fresh B1/B2 cycle within this same run -- but it must
    still block promotion rather than being silently absorbed into
    `visual_critique_issues` with no consequence, which is what happened
    before this fix (only `repair_owner == "html_author"` ever became a
    real `RenderIssue`)."""
    return [
        RenderIssue("c3_narration_level_finding", issue.problem, scene_id=issue.scene_ids[0])
        for issue in issues
        if issue.severity == "critical" and issue.repair_owner == "narration_lead" and issue.scene_ids
    ]


def _attempt_late_narration_repair(
    plan: StoryPlan, narration: list[SceneNarration], claims: list[Claim], finding: CritiqueIssue,
    hero: HeroContent, beat_visuals: list[BeatVisual], html_author: Agent, narration_lead: Agent,
    visual_auditor: Agent, budget: BudgetCounter,
) -> tuple[list[SceneNarration], list[BeatVisual], bool]:
    """STORY_IMPROVEMENT_PLAN.md Phase 15: one bounded attempt to actually resolve a genuine
    screen/narration factual contradiction C3 found, scoped to exactly the one scene named.
    Returns (narration, beat_visuals, resolved) -- `resolved=False` means the finding still
    stands and must still block promotion, exactly as it did before this attempt existed."""
    from editing.models import RevisionPlan, RewriteScene
    from editing.targeted_rewrite import apply_targeted_rewrite
    from review.grounding_verifier import verify_grounding
    from verification.hard.render_rendered import capture_scene_screenshots

    if not finding.scene_ids:
        return narration, beat_visuals, False
    scene_id = finding.scene_ids[0]
    beat_id = next((s.beat_id for s in plan.scene_plan if s.scene_id == scene_id), None)
    beat = next((b for b in plan.beats if b.beat_id == beat_id), None)
    if beat is None:
        return narration, beat_visuals, False

    revision_plan = RevisionPlan(
        run_id="c3-late-repair",
        rewrite_scenes=[RewriteScene(scene_id=scene_id, reason=finding.problem, intent=finding.recommended_intent)],
    )
    narration = apply_targeted_rewrite(plan, narration, claims, revision_plan, narration_lead)
    rewritten_scene = next((n for n in narration if n.scene_id == scene_id), None)
    if rewritten_scene is not None:
        # Sanity check only, scoped to this one scene -- confirms B2's fix didn't itself
        # introduce a new grounding problem. Reuses `visual_auditor` (already paid for in
        # this function) rather than threading in a separate strong-tier agent -- acceptable
        # for this narrow, single-scene, already-exceptional path; never a substitute for the
        # main story+narration loop's own C2b pass.
        verify_grounding([rewritten_scene], claims, visual_auditor, budget)

    beat_visual_by_id = {bv.beat_id: bv for bv in beat_visuals}
    beat_visual_by_id[beat.beat_id] = repair_beat_visual(
        beat, plan, claims, html_author,
        [RenderIssue("c3_narration_contradiction", finding.problem, scene_id=scene_id)], narration,
    )
    beat_visuals = [beat_visual_by_id[b.beat_id] for b in plan.beats]

    # Re-render and re-run C3 on just this one scene to confirm the contradiction is
    # actually gone -- not assumed resolved just because a repair was attempted.
    video_script_html, _ = synthesize_page(plan, hero, beat_visuals, narration)
    try:
        screenshots = capture_scene_screenshots(video_script_html, [scene_id])
    except ImportError:
        return narration, beat_visuals, False  # can't re-confirm without Playwright -- stays blocking
    if not screenshots:
        return narration, beat_visuals, False

    prose = next((s.screen_prose for s in beat_visual_by_id[beat.beat_id].scenes if s.scene_id == scene_id), "")
    narration_text = " ".join(s.text for s in rewritten_scene.sentences) if rewritten_scene else ""
    recheck_payload = [scene_payload(scene_id, 0, prose, narration_text)]
    recheck_issues = critique_visuals(recheck_payload, list(screenshots.values()), visual_auditor, budget)
    still_contradicts = any(
        i.severity == "critical" and i.repair_owner == "narration_lead" for i in recheck_issues
    )
    return narration, beat_visuals, not still_contradicts


def synthesize_and_repair_video_html(
    plan: StoryPlan, narration: list[SceneNarration], claims: list[Claim],
    html_author: Agent, visual_auditor: Agent, budget: BudgetCounter,
    *, narration_lead: Agent | None = None, enable_rendered_checks: bool = True,
) -> HtmlSynthesisResult:
    hero = synthesize_hero(plan, html_author)
    beat_visuals = [synthesize_beat_visual(beat, plan, claims, html_author, narration) for beat in plan.beats]
    repairs_used = 0
    degraded_capabilities: list[str] = []

    def apply_repairs(failures: list[RenderIssue]) -> bool:
        """Regenerates every beat/hero a failure actually named. Returns
        False (no-op) when the budget is spent or nothing here is
        repairable via content -- e.g. a page-wide design-token bug with
        no scene_id at all, which correctly stays a hard failure rather
        than looping forever against something a content repair can't fix."""
        nonlocal hero, beat_visuals, repairs_used
        if repairs_used >= MAX_HTML_REPAIRS:
            return False
        flagged_scene_ids = {i.scene_id for i in failures if i.scene_id}
        if not flagged_scene_ids:
            return False

        applied = False
        if "hero" in flagged_scene_ids:
            hero = repair_hero(plan, html_author, [i for i in failures if i.scene_id == "hero"])
            applied = True

        grouped = beats_to_repair(plan, flagged_scene_ids - {"hero"})
        if grouped:
            beat_by_id = {b.beat_id: b for b in plan.beats}
            beat_visual_by_id = {bv.beat_id: bv for bv in beat_visuals}
            for beat_id, scene_ids in grouped.items():
                beat = beat_by_id.get(beat_id)
                if beat is None:
                    continue
                beat_failures = [i for i in failures if i.scene_id in scene_ids]
                beat_visual_by_id[beat_id] = repair_beat_visual(
                    beat, plan, claims, html_author, beat_failures, narration,
                )
                applied = True
            beat_visuals = [beat_visual_by_id[b.beat_id] for b in plan.beats]

        if applied:
            repairs_used += 1
        return applied

    # ---- static checks: free, deterministic, always run ----
    while True:
        video_script_html, page_html = synthesize_page(plan, hero, beat_visuals, narration)
        static_issues = (
            check_render_static(video_script_html, page_html, narration, claims)
            + check_render_content(page_html, plan, hero, beat_visuals, narration)
            + check_formula_stage_consistency(plan, beat_visuals)
        )
        if not static_issues or not apply_repairs(static_issues):
            break

    render_issues = list(static_issues)

    # ---- rendered checks: need a real browser, degrade visibly if absent ----
    playwright_available = True
    rendered_ran_clean = False
    if enable_rendered_checks:
        while True:
            try:
                from verification.hard.render_rendered import run_rendered_checks
            except ImportError:
                playwright_available = False
                degraded_capabilities.append("playwright_rendered_checks: playwright not installed")
                break
            video_script_html, page_html = synthesize_page(plan, hero, beat_visuals, narration)
            rendered_issues = run_rendered_checks(video_script_html, narration)
            if not rendered_issues:
                rendered_ran_clean = True
                break
            if not apply_repairs(rendered_issues):
                render_issues = render_issues + rendered_issues
                break

    # ---- C3: only meaningful once rendered checks actually ran clean.
    # Not marked degraded when rendered checks ran but never got clean
    # within budget -- that's a real gate that failed, not a missing
    # capability; only "Playwright was never available at all" degrades. ----
    visual_critique_issues: list[CritiqueIssue] = []
    sequence_critique_issues: list[CritiqueIssue] = []
    late_narration_repairs_used = 0
    if enable_rendered_checks and rendered_ran_clean:
        video_script_html, page_html = synthesize_page(plan, hero, beat_visuals, narration)
        scene_ids = [n.scene_id for n in narration]
        selected = select_scenes_for_visual_audit(scene_ids, flagged_scene_ids=set())
        from verification.hard.render_rendered import capture_scene_screenshots

        screenshots = capture_scene_screenshots(video_script_html, selected)
        if screenshots:
            prose_by_scene = {s.scene_id: s.screen_prose for bv in beat_visuals for s in bv.scenes}
            narration_by_scene = {n.scene_id: " ".join(s.text for s in n.sentences) for n in narration}
            scene_meta_by_id = {s.scene_id: s for s in plan.scene_plan}
            running_example = plan.running_example.model_dump()
            # STORY_IMPROVEMENT_PLAN.md Phase 10 follow-up: same claim-scoping as H's own
            # `available_claims` (by beat.source_unit_ids) -- gives C3 something concrete to
            # check screen prose against, confirmed live to matter (2026-09-15): a qualifier
            # C2b flagged as dropped from narration was independently, silently reproduced in
            # H's own screen prose too, and nothing was checking that side at all.
            qualifiers_by_beat_id = {
                beat.beat_id: [
                    q for c in claims if c.source_unit in set(beat.source_unit_ids) for q in c.required_qualifiers
                ]
                for beat in plan.beats
            }
            payloads = []
            for i, sid in enumerate(screenshots):
                meta = scene_meta_by_id.get(sid)
                payloads.append(scene_payload(
                    sid, i, prose_by_scene.get(sid, ""), narration_by_scene.get(sid, ""),
                    scene_function=meta.scene_function if meta else "standard",
                    must_not_repeat=meta.must_not_repeat if meta else [],
                    running_example=running_example,
                    required_qualifiers=qualifiers_by_beat_id.get(meta.beat_id, []) if meta else [],
                ))
            visual_issues = critique_visuals(payloads, list(screenshots.values()), visual_auditor, budget)
            visual_critique_issues = visual_issues
            structural = _visual_critique_to_render_issues(visual_issues)
            if structural and apply_repairs(structural):
                video_script_html, page_html = synthesize_page(plan, hero, beat_visuals, narration)
                render_issues = render_issues + (
                    check_render_static(video_script_html, page_html, narration, claims)
                    + check_render_content(page_html, plan, hero, beat_visuals, narration)
                    + check_formula_stage_consistency(plan, beat_visuals)
                )
            elif structural:
                render_issues = render_issues + structural
            # Phase 8.6: a critical narration-owned finding is never
            # repairable by H, so it's never passed to apply_repairs -- it
            # goes straight to the blocking render_issues list, UNLESS Phase 15's
            # bounded late repair (below) actually resolves it first.
            narration_level_issues = _visual_critique_to_narration_level_issues(visual_issues)
            if narration_level_issues and narration_lead is not None and late_narration_repairs_used < MAX_LATE_NARRATION_REPAIRS:
                first, rest = narration_level_issues[0], narration_level_issues[1:]
                matching_finding = next(
                    (i for i in visual_issues if i.scene_ids and i.scene_ids[0] == first.scene_id), None,
                )
                if matching_finding is not None:
                    late_narration_repairs_used += 1
                    narration, beat_visuals, resolved = _attempt_late_narration_repair(
                        plan, narration, claims, matching_finding, hero, beat_visuals,
                        html_author, narration_lead, visual_auditor, budget,
                    )
                    render_issues = render_issues + (rest if resolved else narration_level_issues)
                else:
                    render_issues = render_issues + narration_level_issues
            else:
                render_issues = render_issues + narration_level_issues

            # STORY_IMPROVEMENT_PLAN.md Phase 15: compositional monotony across the SAME
            # sampled scenes, in true video order (not `selected`'s flagged-first order) --
            # a different, complementary question from per-scene C3 above: not "is this
            # scene wrong" but "is this SEQUENCE boring even though no scene is."
            ordered_scene_ids = [sid for sid in scene_ids if sid in screenshots]
            if len(ordered_scene_ids) >= 2:
                component_by_scene = {
                    s.scene_id: s.component_id for bv in beat_visuals for s in bv.scenes
                }
                sequence_payloads = [
                    sequence_scene_payload(sid, i, component_by_scene.get(sid))
                    for i, sid in enumerate(ordered_scene_ids)
                ]
                sequence_images = [screenshots[sid] for sid in ordered_scene_ids]
                sequence_critique_issues = critique_visual_sequence(
                    sequence_payloads, sequence_images, visual_auditor, budget,
                )
    elif enable_rendered_checks and not playwright_available:
        degraded_capabilities.append("c3_visual_audit: skipped, playwright not installed")

    video_script_html, page_html = synthesize_page(plan, hero, beat_visuals, narration)
    return HtmlSynthesisResult(
        video_script_html=video_script_html, page_html=page_html,
        hero=hero, beat_visuals=beat_visuals, render_issues=render_issues,
        repairs_used=repairs_used, degraded_capabilities=degraded_capabilities,
        visual_critique_issues=visual_critique_issues,
        entity_consistency=check_running_example_entity_consistency(plan, beat_visuals, claims),
        sequence_critique_issues=sequence_critique_issues,
        visual_variety=check_consecutive_component_repetition(beat_visuals),
        late_narration_repairs_used=late_narration_repairs_used,
    )
