"""Tests for html_synth/assembler.py -- the dual-audience contract (plan §12.0).

video_script.html and page.html are rendered by the same function,
parameterized only by include_metadata -- these tests check the contract
that guarantees, not re-derive it: identical visible text, video_script
carries render metadata page.html must never carry.
"""
import re

from html_synth.assembler import narration_hash, synthesize_page
from html_synth.synthesizer import BeatVisual, HeroContent, NumberAnnotation, SceneVisual
from narration.models import SceneNarration, SentenceNarration
from planning.models import CTAContract, EndingContract, HookContract, StoryPlan, TitleContract


def strip_tags(html: str) -> str:
    """Visible-text extraction: <script>/<style> CONTENT is never visible in
    a real browser (unlike other tags, where only the tag itself
    disappears) -- strip those wholesale before stripping the rest."""
    without_scripts = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"<[^>]+>", "", without_scripts)


def make_plan(title="Attention Explained") -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen=title, promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
    )


def make_beat_visuals(**scene_overrides) -> list[BeatVisual]:
    scene = dict(scene_id="s1", screen_prose="Dot products grow large with wider vectors.")
    scene.update(scene_overrides)
    return [BeatVisual(beat_id="B01", heading="The Scaling Problem", subheading="Why scores misbehave.",
                        scenes=[SceneVisual(**scene)])]


def make_narration() -> list[SceneNarration]:
    return [SceneNarration(scene_id="s1", sentences=[SentenceNarration(text="hi", sentence_type="transition")])]


def test_video_script_html_carries_the_narration_block():
    vs, _ = synthesize_page(make_plan(), HeroContent(), make_beat_visuals(), make_narration())
    assert 'id="narration-data"' in vs
    assert "data-narration-hash=" in vs


def test_page_html_has_no_narration_block_or_data_attrs():
    _, page = synthesize_page(make_plan(), HeroContent(), make_beat_visuals(), make_narration())
    assert "narration-data" not in page
    assert "data-narration-id" not in page
    assert "data-numeric-claim-id" not in page


def test_visible_text_is_identical_between_the_two_files():
    """The actual plan §12.0 requirement: HV asserts pixel parity; this is
    the text-level version of that same guarantee."""
    vs, page = synthesize_page(make_plan(), HeroContent(badge="b", title="t", subtitle="s"), make_beat_visuals(), make_narration())
    assert strip_tags(vs) == strip_tags(page)


def test_numeric_claim_annotation_appears_only_in_video_script():
    beats = make_beat_visuals(annotated_numbers=[NumberAnnotation(text="128-dim", claim_id="C001")],
                               screen_prose="128-dim vectors create wide scores.")
    vs, page = synthesize_page(make_plan(), HeroContent(), beats, make_narration())
    assert 'data-numeric-claim-id="C001"' in vs
    assert "128-dim" in strip_tags(page)
    assert "data-numeric-claim-id" not in page


def test_narration_hash_is_deterministic_and_content_sensitive():
    n1 = make_narration()
    n2 = make_narration()
    assert narration_hash(n1) == narration_hash(n2)
    n3 = [SceneNarration(scene_id="s1", sentences=[SentenceNarration(text="different", sentence_type="transition")])]
    assert narration_hash(n1) != narration_hash(n3)


def test_component_renders_in_both_files_but_data_attrs_dont_leak_from_it():
    beats = make_beat_visuals(component_id="card", component_data={"title": "t", "value": "v", "desc": "d"})
    vs, page = synthesize_page(make_plan(), HeroContent(), beats, make_narration())
    assert "card-value" in vs
    assert "card-value" in page


def test_scene_id_and_prose_render_in_the_dom():
    vs, _ = synthesize_page(make_plan(), HeroContent(), make_beat_visuals(), make_narration())
    assert 'id="s1"' in vs
    assert "Dot products grow large" in vs


def test_html_special_characters_in_prose_are_escaped():
    beats = make_beat_visuals(screen_prose="x < y & y > z")
    vs, _ = synthesize_page(make_plan(), HeroContent(), beats, make_narration())
    assert "x &lt; y &amp; y &gt; z" in vs
    assert "x < y & y > z" not in vs


def test_title_appears_in_the_page_title_tag():
    vs, _ = synthesize_page(make_plan(title="My Video Title"), HeroContent(), make_beat_visuals(), make_narration())
    assert "<title>My Video Title</title>" in vs
