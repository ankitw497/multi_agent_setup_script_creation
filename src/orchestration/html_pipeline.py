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
from review.models import CritiqueIssue
from review.visual_critic import critique_visuals, scene_payload
from review.visual_sample import select_scenes_for_visual_audit
from verification.hard.formula_consistency import check_formula_stage_consistency
from verification.hard.render import RenderIssue, check_render_content, check_render_static

MAX_HTML_REPAIRS = 2


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


def synthesize_video_html(
    plan: StoryPlan, narration: list[SceneNarration], claims: list[Claim], narration_lead: Agent,
) -> HtmlSynthesisResult:
    hero = synthesize_hero(plan, narration_lead)
    beat_visuals = [synthesize_beat_visual(beat, plan, claims, narration_lead, narration) for beat in plan.beats]
    video_script_html, page_html = synthesize_page(plan, hero, beat_visuals, narration)
    render_issues = (
        check_render_static(video_script_html, page_html, narration, claims)
        + check_render_content(page_html, plan, hero, beat_visuals, narration)
        + check_formula_stage_consistency(plan, beat_visuals)
    )
    return HtmlSynthesisResult(
        video_script_html=video_script_html, page_html=page_html,
        hero=hero, beat_visuals=beat_visuals, render_issues=render_issues,
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


def synthesize_and_repair_video_html(
    plan: StoryPlan, narration: list[SceneNarration], claims: list[Claim],
    narration_lead: Agent, visual_auditor: Agent, budget: BudgetCounter,
    *, enable_rendered_checks: bool = True,
) -> HtmlSynthesisResult:
    hero = synthesize_hero(plan, narration_lead)
    beat_visuals = [synthesize_beat_visual(beat, plan, claims, narration_lead, narration) for beat in plan.beats]
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
            hero = repair_hero(plan, narration_lead, [i for i in failures if i.scene_id == "hero"])
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
                    beat, plan, claims, narration_lead, beat_failures, narration,
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
            payloads = []
            for i, sid in enumerate(screenshots):
                meta = scene_meta_by_id.get(sid)
                payloads.append(scene_payload(
                    sid, i, prose_by_scene.get(sid, ""), narration_by_scene.get(sid, ""),
                    scene_function=meta.scene_function if meta else "standard",
                    must_not_repeat=meta.must_not_repeat if meta else [],
                    running_example=running_example,
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
    elif enable_rendered_checks and not playwright_available:
        degraded_capabilities.append("c3_visual_audit: skipped, playwright not installed")

    video_script_html, page_html = synthesize_page(plan, hero, beat_visuals, narration)
    return HtmlSynthesisResult(
        video_script_html=video_script_html, page_html=page_html,
        hero=hero, beat_visuals=beat_visuals, render_issues=render_issues,
        repairs_used=repairs_used, degraded_capabilities=degraded_capabilities,
        visual_critique_issues=visual_critique_issues,
    )
