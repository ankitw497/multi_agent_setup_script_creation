"""Tests for verification/hard/render.py's content-level checks (plan §12.0,
§1/§9/§22 renderer_compat)."""
from html_synth.synthesizer import BeatVisual, HeroContent, SceneVisual
from planning.models import (
    CTAContract, EndingContract, HookContract, ScenePlan, StoryPlan, TitleContract,
)
from verification.hard.render import (
    check_deictic_resolution, check_every_scene_has_prose, check_hero_states_problem,
    check_payoff_closes, check_reader_standalone_word_count, check_renderer_compat,
)
from narration.models import SceneNarration, SentenceNarration


def make_plan(**overrides) -> StoryPlan:
    base = dict(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="a token alone has no context", tension="ambiguous meaning", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="attention retrieves context via query key value",
                               capstone_payoff="you can now explain self-attention", viewer_can_now="do x"),
    )
    base.update(overrides)
    return StoryPlan(**base)


# ---- renderer_compat ---------------------------------------------------------

def test_renderer_compat_clean_with_enough_sections_and_words():
    words = " ".join(["word"] * 1600)
    html = f"<html><body><section>{words[:600]}</section><section>{words[600:1200]}</section><section>{words[1200:]}</section></body></html>"
    assert check_renderer_compat(html) == []


def test_renderer_compat_too_few_sections():
    html = "<html><body><section>" + " ".join(["word"] * 1600) + "</section></body></html>"
    issues = check_renderer_compat(html)
    assert any(i.code == "renderer_compat_too_few_sections" for i in issues)


def test_renderer_compat_too_few_words():
    html = "<html><body><section>a</section><section>b</section><section>c</section></body></html>"
    issues = check_renderer_compat(html)
    assert any(i.code == "renderer_compat_too_few_words" for i in issues)


# ---- reader-standalone word count -------------------------------------------

def test_word_count_within_band_is_clean():
    html = "<html><body>" + " ".join(["word"] * 2500) + "</body></html>"
    assert check_reader_standalone_word_count(html) == []


def test_word_count_below_band_is_flagged():
    html = "<html><body>" + " ".join(["word"] * 500) + "</body></html>"
    issues = check_reader_standalone_word_count(html)
    assert any(i.code == "reader_standalone_word_count_out_of_band" for i in issues)


def test_word_count_above_band_is_flagged():
    html = "<html><body>" + " ".join(["word"] * 5000) + "</body></html>"
    issues = check_reader_standalone_word_count(html)
    assert any(i.code == "reader_standalone_word_count_out_of_band" for i in issues)


# ---- every scene has prose ---------------------------------------------------

def test_scene_with_real_prose_is_clean():
    beats = [BeatVisual(beat_id="B01", heading="h", scenes=[
        SceneVisual(scene_id="s1", screen_prose="A real sentence explaining the idea in full."),
    ])]
    assert check_every_scene_has_prose(beats) == []


def test_scene_with_no_prose_is_flagged():
    beats = [BeatVisual(beat_id="B01", heading="h", scenes=[SceneVisual(scene_id="s1", screen_prose="")])]
    issues = check_every_scene_has_prose(beats)
    assert any(i.code == "scene_missing_visible_prose" for i in issues)


def test_scene_missing_prose_is_scene_scoped_for_the_h_repair_loop():
    """V1C: RenderIssue.scene_id must be populated so the repair loop knows
    which beat to regenerate."""
    beats = [BeatVisual(beat_id="B01", heading="h", scenes=[SceneVisual(scene_id="s1", screen_prose="")])]
    issues = check_every_scene_has_prose(beats)
    assert issues[0].scene_id == "s1"


def test_scene_with_only_a_couple_words_is_flagged():
    beats = [BeatVisual(beat_id="B01", heading="h", scenes=[SceneVisual(scene_id="s1", screen_prose="just two")])]
    issues = check_every_scene_has_prose(beats)
    assert any(i.code == "scene_missing_visible_prose" for i in issues)


# ---- hero states the problem --------------------------------------------------

def test_hero_matching_the_hook_is_clean():
    hero = HeroContent(title="A token has no context", subtitle="Why a token alone can't resolve its own meaning.")
    assert check_hero_states_problem(hero, make_plan()) == []


def test_hero_unrelated_to_the_hook_is_flagged():
    hero = HeroContent(title="A recipe for banana bread", subtitle="Mix the ingredients and bake.")
    issues = check_hero_states_problem(hero, make_plan())
    assert any(i.code == "hero_does_not_state_the_problem" for i in issues)


