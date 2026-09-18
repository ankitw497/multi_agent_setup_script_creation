"""Tests for orchestration/run_pipeline.py -- the real CLI entry point wiring
S0 through H/HV/shorts/emission/promotion into one callable command.

Every stage this module calls is independently unit-tested elsewhere (S2,
C2a, A1, the story+narration loop, H/HV, shorts) -- these tests exist to
catch WIRING bugs only: wrong call order, a phase not receiving the
previous phase's live in-memory output, promotion firing on the wrong
status. Every stage-level function is monkeypatched to a stub so no real
LLM call is ever made here (that proof already exists as a live run, see
BUILD_PLAN.md's 2026-09-11 update)."""
from types import SimpleNamespace

import pytest

import orchestration.run_pipeline as rp


def make_extraction():
    return SimpleNamespace(
        units=[SimpleNamespace(id="u1")], profile_name="generic",
        profile_confidence=0.9, source_hash="h", js_literals={}, js_rejected=[], js_parse_ok=True,
    )


def make_story_result(final_status="PASS", hard_failures=None):
    plan = SimpleNamespace(archetype="build")
    narration = [SimpleNamespace(scene_id="s1")]
    return SimpleNamespace(
        plan=plan, narration=narration, final_status=final_status,
        review_bundle=SimpleNamespace(hard_failures=hard_failures or []),
        story_replans_used=0, major_revisions_used=0,
    )


def make_html_result(render_issues=None, degraded_capabilities=None):
    return SimpleNamespace(
        beat_visuals=[SimpleNamespace()], hero=SimpleNamespace(),
        render_issues=render_issues or [], degraded_capabilities=degraded_capabilities or [], repairs_used=0,
        sequence_critique_issues=[], late_narration_repairs_used=0,
    )


