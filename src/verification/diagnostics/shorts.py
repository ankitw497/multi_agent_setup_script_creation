"""D* diagnostics for the `short` profile (plan §20.10). Deterministic.

Only the diagnostics genuinely computable now, without H/HV rendering
(visual density, on-screen text density) or a fitted voice corpus
(sentence rhythm vs the short profile): time to hook event, setup length,
and word count vs the advisory band. Hook STRENGTH itself is C4s's job
(a judgement call), not this module's -- this only measures the
structural timing/length signals plan §20.10 lists as bandable.
"""
from __future__ import annotations

from narration.models import SceneNarration
from planning.shorts_models import ShortPlan
from review.models import DiagnosticResult

PLANNING_WPM = 167
SETUP_LENGTH_TARGET_SECONDS = 10.0  # plan §20.4: "3-10s minimum context"


def check_time_to_hook(plan: ShortPlan) -> DiagnosticResult:
    """Structurally always GREEN -- HookEvent.starts_at_seconds is already
    hard-bounded to 0-3s at the model level (plan §20.4) -- reported here
    for visibility in review_summary.md, not because it can actually fail."""
    seconds = plan.hook.starts_at_seconds
    return DiagnosticResult(
        dimension="short.time_to_hook", band="GREEN", value=seconds, target="<=3s",
        evidence=f"hook event starts at {seconds:.1f}s",
    )


def check_setup_length(narration: list[SceneNarration]) -> DiagnosticResult:
    setup = next((s for s in narration if s.scene_id == "setup"), None)
    if setup is None:
        return DiagnosticResult(dimension="short.setup_length", band="AMBER", evidence="no 'setup' segment found")
    seconds = setup.est_seconds
    band = "GREEN" if seconds <= SETUP_LENGTH_TARGET_SECONDS else "AMBER" if seconds <= SETUP_LENGTH_TARGET_SECONDS * 1.5 else "RED"
    return DiagnosticResult(
        dimension="short.setup_length", band=band, value=round(seconds, 1),
        target=f"<={SETUP_LENGTH_TARGET_SECONDS:.0f}s",
        evidence=f"setup segment estimated at {seconds:.1f}s",
    )


def check_word_count_band(plan: ShortPlan, narration: list[SceneNarration]) -> DiagnosticResult:
    total_words = sum(len(s.text.split()) for scene in narration for s in scene.sentences)
    low, high = plan.narration.word_band
    if low <= total_words <= high:
        band = "GREEN"
    elif (low * 0.8) <= total_words <= (high * 1.2):
        band = "AMBER"
    else:
        band = "RED"
    return DiagnosticResult(
        dimension="short.word_count", band=band, value=total_words, target=f"{low}-{high} (advisory)",
        evidence=f"{total_words} words across {sum(len(s.sentences) for s in narration)} sentences",
    )


def check_short_diagnostics(plan: ShortPlan, narration: list[SceneNarration]) -> list[DiagnosticResult]:
    """The full D* short diagnostics pass -- every diagnostic, one call."""
    return [check_time_to_hook(plan), check_setup_length(narration), check_word_count_band(plan, narration)]
