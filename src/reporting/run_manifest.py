"""run_manifest.json -- narrow V1C scope only: which capabilities this run
degraded, so a viewer of `final/` can see it without cross-referencing
`review_summary.md`'s own prose section. Deliberately NOT the full
manifest IMPLEMENTATION_PLAN.md §16 describes (models, prompt versions,
archetype, analytics schema) -- that's separate, larger, cross-cutting
scope; this only covers what V1C's degrade-visibly requirement needs
today. A run with nothing degraded still gets the file, with an empty list
-- its absence would be ambiguous ("never checked" vs "checked, clean"),
which is exactly the silent-PASS failure mode plan §14 rules out.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RunManifest(BaseModel):
    run_id: str
    degraded_capabilities: list[str] = Field(default_factory=list)


def build_run_manifest(run_id: str, degraded_capabilities: list[str]) -> RunManifest:
    return RunManifest(run_id=run_id, degraded_capabilities=degraded_capabilities)