@pytest.fixture
def patched(monkeypatch, tmp_path):
    """Stubs every phase-level call `run_full_pipeline` makes, and records
    them in `calls` so a test can assert on order/arguments."""
    calls: dict[str, list] = {}

    def record(name):
        def _fn(*args, **kwargs):
            calls.setdefault(name, []).append((args, kwargs))
            return _fn.return_value
        _fn.return_value = None
        return _fn

    extraction = make_extraction()
    claims = ["claim-registry"]
    ledger = "ledger-object"
    source_brief = SimpleNamespace(topic="t")
    story_result = make_story_result()
    html_result = make_html_result()

    monkeypatch.setattr(rp, "make_llm_client", lambda **kw: SimpleNamespace())
    monkeypatch.setattr(rp, "make_worker", lambda client: "worker")
    monkeypatch.setattr(
        rp, "make_story_lead",
        lambda client, tier="strong", alias_override=None: f"story_lead:{tier}:{alias_override}",
    )
    monkeypatch.setattr(rp, "make_narration_lead", lambda client: "narration_lead")
    monkeypatch.setattr(rp, "make_html_author", lambda client: "html_author")
    monkeypatch.setattr(rp, "make_review_lead", lambda client, tier="strong": f"review_lead:{tier}")

    monkeypatch.setattr(rp, "parse_html", record("parse_html"))
    rp.parse_html.return_value = extraction

    monkeypatch.setattr(rp, "_build_claim_registry", record("_build_claim_registry"))
    rp._build_claim_registry.return_value = (claims, ledger)

    # STORY_IMPROVEMENT_PLAN.md: stubbed like every other stage-level call here -- this
    # file's `claims` stand-in is a plain string list, not real Claim objects, so a genuine
    # call would blow up on missing attributes. find_claims_with_no_verdict's own logic is
    # fully covered elsewhere (tests/facts/test_verify.py); this fixture only needs a no-op
    # default so a wiring test can override it to check the log() passthrough specifically.
    monkeypatch.setattr(rp, "find_claims_with_no_verdict", record("find_claims_with_no_verdict"))
    rp.find_claims_with_no_verdict.return_value = []

    monkeypatch.setattr(rp, "needs_narrative_digest", lambda units: False)
    monkeypatch.setattr(rp, "build_narrative_digest", record("build_narrative_digest"))
    rp.build_narrative_digest.return_value = "digest"

    monkeypatch.setattr(rp, "understand_source", record("understand_source"))
    rp.understand_source.return_value = source_brief

    monkeypatch.setattr(rp, "run_story_and_narration_loop", record("run_story_and_narration_loop"))
    rp.run_story_and_narration_loop.return_value = story_result

    monkeypatch.setattr(rp, "save_result", record("save_result"))
    # STORY_IMPROVEMENT_PLAN.md Phase 17.1: stubbed like every other stage-level call here --
    # this file's fixtures use plain SimpleNamespace/string stand-ins, not real pydantic
    # models, so a genuine PipelineState.model_dump_json() call would only produce noisy
    # serializer warnings, never a real checkpoint worth asserting on in a pure wiring test.
    monkeypatch.setattr(rp, "save_checkpoint", record("save_checkpoint"))

    monkeypatch.setattr(rp, "synthesize_and_repair_video_html", record("synthesize_and_repair_video_html"))
    rp.synthesize_and_repair_video_html.return_value = html_result
    monkeypatch.setattr(rp, "emit_html_deliverables", record("emit_html_deliverables"))

    monkeypatch.setattr(rp, "find_candidates", record("find_candidates"))
    rp.find_candidates.return_value = ["candidate-1"]

    monkeypatch.setattr(rp, "plan_shorts", record("plan_shorts"))
    rp.plan_shorts.return_value = ["short-plan-1"]

    # STORY_IMPROVEMENT_PLAN.md Phase 23 continuation: stubbed like every other stage-level
    # call here -- this file's plan_shorts/find_candidates stand-ins are plain strings, not
    # real ShortPlan/ShortsCandidate objects, so a genuine call would blow up on missing
    # attributes. check_bridge_selection_defaulted's own logic is fully covered elsewhere
    # (tests/planning/test_short_planner.py); this fixture only needs a no-op default so
    # wiring tests can override it to check the log() passthrough specifically.
    monkeypatch.setattr(rp, "check_bridge_selection_defaulted", record("check_bridge_selection_defaulted"))
    rp.check_bridge_selection_defaulted.return_value = None

    short_result = SimpleNamespace(final_status="FAIL", narration=[SimpleNamespace(scene_id="hook")], hard_failures=[])
    monkeypatch.setattr(rp, "run_short", record("run_short"))
    rp.run_short.return_value = short_result
    # 2026-09-15: stubbed like save_result/save_checkpoint above -- this file's
    # SimpleNamespace short_result stand-in doesn't carry hard_failures/issues/
    # diagnostics/log, and a real save_short_debug() call would only produce noise here,
    # never something this pure-wiring test file needs to assert on.
    monkeypatch.setattr(rp, "save_short_debug", record("save_short_debug"))

    short_dir = tmp_path / "short_dir"
    short_dir.mkdir()
    monkeypatch.setattr(rp, "emit_short_deliverables", record("emit_short_deliverables"))
    rp.emit_short_deliverables.return_value = short_dir

    monkeypatch.setattr(rp, "synthesize_short_html", record("synthesize_short_html"))
    rp.synthesize_short_html.return_value = "<html>short</html>"

    monkeypatch.setattr(rp, "check_vertical_short", record("check_vertical_short"))
    rp.check_vertical_short.return_value = []

    monkeypatch.setattr(rp, "emit_final_deliverables", record("emit_final_deliverables"))

    fake_paths = SimpleNamespace(
        next_run_dir=record("next_run_dir"),
        scaffold_run_dir=record("scaffold_run_dir"),
        promote_to_final=record("promote_to_final"),
        final_dir=lambda *a, **k: tmp_path / "final",
    )
    run_dir = tmp_path / "runs" / "v01"
    run_dir.mkdir(parents=True)
    fake_paths.next_run_dir.return_value = run_dir
    fake_paths.scaffold_run_dir.return_value = run_dir
    monkeypatch.setattr(rp, "P", fake_paths)

    return SimpleNamespace(
        calls=calls, claims=claims, ledger=ledger, source_brief=source_brief,
        story_result=story_result, html_result=html_result, short_result=short_result,
        run_dir=run_dir, tmp_path=tmp_path,
    )


def _run(patched, **overrides):
    kwargs = dict(
        project_root=patched.tmp_path, playlist="pl", video_slug="vid",
        source_html_path=patched.tmp_path / "in.html", log=lambda *a: None,
    )
    kwargs.update(overrides)
    return rp.run_full_pipeline(**kwargs)


def test_claim_registry_feeds_directly_into_a1_and_the_loop_in_memory(patched):
    _run(patched)
    a1_args = patched.calls["understand_source"][0][0]
    assert a1_args[1] is patched.claims  # claims positional arg, same object, not reloaded
    assert a1_args[2] is patched.ledger

    loop_kwargs = patched.calls["run_story_and_narration_loop"][0][1]
    assert loop_kwargs["claims"] is patched.claims
    assert loop_kwargs["source_brief"] is patched.source_brief


