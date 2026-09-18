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
nothing here re-implements a stage's own logic.

STORY_IMPROVEMENT_PLAN.md Phase 17.1: `--resume <run_dir>` now threads `orchestration.state`'s
`PipelineState` through claims (S2/C2a), source understanding (A1), and the story+narration
loop -- a crash or `BudgetExceeded` after any of those no longer means re-paying for them on
the next attempt. This is stage-level resume only: a crash PARTWAY through the loop's own
bounded revision cycles still means redoing the whole loop from A2, and H/HV/shorts are not
yet checkpointed at all (Phase 17.2, deliberately deferred pending evidence 17.1 alone isn't
enough -- no real failure has reached that far yet).

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
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from agents.html_author import make_html_author
from agents.narration_lead import make_narration_lead
from agents.review_lead import make_review_lead
from agents.story_lead import make_story_lead
from agents.worker import make_worker
from extraction.html_parser import parse_html
from facts.claim_extract import extract_claims
from facts.models import Claim
from facts.normalize import dedupe_claims, link_numeric_claims
from facts.seeds import find_formula_claims, seed_assumption_ledger
from facts.verify import find_claims_with_no_verdict, verify_claims
from facts.web_evidence import WebSearchBackend
from html_synth.vertical_assembler import synthesize_short_html
from llm.budget import BudgetCounter, BudgetTier, DEFAULT_TIERS
from llm.client import make_llm_client
from llm.usage import UsageLedger
from orchestration import paths as P
from orchestration.html_pipeline import HtmlSynthesisResult, synthesize_and_repair_video_html
from orchestration.pipeline import PipelineAgents, PipelineResult, run_story_and_narration_loop, save_result
from orchestration.policy_gate import FinalStatus, apply_editorial_downgrade, compute_final_status
from orchestration.shorts_pipeline import ShortRunResult, ShortsPipelineAgents, run_short, save_short_debug
from orchestration.state import PipelineState, load_checkpoint, save_checkpoint
from planning.candidate_finder import find_candidates
from planning.models import SourceBrief
from planning.narrative_digest import build_narrative_digest, needs_narrative_digest
from planning.short_planner import check_bridge_selection_defaulted, plan_shorts
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
    # None only when the structural-coverage gate below skips H/HV entirely (2026-09-15) --
    # every other path always has a real HtmlSynthesisResult.
    html_result: HtmlSynthesisResult | None
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
    loop_budget_usd: float | None = None,
    resume_from: Path | None = None,
    c2b_audit_sample_rate: float = 0.0,
    log=print,
) -> PipelineRunOutput:
    run_dir = P.next_run_dir(project_root, playlist, video_slug)
    P.scaffold_run_dir(run_dir)
    run_id = run_dir.name
    log(f"run_dir: {run_dir}")

    # ---- S0 (always re-run -- free, deterministic, instant; also gives us the source_hash
    # a --resume checkpoint is verified against) ----
    extraction = parse_html(source_html_path)
    log(f"S0: {len(extraction.units)} source units, profile={extraction.profile_name}")

    # STORY_IMPROVEMENT_PLAN.md Phase 17.1: a crash or BudgetExceeded downstream used to mean
    # every relaunch re-paid for claim verification (C2a) and source understanding (A1) from
    # scratch -- confirmed live (2026-09-15): 5 relaunches in one afternoon each repeated that
    # cost before even reaching the point of the PREVIOUS failure. `--resume <run_dir>` loads
    # that run's own checkpoint.json and skips any stage it already has a good result for.
    state: PipelineState
    if resume_from is not None:
        state = load_checkpoint(resume_from)
        if state.source_hash != extraction.source_hash:
            raise ValueError(
                f"refusing to resume from {resume_from}: its checkpoint's source_hash "
                f"({state.source_hash!r}) does not match this --source file's real hash "
                f"({extraction.source_hash!r}) -- resuming into a mismatched source would "
                "silently mix content from two different runs"
            )
        log(f"resuming from {resume_from}: completed stages = {state.completed_stages}")
    else:
        state = PipelineState(
            run_id=run_id, html_path=str(source_html_path), source_hash=extraction.source_hash,
            config={
                "target_duration_seconds": target_duration_seconds, "audience": audience,
                "run_shorts": run_shorts, "shorts_count": shorts_count,
            },
        )
    state.run_id = run_id  # always the NEW run's own id, even when resuming an old checkpoint

    # PIPELINE_AUDIT_2026-09-17.md finding #5: captured HERE, before any of this run's own
    # stages execute -- `state.{claims,source_brief,loop}_spent_microusd` reflect the true
    # spend for those stages whether resumed (inherited from the old checkpoint, about to be
    # skipped this run) or freshly run (set as this run completes them). `usage_ledger` below
    # is always scoped to THIS run's own new usage.jsonl, so a resumed stage's spend would
    # otherwise never be reflected in the final total at all -- confirmed live: `v03`'s
    # reported "$1.6383 total cost" (resumed from `v02`) never included `v02`'s own ~$0.30
    # spend on claims + A1. For a genuinely fresh run (no --resume) this is always 0, since a
    # brand-new PipelineState() starts with all three at 0 -- no risk of double-counting a
    # freshly-run stage's spend (which lands in `usage_ledger` only).
    carried_over_microusd = (
        state.claims_spent_microusd + state.source_brief_spent_microusd + state.loop_spent_microusd
    )

    usage_ledger = UsageLedger(path=str(run_dir / "usage.jsonl"))
    client = make_llm_client(run_id=run_id, ledger=usage_ledger)

    worker = make_worker(client)
    story_lead = make_story_lead(client, alias_override=story_lead_alias)
    story_lead_mini = make_story_lead(client, tier="mini")
    narration_lead = make_narration_lead(client)
    html_author = make_html_author(client)
    review_lead_strong = make_review_lead(client, tier="strong")
    review_lead_flash = make_review_lead(client, tier="flash")

    # ---- S2a-c + C2a ----
    if "claims" in state.completed_stages:
        claims, ledger = state.claim_registry, state.assumption_ledger
        log(f"S2/C2a: resumed from checkpoint, {len(claims)} claims, "
            f"${state.claims_spent_microusd / 1_000_000:.4f} (already spent, not re-billed)")
    else:
        facts_budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])
        claims, ledger = _build_claim_registry(
            extraction.units, worker, references_dir, review_lead_strong, facts_budget,
            extraction.js_literals, web_backend,
        )
        log(f"S2/C2a: {len(claims)} claims, ${facts_budget.spent_usd:.4f}")
        no_verdict = find_claims_with_no_verdict(claims)
        if no_verdict:
            log(f"S2/C2a: WARNING -- {len(no_verdict)} claim(s) got no verdict at all "
                f"(likely a truncated batch response): {no_verdict}")
        state.claim_registry, state.assumption_ledger = claims, ledger
        state.claims_spent_microusd = facts_budget.spent_microusd
        state.completed_stages.append("claims")
        save_checkpoint(state, run_dir)

    # ---- S1 (only above the word threshold) + A1 ----
    if "source_brief" in state.completed_stages:
        source_brief = state.source_brief
        log(f"A1: resumed from checkpoint, topic={source_brief.topic!r}, "
            f"${state.source_brief_spent_microusd / 1_000_000:.4f} (already spent, not re-billed)")
    else:
        planning_budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])
        digest = build_narrative_digest(extraction.units, worker) if needs_narrative_digest(extraction.units) else None
        source_brief = understand_source(
            extraction.units, claims, ledger, story_lead, planning_budget, audience=audience, narrative_digest=digest,
        )
        log(f"A1: topic={source_brief.topic!r}, ${planning_budget.spent_usd:.4f}")
        state.source_brief = source_brief
        state.source_brief_spent_microusd = planning_budget.spent_microusd
        state.completed_stages.append("source_brief")
        save_checkpoint(state, run_dir)

    # ---- A2 -> B1 -> review -> A3 (the bounded story+narration loop) ----
    agents = PipelineAgents(
        story_lead=story_lead, narration_lead=narration_lead,
        review_lead=review_lead_strong, cm_agent=review_lead_flash, worker=worker,
    )
    if "story_loop" in state.completed_stages:
        story_result = PipelineResult(
            plan=state.plan, narration=state.narration, review_bundle=state.review_bundle,
            final_status=state.story_final_status, story_replans_used=state.story_replans_used,
            major_revisions_used=state.major_revisions_used, log=["resumed from checkpoint"],
        )
        log(f"story+narration loop: resumed from checkpoint, archetype={story_result.plan.archetype}, "
            f"final_status={story_result.final_status}, "
            f"${state.loop_spent_microusd / 1_000_000:.4f} (already spent, not re-billed)")
    else:
        # A reasoning-capable story_lead alias (e.g. gpt-5.6-sol) can cost far
        # more per call than the longform tier's own $1.00 hard cap allows for
        # a full loop -- confirmed live (STORY_IMPROVEMENT_PLAN.md Phase 4):
        # a real comparison run hit BudgetExceeded mid-loop at ~$1.09 spent.
        # loop_budget_usd lets a caller (e.g. a model A/B comparison) raise
        # just this stage's cap without touching every other stage's own
        # independent $1.00 budget.
        loop_tier = DEFAULT_TIERS["longform"]
        if loop_budget_usd is not None:
            base = DEFAULT_TIERS["longform"]
            scale = loop_budget_usd / base.hard_cap_usd
            loop_tier = BudgetTier(
                target_usd=base.target_usd * scale, warning_usd=base.warning_usd * scale,
                hard_cap_usd=loop_budget_usd,
            )
        loop_budget = BudgetCounter(tier=loop_tier)
        story_result = run_story_and_narration_loop(
            source_brief=source_brief, claims=claims, ledger=ledger,
            all_source_unit_ids=[u.id for u in extraction.units],
            target_duration_seconds=target_duration_seconds, agents=agents, budget=loop_budget,
            source_units=extraction.units,
        )
        log(f"story+narration loop: archetype={story_result.plan.archetype}, final_status={story_result.final_status}, ${loop_budget.spent_usd:.4f}")
        save_result(story_result, run_dir)

        # STORY_IMPROVEMENT_PLAN.md Phase 22, step 2 (2026-09-16): opt-in (0.0 = off by
        # default) random audit of C2b's escalation-gating (step 1) -- samples
        # `c2b_audit_sample_rate` of the sentences flash called clean and gets the strong
        # tier's own independent opinion on them too, to MEASURE whether that trust holds
        # rather than assume it. Deliberately off by default: it's a new, not-yet-proven
        # measurement tool, not something that should add cost to every production run
        # before its own signal has been trusted. Uses the final, already-accepted
        # narration's own grounding metadata directly (no second CM pass needed -- CM's
        # mutations already landed on `story_result.narration` during the loop's own last
        # review cycle), so the only new cost is one flash first pass plus the sampled
        # escalation calls, not a full re-verification from scratch.
        if c2b_audit_sample_rate > 0:
            from review.grounding_verifier import audit_clean_verdicts, verify_grounding

            audit_budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])
            audit_verdicts = verify_grounding(story_result.narration, claims, agents.cm_agent, audit_budget)
            audit = audit_clean_verdicts(
                story_result.narration, claims, audit_verdicts, agents.review_lead, audit_budget,
                sample_rate=c2b_audit_sample_rate,
            )
            (run_dir / "reviews" / "c2b_audit.json").write_text(audit.model_dump_json(indent=2))
            log(
                f"C2b audit: sampled {audit.sampled_count}, "
                f"disagreement_rate={audit.disagreement_rate:.2%}, ${audit_budget.spent_usd:.4f}"
            )
        state.plan, state.narration, state.review_bundle = story_result.plan, story_result.narration, story_result.review_bundle
        state.story_replans_used = story_result.story_replans_used
        state.major_revisions_used = story_result.major_revisions_used
        state.story_final_status = story_result.final_status
        state.loop_spent_microusd = loop_budget.spent_microusd
        state.completed_stages.append("story_loop")
        save_checkpoint(state, run_dir)

    # ---- structural-coverage gate (2026-09-15): a FAIL caused by whole source sections
    # never making it into any beat (required_source_unit_uncovered/source_unit_missing_
    # disposition -- verification/hard/structure.py::check_source_disposition) is
    # categorically worse than an ordinary style/critique FAIL that just didn't fully
    # converge: no amount of H/HV or shorts work can fix content that was never planned in
    # the first place, so spending on them is pure waste, and the resulting HTML draft
    # (never actually promoted -- see the final_status gate below) can look deliverable
    # enough to be mistaken for one. Confirmed live: a run whose one replan attempt also
    # missed 3 whole source sections still ran full H/HV and shorts before failing to
    # promote. Skip straight to reporting FAIL instead.
    _uncovered_source_content = story_result.final_status == "FAIL" and any(
        f.startswith("required_source_unit_uncovered:") or f.startswith("source_unit_missing_disposition:")
        for f in story_result.review_bundle.hard_failures
    )
    if _uncovered_source_content:
        log(
            "story loop FAILed with source content never covered by any beat -- skipping H/HV "
            "and shorts entirely (no amount of downstream work fixes content that was never "
            "planned): " + "; ".join(
                f for f in story_result.review_bundle.hard_failures
                if f.startswith("required_source_unit_uncovered:") or f.startswith("source_unit_missing_disposition:")
            )
        )
        total_cost = (usage_ledger.total_billed_microusd() + carried_over_microusd) / 1_000_000
        log(f"total cost: ${total_cost:.4f}")
        return PipelineRunOutput(
            run_dir=run_dir, story_result=story_result, html_result=None,
            short_results=[], promoted=False, total_cost_usd=total_cost, final_status="FAIL",
        )

    # ---- H + HV (V1C: static -> rendered -> C3, each bounded by its own repair budget) ----
    # direct in-memory handoff from the loop's own plan/narration, no disk reload
    html_budget = BudgetCounter(tier=DEFAULT_TIERS["longform"])
    html_result = synthesize_and_repair_video_html(
        story_result.plan, story_result.narration, claims, html_author, review_lead_flash, html_budget,
        narration_lead=narration_lead,
    )
    log(
        f"H/HV: {len(html_result.beat_visuals)} beats, {len(html_result.render_issues)} render issues, "
        f"{html_result.repairs_used} repair(s), {len(html_result.sequence_critique_issues)} sequence issue(s), "
        f"{html_result.late_narration_repairs_used} late narration repair(s), "
        f"degraded={html_result.degraded_capabilities}, ${html_budget.spent_usd:.4f}"
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
            # shorts_count<=0 (2026-09-15): "as many shorts as SC actually found," not a
            # fixed guess made before candidates existed -- a real request after a run
            # found 4 candidates but only ever attempted 1 (the CLI default).
            effective_shorts_count = len(candidates) if shorts_count <= 0 else shorts_count
            shorts_budget = BudgetCounter(tier=DEFAULT_TIERS["short"])
            short_plans = plan_shorts(
                candidates, story_result.plan, claims, story_lead_mini, shorts_budget,
                run_id=run_id, shorts_count=effective_shorts_count,
            )
            bridge_note = check_bridge_selection_defaulted(candidates, short_plans)
            if bridge_note:
                log(bridge_note)
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
                if vertical_issues:
                    # 2026-09-16: confirmed live -- this was computed and logged as a bare
                    # count but never actually consulted for the short's own pass/fail
                    # decision, the exact same class of gap the 2026-09-11 long-form fix
                    # (this module's own docstring, "the combined status below is what
                    # actually gates promotion now") already closed for H/HV. A short with
                    # a real vertical defect (a tampered narration hash, a missing safe
                    # zone, an undeclared CSS variable silently dropping a style) could
                    # PASS its narration review and still ship broken -- mirrors
                    # _combine_final_status's own story+html combination, scaled to shorts.
                    vertical_hard_failures = [f"{i.code}: {i.detail}" for i in vertical_issues]
                    vertical_status = compute_final_status(
                        hard_failures=vertical_hard_failures, diagnostics=[], revision_budget_remaining=False,
                    )
                    short_result.hard_failures = short_result.hard_failures + vertical_hard_failures
                    short_result.final_status = apply_editorial_downgrade(short_result.final_status, vertical_status)
                    log(f"  vertical HV downgraded final_status to {short_result.final_status}")

                # Always written, regardless of pass/fail AND regardless of the overall
                # run's own status (2026-09-15) -- unlike final/shorts/<i>/, which is
                # gated on the OVERALL run's combined status (the parent long-form
                # result), not this short's own. Confirmed live: a short can
                # individually PASS_WARN with zero hard failures yet never be written
                # anywhere on disk simply because the unrelated parent run FAILed.
                save_short_debug(short_result, i, run_dir, short_html=short_html)

                short_results.append(short_result)
                short_artifacts.append((i, short_result, short_html))

    # ---- final emission + promotion, gated on the loop's status combined with H/HV's ----
    final_status = _combine_final_status(story_result.final_status, html_result)
    promoted = False
    if final_status in ("PASS", "PASS_WARN"):
        emit_final_deliverables(
            story_result, run_dir, run_id, usage_ledger,
            degraded_capabilities=html_result.degraded_capabilities,
            carried_over_microusd=carried_over_microusd,
        )
        # 2026-09-17 fix: emit_html_deliverables above (line ~363) only ever wrote
        # into run_dir/"html" -- promote_to_final() copies run_dir/"final" verbatim,
        # so video_script.html/page.html/render_report.json never reached the
        # promoted final/ at all (confirmed live: a real promoted run had every
        # report *about* the script but not the script itself). Mirror shorts'
        # own pattern of writing a second, final-bound copy only once promotion
        # is actually happening.
        emit_html_deliverables(html_result, run_dir / "final")
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

    total_cost = (usage_ledger.total_billed_microusd() + carried_over_microusd) / 1_000_000
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
    parser.add_argument(
        "--shorts-count", type=int, default=1,
        help="how many shorts to attempt; 0 means one per candidate SC actually finds, "
             "rather than a fixed guess made before candidates exist (default: 1)",
    )
    parser.add_argument("--references-dir", type=Path, default=DEFAULT_REFERENCES_DIR)
    parser.add_argument(
        "--story-lead-alias", default=None,
        help="paid_api_lane alias to pin story_lead to, overriding the tier's own default -- "
             "e.g. pass openai_story_strong to roll back to gpt-4o. Default (2026-09-16, "
             "STORY_IMPROVEMENT_PLAN.md Phase 4) is now openai_story_strong_gpt56 (gpt-5.6-sol), "
             "never changed by this flag alone",
    )
    parser.add_argument(
        "--loop-budget-usd", type=float, default=None,
        help="raise the story+narration loop's own hard budget cap above the longform tier's "
             "default $1.00 (target/warning scale proportionally) -- needed for a reasoning-"
             "capable story_lead alias (e.g. gpt-5.6-sol via --story-lead-alias), which can cost "
             "far more per call than gpt-4o and hit the default cap before the loop finishes",
    )
    parser.add_argument(
        "--resume", type=Path, default=None,
        help="path to a previous run's own runs/vNN directory to resume from (e.g. "
             "project/<playlist>/<video-slug>/runs/v03) -- STORY_IMPROVEMENT_PLAN.md Phase "
             "17.1: skips claim verification (C2a), source understanding (A1), and the "
             "story+narration loop if that run's checkpoint.json already has a good result "
             "for it, instead of re-paying for them after a crash or BudgetExceeded. Refuses "
             "to resume if the checkpoint's source_hash doesn't match --source. Writes into a "
             "NEW runs/vNN directory, same as any other invocation -- never mutates the "
             "resumed-from run's own directory. Does not (yet) resume from partway through "
             "the loop's own revision cycles, H/HV, or shorts -- see Phase 17.2.",
    )
    parser.add_argument(
        "--c2b-audit-sample-rate", type=float, default=0.0,
        help="STORY_IMPROVEMENT_PLAN.md Phase 22, step 2: fraction (0.0-1.0) of C2b's "
             "flash-tier 'clean' verdicts to re-check against the strong tier, to measure "
             "(not gate) how often that trust actually holds -- writes reviews/c2b_audit.json. "
             "0.0 (default) means off; the plan's own suggested starting point once enabled "
             "is 0.10.",
    )
    return parser.parse_args(argv)


def _prevent_system_sleep() -> None:
    """A full run can take well over an hour (a reasoning-capable
    story_lead alias especially, see ERR-046/047) -- macOS idle/display
    sleep mid-run doesn't kill the process, but it can stall or drop
    in-flight network calls in ways indistinguishable from ERR-047's hang
    without close inspection. `caffeinate -w <pid>` prevents idle sleep for
    exactly as long as THIS process is alive and exits on its own once it
    isn't -- never left running after the fact. Best-effort only: silently
    does nothing on a non-Darwin platform or if `caffeinate` isn't on PATH,
    since this is a convenience, not something the pipeline should ever
    fail a real run over."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.Popen(
            ["caffeinate", "-i", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    _prevent_system_sleep()
    args = _parse_args(argv)
    output = run_full_pipeline(
        project_root=args.project_root, playlist=args.playlist, video_slug=args.video_slug,
        source_html_path=args.source, target_duration_seconds=args.duration, audience=args.audience,
        run_shorts=not args.no_shorts, shorts_count=args.shorts_count, references_dir=args.references_dir,
        story_lead_alias=args.story_lead_alias, loop_budget_usd=args.loop_budget_usd,
        resume_from=args.resume, c2b_audit_sample_rate=args.c2b_audit_sample_rate,
    )
    print(f"\nfinal_status: {output.final_status}")
    print(f"promoted: {output.promoted}")
    print(f"total_cost_usd: {output.total_cost_usd:.4f}")
    return 0 if output.final_status in ("PASS", "PASS_WARN") else 1


if __name__ == "__main__":
    sys.exit(main())
