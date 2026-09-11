"""The real end-to-end CLI entry point (plan §16/§17's "one callable command").

Wires, in order, every stage from a raw source HTML file through to a
promoted `final/`, with a genuine in-memory handoff between phases (no
phase reloads a previous phase's output from disk -- the exact gap a
2026-09-11 live chained run proved closed, see BUILD_PLAN.md's
cross-cutting section):

    S0  extraction.html_parser.parse_html
    S2a facts.seeds.seed_assumption_ledger / find_formula_claims
    S2b facts.claim_extract.extract_claims
    S2c facts.normalize.dedupe_claims / link_numeric_claims
    C2a facts.verify.verify_claims
    S1  planning.narrative_digest (only above the word threshold)
    A1  planning.source_understanding.understand_source
        orchestration.pipeline.run_story_and_narration_loop (A2/B1/review/A3)
    H+HV orchestration.html_pipeline.synthesize_and_repair_video_html (V1C:
         static -> rendered (Playwright) -> C3 visual audit, each bounded
         by its own repair budget)
        planning.candidate_finder.find_candidates (SC)
        planning.short_planner.plan_shorts (A2s)
        orchestration.shorts_pipeline.run_short
        html_synth.vertical_assembler.synthesize_short_html
        reporting.emit* -> orchestration.paths.promote_to_final() (PASS/PASS_WARN only)

This module owns wiring only -- every stage above is independently built,
unit-tested, and (per BUILD_PLAN.md) individually live-verified elsewhere;
nothing here re-implements a stage's own logic. `orchestration.state`'s
`PipelineState` is the plan's own designed checkpoint/resume format but
is not threaded through here yet -- this entry point runs a single attempt
start to finish and is not itself resumable (a real gap, tracked in
BUILD_PLAN.md, not silently glossed over).

2026-09-11 fix: `html_result.render_issues` used to be computed and logged
but never actually consulted for the promotion decision -- only
`story_result.final_status` gated `promote_to_final()`, so a run with real,
unresolved render issues promoted anyway. The combined status below is
what actually gates promotion now; a degraded HTML pass (e.g. Playwright
unavailable) caps it at PASS_WARN, never a silent PASS (plan §14's "a
degraded run must look degraded").
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from agents.narration_lead import make_narration_lead
from agents.review_lead import make_review_lead
from agents.story_lead import make_story_lead
from agents.worker import make_worker
from extraction.html_parser import parse_html
from facts.claim_extract import extract_claims
from facts.models import Claim
from facts.normalize import dedupe_claims, link_numeric_claims
from facts.seeds import find_formula_claims, seed_assumption_ledger
from facts.verify import verify_claims
from facts.web_evidence import WebSearchBackend
from html_synth.vertical_assembler import synthesize_short_html
from llm.budget import BudgetCounter, DEFAULT_TIERS
from llm.client import make_llm_client
from llm.usage import UsageLedger
from orchestration import paths as P
from orchestration.html_pipeline import HtmlSynthesisResult, synthesize_and_repair_video_html
from orchestration.pipeline import PipelineAgents, PipelineResult, run_story_and_narration_loop, save_result
from orchestration.policy_gate import FinalStatus, apply_editorial_downgrade, compute_final_status
from orchestration.shorts_pipeline import ShortRunResult, ShortsPipelineAgents, run_short
from planning.candidate_finder import find_candidates
from planning.models import SourceBrief
from planning.narrative_digest import build_narrative_digest, needs_narrative_digest
from planning.short_planner import plan_shorts
from planning.source_understanding import understand_source
from reporting.emit import emit_final_deliverables
from reporting.emit_html import emit_html_deliverables
from reporting.emit_short import emit_short_deliverables
from verification.hard.vertical import check_vertical_short

DEFAULT_REFERENCES_DIR = Path("src/config/references")


@dataclass
class PipelineRunOutput:
    run_dir: Path
    story_result: PipelineResult
    html_result: HtmlSynthesisResult
    short_results: list[ShortRunResult] = field(default_factory=list)
    promoted: bool = False
    total_cost_usd: float = 0.0
    final_status: FinalStatus = "FAIL"  # the loop's own status combined with the HTML pass's


def _combine_final_status(story_status: FinalStatus, html_result: HtmlSynthesisResult) -> FinalStatus:
    """The loop's own status is necessary but no longer sufficient --
    unresolved render_issues (repairs exhausted) or a degraded HTML pass
    (e.g. Playwright unavailable) must be able to block promotion or cap
    it at PASS_WARN, never silently waved through (plan §14)."""
    html_status = compute_final_status(
        hard_failures=html_result.render_issues, diagnostics=[], revision_budget_remaining=False,
    )
    combined = apply_editorial_downgrade(story_status, html_status)
    if html_result.degraded_capabilities:
        combined = apply_editorial_downgrade(combined, "PASS_WARN")
    return combined


def _build_claim_registry(
    units, worker, references_dir: Path, review_lead, facts_budget: BudgetCounter,
    js_literals: dict, web_backend: WebSearchBackend | None,
) -> tuple[list[Claim], object]:
    """S2a-c + C2a: extract -> dedupe/link -> verify. Returns (verified_claims, ledger)."""
    ledger = seed_assumption_ledger(js_literals)
    numeric_claims, _unparsed = find_formula_claims(js_literals)

    claims = extract_claims(units, worker)
    claims, _dropped = dedupe_claims(claims)
    numeric_claims = link_numeric_claims(claims, numeric_claims)

    verified = verify_claims(claims, numeric_claims, review_lead, facts_budget, references_dir, web_backend=web_backend)
    return verified, ledger


def run_full_pipeline(
    project_root: Path,
    playlist: str,
    video_slug: str,
    source_html_path: Path,
    target_duration_seconds: float = 900.0,
    audience: str = "",
    run_shorts: bool = True,
    shorts_count: int = 1,
    references_dir: Path = DEFAULT_REFERENCES_DIR,
    web_backend: WebSearchBackend | None = None,
    story_lead_alias: str | None = None,
    log=print,
) -> PipelineRunOutput:
    run_dir = P.next_run_dir(project_root, playlist, video_slug)
    P.scaffold_run_dir(run_dir)
    run_id = run_dir.name
    log(f"run_dir: {run_dir}")

    usage_ledger = UsageLedger(path=str(run_dir / "usage.jsonl"))
    client = make_llm_client(run_id=run_id, ledger=usage_ledger)

    worker = make_worker(client)
    story_lead = make_story_lead(client, alias_override=story_lead_alias)
    story_lead_mini = make_story_lead(client, tier="mini")
    narration_lead = make_narration_lead(client)
    review_lead_strong = make_review_lead(client, tier="strong")
    review_lead_flash = make_review_lead(client, tier="flash")

    # ---- S0 ----
    extraction = parse_html(source_html_path)
    log(f"S0: {len(extraction.units)} source units, profile={extraction.profile_name}")

    # ---- S2a-c + C2a ----
    facts_budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])
    claims, ledger = _build_claim_registry(
        extraction.units, worker, references_dir, review_lead_strong, facts_budget,
        extraction.js_literals, web_backend,
    )
    log(f"S2/C2a: {len(claims)} claims, ${facts_budget.spent_usd:.4f}")

    # ---- S1 (only above the word threshold) + A1 ----
    planning_budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])
    digest = build_narrative_digest(extraction.units, worker) if needs_narrative_digest(extraction.units) else None
    source_brief: SourceBrief = understand_source(
        extraction.units, claims, ledger, story_lead, planning_budget, audience=audience, narrative_digest=digest,
    )
    log(f"A1: topic={source_brief.topic!r}, ${planning_budget.spent_usd:.4f}")

    # ---- A2 -> B1 -> review -> A3 (the bounded story+narration loop) ----
    agents = PipelineAgents(
        story_lead=story_lead, narration_lead=narration_lead,
        review_lead=review_lead_strong, cm_agent=review_lead_flash, worker=worker,
    )
    loop_budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])
    story_result = run_story_and_narration_loop(
        source_brief=source_brief, claims=claims, ledger=ledger,
        all_source_unit_ids=[u.id for u in extraction.units],
        target_duration_seconds=target_duration_seconds, agents=agents, budget=loop_budget,
        source_units=extraction.units,
    )
    log(f"story+narration loop: archetype={story_result.plan.archetype}, final_status={story_result.final_status}, ${loop_budget.spent_usd:.4f}")
    save_result(story_result, run_dir)

    # ---- H + HV (V1C: static -> rendered -> C3, each bounded by its own repair budget) ----
    # direct in-memory handoff from the loop's own plan/narration, no disk reload
    html_budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])
    html_result = synthesize_and_repair_video_html(
        story_result.plan, story_result.narration, claims, narration_lead, review_lead_flash, html_budget,
    )
    log(
        f"H/HV: {len(html_result.beat_visuals)} beats, {len(html_result.render_issues)} render issues, "
        f"{html_result.repairs_used} repair(s), degraded={html_result.degraded_capabilities}, ${html_budget.spent_usd:.4f}"
    )
    emit_html_deliverables(html_result, run_dir / "html")

    # ---- shorts: SC -> A2s -> run_short -> vertical HTML, same in-memory plan/narration/claims ----
    # Computed in memory only here -- nothing is written under run_dir/final/
    # yet. A short's own deliverables land in final/ only once we know the
    # overall run actually finishes PASS/PASS_WARN (below), same rule the
    # long-form side already follows: final/ never holds a partial or
    # failed artifact, so it's never misleading to browse.
    short_results: list[ShortRunResult] = []
    short_artifacts: list[tuple[int, ShortRunResult, str]] = []
    if run_shorts:
        candidates = find_candidates(story_result.plan, story_result.narration, claims, worker)
        log(f"SC: {len(candidates)} candidates")
        if candidates:
            shorts_budget = BudgetCounter(tier=DEFAULT_TIERS["short"])
            short_plans = plan_shorts(
                candidates, story_result.plan, claims, story_lead_mini, shorts_budget,
                run_id=run_id, shorts_count=shorts_count,
            )
            shorts_agents = ShortsPipelineAgents(
                narration_lead=narration_lead, worker=worker, review_agent=review_lead_flash,
            )
            for i, short_plan in enumerate(short_plans, start=1):
                short_budget = BudgetCounter(tier=DEFAULT_TIERS["short"])
                short_result = run_short(short_plan, claims, shorts_agents, short_budget)
                log(f"run_short #{i}: final_status={short_result.final_status}, ${short_budget.spent_usd:.4f}")

                short_html = synthesize_short_html(short_plan, short_result.narration)
                vertical_issues = check_vertical_short(short_html, short_result.narration)
                log(f"  vertical HV: {len(vertical_issues)} issues")

                short_results.append(short_result)
                short_artifacts.append((i, short_result, short_html))

    # ---- final emission + promotion, gated on the loop's status combined with H/HV's ----
    final_status = _combine_final_status(story_result.final_status, html_result)
    promoted = False
    if final_status in ("PASS", "PASS_WARN"):
        emit_final_deliverables(
            story_result, run_dir, run_id, usage_ledger,
            degraded_capabilities=html_result.degraded_capabilities,
        )
        for i, short_result, short_html in short_artifacts:
            if short_result.final_status not in ("PASS", "PASS_WARN"):
                log(f"  short #{i}: final_status={short_result.final_status} -- excluded from final/")
                continue
            short_dir = emit_short_deliverables(short_result, run_dir / "final" / "shorts" / str(i))
            (short_dir / "short.html").write_text(short_html)
        P.promote_to_final(run_dir, project_root, playlist, video_slug)
        promoted = True
        log(f"promoted to: {P.final_dir(project_root, playlist, video_slug)}")
    else:
        log(f"final_status={final_status} (story={story_result.final_status}) -- not promoting (shorts excluded too)")

    total_cost = usage_ledger.total_billed_microusd() / 1_000_000
    log(f"total cost: ${total_cost:.4f}")

    return PipelineRunOutput(
        run_dir=run_dir, story_result=story_result, html_result=html_result,
        short_results=short_results, promoted=promoted, total_cost_usd=total_cost,
        final_status=final_status,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-root", type=Path, default=Path("project"))
    parser.add_argument("--playlist", required=True)
    parser.add_argument("--video-slug", required=True)
    parser.add_argument("--source", type=Path, required=True, help="path to the raw source HTML")
    parser.add_argument("--duration", type=float, default=900.0, help="target narration duration in seconds")
    parser.add_argument("--audience", default="")
    parser.add_argument("--no-shorts", action="store_true", help="skip the shorts pipeline")
    parser.add_argument("--shorts-count", type=int, default=1)
    parser.add_argument("--references-dir", type=Path, default=DEFAULT_REFERENCES_DIR)
    parser.add_argument(
        "--story-lead-alias", default=None,
        help="paid_api_lane alias to pin story_lead to (e.g. openai_story_strong_gpt56 for a "
             "model-tier A/B comparison, STORY_IMPROVEMENT_PLAN.md Phase 4) -- default is the "
             "tier's own default (openai_story_strong / gpt-4o), never changed by this flag alone",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output = run_full_pipeline(
        project_root=args.project_root, playlist=args.playlist, video_slug=args.video_slug,
        source_html_path=args.source, target_duration_seconds=args.duration, audience=args.audience,
        run_shorts=not args.no_shorts, shorts_count=args.shorts_count, references_dir=args.references_dir,
        story_lead_alias=args.story_lead_alias,
    )
    print(f"\nfinal_status: {output.final_status}")
    print(f"promoted: {output.promoted}")
    print(f"total_cost_usd: {output.total_cost_usd:.4f}")
    return 0 if output.final_status in ("PASS", "PASS_WARN") else 1


if __name__ == "__main__":
    sys.exit(main())