def test_loop_result_feeds_html_synthesis_directly_in_memory_not_reloaded(patched):
    output = _run(patched)
    html_args = patched.calls["synthesize_and_repair_video_html"][0][0]
    assert html_args[0] is patched.story_result.plan
    assert html_args[1] is patched.story_result.narration
    assert output.html_result is patched.html_result


def test_html_synthesis_uses_the_html_author_identity_not_narration_lead(patched):
    """STORY_IMPROVEMENT_PLAN.md Phase 14: the real wiring bug this test file exists to
    catch -- H/H-repair must run under the dedicated html_author identity, not
    narration_lead (whose own base prompt says the opposite of what H's task asks for)."""
    _run(patched)
    html_args = patched.calls["synthesize_and_repair_video_html"][0][0]
    assert html_args[3] == "html_author"


def test_html_synthesis_receives_narration_lead_for_the_bounded_late_repair_path(patched):
    """STORY_IMPROVEMENT_PLAN.md Phase 15: without this, the bounded C3 late-narration-repair
    cycle (B2 -> C2b -> H-repair -> C3-recheck) can never actually run in production --
    `narration_lead` defaults to None and the capability silently stays inert."""
    _run(patched)
    html_kwargs = patched.calls["synthesize_and_repair_video_html"][0][1]
    assert html_kwargs.get("narration_lead") == "narration_lead"


def test_shorts_receive_the_same_in_memory_plan_narration_claims(patched):
    _run(patched)
    sc_args = patched.calls["find_candidates"][0][0]
    assert sc_args[0] is patched.story_result.plan
    assert sc_args[1] is patched.story_result.narration
    assert sc_args[2] is patched.claims

    a2s_args = patched.calls["plan_shorts"][0][0]
    assert a2s_args[1] is patched.story_result.plan
    assert a2s_args[2] is patched.claims


def test_no_verdict_claims_reaches_the_log(patched):
    """STORY_IMPROVEMENT_PLAN.md: a truncated C2a batch response silently dropped 21/80
    claims from verification with no error and no log line. find_claims_with_no_verdict's
    own logic is unit-tested in tests/facts/test_verify.py -- this is a pure wiring test
    confirming a real finding it returns actually reaches log()."""
    rp.find_claims_with_no_verdict.return_value = ["C037", "C038"]
    logged = []
    _run(patched, log=logged.append)
    assert any("C037" in line and "C038" in line for line in logged)


def test_no_dropped_claims_logs_nothing_extra(patched):
    rp.find_claims_with_no_verdict.return_value = []
    logged = []
    _run(patched, log=logged.append)
    assert not any("WARNING" in line for line in logged)


def test_bridge_selection_check_runs_on_the_same_candidates_and_plans(patched):
    _run(patched)
    args = patched.calls["check_bridge_selection_defaulted"][0][0]
    assert args[0] is rp.find_candidates.return_value
    assert args[1] is rp.plan_shorts.return_value


def test_a_real_bridge_note_reaches_the_log(patched):
    """STORY_IMPROVEMENT_PLAN.md Phase 23 continuation: check_bridge_selection_defaulted's
    own logic is unit-tested in tests/planning/test_short_planner.py -- this is a pure
    wiring test confirming a real note it returns actually reaches log(), matching this
    file's own stated purpose (catch wiring bugs, not stage-level logic bugs)."""
    rp.check_bridge_selection_defaulted.return_value = "NOTE: all shorts defaulted to DISCOVERY/NONE"
    logged = []
    _run(patched, log=logged.append)
    assert "NOTE: all shorts defaulted to DISCOVERY/NONE" in logged


def test_no_bridge_note_logs_nothing_extra(patched):
    rp.check_bridge_selection_defaulted.return_value = None
    logged = []
    _run(patched, log=logged.append)
    assert not any("DISCOVERY" in line for line in logged)


def test_shorts_count_zero_matches_however_many_candidates_sc_actually_found(patched):
    """2026-09-15: `--shorts-count 0` means "one per candidate SC found," not a fixed
    guess made before candidates exist -- a real request after a run found 4 candidates
    but only ever attempted 1 (the CLI default)."""
    rp.find_candidates.return_value = ["candidate-1", "candidate-2", "candidate-3", "candidate-4"]
    _run(patched, shorts_count=0)
    a2s_kwargs = patched.calls["plan_shorts"][0][1]
    assert a2s_kwargs["shorts_count"] == 4


def test_a_positive_shorts_count_is_passed_through_unchanged(patched):
    rp.find_candidates.return_value = ["candidate-1", "candidate-2", "candidate-3", "candidate-4"]
    _run(patched, shorts_count=2)
    a2s_kwargs = patched.calls["plan_shorts"][0][1]
    assert a2s_kwargs["shorts_count"] == 2


