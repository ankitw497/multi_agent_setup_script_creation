"""H + HV static (plan §12, §13). V1B scope -- no Playwright, no rendered
checks, no C3/repair loop (all V1C). Single pass: synthesize, then run the
static verification suite; a failing result is reported, not auto-repaired
(the H REPAIR cycle is explicitly V1C, gated on the rendered checks this
module never runs).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.base import Agent
from facts.models import Claim
from html_synth.assembler import synthesize_page
from html_synth.synthesizer import BeatVisual, HeroContent, synthesize_beat_visual, synthesize_hero
from narration.models import SceneNarration
from planning.models import StoryPlan
from verification.hard.render import RenderIssue, check_render_content, check_render_static


@dataclass
class HtmlSynthesisResult:
    video_script_html: str
    page_html: str
    hero: HeroContent
    beat_visuals: list[BeatVisual]
    render_issues: list[RenderIssue] = field(default_factory=list)


def synthesize_video_html(
    plan: StoryPlan, narration: list[SceneNarration], claims: list[Claim], narration_lead: Agent,
) -> HtmlSynthesisResult:
    hero = synthesize_hero(plan, narration_lead)
    beat_visuals = [synthesize_beat_visual(beat, plan, claims, narration_lead) for beat in plan.beats]
    video_script_html, page_html = synthesize_page(plan, hero, beat_visuals, narration)
    render_issues = (
        check_render_static(video_script_html, page_html, narration, claims)
        + check_render_content(page_html, plan, hero, beat_visuals, narration)
    )
    return HtmlSynthesisResult(
        video_script_html=video_script_html, page_html=page_html,
        hero=hero, beat_visuals=beat_visuals, render_issues=render_issues,
    )