def test_hero_issue_uses_the_hero_sentinel_scene_id():
    """V1C: the H-repair loop routes scene_id="hero" to repair_hero, not a beat."""
    hero = HeroContent(title="A recipe for banana bread", subtitle="Mix the ingredients and bake.")
    issues = check_hero_states_problem(hero, make_plan())
    assert issues[0].scene_id == "hero"


# ---- payoff closes ------------------------------------------------------------

def test_final_scene_matching_the_ending_is_clean():
    beats = [BeatVisual(beat_id="B01", heading="h", scenes=[
        SceneVisual(scene_id="s1", screen_prose="Attention retrieves context via query key value, and you can now explain self-attention end to end."),
    ])]
    assert check_payoff_closes(beats, make_plan()) == []


def test_final_scene_unrelated_to_the_ending_is_flagged():
    beats = [BeatVisual(beat_id="B01", heading="h", scenes=[
        SceneVisual(scene_id="s1", screen_prose="A completely unrelated sentence about baking bread."),
    ])]
    issues = check_payoff_closes(beats, make_plan())
    assert any(i.code == "payoff_does_not_close" for i in issues)


def test_no_beats_is_flagged_not_a_crash():
    issues = check_payoff_closes([], make_plan())
    assert any(i.code == "no_payoff_scene" for i in issues)


def test_ending_on_a_next_video_bridge_is_clean_not_a_false_positive():
    """Real false positive found live: a "Part 1 of 3" source correctly
    ends on `ending.next_video_bridge` rather than restating the capstone
    -- both are valid endings per EndingContract's own shape."""
    plan = make_plan(ending=EndingContract(
        resolve_hook="x", compressed_mental_model="unrelated capstone text", capstone_payoff="unrelated too",
        viewer_can_now="do x", next_video_bridge="explore alternative attention mechanisms next time",
    ))
    beats = [BeatVisual(beat_id="B01", heading="h", scenes=[
        SceneVisual(scene_id="s1", screen_prose="Teams are exploring alternative attention mechanisms in the next video."),
    ])]
    assert check_payoff_closes(beats, plan) == []


# ---- deictic resolution --------------------------------------------------------

def make_plan_with_scene(scene_id="s1", visual_description="") -> StoryPlan:
    return make_plan(scene_plan=[ScenePlan(scene_id=scene_id, beat_id="B01", visual_description=visual_description)])


def sentence(text) -> SentenceNarration:
    return SentenceNarration(text=text, sentence_type="transition")


def test_demonstrative_with_a_visual_to_point_at_is_clean():
    plan = make_plan_with_scene(visual_description="a diagram showing the score distribution widening")
    narration = [SceneNarration(scene_id="s1", sentences=[sentence("This creates a problem for softmax.")])]
    assert check_deictic_resolution(plan, narration) == []


def test_demonstrative_with_no_visual_is_flagged():
    plan = make_plan_with_scene(visual_description="")
    narration = [SceneNarration(scene_id="s1", sentences=[sentence("This creates a problem for softmax.")])]
    issues = check_deictic_resolution(plan, narration)
    assert any(i.code == "deictic_reference_unresolved" for i in issues)


def test_deictic_issue_is_scene_scoped_for_the_h_repair_loop():
    plan = make_plan_with_scene(visual_description="")
    narration = [SceneNarration(scene_id="s1", sentences=[sentence("This creates a problem for softmax.")])]
    issues = check_deictic_resolution(plan, narration)
    assert issues[0].scene_id == "s1"


def test_it_is_never_flagged_deliberately_excluded():
    """"it" is far too common for ordinary anaphoric reference (as in this
    very source's own running "it" example) to be a reliable signal."""
    plan = make_plan_with_scene(visual_description="")
    narration = [SceneNarration(scene_id="s1", sentences=[sentence("It creates a problem for softmax.")])]
    assert check_deictic_resolution(plan, narration) == []


def test_mid_sentence_demonstrative_is_not_flagged():
    """Only a SENTENCE-OPENING demonstrative is checked -- mid-sentence use
    ("the fact that...") is ordinary English, not a visual reference."""
    plan = make_plan_with_scene(visual_description="")
    narration = [SceneNarration(scene_id="s1", sentences=[sentence("We know that this happens for a reason.")])]
    assert check_deictic_resolution(plan, narration) == []