def test_every_short_gets_a_debug_status_written_regardless_of_pass_or_fail(patched):
    """2026-09-15: a real gap -- a FAILed short's own hard_failures/issues/log used to
    exist only in a stdout log line, gone once the process exited. Must be written for
    every short, not just ones that get promoted (final/shorts/<i>/ stays promotion-only)."""
    _run(patched)
    assert len(patched.calls["save_short_debug"]) == 1
    args, kwargs = patched.calls["save_short_debug"][0]
    assert args[0] is patched.short_result
    assert args[1] == 1  # 1-indexed, matching run_short's own #1/#2/... log lines
    assert args[2] == patched.run_dir


def test_save_short_debug_receives_the_actual_generated_html_regardless_of_overall_run_status(patched):
    """2026-09-15: confirmed live -- a short can individually PASS_WARN with zero hard
    failures, yet final/shorts/<i>/ (gated on the OVERALL run's combined status) never
    gets written when the unrelated parent long-form run FAILed. save_short_debug must
    receive the short's real HTML unconditionally, not just when the run promotes."""
    rp.run_story_and_narration_loop.return_value = make_story_result("FAIL")  # overall run will not promote
    rp.synthesize_short_html.return_value = "<html>the actual short</html>"
    _run(patched)
    _args, kwargs = patched.calls["save_short_debug"][0]
    assert kwargs["short_html"] == "<html>the actual short</html>"


def test_short_html_synthesized_from_run_shorts_own_in_memory_narration(patched):
    _run(patched)
    vertical_args = patched.calls["synthesize_short_html"][0][0]
    assert vertical_args[1] is patched.short_result.narration


def test_vertical_issues_downgrade_a_passing_shorts_own_final_status(patched):
    """2026-09-16: confirmed live -- check_vertical_short()'s result used to be
    computed and logged as a bare count, never actually consulted for the short's
    own pass/fail decision. A short with a real vertical defect (a tampered
    narration hash, a missing safe zone, an undeclared CSS variable) could PASS its
    narration review and still ship broken."""
    patched.short_result.final_status = "PASS"
    rp.check_vertical_short.return_value = [SimpleNamespace(code="css_variable_never_declared", detail="var(--r_sm) is undeclared")]

    _run(patched)

    assert patched.short_result.final_status == "FAIL"
    assert any("css_variable_never_declared" in f for f in patched.short_result.hard_failures)


def test_no_vertical_issues_leaves_the_shorts_own_final_status_untouched(patched):
    patched.short_result.final_status = "PASS"
    rp.check_vertical_short.return_value = []

    _run(patched)

    assert patched.short_result.final_status == "PASS"
    assert patched.short_result.hard_failures == []


def test_shorts_skipped_entirely_when_no_candidates_found(patched):
    rp.find_candidates.return_value = []
    _run(patched)
    assert "plan_shorts" not in patched.calls
    assert "run_short" not in patched.calls


def test_no_shorts_flag_skips_the_whole_shorts_branch(patched):
    _run(patched, run_shorts=False)
    assert "find_candidates" not in patched.calls
    assert "plan_shorts" not in patched.calls


@pytest.mark.parametrize("final_status,expect_promoted", [("PASS", True), ("PASS_WARN", True), ("FAIL", False), ("REVISE", False)])
def test_promotes_only_on_pass_or_pass_warn(patched, final_status, expect_promoted):
    rp.run_story_and_narration_loop.return_value = make_story_result(final_status)
    output = _run(patched)
    assert output.promoted is expect_promoted
    assert ("emit_final_deliverables" in patched.calls) is expect_promoted
    assert ("promote_to_final" in patched.calls) is expect_promoted


@pytest.mark.parametrize("code", ["required_source_unit_uncovered", "source_unit_missing_disposition"])
def test_uncovered_source_content_skips_html_and_shorts_entirely(patched, code):
    """2026-09-15: confirmed live -- a run whose one replan attempt still left whole source
    sections (e.g. the source's own cross-attention section) uncovered by any beat still ran
    full H/HV and shorts before failing to promote, wasting real $ and producing a draft HTML
    that could be mistaken for a real deliverable. No amount of downstream work fixes content
    that was never planned, so this must short-circuit before H/HV, not just before promotion."""
    rp.run_story_and_narration_loop.return_value = make_story_result(
        "FAIL", hard_failures=[f"{code}: never referenced by any beat: heads (SUPPORTING, reason: 'x')"],
    )
    output = _run(patched)
    assert output.final_status == "FAIL"
    assert output.promoted is False
    assert output.html_result is None
    assert output.short_results == []
    assert "synthesize_and_repair_video_html" not in patched.calls
    assert "find_candidates" not in patched.calls
    assert "emit_final_deliverables" not in patched.calls


