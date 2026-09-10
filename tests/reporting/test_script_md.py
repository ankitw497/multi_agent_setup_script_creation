"""Tests for reporting/script_md.py."""
from narration.models import SceneNarration, SentenceNarration
from planning.models import CTAContract, EndingContract, HookContract, StoryPlan, TitleContract
from reporting.script_md import render_script_md


def make_plan(title="The Title") -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen=title, promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
    )


def test_renders_title_and_scenes_in_order():
    narration = [
        SceneNarration(scene_id="s1", sentences=[SentenceNarration(text="First line.", sentence_type="transition")]),
        SceneNarration(scene_id="s2", sentences=[SentenceNarration(text="Second line.", sentence_type="transition")]),
    ]
    md = render_script_md(make_plan("Attention Explained"), narration)
    assert "# Attention Explained" in md
    assert md.index("First line.") < md.index("Second line.")


def test_joins_multiple_sentences_in_one_scene():
    narration = [SceneNarration(scene_id="s1", sentences=[
        SentenceNarration(text="One.", sentence_type="transition"),
        SentenceNarration(text="Two.", sentence_type="transition"),
    ])]
    md = render_script_md(make_plan(), narration)
    assert "One. Two." in md


def test_empty_scene_shows_a_placeholder_not_a_blank():
    narration = [SceneNarration(scene_id="s1", sentences=[])]
    md = render_script_md(make_plan(), narration)
    assert "no narration" in md
