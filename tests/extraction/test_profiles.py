"""Profile confidence + extraction tests (plan §6.1).

Uses small, tracked HTML fixtures under tests/fixtures/extraction/ rather
than the real corpus (docs/corpus/, project/) — both of those are
gitignored working content, not part of the repo, so tests must not
depend on them being present.
"""
from pathlib import Path

from bs4 import BeautifulSoup

from extraction.html_parser import _strip_chrome
from extraction.profiles.generic import GenericProfile
from extraction.profiles.guide import GuideProfile
from extraction.profiles.video_script import VideoScriptProfile

FIXTURES = Path(__file__).parent.parent / "fixtures" / "extraction"


def _soup(name: str) -> BeautifulSoup:
    html = (FIXTURES / name).read_text()
    soup = BeautifulSoup(html, "lxml")
    _strip_chrome(soup)
    return soup


def test_guide_profile_scores_high_on_guide_markup():
    soup = _soup("guide_sample.html")
    assert GuideProfile().confidence(soup) >= 0.8


def test_guide_profile_scores_zero_on_video_script_markup():
    soup = _soup("video_script_sample.html")
    assert GuideProfile().confidence(soup) == 0.0


def test_video_script_profile_scores_high_on_its_own_markup():
    soup = _soup("video_script_sample.html")
    assert VideoScriptProfile().confidence(soup) >= 0.8


def test_video_script_profile_scores_zero_on_guide_markup():
    soup = _soup("guide_sample.html")
    assert VideoScriptProfile().confidence(soup) == 0.0


def test_generic_profile_always_available_as_a_low_confidence_fallback():
    soup = _soup("generic_sample.html")
    assert 0.0 < GenericProfile().confidence(soup) < GuideProfile().confidence(_soup("guide_sample.html"))


def test_guide_extraction_recovers_sections_headings_and_numbers():
    soup = _soup("guide_sample.html")
    units = GuideProfile().extract(soup)
    assert [u.id for u in units] == ["intro", "scaling"]
    assert "compare itself" in units[0].heading
    assert any("128" in n for n in units[1].numbers)


def test_guide_extraction_never_leaks_nav_chrome_into_a_unit():
    """The nav link text ('Nav Leak Text') must never appear in a SourceUnit —
    chrome is stripped before any profile sees the document."""
    soup = _soup("guide_sample.html")
    units = GuideProfile().extract(soup)
    all_text = " ".join(u.text + u.heading for u in units)
    assert "Nav Leak Text" not in all_text
    assert "Copyright chrome" not in all_text


def test_guide_extraction_recovers_footer_tagged_diagrams_and_equations():
    """Regression test for a real bug found 2026-09-10: .diagram-caption and
    .math-block both render as <footer> tags in this design system, and an
    earlier chrome-stripping selector used a bare "footer" tag match, which
    silently deleted them. Fixed by scoping the selector to .page-footer only."""
    soup = _soup("guide_sample.html")
    units = GuideProfile().extract(soup)
    intro = units[0]
    assert intro.diagrams == ["Three projections, three different jobs."]
    assert intro.equations == ["$$Q=XW_Q$$"]


def test_video_script_extraction_recovers_wraps_and_callouts():
    soup = _soup("video_script_sample.html")
    units = VideoScriptProfile().extract(soup)
    assert [u.id for u in units] == ["hero-story", "setup"]
    assert "7.61 billion parameters" in units[1].callouts[0]


def test_generic_extraction_segments_by_heading_when_no_profile_matches():
    soup = _soup("generic_sample.html")
    units = GenericProfile().extract(soup)
    assert len(units) == 2
    assert units[0].heading == "A rough note about attention"
    assert units[1].heading == "The scaling trick"
    assert all(u.structure_confidence < 0.5 for u in units)