def test_an_ordinary_fail_without_uncovered_source_content_still_runs_html_and_shorts(patched):
    """The gate must be specific to a structural coverage gap -- an ordinary style/critique
    FAIL that never resolved (e.g. a run that just exhausted its revision budget on tone
    issues) still gets its H/HV draft rendered same as before; only a coverage-type hard
    failure is categorically un-fixable downstream."""
    rp.run_story_and_narration_loop.return_value = make_story_result(
        "FAIL", hard_failures=["critical/clarity (TECHNICAL) [c1_x]: some unrelated critique issue"],
    )
    output = _run(patched)
    assert output.final_status == "FAIL"
    assert output.promoted is False
    assert output.html_result is not None
    assert "synthesize_and_repair_video_html" in patched.calls


def test_narrative_digest_only_built_above_the_word_threshold(patched, monkeypatch):
    monkeypatch.setattr(rp, "needs_narrative_digest", lambda units: True)
    _run(patched)
    assert "build_narrative_digest" in patched.calls
    a1_kwargs = patched.calls["understand_source"][0][1]
    assert a1_kwargs["narrative_digest"] == "digest"


def test_narrative_digest_skipped_below_the_threshold(patched):
    _run(patched)
    assert "build_narrative_digest" not in patched.calls
    a1_kwargs = patched.calls["understand_source"][0][1]
    assert a1_kwargs["narrative_digest"] is None


def test_a_clean_html_result_promotes_exactly_as_before(patched):
    """V1C: html_result.render_issues/degraded_capabilities must now
    actually be consulted -- confirms the happy path is unaffected."""
    output = _run(patched)
    assert output.promoted is True
    assert output.final_status == "PASS"


def test_unresolved_render_issues_block_promotion_even_when_the_story_passed(patched):
    """Real gap this fix closes: html_result.render_issues used to be
    computed and logged but never actually consulted -- a run with real,
    unresolved render issues promoted anyway."""
    from verification.hard.render import RenderIssue

    rp.run_story_and_narration_loop.return_value = make_story_result("PASS")
    rp.synthesize_and_repair_video_html.return_value = make_html_result(
        render_issues=[RenderIssue("rendered_clipping", "still broken after repair budget exhausted")],
    )

    output = _run(patched)

    assert output.promoted is False
    assert output.final_status == "FAIL"


def test_a_degraded_html_pass_caps_promotion_at_pass_warn_never_pass(patched):
    """Playwright being unavailable (or any other recorded degradation)
    must never let an otherwise-clean run silently reach PASS."""
    rp.run_story_and_narration_loop.return_value = make_story_result("PASS")
    rp.synthesize_and_repair_video_html.return_value = make_html_result(
        degraded_capabilities=["playwright_rendered_checks: playwright not installed"],
    )

    output = _run(patched)

    assert output.promoted is True  # PASS_WARN still promotes
    assert output.final_status == "PASS_WARN"


def test_a_passing_short_is_written_into_final_when_the_run_passes(patched):
    """final/ should hold both the long-form and its shorts together --
    never a run's own final/ with shorts but no script, or vice versa."""
    rp.run_short.return_value = SimpleNamespace(final_status="PASS", narration=[SimpleNamespace(scene_id="hook")])

    _run(patched)

    assert "emit_short_deliverables" in patched.calls
    short_dir_arg = patched.calls["emit_short_deliverables"][0][0][1]
    assert short_dir_arg == patched.run_dir / "final" / "shorts" / "1"


def test_html_deliverables_are_written_into_final_when_the_run_passes(patched):
    """2026-09-17 fix: emit_html_deliverables used to be called only once, into
    run_dir/"html" -- promote_to_final() copies run_dir/"final" verbatim, so
    video_script.html/page.html never actually reached the promoted final/
    (confirmed live: a real promoted run had every report about the script but
    not the script itself). Must be written into both the working html/ dir
    (always) and final/ (only on promotion), mirroring how shorts already do it."""
    _run(patched)

    targets = [call[0][1] for call in patched.calls["emit_html_deliverables"]]
    assert patched.run_dir / "html" in targets
    assert patched.run_dir / "final" in targets


