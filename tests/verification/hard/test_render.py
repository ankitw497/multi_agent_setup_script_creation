"""Tests for verification/hard/render.py -- HV static checks (plan §13)."""
from facts.models import Claim
from html_synth.assembler import synthesize_page
from html_synth.synthesizer import BeatVisual, HeroContent, NumberAnnotation, SceneVisual
from narration.models import SceneNarration, SentenceNarration
from planning.models import CTAContract, EndingContract, HookContract, StoryPlan, TitleContract
from verification.hard.render import (
    check_html_parses, check_narration_hash_matches, check_numeric_claim_ids_exist, check_page_parity,
    check_render_static, check_scenes_present_in_order, check_unique_ids,
)


def make_plan() -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
    )


def make_beat_visuals(scene_ids=("s1", "s2")) -> list[BeatVisual]:
    return [BeatVisual(beat_id="B01", heading="h", subheading="s", scenes=[
        SceneVisual(scene_id=sid, screen_prose=f"prose for {sid}") for sid in scene_ids
    ])]


def make_narration(scene_ids=("s1", "s2")) -> list[SceneNarration]:
    return [SceneNarration(scene_id=sid, sentences=[SentenceNarration(text="hi", sentence_type="transition")]) for sid in scene_ids]


def build_page(scene_ids=("s1", "s2"), annotated_numbers=None):
    beats = make_beat_visuals(scene_ids)
    if annotated_numbers:
        beats[0].scenes[0].annotated_numbers = annotated_numbers
        beats[0].scenes[0].screen_prose = annotated_numbers[0].text + " appears here"
    return synthesize_page(make_plan(), HeroContent(), beats, make_narration(scene_ids))


def test_valid_html_parses_cleanly():
    vs, _ = build_page()
    assert check_html_parses(vs) == []


def test_unique_ids_are_clean_on_a_normal_page():
    vs, _ = build_page()
    assert check_unique_ids(vs) == []


def test_duplicate_ids_are_flagged():
    vs, _ = build_page(scene_ids=("s1", "s1"))
    issues = check_unique_ids(vs)
    assert any(i.code == "duplicate_id" for i in issues)


def test_all_scenes_present_is_clean():
    vs, _ = build_page()
    assert check_scenes_present_in_order(vs, ["s1", "s2"]) == []


def test_missing_scene_is_flagged():
    vs, _ = build_page(scene_ids=("s1",))
    issues = check_scenes_present_in_order(vs, ["s1", "s2"])
    assert any(i.code == "scene_missing_from_dom" for i in issues)


def test_matching_narration_hash_is_clean():
    vs, _ = build_page()
    assert check_narration_hash_matches(vs, make_narration()) == []


def test_mismatched_narration_is_flagged():
    vs, _ = build_page()
    different_narration = make_narration(("s1", "s3"))
    issues = check_narration_hash_matches(vs, different_narration)
    assert any(i.code == "narration_hash_mismatch" for i in issues)


def test_known_numeric_claim_id_is_clean():
    claims = [Claim(claim_id="C001", source_unit="u1", claim="x", type="mechanism")]
    vs, _ = build_page(annotated_numbers=[NumberAnnotation(text="175B", claim_id="C001")])
    assert check_numeric_claim_ids_exist(vs, claims) == []


def test_unknown_numeric_claim_id_is_flagged():
    vs, _ = build_page(annotated_numbers=[NumberAnnotation(text="175B", claim_id="C999")])
    issues = check_numeric_claim_ids_exist(vs, [])
    assert any(i.code == "numeric_claim_id_unknown" for i in issues)


def test_page_parity_is_clean_for_the_real_output():
    vs, page = build_page()
    assert check_page_parity(vs, page) == []


def test_page_parity_catches_a_real_mismatch():
    vs, _ = build_page()
    tampered_page = vs.replace("prose for s1", "totally different text")
    issues = check_page_parity(vs, tampered_page)
    assert any(i.code == "page_parity_mismatch" for i in issues)


def test_check_render_static_on_a_fully_clean_page_is_empty():
    claims = [Claim(claim_id="C001", source_unit="u1", claim="x", type="mechanism")]
    vs, page = build_page(annotated_numbers=[NumberAnnotation(text="175B", claim_id="C001")])
    assert check_render_static(vs, page, make_narration(), claims) == []
