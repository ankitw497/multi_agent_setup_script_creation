"""D* voice diagnostic (plan §10.4, §11.3) -- PROVISIONAL.

The plan's real design is two fitted fingerprints (channel + reference
corpus, plan §11.2) with bands tuned against them -- explicitly deferred
to V1D (BUILD_PLAN.md: "Voice-corpus restoration + refit ... V1D"), since
no corpus exists yet to fit against.

This exists only so C5 (plan §8: "only if voice bands AMBER/RED") has a
real, computable signal to gate on in the meantime, using the plan's own
example statistic (sentence-length burstiness) against a generic,
undemanding placeholder band -- not a claim that this is the real,
calibrated voice diagnostic. It deliberately never returns RED: an
unfitted heuristic should never be able to trigger the same forced-revision
escalation a real, validated RED would (policy_gate's "a RED that survived
a revision round" rule), so it can only ever nudge C5 on, never fail a run.
"""
from __future__ import annotations

import statistics

from narration.models import SceneNarration
from review.models import DiagnosticResult

# Placeholder band, not corpus-fitted (see module docstring). A monotone
# narration (every sentence nearly the same length) reads as robotic; real
# human writing varies more -- stdev in words per sentence.
PROVISIONAL_BURSTINESS_BAND = (4.0, 12.0)


def check_burstiness(narration: list[SceneNarration]) -> DiagnosticResult:
    lengths = [len(s.text.split()) for scene in narration for s in scene.sentences if s.text.strip()]
    if len(lengths) < 2:
        return DiagnosticResult(dimension="voice.burstiness", band="GREEN", evidence="too few sentences to measure")

    stdev = statistics.stdev(lengths)
    low, high = PROVISIONAL_BURSTINESS_BAND
    band = "GREEN" if low <= stdev <= high else "AMBER"
    return DiagnosticResult(
        dimension="voice.burstiness", band=band, value=round(stdev, 2), target=f"{low:.0f}-{high:.0f} (provisional, unfitted)",
        evidence=f"sentence-length stdev {stdev:.2f} words across {len(lengths)} sentences",
    )