def test_html_deliverables_are_not_written_into_final_when_the_run_does_not_promote(patched):
    rp.run_story_and_narration_loop.return_value = make_story_result("FAIL")

    _run(patched)

    targets = [call[0][1] for call in patched.calls["emit_html_deliverables"]]
    assert targets == [patched.run_dir / "html"]


def test_a_failed_short_is_excluded_from_final_even_when_the_run_passes(patched):
    """A short can fail its own hard gate independently of the long-form --
    it must not end up looking like a finished deliverable in final/."""
    rp.run_short.return_value = SimpleNamespace(final_status="FAIL", narration=[SimpleNamespace(scene_id="hook")])

    output = _run(patched)

    assert output.promoted is True  # the long-form itself still passed
    assert "emit_short_deliverables" not in patched.calls


def test_no_shorts_are_written_into_final_when_the_overall_run_fails(patched):
    """Shorts are still computed (so their own FAIL/PASS is visible in the
    log/PipelineRunOutput), but none of them belong in final/ when the
    run as a whole didn't reach PASS/PASS_WARN."""
    rp.run_short.return_value = SimpleNamespace(final_status="PASS", narration=[SimpleNamespace(scene_id="hook")])
    rp.run_story_and_narration_loop.return_value = make_story_result("FAIL")

    output = _run(patched)

    assert output.promoted is False
    assert "emit_short_deliverables" not in patched.calls
    assert "run_short" in patched.calls  # still computed, just not promoted


def test_story_lead_alias_override_reaches_make_story_lead(patched, monkeypatch):
    """STORY_IMPROVEMENT_PLAN.md Phase 4: a model-tier A/B comparison run
    must be able to pin story_lead to a specific alias end to end from the
    CLI/run_full_pipeline() call, not just at the make_story_lead() level."""
    calls = []
    monkeypatch.setattr(
        rp, "make_story_lead",
        lambda client, tier="strong", alias_override=None: calls.append((tier, alias_override)) or f"story_lead:{tier}",
    )

    _run(patched, story_lead_alias="openai_story_strong_gpt56")

    assert ("strong", "openai_story_strong_gpt56") in calls  # the main story_lead got the override
    assert ("mini", None) in calls  # story_lead_mini is untouched by the override


def test_story_lead_alias_defaults_to_none(patched, monkeypatch):
    calls = []
    monkeypatch.setattr(
        rp, "make_story_lead",
        lambda client, tier="strong", alias_override=None: calls.append((tier, alias_override)) or f"story_lead:{tier}",
    )

    _run(patched)

    assert ("strong", None) in calls


def test_loop_budget_usd_raises_only_the_loops_own_hard_cap(patched):
    """Real gap found live 2026-09-11: a gpt-5.6-sol comparison run hit
    BudgetExceeded mid-loop at ~$1.09 spent, since the story+narration
    loop shares the same $1.00 longform-tier cap as every other stage.
    loop_budget_usd must raise ONLY the loop's own cap, not the whole
    pipeline's default."""
    _run(patched, loop_budget_usd=3.0)

    (_args, kwargs) = patched.calls["run_story_and_narration_loop"][0]
    loop_budget = kwargs["budget"]
    assert loop_budget.tier.hard_cap_usd == 3.0
    assert loop_budget.tier.target_usd < loop_budget.tier.hard_cap_usd  # still a real, ordered tier


def test_loop_budget_usd_defaults_to_the_standard_longform_cap(patched):
    _run(patched)

    (_args, kwargs) = patched.calls["run_story_and_narration_loop"][0]
    loop_budget = kwargs["budget"]
    assert loop_budget.tier.hard_cap_usd == 2.0


