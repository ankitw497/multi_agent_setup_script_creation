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


def test_plain_page_footer_produces_no_production_notes_unit():
    """.page-footer with no .pipeline-step content is pure chrome and stays
    fully stripped -- only a footer that actually holds production notes
    gets a unit carved out of it."""
    result = parse_html(FIXTURES / "guide_sample.html")
    assert "production_notes" not in {u.id for u in result.units}


def test_production_notes_survive_page_footer_chrome_stripping():
    """Real bug (2026-09-10): .page-footer is chrome-stripped wholesale, which
    was silently deleting an author's own "Production notes" production plan
    -- the single most direct piece of story-archetype evidence in a real
    source -- before A1/A2 ever saw it. It must now survive as its own unit."""
    result = parse_html(FIXTURES / "guide_sample_with_production_notes.html")
    assert result.profile_name == "guide"
    notes = [u for u in result.units if u.id == "production_notes"]
    assert len(notes) == 1
    unit = notes[0]
    assert "Problem" in unit.text
    assert "Mini payoff" in unit.text
    assert "Open on the unresolved question" in unit.text
    assert "0:00" in unit.text
    # STORY_IMPROVEMENT_PLAN.md Phase 11 (doc §30.8's source-meta-contamination case):
    # production notes are the author's own storyboard intent, not a technical claim about
    # the subject matter -- S2b must never extract a Claim from this unit.
    assert unit.kind == "PRODUCTION_META"


def test_plain_source_with_no_hero_header_produces_no_hook_unit():
    result = parse_html(FIXTURES / "guide_sample.html")
    assert "hook" not in {u.id for u in result.units}


def test_hero_header_is_extracted_as_its_own_unit():
    """Real gap found 2026-09-11 (user-reported: the generated hook was
    generic while the source's own hook used a concrete minimal-pair
    example). `<header class="hero">` sits BEFORE any `<section
    class="section">`, so every profile's `section.select("section.section")`
    walk was structurally blind to it -- the same shape of gap already fixed
    once for `.page-footer` (test_production_notes_survive_page_footer_
    chrome_stripping). It must now survive as its own leading unit."""
    result = parse_html(FIXTURES / "guide_sample_with_hero_hook.html")
    assert result.units[0].id == "hook"
    assert result.units[0].heading == 'How does "it" know to look back at "cat"?'
    assert "too tired" in result.units[0].text
    # the section content that follows the header must still be present too
    assert any(u.id == "intro" for u in result.units)


REAL_SOURCE = (
    Path(__file__).parent.parent.parent
    / "project" / "attention_series" / "input" / "video-01-attention-coherent-story.html"
)


def test_real_source_hero_header_carries_the_concrete_hook_example():
    """The real regression this fix exists for: the source's own hook is a
    concrete minimal-pair example ("tired" vs "steep" changes what "it"
    refers to) that a generic paraphrase can never recover once it's
    silently missing from every downstream A1/A2 payload."""
    result = parse_html(REAL_SOURCE)
    hooks = [u for u in result.units if u.id == "hook"]
    assert len(hooks) == 1
    assert "too tired" in hooks[0].text
    assert "too steep" in hooks[0].text


def test_real_source_production_notes_carry_the_build_archetype_signal():
    """The real regression this fix exists for: on the actual attention-series
    source, the author's own Production notes are a Problem -> Mini payoff ->
    new-problem chain (the "build" archetype's shape) -- and before this fix
    they never reached A1/A2 at all because .page-footer was chrome-stripped
    wholesale (see IMPLEMENTATION_PLAN.md build-plan notes, 2026-09-10)."""
    result = parse_html(REAL_SOURCE)
    notes = [u for u in result.units if u.id == "production_notes"]
    assert len(notes) == 1
    text = notes[0].text
    assert "Problem" in text
    assert "Score creates a new problem" in text
    assert "Payoff and Part 2 bridge" in text
    # the 11 numbered sections plus the hero-hook unit must still be present
    # alongside this one (2026-09-11: 12 -> 13 once the hero header stopped
    # being silently skipped too -- see test_hero_header_is_extracted_as_its_own_unit)
    assert len(result.units) == 13


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
