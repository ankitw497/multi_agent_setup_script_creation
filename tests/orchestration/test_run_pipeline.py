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


def make_story_result(final_status="PASS"):
    plan = SimpleNamespace(archetype="build")
    narration = [SimpleNamespace(scene_id="s1")]
    return SimpleNamespace(plan=plan, narration=narration, final_status=final_status, review_bundle=SimpleNamespace())


def make_html_result(render_issues=None, degraded_capabilities=None):
    return SimpleNamespace(
        beat_visuals=[SimpleNamespace()], hero=SimpleNamespace(),
        render_issues=render_issues or [], degraded_capabilities=degraded_capabilities or [], repairs_used=0,
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
    monkeypatch.setattr(rp, "make_story_lead", lambda client, tier="strong": f"story_lead:{tier}")
    monkeypatch.setattr(rp, "make_narration_lead", lambda client: "narration_lead")
    monkeypatch.setattr(rp, "make_review_lead", lambda client, tier="strong": f"review_lead:{tier}")

    monkeypatch.setattr(rp, "parse_html", record("parse_html"))
    rp.parse_html.return_value = extraction

    monkeypatch.setattr(rp, "_build_claim_registry", record("_build_claim_registry"))
    rp._build_claim_registry.return_value = (claims, ledger)

    monkeypatch.setattr(rp, "needs_narrative_digest", lambda units: False)
    monkeypatch.setattr(rp, "build_narrative_digest", record("build_narrative_digest"))
    rp.build_narrative_digest.return_value = "digest"

    monkeypatch.setattr(rp, "understand_source", record("understand_source"))
    rp.understand_source.return_value = source_brief

    monkeypatch.setattr(rp, "run_story_and_narration_loop", record("run_story_and_narration_loop"))
    rp.run_story_and_narration_loop.return_value = story_result

    monkeypatch.setattr(rp, "save_result", record("save_result"))

    monkeypatch.setattr(rp, "synthesize_and_repair_video_html", record("synthesize_and_repair_video_html"))
    rp.synthesize_and_repair_video_html.return_value = html_result
    monkeypatch.setattr(rp, "emit_html_deliverables", record("emit_html_deliverables"))

    monkeypatch.setattr(rp, "find_candidates", record("find_candidates"))
    rp.find_candidates.return_value = ["candidate-1"]

    monkeypatch.setattr(rp, "plan_shorts", record("plan_shorts"))
    rp.plan_shorts.return_value = ["short-plan-1"]

    short_result = SimpleNamespace(final_status="FAIL", narration=[SimpleNamespace(scene_id="hook")])
    monkeypatch.setattr(rp, "run_short", record("run_short"))
    rp.run_short.return_value = short_result

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


def test_shorts_receive_the_same_in_memory_plan_narration_claims(patched):
    _run(patched)
    sc_args = patched.calls["find_candidates"][0][0]
    assert sc_args[0] is patched.story_result.plan
    assert sc_args[1] is patched.story_result.narration
    assert sc_args[2] is patched.claims

    a2s_args = patched.calls["plan_shorts"][0][0]
    assert a2s_args[1] is patched.story_result.plan
    assert a2s_args[2] is patched.claims


def test_short_html_synthesized_from_run_shorts_own_in_memory_narration(patched):
    _run(patched)
    vertical_args = patched.calls["synthesize_short_html"][0][0]
    assert vertical_args[1] is patched.short_result.narration


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
