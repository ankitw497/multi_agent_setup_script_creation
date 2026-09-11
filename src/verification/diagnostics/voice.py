"""D* voice diagnostic (plan §10.4, §11.3, V1D).

Real, corpus-fitted replacement for the old provisional single-dimension
placeholder (a single unfitted burstiness stdev check, capped at AMBER,
never RED). Bands are fitted against `docs/corpus/transcripts/` -- real,
human-narrated technical YouTube scripts -- via `voice/fingerprint.py`,
and loaded here from the checked-in `config/voice_fingerprint.yaml` (the
fitted RESULT; the raw corpus itself is gitignored and never a runtime
dependency).

Still deliberately never returns RED (see `fingerprint.score_against_fingerprint`'s
own docstring): a corpus this small (6 documents) doesn't license an
automatic hard failure, only AMBER -- an unfitted-strength signal would
otherwise be able to trigger the same forced-revision escalation a real,
validated RED would (policy_gate's "a RED that survived a revision round"
rule).
"""
from __future__ import annotations

from narration.models import SceneNarration
from review.models import DiagnosticResult
from voice.fingerprint import load_fitted_fingerprint, score_against_fingerprint


def _narration_text(narration: list[SceneNarration]) -> str:
    return " ".join(s.text for scene in narration for s in scene.sentences if s.text.strip())


def check_voice(narration: list[SceneNarration]) -> DiagnosticResult:
    text = _narration_text(narration)
    fingerprint = load_fitted_fingerprint()
    result = score_against_fingerprint(text, fingerprint)
    return DiagnosticResult(dimension="voice", band=result.band, evidence=result.evidence)