class TestC2bAudit:
    """STORY_IMPROVEMENT_PLAN.md Phase 22, step 2: opt-in, off by default."""

    def test_disabled_by_default_no_call_no_file(self, patched, monkeypatch):
        calls = []
        monkeypatch.setattr("review.grounding_verifier.verify_grounding", lambda *a, **k: calls.append("verify") or [])
        monkeypatch.setattr("review.grounding_verifier.audit_clean_verdicts", lambda *a, **k: calls.append("audit"))

        _run(patched)

        assert calls == []
        assert not (patched.run_dir / "reviews" / "c2b_audit.json").exists()

    def test_enabled_writes_the_audit_file_and_uses_the_given_sample_rate(self, patched, monkeypatch):
        from review.grounding_verifier import GroundingAudit

        captured = {}
        monkeypatch.setattr("review.grounding_verifier.verify_grounding", lambda *a, **k: ["fake-verdicts"])

        def fake_audit(*args, **kwargs):
            captured["sample_rate"] = kwargs.get("sample_rate")
            return GroundingAudit(sampled_count=3, disagreement_count=1)

        monkeypatch.setattr("review.grounding_verifier.audit_clean_verdicts", fake_audit)
        (patched.run_dir / "reviews").mkdir(exist_ok=True)  # scaffold_run_dir is stubbed in `patched`

        _run(patched, c2b_audit_sample_rate=0.25)

        assert captured["sample_rate"] == 0.25
        written = (patched.run_dir / "reviews" / "c2b_audit.json").read_text()
        assert '"sampled_count": 3' in written
        assert '"disagreement_count": 1' in written

    def test_a_resumed_story_loop_never_runs_the_audit(self, patched, monkeypatch):
        """The audit only runs alongside a FRESH story-loop computation (inside the same
        `else` branch as `run_story_and_narration_loop` itself) -- a `--resume`-d run that
        skips straight to a checkpointed story_loop result skips the audit too, a known,
        deliberate scope limitation, not a bug."""
        calls = []
        monkeypatch.setattr("review.grounding_verifier.verify_grounding", lambda *a, **k: calls.append("verify") or [])
        monkeypatch.setattr("review.grounding_verifier.audit_clean_verdicts", lambda *a, **k: calls.append("audit"))
        checkpoint_state = SimpleNamespace(
            source_hash="h", completed_stages=["claims", "source_brief", "story_loop"],
            claim_registry=patched.claims, assumption_ledger=patched.ledger,
            claims_spent_microusd=0, source_brief=patched.source_brief, source_brief_spent_microusd=0,
            plan=patched.story_result.plan, narration=patched.story_result.narration,
            review_bundle=patched.story_result.review_bundle, story_replans_used=0,
            major_revisions_used=0, story_final_status="PASS", loop_spent_microusd=0,
        )
        monkeypatch.setattr(rp, "load_checkpoint", lambda path: checkpoint_state)

        _run(patched, resume_from=patched.tmp_path, c2b_audit_sample_rate=0.5)

        assert calls == []


