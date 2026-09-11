"""R* for shorts (plan §16, §17): `final/shorts/<k>/{short_plan.json, narration.json,
preview.mp3}`.

`short.html` and `screenshots/` are V1B/V1C (H/HV) -- out of V1A-S's own
scope (plan §17: V1A-S's bar is explicitly "narration.json for a derived
short", not a rendered one). `preview.mp3` (V1C, §20.4) is written only
when TTS synthesis actually succeeded (`result.preview_audio` is not
`None`) -- a degraded/opted-out run has no audio to write, and the
absence of the file is itself accurate, not a bug to paper over.
`quality_report.json`/`cost_report.json` for shorts reuse the exact same
`llm.usage.CostReport`/`verification.models.QualityReport` shapes as
long-form; not wired up yet since ShortRunResult doesn't carry a
UsageLedger reference the way PipelineResult's caller does -- left for
when a real multi-short orchestration run needs it (BUILD_PLAN.md).
"""
from __future__ import annotations

import json
from pathlib import Path

from orchestration.shorts_pipeline import ShortRunResult


def emit_short_deliverables(result: ShortRunResult, short_dir: str | Path) -> Path:
    short_dir = Path(short_dir)
    short_dir.mkdir(parents=True, exist_ok=True)

    (short_dir / "short_plan.json").write_text(result.plan.model_dump_json(indent=2))
    (short_dir / "narration.json").write_text(json.dumps([n.model_dump() for n in result.narration], indent=2))
    if result.preview_audio is not None:
        (short_dir / "preview.mp3").write_bytes(result.preview_audio)

    return short_dir
