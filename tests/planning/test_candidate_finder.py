"""Tests for planning/candidate_finder.py -- SC (plan §20.6)."""
from facts.models import Claim
from narration.models import SceneNarration, SentenceNarration
from planning.candidate_finder import CandidateShortlist, find_candidates
from planning.models import (
    CTAContract, EndingContract, HookContract, StoryBeat, StoryPlan, TitleContract,
)


class FakeWorker:
    def __init__(self, response: CandidateShortlist):
        self._response = response
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def make_plan() -> StoryPlan:
    return StoryPlan(
        archetype="build", selection_reason="x", story_promise="x", central_question="x",
        title=TitleContract(chosen="t", promise="p"),
        hook=HookContract(viewer_problem="x", tension="y", promise="z"),
        cta=CTAContract(primary_after_beat="B01"),
        ending=EndingContract(resolve_hook="x", compressed_mental_model="y", capstone_payoff="z", viewer_can_now="do x"),
        beats=[StoryBeat(beat_id="B01", purpose="explain scaling", learning_objective="explain why /sqrt(d_k)")],
    )


def test_returns_the_shortlisted_candidates():
    worker = FakeWorker(CandidateShortlist(candidates=[
        {"beat_ids": ["B01"], "insight": "dividing by sqrt(d_k) keeps softmax stable"},
    ]))
    candidates = find_candidates(make_plan(), [], [], worker)
    assert len(candidates) == 1
    assert candidates[0].beat_ids == ["B01"]


def test_no_candidates_is_valid():
    worker = FakeWorker(CandidateShortlist(candidates=[]))
    assert find_candidates(make_plan(), [], [], worker) == []


def test_passes_beats_narration_and_claims():
    worker = FakeWorker(CandidateShortlist(candidates=[]))
    narration = [SceneNarration(scene_id="s1", sentences=[SentenceNarration(text="x", sentence_type="transition")])]
    claims = [Claim(claim_id="C001", source_unit="u1", claim="x", type="mechanism")]

    find_candidates(make_plan(), narration, claims, worker)

    payload = worker.calls[0]["payload"]
    assert payload["beats"][0]["beat_id"] == "B01"
    assert payload["narration"][0]["scene_id"] == "s1"
    assert payload["claims"][0]["claim_id"] == "C001"


def test_uses_pass_id_sc_and_candidate_finder_mode():
    worker = FakeWorker(CandidateShortlist(candidates=[]))
    find_candidates(make_plan(), [], [], worker)
    call = worker.calls[0]
    assert call["pass_id"] == "SC"
    assert call["mode"] == "CANDIDATE_FINDER"
