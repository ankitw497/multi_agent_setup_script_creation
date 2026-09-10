"""parse_html() orchestrator tests (plan §6, §8 S0)."""
from pathlib import Path

from extraction.html_parser import MIN_PROFILE_CONFIDENCE, parse_html, parse_html_string

FIXTURES = Path(__file__).parent.parent / "fixtures" / "extraction"


def test_parse_html_picks_the_guide_profile():
    result = parse_html(FIXTURES / "guide_sample.html")
    assert result.profile_name == "guide"
    assert len(result.units) == 2


def test_parse_html_picks_the_video_script_profile():
    result = parse_html(FIXTURES / "video_script_sample.html")
    assert result.profile_name == "video_script"


def test_parse_html_falls_back_to_generic_below_the_confidence_floor():
    result = parse_html(FIXTURES / "generic_sample.html")
    assert result.profile_name == "generic"
    assert result.profile_confidence < MIN_PROFILE_CONFIDENCE


def test_parse_html_is_deterministic_and_content_hashed():
    """S0 is 100% deterministic -- same input, same hash, same units, every time
    (plan §8: this is what makes it cacheable and free to re-run)."""
    r1 = parse_html(FIXTURES / "guide_sample.html")
    r2 = parse_html(FIXTURES / "guide_sample.html")
    assert r1.source_hash == r2.source_hash
    assert r1.source_hash.startswith("sha256:")
    assert [u.id for u in r1.units] == [u.id for u in r2.units]


def test_a_single_byte_change_changes_the_hash():
    html = (FIXTURES / "guide_sample.html").read_text()
    r1 = parse_html_string(html)
    r2 = parse_html_string(html + " ")
    assert r1.source_hash != r2.source_hash


def test_js_literals_are_extracted_and_attached_to_the_result():
    result = parse_html(FIXTURES / "js_literals_sample.html")
    assert result.js_literals["HIDDEN"] == 3584
    assert result.js_literals["LAYERS"] == 28
    assert result.js_literals["modes"]["inference"]["segs"][0]["gb"] == 15.2


def test_dynamic_js_is_rejected_not_evaluated_and_not_silently_dropped():
    """The security property in one assertion: a fetch() call never becomes a
    literal, and its rejection is visible, not silent (plan §6.2, Appendix G #1)."""
    result = parse_html(FIXTURES / "js_literals_sample.html")
    assert "dangerous" not in result.js_literals
    rejected_names = [r["name"] for r in result.js_rejected]
    assert "dangerous" in rejected_names
