"""Round-trip tests for verification/models.py (plan §12.0, §13, §14)."""
from verification.models import ApprovalQuestion, QualityReport, RenderReport

from tests.conftest import roundtrip, roundtrip_fixture


def test_render_report_roundtrips_dual_audience_checks():
    """reader_standalone_ok and page_parity_ok are the two checks the §12.0
    dual-audience contract added beyond ordinary render validity."""
    report = roundtrip_fixture(RenderReport, "verification", "RenderReport")
    assert report.reader_standalone_ok is True
    assert report.page_parity_ok is True
    assert report.renderer_compat_ok is True


def test_render_report_defaults_assume_success_until_a_check_fails():
    report = RenderReport(run_id="r1")
    assert report.scene_order_ok is True
    assert report.duplicate_ids == []


def test_approval_question_marks_hard_gate_questions():
    """Playbook's ten questions, 3/4/7/9 block (plan §14)."""
    q = roundtrip(
        ApprovalQuestion,
        {"index": 3, "question": "Is there exactly one primary story arc?", "passed": True, "is_hard_gate": True},
    )
    assert q.is_hard_gate is True


def test_quality_report_roundtrips_and_matches_the_final_status_policy():
    report = roundtrip_fixture(QualityReport, "verification", "QualityReport")
    assert report.final_status == "PASS_WARN"
    assert report.amber_count == 1
    assert report.red_count == 0
    # PASS_WARN here because there's an unresolved AMBER (within allowance it
    # would still be PASS_WARN per plan §14's precedence: any hard-failure-free
    # AMBER makes it at least PASS_WARN unless explicitly within an allowance
    # that a status-computing function decides — this model just stores the
    # decision, it doesn't compute it (that's orchestration/policy_gate.py, Phase 6+).
    assert report.editorial_summary is not None


def test_quality_report_status_is_restricted_to_the_four_defined_values():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        QualityReport(run_id="r1", final_status="APPROVED")  # not one of FAIL/REVISE/PASS_WARN/PASS
