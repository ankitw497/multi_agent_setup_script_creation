# Story Improvement Plan — phase-wise task tracker (V2: Narrative Continuity)

This tracks implementation of `multi_agent_script_and_model_feedback.md`'s findings against
this codebase. Unlike that document (external feedback, not tracked), this file is the
"what's actually built" tracker for the fix — same convention as `BUILD_PLAN.md`: checkboxes
get updated as work lands, not on code-complete alone but on live verification. Every real
bug/finding surfaced while doing this work goes in `ERROR_LOG.md` in full; this file only
summarizes.

Legend: `[x]` done · `[~]` partial/in progress · `[ ]` not started.

---

## Why (root cause, not just symptoms)

The generated script repeats concepts (Q/K/V explained 3×) and the hook takes too long to
resolve, because **nothing in the pipeline tracks what the viewer already knows across
scenes**. Traced to specific real gaps, not hypothetical ones:

- `planning/scene_expander.py` (A2b) expands each story beat **in complete isolation** —
  `story_planner.py`'s `plan_story()` loop calls `expand_beat_scenes()` once per beat with
  zero state carried from one beat to the next. This is the direct mechanical cause of
  multi-beat repetition.
- `ScenePlan` (`planning/models.py`) has no concept-tracking fields — no `viewer_knows`, no
  `must_not_repeat`, no `running_example`, no preview/derivation/recap distinction.
- `narration/generator.py` (B1)'s prompt never says "don't repeat" and has no signal for
  what's already been taught.
- **Confirmed live, not hypothetical**: grepped a real saved run
  (`project/attention_series/video-01-attention-coherent-story/runs/v13/drafts/narration_final.json`)
  and found *"That combined vector is then believed to pass through a learned output
  projection..."* — the exact verifier-hedge-leak pattern the feedback describes.
- `review/models.py`'s `Category` already has `"repetition"` and `"pacing"` as valid values,
  but `review/story_critic.py` (C1)'s prompt never asks a question that would produce either.
- No deterministic check exists for "how long until the first real payoff lands" — the
  pattern already exists for retention/CTA (`verification/diagnostics/{retention,cta}.py`)
  but nothing analogous covers hook pacing.
- `config/models.yaml` already has `openai_story_strong_gpt56` (`gpt-5.6-sol`,
  reasoning-capable) configured and tried once, but never adopted as the default
  `story_lead` model — the feedback's "spend the strongest reasoning on story architecture"
  recommendation maps directly onto a real, already-half-validated option.

**Non-goals for this pass** (deferred, not forgotten):
- Swapping the default `story_lead` model to `gpt-5.6-sol` — needs a live A/B comparison
  first (Phase 4), never adopted on the feedback doc's word alone.
- A dedicated standalone "Redundancy/Compression Critic" agent pass — folded into
  strengthening C1's existing prompt first (Phase 3); only build a separate pass if a live
  run shows C1 alone doesn't catch it.