class TestResume:
    """STORY_IMPROVEMENT_PLAN.md Phase 17.1: --resume must skip a stage the checkpoint
    already has a good result for, refuse a mismatched source, and never touch the
    resumed-from run's own directory (writes into a fresh runs/vNN, same as any other
    invocation)."""

    def _fake_checkpoint(self, patched, completed_stages):
        return SimpleNamespace(
            run_id="old-run", html_path="x", source_hash="h", config={},
            source_units=[], claim_registry=patched.claims, assumption_ledger=patched.ledger,
            claims_spent_microusd=70_000,
            source_brief=patched.source_brief, source_brief_spent_microusd=20_000,
            plan=patched.story_result.plan, narration=patched.story_result.narration,
            review_bundle=patched.story_result.review_bundle, story_final_status="PASS",
            story_replans_used=0, major_revisions_used=1, loop_spent_microusd=900_000,
            completed_stages=list(completed_stages), status="running",
        )

    def test_fully_completed_checkpoint_skips_claims_a1_and_the_loop_entirely(self, patched, monkeypatch):
        checkpoint = self._fake_checkpoint(patched, ["claims", "source_brief", "story_loop"])
        monkeypatch.setattr(rp, "load_checkpoint", lambda run_dir: checkpoint)

        _run(patched, resume_from=patched.tmp_path / "old_run")

        assert "_build_claim_registry" not in patched.calls
        assert "understand_source" not in patched.calls
        assert "run_story_and_narration_loop" not in patched.calls
        # still proceeds into H+HV using the resumed plan/narration
        html_args = patched.calls["synthesize_and_repair_video_html"][0][0]
        assert html_args[0] is checkpoint.plan
        assert html_args[1] is checkpoint.narration

    def test_partially_completed_checkpoint_only_skips_what_it_actually_has(self, patched, monkeypatch):
        checkpoint = self._fake_checkpoint(patched, ["claims"])  # source_brief/story_loop still needed
        monkeypatch.setattr(rp, "load_checkpoint", lambda run_dir: checkpoint)

        _run(patched, resume_from=patched.tmp_path / "old_run")

        assert "_build_claim_registry" not in patched.calls
        assert "understand_source" in patched.calls
        assert "run_story_and_narration_loop" in patched.calls

    def test_mismatched_source_hash_refuses_to_resume(self, patched, monkeypatch):
        checkpoint = self._fake_checkpoint(patched, ["claims", "source_brief", "story_loop"])
        checkpoint.source_hash = "a-different-hash"  # extraction's own is "h" (make_extraction())
        monkeypatch.setattr(rp, "load_checkpoint", lambda run_dir: checkpoint)

        with pytest.raises(ValueError, match="does not match"):
            _run(patched, resume_from=patched.tmp_path / "old_run")

        assert "_build_claim_registry" not in patched.calls  # refused before any stage ran

    def test_resume_writes_into_a_fresh_run_dir_not_the_old_one(self, patched, monkeypatch):
        """`next_run_dir`/`scaffold_run_dir` are called exactly as for any other invocation --
        resuming never mutates the crashed attempt's own directory."""
        checkpoint = self._fake_checkpoint(patched, ["claims", "source_brief", "story_loop"])
        monkeypatch.setattr(rp, "load_checkpoint", lambda run_dir: checkpoint)

        _run(patched, resume_from=patched.tmp_path / "old_run")

        assert len(patched.calls["next_run_dir"]) == 1
        assert len(patched.calls["scaffold_run_dir"]) == 1

    def test_no_resume_flag_never_calls_load_checkpoint(self, patched, monkeypatch):
        calls = []
        monkeypatch.setattr(rp, "load_checkpoint", lambda run_dir: calls.append(run_dir))

        _run(patched)

        assert calls == []

    def test_resumed_runs_total_cost_includes_the_checkpoint_carried_spend(self, patched, monkeypatch):
        """PIPELINE_AUDIT_2026-09-17.md finding #5: a resumed run's own UsageLedger is
        always scoped to the NEW run dir's own usage.jsonl -- it never contains whatever
        was spent on a skipped stage. `total_cost_usd` must include the checkpoint's own
        claims/source_brief/loop spend, not just this run's fresh billing."""
        checkpoint = self._fake_checkpoint(patched, ["claims", "source_brief", "story_loop"])
        monkeypatch.setattr(rp, "load_checkpoint", lambda run_dir: checkpoint)

        output = _run(patched, resume_from=patched.tmp_path / "old_run")

        # 70_000 + 20_000 + 900_000 microusd = $0.99, and this fixture's own mocked stages
        # bill nothing new (make_llm_client is stubbed to a bare SimpleNamespace)
        assert output.total_cost_usd == pytest.approx(0.99)

    def test_a_fresh_non_resumed_run_never_double_counts_or_fabricates_carried_over_cost(self, patched):
        """A genuinely fresh run's `PipelineState` starts with all three spend fields at 0
        -- `total_cost_usd` must reflect only this run's own real billing, never a stale or
        fabricated carried-over figure."""
        output = _run(patched)
        assert output.total_cost_usd == pytest.approx(0.0)

    def test_a_fresh_run_checkpoints_after_each_completed_stage(self, patched, monkeypatch):
        # The generic `record()` stub stores a reference to the same mutated `state` object on
        # every call, not a snapshot -- this test needs the actual progression, so it captures
        # its own copy at call time instead of reusing the shared stub.
        snapshots = []
        monkeypatch.setattr(rp, "save_checkpoint", lambda state, run_dir: snapshots.append(list(state.completed_stages)))

        _run(patched)

        assert snapshots == [["claims"], ["claims", "source_brief"], ["claims", "source_brief", "story_loop"]]


class TestPreventSystemSleep:
    """A real live run (`--story-lead-alias openai_story_strong_gpt56`,
    ERR-046/047) can take well over an hour -- macOS idle sleep mid-run can
    stall in-flight network calls in ways that look identical to a hang.
    `_prevent_system_sleep()` is best-effort only: it must never raise or
    block real pipeline execution, on any platform."""

    def test_spawns_caffeinate_tied_to_this_process_on_macos(self, monkeypatch):
        monkeypatch.setattr(rp.sys, "platform", "darwin")
        calls = []
        monkeypatch.setattr(rp.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
        monkeypatch.setattr(rp.os, "getpid", lambda: 12345)

        rp._prevent_system_sleep()

        assert len(calls) == 1
        (args, _kwargs) = calls[0]
        assert args[0] == ["caffeinate", "-i", "-w", "12345"]

    def test_does_nothing_on_a_non_macos_platform(self, monkeypatch):
        monkeypatch.setattr(rp.sys, "platform", "linux")
        calls = []
        monkeypatch.setattr(rp.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))

        rp._prevent_system_sleep()

        assert calls == []

    def test_missing_caffeinate_binary_is_swallowed_not_raised(self, monkeypatch):
        monkeypatch.setattr(rp.sys, "platform", "darwin")

        def raise_not_found(*a, **k):
            raise FileNotFoundError("caffeinate not found")

        monkeypatch.setattr(rp.subprocess, "Popen", raise_not_found)

        rp._prevent_system_sleep()  # must not raise