- Numeric-value continuity (feedback's raw-dot-product example surviving to softmax) is
  folded into the same `running_example` object as the qualitative running example, not
  built as a separate mechanism.
- Claim extraction / fact verification / HTML generation model tiers — out of scope; the
  feedback's own reasoning targets story/narration stages specifically.

---

## Where to start next (recommended order across the open phases)

Phases 1-4 are done. Phases 5-8 are open, but they are NOT equally urgent, and phase numbers
are chronological (order discovered), not priority. Recommended order, smallest-and-most-
certain first:

| # | Item | Phase | Why first |
|---|---|---|---|
| 1 | Thread the ledger into B2 | 8.1 | It's an outright bug silently undoing Phase 1 on every run; ~20 lines |
| 2 | Wire `critique_cold_hook` into long-form | 8.2 | The critic already exists and is tested -- it's one call site |
| 3 | Build the §9 Learning gate | 8.3 | Deterministic, cheap, a designed hard gate that was simply skipped |
| 4 | Retention diagnostics read narration, not planner flags | 8.4 | Turns three always-GREEN diagnostics into real signal |
| 5 | Reject regressing revision cycles + narrow B2's blast radius | 8.5 | Stops the loop making things worse; cheap guard |
| 6 | C1 also reviews H's screen prose | 6 | A whole artifact currently has zero critique coverage |
| 7 | Typed formula/numeric state validators | 6 | Fixes the confirmed raw-vs-scaled and dropped-`√d_k` class of bug |
| 8 | A2b neighbor contract | 5 | Improves transitions; larger change than the above |
| 9 | Airtime by narrative role, not source volume | 7 | Real fix for section bloat, but touches allocation for every run |
| 10 | Build C4c mid-video cold viewer | 8.2 | New module; do after the cheap retention wins land |

Everything above item 5 is small and low-risk. Items 6-10 are real work. Item 8.6 (story
and visual layers informing each other) is deliberately left unscoped pending the cheaper
partial fixes above.

---

## Confirmed bugs — implementation detail

Every bug below is code-confirmed (not inferred), with the exact location and current shape,
so it can be fixed without re-deriving the diagnosis. Line numbers are as of 2026-09-11 and
may drift -- match on the code, not the line.

### BUG-1 — B2 discards the Viewer Knowledge Ledger (Phase 8.1) · *start here*

**Where:** `src/editing/targeted_rewrite.py`, in `apply_targeted_rewrite()`.

**Current (broken) shape** — `scenes_payload` (~line 100) and the outer `payload` (~line 111):

```python
scenes_payload.append({
    "scene_id": scene.scene_id, "beat_id": scene.beat_id,
    "narrative_job": scene.narrative_job, "archetype_role": scene.archetype_role,
    "narrative_beat": scene.narrative_beat, "visual_description": scene.visual_description,
    "word_budget": scene.word_budget, "required_intent": intent,
    "available_claims": [_claim_payload(c) for c in beat_claims],
})
payload = {
    "story_promise": plan.story_promise, "central_question": plan.central_question,
    "preserve": revision_plan.preserve, "scenes": scenes_payload,
}
```

**Fix:** add the four Phase 1 fields, mirroring exactly what `narration/generator.py` already
sends. Everything needed is already in scope -- `scene` is a `ScenePlan` (carries
`scene_function`/`new_concepts`/`must_not_repeat`) and `plan` is a `StoryPlan` (carries
`running_example`). **No signature change required.**

```python
    "scene_function": scene.scene_function, "new_concepts": scene.new_concepts,
    "must_not_repeat": scene.must_not_repeat,
# and on the outer payload:
    "running_example": plan.running_example.model_dump(),
```

**Also:** `targeted_rewrite.py`'s `TASK_PROMPT` needs the same compress-don't-re-derive and
reuse-the-locked-example rules `narration/generator.py`'s prompt already carries -- copy the
generic (non-topic-specific) wording from there, and keep it generic (see the Phase 3
overfitting note).

**Verify:** unit test that B2's payload carries all four fields; then a real run where a scene
tagged `scene_function=derivation` is rewritten by B2 and still doesn't re-derive its
`must_not_repeat` concepts.

### BUG-2 — hook pacing sums "hook"-tagged scenes across the whole video (Phase 2)

**Where:** `src/verification/diagnostics/pacing.py`, `_hook_scene_seconds()` (~line 32).

**Current (broken) shape:**

```python
hook_scenes = [s for s in plan.scene_plan if s.narrative_beat == "hook"]
if hook_scenes:
    return sum(s.word_budget for s in hook_scenes) / PLANNING_WPM * 60
```

**Why it's wrong:** A2b uses `narrative_beat="hook"` as a *per-section* rhetorical device, not
exclusively for the video's opening. Real plan
(`video-01-attention-model-c-gpt56sol-tuned/runs/v01`) tagged `B1_s01, B2_s01, B3_s01, B4_s01,
B9_s01, B10_s01, B11_s01` -- so the sum included scenes from near the END of the video and
reported 143s where the true hook was 64s.

**Fix:** intersect the tag scan with the FIRST beat's own scenes, never the whole plan. The
existing fallback branch (first beat's scenes) was correct all along -- make it the primary
path, or filter `hook_scenes` to `s.beat_id == plan.beats[0].beat_id`.

**Verify:** regression test where a late beat also carries a `narrative_beat="hook"` scene and
must not inflate the measurement; then re-check the same real plan reports ~64s, not 143s.

### BUG-3 — retention diagnostics read the planner's own booleans (Phase 8.4)

**Where:** `src/verification/diagnostics/retention.py`, `_is_state_change()` (~line 32), used
by `check_valleys` (~line 58) and `check_payoff_gap` (~line 90).

**Current (broken) shape:**

```python
def _is_state_change(beat) -> bool:
    return beat.new_information or beat.payoff or beat.visual_mode_change or beat.question_progress != "none"
```

All four are fields **A2 sets about its own plan**, so a plan that fills them in passes by
construction. `check_driver_coverage` has the same problem in weaker form -- it only checks
`forward_driver.strip()` is non-empty, never that the driver drives anything.

**Fix:** derive state-change from the narration against the Phase 1 ledger -- did this beat's
scenes actually introduce anything in `new_concepts`, or were they all `must_not_repeat`
references? This wasn't possible when these diagnostics were written; Phase 1 made it
possible. Note this changes the signature: these functions currently take only `plan`, and
will need `narration` too (all call sites are in `orchestration/pipeline.py::_run_review_block`,
which already has `narration` in scope).

**Keep** the self-reported fields as a secondary signal: a beat declaring
`new_information=True` whose scenes introduce zero `new_concepts` is itself a useful finding
(planner/narration disagreement), just not the primary measurement.

### BUG-4 — C1 cannot see H's on-screen prose, and cannot be simply extended to (Phase 6)

**Where:** `src/review/story_critic.py`'s payload (~line 120) contains `narration` but no
screen prose. H's output (`BeatVisual.scenes[].screen_prose`) is what the viewer actually
reads, and no critic reviews it.

**Implementation constraint that Phase 6's wording understates:** C1 runs inside
`run_story_and_narration_loop()`, which **completes before** `synthesize_and_repair_video_html()`
is called at all (`orchestration/run_pipeline.py` calls them in sequence). So "add screen prose
to `critique_story()`'s payload" is *not implementable as written* -- at the time C1 runs, the
screen prose does not exist yet.

**Fix, one of:**
- (a) a separate post-H critique pass reusing `story_critic.py`'s REPETITION/OVERCLAIM prompt
  text against `BeatVisual` content, run inside `synthesize_and_repair_video_html`'s existing
  repair loop so its findings can actually drive an H repair; **or**
- (b) move the screen-prose review into the existing C3 visual-critic pass
  (`review/visual_critic.py`), which already runs post-H and already has an `H REPAIR` route.

(b) is likely cheaper -- C3 already exists, already runs at the right point, and already has a
repair path. Decide before building.

### BUG-5 — H receives none of the shared story state (Phase 6)

**Where:** `src/html_synth/synthesizer.py::synthesize_beat_visual(beat, plan, claims, narration_lead)`
(~line 110). Its payload carries `beat_purpose`, `forward_driver`, `learning_objective`, each
scene's `visual_description`, allowed components and claims -- but no `running_example`, no
`viewer_knows`, and not the scene's actual narration text.

**Useful detail:** `plan` is *already a parameter*, so `plan.running_example` needs **no
signature change** -- it's a payload-only fix. Passing the actual narration DOES need a
signature change; both call sites are `orchestration/html_pipeline.py` (~lines 45 and 75),
which already have `narration` in scope.

**Verify:** re-render the real source and confirm a `diagram_card` in the scoring section
reuses the locked example instead of inventing new entities (the confirmed `dog/park/bone`
regression).

---

## Phase 1 — Viewer Knowledge Ledger threaded through A2b (highest leverage)

**Fixes:** the mechanical cause of cross-scene repetition (feedback §2.2, §3, §4, §5, §6, §7).

- [x] `planning/models.py` — added `RunningExample` (`label`, `description`, `values: dict[str,str]`)
      and `ViewerLedger` (`viewer_knows: list[str]`, `running_example: RunningExample`)
- [x] `planning/models.py` — added to `ScenePlan`: `new_concepts: list[str]`,
      `must_not_repeat: list[str]`, `scene_function: SceneFunction` (`"preview"|"derivation"|"recap"|"standard"`)
- [x] `planning/models.py` — added `running_example: RunningExample` to `StoryStructure`, seeded
      once during A2 from the same "concrete illustration" the hook prompt already extracts
- [x] `planning/scene_expander.py` — `expand_beat_scenes()` now accepts `ledger: ViewerLedger`,
      returns `(scenes, updated_ledger)`
- [x] `planning/scene_expander.py` — extended `TASK_PROMPT`: reuse `running_example`'s exact
      objects/values; `scene_function=derivation` + `must_not_repeat` for a brief reference
      to an already-taught concept (≤1 sentence, never re-derive); `scene_function=recap` only
      when the scene's whole job is compression; list genuinely new concepts in `new_concepts`
- [x] `planning/story_planner.py` — seeds the ledger from `structure.running_example` after the
      A2 call, threads it through the existing `for beat in structure.beats:` loop, accumulates
      `viewer_knows` from each beat's returned `new_concepts` between iterations
- [x] `narration/generator.py` (B1) — extended per-scene payload with `new_concepts`,
      `must_not_repeat`, `scene_function`, and the shared `running_example`
- [x] `narration/generator.py` (B1) — extended `TASK_PROMPT`: compress `recap` scenes to 1-2
      bridging sentences, mention `must_not_repeat` concepts briefly by name only, reuse
      `running_example`'s exact values rather than inventing new numbers/objects
- [x] Unit tests: `tests/planning/test_scene_expander.py` — ledger accumulates correctly
      across sequential beats, dedupes, `must_not_repeat`/`scene_function` flow through (10 tests)
- [x] Unit tests: `tests/planning/test_story_planner.py` — the actual multi-beat integration:
      `test_viewer_ledger_threads_across_multiple_beats_end_to_end` proves beat 2's A2b call
      really receives beat 1's `new_concepts` as `viewer_knows`, through `plan_story()`'s real
      loop (not just one isolated `expand_beat_scenes()` call)
- [x] Unit tests: `tests/narration/test_generator.py` — payload carries the new fields (2 tests)
- [x] `.venv/bin/python3 -m pytest -q` green
- [x] **Live-verify** (`runs/v17`, 2026-09-11): real model output confirms the mechanism works.
      "queries"/"keys"/"values" are each tagged `new_concepts` exactly ONCE (`beat_2_s03`), and
      every later touch across beats 3/4/5/6/7/9/10 is correctly tagged into `must_not_repeat`,
      never re-listed as new. The actual narration text for those `derivation`-tagged scenes
      references the concept in one clause without re-deriving it (e.g. `beat_9_s02`: "each
      with its own query, key, and value projections" -- no re-explanation). `running_example`
      was populated correctly from the hook's own concrete illustration. See ERROR_LOG.md.

---

## Phase 2 — Hook-tension pacing diagnostic (deterministic, no LLM)

**Fixes:** feedback §2.1 (hook takes too long to resolve) — measurable, not just narrated.
Grounded in `IMPLEMENTATION_PLAN.md` §10.2's own explicit stated target ("tension reached
inside ~30 s") — a real, previously-unbuilt gap alongside `retention.py`'s other §10.2
diagnostics, not an invented threshold.

- [x] `verification/diagnostics/pacing.py` (new) — `check_hook_tension_pacing(plan) ->
      DiagnosticResult`: sums `word_budget / 167 * 60` seconds across scenes tagged
      `narrative_beat="hook"` (falling back to the plan's first beat's scenes if none are
      tagged that way); GREEN ≤30s, AMBER ≤60s, RED beyond
- [x] `orchestration/pipeline.py` — wired into `_run_review_block`, alongside the existing
      `check_retention(plan) + [check_cta_position(plan), check_hook_tension_pacing(plan)]` line
- [x] Unit tests: `tests/verification/diagnostics/test_pacing.py` (new) — pure Python, no
      agent/LLM, mirrors `test_cta.py`'s structure (6 tests, including the fallback path)
- [x] Fixed a real fixture-realism gap this surfaced: `tests/orchestration/test_pipeline.py`'s
      `make_plan()`/`make_good_expansions()` used to give the hook beat 3 scenes (~75s) --
      correctly flagged RED by the new diagnostic. Reduced to 1 scene (~25s, GREEN), matching
      the fixture's own "hook, ~small" comment, which was never actually enforced before.
- [x] `.venv/bin/python3 -m pytest -q` green (721 passed after this phase)
- [x] **Live-verify** (`runs/v18`, 2026-09-11): `pacing.hook_tension` appears in
      `review_bundle.json` and correctly fired RED -- "hook scenes take 172s of narration
      before the central tension is established" (target ≤30s) -- independently
      reproducing almost the exact magnitude the original feedback complained about
      (~180s). Confirms the diagnostic is wired correctly end to end. See ERROR_LOG.md.
- [ ] **Real bug found — see BUG-2 above for the exact code and fix** (2026-09-11, while
      independently verifying an external review's
      timing table against `video-01-attention-model-c-gpt56sol-tuned/runs/v01`): the review's
      own precise word-count-based timing (hook = 64s) was exactly right; this diagnostic
      instead reported 143s. Root cause: `check_hook_tension_pacing()` sums every scene
      tagged `narrative_beat="hook"` **anywhere in the whole plan**, but A2b tags "hook" onto
      the first scene of MANY beats (`B1_s01, B2_s01, B3_s01, B4_s01, B9_s01, B10_s01,
      B11_s01` in this real plan) as a per-section rhetorical device, not exclusively the
      video's true opening -- so the sum accidentally included hook-tagged scenes scattered
      near the END of the video. Fix: restrict the scan to the plan's FIRST beat's own scenes
      only (the existing fallback path was actually the correct, safe behavior all along --
      make it the primary path, or intersect the "hook"-tag scan with the first beat's own
      scene ids, never the whole plan)
- [ ] Regression test: a plan where a later beat's scene is also tagged `narrative_beat="hook"`
      must not inflate the measured hook duration
- [ ] `.venv/bin/python3 -m pytest -q` green
- [ ] **Re-verify live** against the same `video-01-attention-model-c-gpt56sol-tuned` plan --
      confirm the diagnostic now reports ~64s (or whatever the first beat's real total is),
      not 143s

---

## Phase 3 — Strengthen C1 (story critic) + fix the hedge-leak at the source

**Fixes:** feedback §2.2 (repetition), §2.1 (pacing), §8 (overclaims), §9 (verifier hedge leak).
Reuses the `"repetition"`/`"pacing"` categories already in `review/models.py` — no schema
change needed here, prompt-only.

- [x] `review/story_critic.py` — added **REPETITION** check to `TASK_PROMPT`: does any concept
      get substantively re-explained after being taught, without being a marked recap? name
      scenes + concept (`category="repetition"`)
- [x] `review/story_critic.py` — added **PACING** check: does the hook resolve its central
      tension quickly, or does setup delay the first real mechanism? (`category="pacing"`)
- [x] `review/story_critic.py` — added **OVERCLAIM** check (`category="clarity"`): hard-selection
      language for a soft/weighted mechanism; a single component claimed to fully cause/resolve
      a distributed outcome; an architecture/algorithm-specific detail stated as universal;
      an overstated absolute motivation/limitation claim
- [x] `narration/generator.py` (B1) — added to `TASK_PROMPT`: state
      `verification_status=VERIFIED` claims as plain fact — never "is believed to" / "is
      thought to" / "seems to" on a verified technical claim (fixes the real `runs/v13` leak;
      landed as part of the Phase 1 edit to the same file, since it's the same prompt)
- [x] Unit tests: `tests/review/test_story_critic.py` — prompt-content tests for all three new
      checks, plus a real-shaped `test_returns_a_repetition_issue_when_the_critic_flags_one`
- [x] Unit tests: `tests/narration/test_generator.py` — `test_prompt_instructs_not_hedging_verified_claims`
- [x] `.venv/bin/python3 -m pytest -q` green (727 passed after this phase)
- [x] **Live-verify** (`runs/v18`, 2026-09-11): narration has no hedge language on a verified
      claim (confirmed clean in both `v17` and `v18`). C1's new REPETITION check fired a real,
      correct catch: `beat_4_s01`/`beat_4_s02` restate the same softmax explanation almost
      verbatim -- a genuine residual gap Phase 1's ledger didn't fully prevent (both scenes
      are in the SAME beat's own A2b call; see the "Open items" note in ERROR_LOG.md), caught
      exactly as the two-layer design intended. The narration also independently reflects the
      OVERCLAIM soft-language guidance: "a blend across all the values, weighted by
      relevance, not a single pick." See ERROR_LOG.md for full detail.

### Overfitting fix (user-flagged mid-implementation, 2026-09-11)

**Real finding:** my first drafts of the Phase 1/3 prompt text (`scene_expander.py`,
`narration/generator.py`, `review/story_critic.py`) baked in attention/Q-K-V-specific example
language lifted directly from the feedback doc (`"Q asks, K matches, V carries"`,
`"attention as retrieval"`, `"the highest-matching value is pulled in"`, `"one head can only
capture one relationship"`). These prompts run on **every future video regardless of topic**
(this pipeline is explicitly multi-video/multi-series, see `SeriesLedger`) — hardcoding one
video's vocabulary into them would bias or confuse the model on an unrelated source (a video
about databases, compilers, biology, etc. has no "Q/K/V" and no "attention mechanism").

**Fix:** rewrote all four spots to state the underlying principle generically (soft/weighted
vs. hard-selection language; one-component-vs-distributed-cause; architecture-specific-vs-
universal; the preview/derivation/recap format) with either no concrete example or a
deliberately different, throwaway illustrative domain (e.g. "a networking retry-backoff
formula" / "a tree-rotation invariant") so the instruction reads as pattern-teaching, not
domain content. `planning/story_planner.py`'s `running_example` instruction was also
degenericized (dropped the literal "trophy/suitcase" numeric values, kept the format
description abstract).

- [x] `planning/scene_expander.py`, `narration/generator.py`, `review/story_critic.py`,
      `planning/story_planner.py` — all four prompts rewritten, zero hardcoded topic vocabulary
- [x] Regression tests added to all four test files (`test_prompt_has_no_hardcoded_topic_vocabulary`)
      asserting `"q/k/v"`, `"softmax"`, `"multi-head"`, etc. never appear in these prompts again
- [x] `.venv/bin/python3 -m pytest -q` green (731 passed after this fix)

---

## Phase 4 — Model-tier verification (not adopted blind)

**Fixes:** the feedback's model-allocation recommendation, grounded in this project's real config.

- [x] Ran a live A2/A2b comparison on the same real source: `story_lead` on `gpt-4o`
      (`openai_story_strong`, current default, `video-01-attention-model-a-gpt4o`) vs.
      `gpt-5.6-sol` (`openai_story_strong_gpt56`, `video-01-attention-model-b-gpt56sol`)
- [x] **Real finding**: `gpt-5.6-sol` with `reasoning_effort` unset and `max_tokens=4000`
      (inherited from gpt-4o's own hardcoded A2 override) burned its ENTIRE ceiling on hidden
      reasoning and returned an empty `StoryStructure` (`beats=0`) -- confirmed via
      `litellm.model_cost["gpt-5.6-sol"]` that `max_tokens` is a combined reasoning+output
      budget, not a separate reasoning allowance, and that `"medium"` is this model's own
      provider default. Cost ~$0.28 wasted on two empty A2 calls, run ended FAIL. The
      `gpt-4o` baseline worked properly (10 beats, 49 scenes, narrowed to 1 real hard failure
      after 2 revision rounds) but did not reach a clean PASS either. See ERROR_LOG.md.
- [x] Fixed the underlying config gap (not the same as adopting the alias): added per-alias
      `max_tokens` support to `config/models.yaml`/`config/loader.py`/`agents/*.py`, pinned
      `gpt-5.6-sol` to `reasoning_effort: "medium"` + `max_tokens: 10000` explicitly. Also
      fixed a separate real gap found in the process: `reasoning_tokens` was extracted from
      the provider response but silently dropped before being logged to `usage.jsonl`.
- [x] Re-ran the comparison with the fixed config (`video-01-attention-model-c-gpt56sol-tuned`)
      -- the config fix worked: A2 produced a real plan (12 beats, 42 scenes) using only 820 of
      its 10000-token ceiling on reasoning (confirmed via the newly-persisted
      `reasoning_tokens` field), no truncation on any of the 12 A2b calls either
- [x] **Quality comparison, using the Phase 1 ledger machinery on both**: `gpt-5.6-sol` (tuned)
      ended FAIL with 3 hard failures, two of them a genuine story-architecture coherence
      break `gpt-4o` didn't have -- `title_promise_unrelated_to_hook` (title and hook share
      almost no content) and `hook_promise_unpaid_by_ending` (the hook's own promise is never
      resolved by the ending) -- plus `cta.position` RED (CTA at 100% through the story) and
      `pacing.hook_tension` RED (143s vs. the 30s target). `gpt-4o` ended FAIL with 1 hard
      failure (a source-coverage gap, not a coherence break) after narrowing down from 2 across
      2 revision rounds -- `gpt-5.6-sol` went from 2 hard failures up to 3 across its 2 rounds,
      not down. C1's REPETITION check (Phase 3) did correctly fire on `gpt-5.6-sol`'s output too
      (the same raw-score-to-weight arithmetic re-explained 3 times) -- the Phase 1-3
      machinery works identically regardless of which model is under `story_lead`.
- [x] **Cost**: `gpt-5.6-sol` (tuned) cost $1.0974 for the full run vs. `gpt-4o`'s $0.6645 --
      65% more expensive.
- [x] **Decision: do NOT promote `gpt-5.6-sol` to the default `openai_story_strong`.** The
      config fix was worth keeping (it now works instead of catastrophically failing), but on
      this real comparison it produced a structurally less coherent plan for 65% more cost --
      the opposite of what the feedback doc predicted. Matches the plan's own explicit
      criterion: promote only if the comparison shows a real improvement; it showed the
      opposite. See ERROR_LOG.md for full detail. Re-evaluate later only if a specific,
      different `reasoning_effort` (e.g. `"high"`) or prompt change is tried and separately
      justified -- not on the strength of the model's name alone.
- [x] Confirmed no change to `narration_lead` (Sonnet, subscription lane — free, already strong;
      Phase 1's richer input is the actual lever, not a model swap)
- [x] Confirmed no change to claim extraction / fact verification / HTML generation tiers

---

## Phase 5 — Forward-looking coordination context (A2b neighbor contract, C1 plan-intent exposure)

**Fixes:** a gap surfaced by external review of Phases 1-3 (2026-09-11): the Viewer Knowledge
Ledger is backward-looking only (*"what has the viewer already learned"*) and has no
forward-looking coordination (*"what must this scene leave unresolved for the next scene,"
"is another scene already responsible for this concept"*). Confirmed as real via direct code
inspection, not just plausible in theory:

- `planning/scene_expander.py`'s A2b payload carries the current beat's own fields plus the
  backward `viewer_knows`/`running_example` ledger -- **zero** next-beat or previous-beat
  information reaches it, even though `story_planner.py`'s loop has the full ordered
  `structure.beats` list in scope when it calls `expand_beat_scenes()`.
- `review/story_critic.py`'s C1 payload passes `plan.beats`, **never `plan.scene_plan`** -- C1
  can independently notice a repetition by re-reading narration text (proven live in
  `runs/v18`), but cannot cross-check narration against the planner's own explicit
  `scene_function`/`must_not_repeat`/`running_example` intent, because it never receives them.

Deliberately **not** adopting the reviewed feedback's proposed `global_story_state` /
`neighbor_contract` / `callback_ids_to_plant`/`callback_ids_to_payoff` schema wholesale --
most of that already exists in this codebase and just isn't threaded through yet:
`StoryStructure.central_question`, `StoryBeat.next_question`/`viewer_question_before`/
`answer_or_payoff`, `StoryPlan.mini_payoffs` (with an `opens` field -- an existing callback
mechanism), and `ScenePlan.word_budget` (existing budget field). Building a parallel
callback-ID bookkeeping system risks drifting out of sync with these existing fields instead
of using them. The leaner fix: thread the EXISTING fields through, don't invent new ones.

- [ ] `planning/story_planner.py` — pass beat N-1 and N+1 (when they exist) into each
      `expand_beat_scenes()` call in the existing per-beat loop
- [ ] `planning/scene_expander.py` — accept `previous_beat`/`next_beat` (or `None`), add a
      compact `neighbor_contract` to the payload built from their EXISTING fields (`purpose`,
      `forward_driver`, `viewer_question_before`, `next_question`) -- no new schema. Also add
      `central_question` (already on `StoryStructure`, just never passed here)
- [ ] `planning/scene_expander.py` — extend `TASK_PROMPT`: this beat must leave the next
      beat's own open question genuinely open -- do not resolve what a later beat is
      responsible for, even if it would be easy to add a sentence that does
- [ ] `review/story_critic.py` — switch/extend the payload to include `plan.scene_plan`
      (`scene_function`, `must_not_repeat`, `new_concepts`, `running_example`), not just
      `plan.beats`
- [ ] `review/story_critic.py` — extend the REPETITION check: when a scene's own
      `scene_function=derivation` lists a `must_not_repeat` concept and narration re-explains
      it anyway, that is a confirmed plan-violation, not just a suspected repetition
- [x] **Confirmed real, not hypothetical** (2026-09-11, visual audit of `runs/video-01-attention-model-a-gpt4o/v01`):
      rendered the real HTML with Playwright and read the screenshots directly. `hook_s01`,
      `origin_s01`, `matrix_s01`, `heads_s01`, `recap_s01` all correctly use the locked example
      ("the cat couldn't climb the stairs because it was too tired"). `score_s02`/`score_s03`
      invent an entirely different one (`q(it) . k(dog)`, `k(park)`, `k(bone)`) -- isolated to
      those two adjacent scenes, not pervasive. `render_report.json` shows zero hard-check hits
      for this (only the known word-count band issue) -- confirms nothing today catches
      semantic example drift, only structural defects. See ERROR_LOG.md and Phase 6 below for
      the root cause this pointed to.
- [ ] New check for running-example fidelity, now that the failure mode is confirmed real: best
      done as a C1 judgment check (semantic equivalence isn't something a deterministic Python
      check can fully verify), given `running_example` explicitly and asked to flag any scene
      that introduces different named entities for the same underlying illustration
- [ ] Unit tests: neighbor contract threading in `scene_expander.py`/`story_planner.py`
      (first/last beat have `None` neighbors, correctly handled); `story_critic.py` payload
      carries `scene_plan` fields
- [ ] `.venv/bin/python3 -m pytest -q` green
- [ ] **Live-verify**: a real run's A2b calls carry real neighbor context (inspect
      `usage.jsonl`/a captured payload); C1's `review_bundle.json` issues (if any) reference
      plan-intent violations specifically, not just independent text observations; running-
      example fidelity confirmed across every scene in the narration

---

## Phase 6 — Cross-artifact consistency + technical invariants (new, from general pipeline feedback)

**Fixes:** items #9 (numeric state), #10 (technical invariants), #20 (cross-agent artifact
consistency) from `General Multi-Agent Video Script Pipeline Improvement Feedback.md` --
genuinely new territory, not covered by Phases 1-5. The Phase 5 visual audit's `score_s02`/
`score_s03` finding pointed directly at the root cause this phase targets.

**Root cause, confirmed by reading the actual code** (`html_synth/synthesizer.py`):
`synthesize_beat_visual()` (H -- generates the on-screen `diagram_card`/component content) is
a call **completely separate** from `generate_narration()` (B1) and receives **none** of the
shared state Phase 1 built: no `running_example`, no `viewer_knows`, not even the actual
narration text for the scene it's illustrating -- only `visual_description` (a field set back
during A2b, before narration exists) and the beat's own claims. So even where A2b/B1 get the
running example right, H has no way to know it, and vice versa -- two independently-generated
artifacts (spoken narration and on-screen diagram) can each be locally consistent with
whatever they were told, while diverging from each other and from the plan's own locked
example. This is exactly feedback item #20's *"narration entities vs. HTML entities vs.
diagram entities... a render should fail validation if these diverge materially."*

- [ ] **See BUG-5 above** (`plan` is already a parameter, so `running_example` needs no
      signature change; the narration text does). `html_synth/synthesizer.py` — thread
      `plan.running_example` into `synthesize_beat_visual()`
      and `synthesize_hero()`'s payloads; extend `TASK_PROMPT`/`HERO_TASK_PROMPT`: if
      `running_example` is set and a `diagram_card`/component illustrates it, reuse its exact
      named objects/values -- never invent a different one for the same underlying idea (same
      instruction pattern already used in `scene_expander.py`/`narration/generator.py`)
- [ ] `html_synth/synthesizer.py` — also thread the scene's own actual narration text (not just
      `visual_description`) into `synthesize_beat_visual()`'s payload, so H illustrates what was
      actually narrated, not a stale pre-narration description that may have drifted
- [ ] New deterministic-leaning check: given `running_example.values`' named entities, scan a
      beat's generated `diagram_card`/component content for named entities that don't overlap
      with either the locked example or the beat's `available_claims` -- flag as a candidate
      cross-artifact mismatch. Entity extraction for arbitrary technical prose is not perfectly
      reliable by regex alone, so treat this as a diagnostic signal (AMBER-banded), not a hard
      gate that blocks promotion on its own -- pair it with a C1-style judgment check for the
      cases the heuristic can't resolve confidently

### Confirmed by a second, independent visual audit (2026-09-11, `video-01-attention-model-c-gpt56sol-tuned/runs/v01`)

Rendered and read the `gpt-5.6-sol` (tuned) run's real HTML/narration directly, verifying an
external review's specific claims rather than taking them on faith. Both of the review's
headline "accuracy" bugs are real:

- **Raw vs. scaled score confusion**: `B2_s02` narration states *"'Cat' scores 4.8, 'tired'
  scores 2.6, 'stairs' only 1.2"* as the initial match score. `B7_s01` narration: *"Take the
  **scaled** scores for 'it' — cat 4.8, stairs 1.2, tired 2.6"* -- the identical three numbers,
  now called "scaled." Scaling divides by `√d_k`, so scaled values should differ from raw ones.
- **Missing scaling term in a later equation card**: `B7_s03`'s narration correctly states the
  complete equation verbally ("softmax of QK-transpose over square root of d_k, times V"), but
  `B8`'s own `math-block-equation` in the rendered HTML is literally `softmax(QK^T)_row` --
  the `/√d_k` term silently disappears one beat later, even though B8 reuses the exact same
  4.8/1.2/2.6 example and calls them "raw scores against every key" in its diagram caption.

**A bigger, structural gap this trace surfaced**: two of the review's other flagged sentences
(an architecture-universality overclaim in the position section, an unnecessary empirical
claim in the multi-head section) turned out to **not be in the spoken narration at all** --
they're in H's separately-generated on-screen article prose (`synthesize_beat_visual()`'s
`screen_prose`/`subsection-body` output). **C1 (`review/story_critic.py`) never receives or
reviews this artifact at all** -- only spoken narration. So the on-screen text a viewer
actually reads has zero critique coverage today, not even the OVERCLAIM check Phase 3 already
built. This is a bigger, more concrete version of this phase's "cross-artifact" scope:

- [ ] Get H's generated `screen_prose`/component content under REPETITION/OVERCLAIM review --
      a real, currently fully-uncovered artifact. **See BUG-4 above before starting**: C1 runs
      inside the story loop, which finishes before H is ever called, so simply extending
      `critique_story()`'s payload is NOT implementable -- the screen prose doesn't exist yet
      at that point. Choose between a post-H critique pass and folding it into C3 (which
      already runs post-H and already has an H-repair route); BUG-4 records why (b) looks
      cheaper
- [ ] **Do not** reach for "add more critic passes" or "escalate to a stronger model" as the
      first response to a missed on-screen overclaim -- the honest cause here is zero coverage,
      not weak coverage. Only consider giving C1 an escalation tier (matching the existing
      `A3/A4/C3/C4b/C5` pattern in `config/models.yaml`) as a later, separately-tested
      hypothesis if misses persist after C1 actually has the content in scope
- [ ] **Technical invariants** (item #10), sharpened into a typed formula-state object rather
      than a loose "invariants" bag, per the review's own concrete proposal:
      ```yaml
      attention_formula:
        score: "QK^T"
        scaled_score: "QK^T / sqrt(d_k)"
        normalized: "softmax(QK^T / sqrt(d_k))"
        output: "softmax(QK^T / sqrt(d_k)) V"
      ```
      Once a beat has narrated/derived a given stage (e.g. "scaled_score" in B6/B7), every
      LATER equation card referencing the same underlying computation must match that stage's
      registered form, not regress to an earlier one (B8's `softmax(QK^T)_row` regressing past
      the already-derived scaled form is exactly the bug this catches). Implement as a new
      `verification/hard/` check: Python pattern-matching against the registered stage strings,
      not model judgment -- this is exactly the class of bug a critic will not reliably catch
      run after run (confirmed live: it slipped through this run's C1 pass untouched)
- [ ] **Numeric state tracking** (item #9), sharpened by the confirmed bug above: a
      `numeric_state` object distinguishing `raw_scores`/`scaled_scores`/`attention_weights` as
      SEPARATE typed values (not one flat `values` dict reused ambiguously across stages), so
      a scene can only claim "these are the scaled scores" if they match the registered
      `scaled_scores`, not the registered `raw_scores`. Extend `RunningExample` (or add a
      sibling model) accordingly; extend `narration/generator.py`'s prompt to require reusing
      the correct stage's numbers, not just "prior numeric values" generically
- [ ] Unit tests: `synthesizer.py` payload carries `running_example` and actual narration text;
      the new entity-overlap diagnostic (clean case, mismatch case, ambiguous case treated as
      AMBER not a crash); the formula-stage check (regression from a later to an earlier stage
      is caught; a consistent stage progression is not flagged); C1 payload carries screen prose
- [ ] `.venv/bin/python3 -m pytest -q` green
- [ ] **Live-verify**: re-render the same real source; confirm `score_s02`/`score_s03`-style
      diagrams now reuse the locked running example instead of inventing `dog/park/bone`;
      confirm B8's equation now retains `/√d_k` instead of regressing; confirm the new
      diagnostics actually fire on a deliberately-reintroduced mismatch (so we know they aren't
      silently inert) before trusting them clean on a real run

---

## Phase 7 — Planning-time runtime budgets, preview-completeness control, mechanism scope

**Fixes:** item #12 (runtime budgets at the planning stage, not measured only after narration)
from `General Multi-Agent Video Script Pipeline Improvement Feedback.md`, plus two further
real findings from the `gpt-5.6-sol` (tuned) review that don't fit Phase 6's artifact-
consistency scope.

**#1 -- Runtime budgets belong at planning time, not just as a post-hoc diagnostic.**
Phase 2's `pacing.hook_tension` (and `retention.py`'s `payoff_gap`) MEASURE the plan's own
already-decided word budgets after the fact -- they can flag a bloated hook, but nothing
constrains `beat_word_budget.py`'s allocation or A2's own beat count from producing one in
the first place. The `gpt-5.6-sol` (tuned) run's real total came in at 12:39 against a 900s
(15:00) target -- actually under budget in aggregate -- but individual sections (masking
1:25, heads 1:20) ran 30-50% over what their content needed, while the hook (1:04) ran over
its own ~30s retention target despite the overall video having slack elsewhere. Aggregate
word-budget-matches-target (the existing `check_word_budget_matches_target` hard check) does
not catch this -- it only checks the sum, never the distribution.

**The concrete mechanism, confirmed 2026-09-11**: `beat_word_budget.py::allocate_beat_word_budgets()`
splits the target duration proportionally to `len(beat.source_unit_ids)` -- i.e. **airtime is
proportional to how much SOURCE MATERIAL a beat cites, not to its narrative importance or
retention value**. Run C's real allocation shows the effect exactly: B1 through B9 each got
precisely 193 words, B10/B11 got ~290. The hook received the same budget as the multi-head
section, because they happened to cite a similar number of source units. The "hook is too
long / masking is too long" complaints every review has raised are therefore not narration
failures at all -- they are decided at allocation time, before a word is written.

- [ ] `planning/beat_word_budget.py` — allow the plan's own archetype/hook to declare
      `retention_deadlines` (central_problem/mechanism_preview/first_payoff seconds), and
      weight the deterministic per-beat allocation to respect them, not just split
      proportionally by `len(source_unit_ids)`. Keep the allocation itself deterministic
      Python, matching this module's own existing ERR-010/ERR-023 rationale -- do not move
      this back into an LLM call
- [ ] `verification/hard/structure.py` or a new diagnostic — flag a beat whose ALLOCATED
      budget is a large outlier relative to its own content density (e.g. `available_claims`
      count), not just whether the grand total matches -- catches an individual bloated
      section even when the overall video is within budget

**#2 -- Preview can be too complete, not just present.** `B2` (Phase 1's `scene_function` would
tag this `preview`) gives the viewer the exact Q, K, V roles, exact match scores, and exact
softmax weights -- effectively the whole attention computation -- and then `B4`-`B7` spend four
beats re-deriving the same facts as if new. This is a real, different failure mode from
"repetition" (Phase 3's REPETITION check is about re-explaining something at the SAME level of
completeness twice; this is about the PREVIEW itself being too complete for its own declared
function). Reviewer's own resolution -- keep the full preview (better for retention), but the
DERIVATION beats must narrate as "confirming/explaining what we already saw," not
"discovering it":

- [ ] `planning/scene_expander.py` — extend `scene_function=preview`'s own guidance: a preview
      may show the mechanism's SHAPE (what stages exist) but should be explicit in
      `must_not_repeat`/`new_concepts` about which EXACT values (if any) it reveals, so later
      `derivation` scenes know whether they're deriving something genuinely new or explaining
      the reasoning behind a number the viewer already saw
- [ ] `narration/generator.py` — when a later scene's job is to derive something the viewer
      already saw an exact value for (per the ledger), require narration to frame it as
      confirming/explaining ("that's the 0.88 we already saw — here's why"), never as a fresh
      reveal

**#3 -- Mechanism scope (masking is conditional, not universal).** `B12`'s recap states *"scores
get scaled and masked"* as if masking is inherent to all self-attention, even though the plan's
own `B10` correctly established masking as specific to causal/autoregressive attention. This is
the same class of "architecture-specific fact stated as universal" the OVERCLAIM check targets,
but scoped to a STATEFUL claim (whether masking applies) that changes partway through the video
-- a plain per-sentence overclaim check can't easily tell "masking" was scoped earlier without
knowing the video's own current mode:

- [ ] `planning/models.py` — add a lightweight `mechanism_scope` concept to `ViewerLedger` (or a
      sibling), e.g. `{"causal_mask_required": bool}`, set once a beat like B10 establishes it
- [ ] `narration/generator.py`/`review/story_critic.py` — a recap/summary scene must not state a
      scoped mechanism as if unconditional; extend the OVERCLAIM check (or a new, narrow check)
      to flag exactly this pattern using the ledger's own recorded scope, not just prose judgment
- [ ] Unit tests for all three sub-items above
- [ ] `.venv/bin/python3 -m pytest -q` green
- [ ] **Live-verify**: re-run against the same real source; confirm per-section outlier
      detection fires on a deliberately-bloated section; confirm a derivation scene following a
      complete preview narrates as confirmation, not fresh discovery; confirm a recap after a
      scoped mechanism (like masking) is introduced states the scope correctly

---

## Phase 8 — Measure the viewer's experience, not the planner's self-report

**Why this phase exists.** User report (2026-09-11): *"the pipeline is ready but the script
is not coming out to be good -- narration has mistakes, viewer retention and interest aren't
taken into account, story building, causal link, viewer should learn something new."* A code
audit traced each complaint to a specific, confirmed gap. The pattern underneath all of them:

> The pipeline is genuinely strong at **verifying facts** -- claims, grounding, numeric
> fidelity, render integrity are all real, built and working. It has almost no independent
> measurement of **whether the result is a good watch**. Every retention/learning signal is
> either self-reported by the planner or entirely absent. That asymmetry is the quality
> ceiling, and Phase 4 already demonstrated a stronger model does not move it.

### 8.1 — BUG: every revision cycle silently discards the Viewer Knowledge Ledger

`editing/targeted_rewrite.py` (B2) regenerates a flagged scene's narration from scratch using
B1's own `GeneratedNarration` schema, but its payload contains **none** of Phase 1's fields --
no `scene_function`, no `must_not_repeat`, no `new_concepts`, no `running_example` (grep
returns empty). So the anti-repetition and example-lock machinery is live in A2b and B1, then
thrown away by the exact pass most likely to reintroduce those defects. Every real run hits
B2 (both comparison runs ran it twice). This is the most likely mechanism behind repetition
issues that never clear across revision rounds, and a plausible one for the confirmed
`dog/park/bone` running-example drift.

- [x] **Fixed 2026-09-11 (see BUG-1 above for the original shape).** `editing/targeted_rewrite.py` —
      added `scene_function`, `new_concepts`, `must_not_repeat` per scene and the shared
      `running_example` to B2's payload, matching what `narration/generator.py` already sends;
      extended B2's `TASK_PROMPT` with the same compress-don't-re-derive and
      reuse-the-locked-example rules B1 already carries. No signature change needed (`scene`
      and `plan` were both already in scope) -- payload- and prompt-only.
- [x] Unit tests: `tests/editing/test_targeted_rewrite.py` --
      `test_scene_function_new_concepts_and_must_not_repeat_reach_a_rewrite`,
      `test_running_example_reaches_a_rewrite`,
      `test_prompt_instructs_the_same_scene_function_and_running_example_rules_as_b1`,
      `test_prompt_has_no_hardcoded_topic_vocabulary` (overfitting guard, matching Phase 3's
      precedent)
- [x] `.venv/bin/python3 -m pytest -q` green (748 passed, up from 744)
- [x] **Live-verify** (`video-01-attention-bug1-verify/runs/v01`, 2026-09-11): this run hit
      `TARGETED_REWRITE` twice, and its final cycle rewrote all 7 of the plan's beats (36
      scenes) -- so every scene in the final narration passed through the fixed B2. Checked
      15 `scene_function=derivation` scenes with real `must_not_repeat` lists; every one
      correctly compresses the reference into a bridging clause instead of re-deriving it,
      e.g. `build_step_1_s02`: *"Since we already know 'it' could mean either word..."*;
      `build_step_1_s05`: *"Since queries and keys are already doing the matching..."*. Direct
      confirmation the fix works outside mocked tests. See ERROR_LOG.md.

### 8.2 — No cold-viewer critique exists for long-form at all

`review/cold_hook_critic.py` (C4s) is built, tested and good -- and is wired **only** into
`orchestration/shorts_pipeline.py`. `orchestration/pipeline.py::_run_review_block` never calls
it. A 60-second short gets its hook judged by a cold viewer; a 12-minute video's hook gets
nothing. `IMPLEMENTATION_PLAN.md` §8/§10.2 additionally specifies **C4c, a MID-VIDEO cold
viewer** asking *"do you know why this is being discussed?"* -- unbuilt entirely. This is
precisely the retention/interest measurement every external review has asked for.

- [x] **Fixed 2026-09-11.** `orchestration/pipeline.py` — calls the existing `critique_cold_hook`
      on the long-form opening inside `_run_review_block`, reusing the existing
      Haiku→Gemini-flash cascade as-is (no new agent identity). `PipelineAgents` gained a
      `worker` field (`run_pipeline.py` already built one, just hadn't threaded it through);
      new `_hook_context(plan, narration)` extracts the first beat's narration text and
      `visual_description` (same "first beat is the opening" reasoning as `pacing.py`'s
      fallback, not dependent on `narrative_beat="hook"` tags -- see BUG-2, still open, for
      why those tags aren't reliable). `critique_cold_hook()` gained optional
      `haiku_pass_id`/`gemini_pass_id` params (default `"C4s"`, unchanged for shorts) so
      long-form logs as `C4a`/`C4b` per `IMPLEMENTATION_PLAN.md`'s own naming -- cost-report
      label only
- [x] Unit tests: `tests/orchestration/test_pipeline.py` --
      `test_cold_hook_critic_receives_the_plans_title_and_first_beats_narration`,
      `test_cold_hook_uses_c4a_c4b_pass_ids_not_the_shorts_c4s_default`,
      `test_a_flagged_cold_hook_verdict_produces_a_real_issue_in_the_bundle`;
      `tests/review/test_cold_hook_critic.py::test_pass_ids_are_overridable_for_a_non_shorts_caller`;
      confirmed the cascade still short-circuits on a clean, confident Haiku verdict (existing
      tests use a clean default and never call the Gemini escalation)
- [x] `.venv/bin/python3 -m pytest -q` green (752 passed, up from 748)
- [ ] **Live-verify**: a real long-form run shows a `C4a`/`C4b` entry in `usage.jsonl`, and (on
      a source with a genuinely weak hook) a real `category="hook"` issue in
      `review_bundle.json` that a clean run doesn't produce -- not yet run
- [ ] New `review/cold_viewer_critic.py` (C4c) — mid-video cold viewer, sampled at a few
      deterministic points (reuse `review/visual_sample.py`'s evenly-spaced selection pattern
      rather than inventing another sampler): at this point in the video, would a viewer who
      just arrived know why this is being discussed, and want to keep watching? Still unbuilt.
- [ ] Wire C4c into `_run_review_block`; route its findings through the existing
      `CritiqueIssue` `category="pacing"`/`"cognitive_load"` values -- no schema change needed

### 8.3 — The §9 Learning gate was designed as a HARD gate and is entirely unbuilt

`IMPLEMENTATION_PLAN.md:669` specifies: *"Learning (structural part): no `central_insight`; a
major beat with no `learning_objective`; `viewer_can_now` not reachable from the beats'
objectives."* None of it exists. `verification/hard/structure.py`'s gates are word budget,
source units, source coverage, referential integrity, core roles, promise chain, CTA
placement -- no learning gate. Worse, `SourceBrief.novelty_statement` ("what this audience
doesn't already know") is collected by A1, explicitly asked for in its prompt, and then
**never read by anything downstream** -- it exists only as a field. `learning_objective` is
passed to A2b/H/candidate_finder but never validated as non-empty or meaningful. Shorts have
`check_central_insight_present`; long-form has no equivalent.

- [ ] `verification/hard/structure.py` — add `check_learning_gate(plan, source_brief)`:
      `central_insight` non-empty; every beat carrying an `archetype_role` has a non-empty
      `learning_objective`; `ending.viewer_can_now` has real word-overlap with at least one
      beat's `learning_objective` (reuse `check_promise_chain`'s existing word-overlap
      heuristic rather than writing a second one)
- [ ] Thread `source_brief` into `check_structure()`'s signature so `novelty_statement` is
      finally reachable by a check; flag a plan whose beats show no overlap with the stated
      novelty as a diagnostic (AMBER), not a hard failure -- novelty is a judgment call and a
      word-overlap heuristic shouldn't block a run on its own
- [ ] Unit tests mirroring `tests/verification/hard/test_structure.py`'s existing style
- [ ] **Live-verify**: confirm the gate fires on a real plan with a blank `learning_objective`,
      and does NOT fire on a genuinely well-formed plan (so it isn't inert or over-strict)

### 8.4 — Retention diagnostics grade the planner's own homework

`verification/diagnostics/retention.py::_is_state_change()` reads
`beat.new_information or beat.payoff or beat.visual_mode_change or beat.question_progress != "none"`
-- **every one of those is a boolean A2 sets about its own plan.** `check_driver_coverage`
only checks `forward_driver.strip()` is non-empty; it never checks the driver actually drives
anything. A model that dutifully fills in its fields passes by construction. Confirmed live:
run C returned GREEN on all three retention diagnostics (`driver_coverage`, `valley`,
`payoff_gap`) while the human review scored retention/pacing as that run's *weakest*
dimension. These currently measure schema compliance, not viewer experience.

- [ ] **See BUG-3 above for the exact code, the signature change it forces, and the fix.**
      `verification/diagnostics/retention.py` — derive state-change from the NARRATION against
      the ledger (did this beat's scenes actually introduce anything in `new_concepts`, or was
      it all `must_not_repeat` references?) instead of trusting the planner's booleans. The
      Phase 1 ledger makes this possible for the first time -- it wasn't available when these
      diagnostics were written
- [ ] Keep the self-reported fields as a SECONDARY signal (a beat claiming
      `new_information=True` whose scenes introduce zero `new_concepts` is itself a useful
      finding -- a planner/narration disagreement), not as the primary measurement
- [ ] Unit tests: a beat that declares `new_information=True` but whose scenes introduce no
      new concepts is flagged; a genuinely informative beat is not

### 8.5 — The revision loop does not converge, and can regress

Measured across both comparison runs (`final/status.json` logs):

| | run A (`gpt-4o`) | run C (`gpt-5.6-sol` tuned) |
|---|---|---|
| critique issues | 4 → 3 → 3 | 5 → 3 → 3 |
| hard failures | 2 → 2 → 1 | 2 → 2 → **3** |

Critique issues plateau and never clear. Run C rewrote **6 beats to apply 1 fix** and finished
with MORE hard failures than it started with -- the blast radius of a repair exceeds the
defect, so each cycle re-rolls grounding/quality dice across six beats. Contributing cause:
`orchestration/routing.py` only has `REPLAN` / `TARGETED_REWRITE` / `NONE`. The design's
dedicated repair paths -- **B3 precision edit** (*"verbose/repetitive only"*), **B4 humanize**
(*"voice RED or C5 major"*), **C6 entailment** -- have no modules at all, so a voice finding, a
verbosity finding and a factual finding all funnel into the same generic narration rewrite.

- [ ] `orchestration/pipeline.py` — before accepting a revision cycle's output, compare the new
      issue/hard-failure counts against the previous cycle's; if a rewrite made things strictly
      worse, keep the previous narration rather than the regression (the loop already retains
      a "best candidate" concept at exhaustion -- apply it per-cycle, not only at the end)
- [ ] `editing/targeted_rewrite.py` — narrow the default blast radius: rewrite only the scenes
      A3 actually named, never a whole beat's worth of scenes, unless the issue is explicitly
      beat-level
- [ ] Decide (and record) whether B3/B4/C6 are genuinely wanted or should be formally dropped
      from the design -- right now they are neither built nor removed, and `routing.py`'s
      missing branches mean C5's voice findings have nowhere to go except a content rewrite
      that isn't designed to fix voice. Either is defensible; the current in-between is not
- [ ] Unit tests: a regressing cycle is rejected; a genuinely improving cycle is accepted

### 8.6 — Story and visual layers never inform each other

`run_pipeline.py` runs `run_story_and_narration_loop()` to completion, and only then calls
`synthesize_and_repair_video_html()`. H's own `MAX_HTML_REPAIRS` loop can fix render issues
and C3 visual mismatches, but nothing the visual layer learns can ever feed back into the
story. Combined with Phase 6's finding that C1 never sees H's screen prose, the on-screen
half of the product is effectively outside the quality loop entirely.

- [ ] Scope this one deliberately before building: full bidirectional feedback is a large
      architectural change and may not be worth it. The cheaper 80% is probably Phase 6's
      "C1 also reviews H's screen prose" plus letting a CRITICAL C3 `visual_mismatch` finding
      raise a narration-level issue rather than only an H-repair -- evaluate that first and
      only go further if a real run shows it insufficient

---

## Final verification (Phases 1-4 done; Phases 5-8 still open)

- [x] `.venv/bin/python3 -m pytest -q` green throughout (checked after each phase; 744 passed
      as of the Phase 4 config fix, up from 689 before this work began)
- [x] Several full live runs via `run_pipeline.py` against `video-01-attention-coherent-story`
      (`runs/v17`, `runs/v18`, and the model-a/b/c comparison runs) -- see the detailed
      ERROR_LOG.md entries for what each confirmed: cross-beat repetition prevented,
      hedge-language bug gone, `pacing.hook_tension` wired and firing correctly, C1's new
      REPETITION check catching a real residual case, and a real gpt-5.6-sol config gap found
      and fixed.
- [ ] `BUILD_PLAN.md` updated with a "V2 — Narrative continuity" section pointing back here
      (not yet done -- do this once Phases 4 and 5 are resolved, so the summary covers the
      whole fix)
- [x] `ERROR_LOG.md` updated with the concrete before/after (the specific repeated phrase
      found vs. gone, hook-pacing seconds measured, the residual within-beat gap found) —
      not just "improved quality"
- [ ] Phase 4 (model-tier comparison) — still open, needs another live run + a real decision;
      not started yet
