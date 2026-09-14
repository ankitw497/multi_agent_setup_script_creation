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
| 1 | ~~Thread the ledger into B2~~ [x] done, live-verified | 8.1 | It's an outright bug silently undoing Phase 1 on every run; ~20 lines |
| 2 | ~~Wire `critique_cold_hook` into long-form~~ [x] done, live-verified | 8.2 | The critic already exists and is tested -- it's one call site |
| 3 | ~~Build the §9 Learning gate~~ [x] done, live-verified | 8.3 | Deterministic, cheap, a designed hard gate that was simply skipped |
| 4 | ~~Retention diagnostics read narration, not planner flags~~ [x] done, live-verified | 8.4 | Turns three always-GREEN diagnostics into real signal |
| 5 | ~~Reject regressing revision cycles + narrow B2's blast radius~~ [x] done, live-verified | 8.5 | Stops the loop making things worse; cheap guard |
| 6 | ~~C3 also reviews H's screen prose~~ [x] code+tests done, live-verify pending | 6 | A whole artifact currently has zero critique coverage |
| 7 | ~~Typed formula/numeric state validators~~ [x] code+tests done, live-verify pending | 6 | Fixes the confirmed raw-vs-scaled and dropped-`√d_k` class of bug |
| 8 | ~~A2b neighbor contract~~ [x] code+tests done, live-verify pending | 5 | Improves transitions; larger change than the above |
| 9 | ~~Airtime by narrative role, not source volume~~ [x] sub-item #1 done, #2/#3 still open | 7 | Real fix for section bloat, but touches allocation for every run |
| 10 | ~~Build C4c mid-video cold viewer~~ [x] code+tests done, live-verify pending | 8.2 | New module; do after the cheap retention wins land |

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

**[x] Decided and implemented (b).** `review/visual_critic.py`'s `TASK_PROMPT` now carries
REPETITION (against `must_not_repeat`/`running_example`) and OVERCLAIM checks
(`category="repetition"`/`"clarity"`, `layer="NARRATION"`, `repair_owner="html_author"`,
severity capped at major/minor -- never critical, so these never trigger an H repair loop on
their own, only get surfaced). `scene_payload()` gained optional `scene_function`,
`must_not_repeat`, `running_example` params; `html_pipeline.py` threads
`plan.scene_plan[i].scene_function`/`.must_not_repeat` and `plan.running_example` into each
call. **Coverage caveat, not fixed:** this only covers C3's *sampled* scenes
(`review/visual_sample.py::select_scenes_for_visual_audit`), not full coverage -- a real,
accepted limitation of reusing C3 rather than building a dedicated full-coverage pass.

**Bug found and fixed while implementing this:** `html_pipeline.py`'s
`synthesize_and_repair_video_html()` computed C3's full `visual_issues` list but only
extracted the `structural` (critical-severity) subset into `render_issues` -- every ordinary
`visual_mismatch`/major/minor finding, including the brand-new repetition/overclaim findings
this fix adds, was silently discarded: never returned in `HtmlSynthesisResult`, never written
anywhere. Fixed by adding `HtmlSynthesisResult.visual_critique_issues: list[CritiqueIssue]`
capturing the full list, now written to `render_report.json` by `reporting/emit_html.py`. See
ERROR_LOG.md for the live-verify entry (once run).

Tests: `tests/review/test_visual_critic.py` (payload/prompt), `tests/orchestration/
test_html_repair_loop.py` (two new tests forcing the real C3 code path via direct mocks of
`run_rendered_checks`/`capture_scene_screenshots`, since both are function-local imports --
every pre-existing test in this file blocks Playwright or opts out of rendered checks and so
never exercised this code path), `tests/reporting/test_emit_html.py`. Full suite: 786 passed.
Live-verify: `[ ]` not yet run against a real source.

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

- [x] `planning/story_planner.py` — pass beat N-1 and N+1 (when they exist) into each
      `expand_beat_scenes()` call in the existing per-beat loop
- [x] `planning/scene_expander.py` — accept `previous_beat`/`next_beat` (or `None`), add a
      compact `neighbor_contract` to the payload built from their EXISTING fields (`purpose`,
      `forward_driver`, `viewer_question_before`, `next_question`) -- no new schema. Also added
      `central_question` (already on `StoryStructure`, just never passed here)
- [x] `planning/scene_expander.py` — extended `TASK_PROMPT`: this beat must leave the next
      beat's own open question genuinely open -- do not resolve what a later beat is
      responsible for, even if it would be easy to add a sentence that does
- [x] `review/story_critic.py` — payload now includes `plan.scene_plan`
      (`scene_function`, `must_not_repeat`, `new_concepts`) and `plan.running_example`,
      alongside the existing `plan.beats`
- [x] `review/story_critic.py` — extended the REPETITION check: when a scene's own
      `scene_function=derivation` lists a `must_not_repeat` concept and narration re-explains
      it anyway, the prompt now instructs the critic to call it CONFIRMED (major+ severity),
      not just a suspected repetition; added a sibling running-example-fidelity check (new
      entities for the same locked illustration -> `category: repetition`)
- [x] **Confirmed real, not hypothetical** (2026-09-11, visual audit of `runs/video-01-attention-model-a-gpt4o/v01`):
      rendered the real HTML with Playwright and read the screenshots directly. `hook_s01`,
      `origin_s01`, `matrix_s01`, `heads_s01`, `recap_s01` all correctly use the locked example
      ("the cat couldn't climb the stairs because it was too tired"). `score_s02`/`score_s03`
      invent an entirely different one (`q(it) . k(dog)`, `k(park)`, `k(bone)`) -- isolated to
      those two adjacent scenes, not pervasive. `render_report.json` shows zero hard-check hits
      for this (only the known word-count band issue) -- confirms nothing today catches
      semantic example drift, only structural defects. See ERROR_LOG.md and Phase 6 below for
      the root cause this pointed to.
- [x] New check for running-example fidelity, now that the failure mode is confirmed real:
      built as a C1 judgment check (semantic equivalence isn't something a deterministic
      Python check can fully verify) -- see above, `running_example` is now given explicitly
      and the prompt asks the critic to flag any scene that introduces different named
      entities for the same underlying illustration
- [x] Unit tests: neighbor contract threading in `tests/planning/test_scene_expander.py`
      (isolated call) and `test_story_planner.py` (the real multi-beat loop via
      `SequencedStoryLead` -- first/last beat correctly get `None` neighbors);
      `tests/review/test_story_critic.py` (payload carries `scene_plan`/`running_example`;
      prompt-content tests for both new checks plus the no-hardcoded-topic-vocabulary guard)
- [x] `.venv/bin/python3 -m pytest -q` green (809 passed, up from 802)
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

- [x] **See BUG-5 above -- implemented 2026-09-14.** `html_synth/synthesizer.py` --
      `plan.running_example` threaded into both `synthesize_beat_visual()` and
      `synthesize_hero()`'s payloads; `TASK_PROMPT`/`HERO_TASK_PROMPT` instruct reusing its
      exact named objects/values, never inventing a different one for the same underlying
      idea. Mirrored into the H-repair path too (`editing/html_repair.py`'s
      `repair_beat_visual()`/`repair_hero()`), so a repair pass can't reintroduce the exact
      drift a first pass avoided.
- [x] `html_synth/synthesizer.py` -- `synthesize_beat_visual()` gained an optional `narration`
      param threading each scene's actual narrated text into its own payload entry
      (`narration_text`), so H illustrates what was actually narrated, not a stale
      pre-narration `visual_description` that may have drifted. Same threading mirrored into
      `repair_beat_visual()`.
- [x] **Implemented 2026-09-14.** `verification/diagnostics/entity_consistency.py` (new):
      `check_running_example_entity_consistency(plan, beat_visuals, claims) -> DiagnosticResult`
      -- scans H's generated `screen_prose`/`component_data` for quoted entities (this
      project's own observed convention for concrete examples: `'cat'`, `'stairs'`, `'it'`)
      matching neither the locked `running_example` nor the beat's own claim text; AMBER-banded
      (never a hard gate, exactly as originally scoped -- entity extraction from prose isn't
      reliable enough to promote further). Wired into `HtmlSynthesisResult.entity_consistency`,
      computed by both `synthesize_video_html()` and `synthesize_and_repair_video_html()`,
      written to `render_report.json` by `reporting/emit_html.py`.
- [x] Unit tests: `tests/html_synth/test_synthesizer.py`/`tests/editing/test_html_repair.py`
      (running_example/narration_text threading, both first-pass and repair paths, prompt-
      content tests); `tests/verification/diagnostics/test_entity_consistency.py` (8 tests:
      no-op/clean-reuse/invented-entity/claim-backed/no-quotes/component_data/label-words/
      never-RED); `tests/orchestration/test_html_repair_loop.py` and
      `tests/reporting/test_emit_html.py` (wiring + report serialization). Full suite: 882
      passed, 16 deselected -- **Phase 6 is now fully code-complete.**
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

- [x] Get H's generated `screen_prose`/component content under REPETITION/OVERCLAIM review --
      a real, previously fully-uncovered artifact. **See BUG-4 above**: folded into C3
      (`review/visual_critic.py`), which already runs post-H and already has an H-repair
      route. Code+tests done (full suite 786 passed); live-verify against a real source still
      `[ ]`. Coverage is limited to C3's sampled scenes, not every scene -- an accepted
      limitation, not a bug.
- [x] **Followed throughout.** Every Phase 6 fix folded into an EXISTING mechanism (C3's own
      prompt, the existing H-repair route, a new deterministic diagnostic) rather than adding a
      new critic pass or escalating a model tier -- no case has arisen yet where this guidance
      needed revisiting.
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

  **[x] Implemented.** `planning/models.py` gained `FormulaStage(stage_id, expression,
  values: dict[str,str])`; `StoryStructure.formula_stages: list[FormulaStage]` (empty for
  every source with no evolving expression -- registered once by A2, per its own new
  `TASK_PROMPT` instructions). `ScenePlan.formula_stage_id: str` tags which registered stage
  a scene's own equation/diagram represents, set by A2b via the existing `ViewerLedger`
  threading (`ViewerLedger.formula_stages`, no new LLM call). New
  `verification/hard/formula_consistency.py::check_formula_stage_consistency(plan,
  beat_visuals)`: walks `scene_plan` in order, tracks the most-advanced stage reached, and
  flags a `formula_stage_regression` `RenderIssue` (scene_id-carrying, so it drives the
  existing H-repair route automatically) whenever a scene's actual rendered content
  (`screen_prose` + every string in `component_data`, whitespace-normalized) doesn't contain
  the expected stage's exact `expression`. Wired into `synthesize_and_repair_video_html`'s
  static-check loop.

- [x] **Numeric state tracking** (item #9), folded into the SAME `FormulaStage` object rather
      than a separate sibling model -- each stage carries its own `values: dict[str, str]`
      (its own worked numbers), so a stage can only "own" numbers it was actually registered
      with. `check_formula_stage_consistency` also flags `formula_stage_values_missing` when a
      scene's content lacks its own stage's registered numbers -- directly catches the
      raw-vs-scaled confusion (a later stage claiming numbers that never actually changed).
      `narration/generator.py`'s prompt was NOT separately extended -- the check operates on
      H's rendered content (`beat_visuals`/screen prose + component_data), which is where both
      confirmed bugs actually lived (B7/B8's on-screen cards), not spoken narration.
- [x] Unit tests: `tests/verification/hard/test_formula_consistency.py` (no-op empty case,
      clean progression not flagged, regression caught, whitespace-insensitive matching,
      component_data matching, missing-values detection, unregistered stage_id ignored not a
      crash); `tests/planning/test_scene_expander.py`/`test_story_planner.py` (payload
      threading, prompt instructs registering stages, no-hardcoded-topic-vocabulary guard);
      `tests/orchestration/test_html_repair_loop.py` (forces the check through the real
      repair loop end to end, not just the isolated check function).
      **Not done from the original scope**: the entity-overlap diagnostic and C1-screen-prose
      payload items below (`viewer_can_now`/entity-overlap heuristic, `synthesizer.py`
      threading running_example+narration text) remain open -- see the unchecked items below.
- [x] `.venv/bin/python3 -m pytest -q` green (802 passed, 16 deselected)
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

- [x] **Implemented 2026-09-11.** `planning/models.py` gained `RetentionDeadline
      (archetype_role, max_seconds)`; `StoryStructure.retention_deadlines: list[RetentionDeadline]`
      (empty by default, A2's own `TASK_PROMPT` instructs it to only declare one where pacing
      genuinely matters). `planning/beat_word_budget.py::allocate_beat_word_budgets()` gained
      an optional `retention_deadlines` param -- caps the beat matching a declared
      `archetype_role` so its cumulative runtime never exceeds `max_seconds` (never below
      `MIN_BEAT_WORDS`), redistributing the reclaimed words proportionally across every other
      beat so the total still sums to exactly the target. Allocation stays deterministic
      Python throughout, per this module's own ERR-010/ERR-023 rationale -- no LLM involved.
- [x] **Implemented.** `verification/diagnostics/pacing.py::check_beat_airtime_outliers(plan,
      claims)` -- new AMBER-banded diagnostic (never a hard gate, matching this session's
      pattern for new soft checks) flagging a beat whose allocated words-per-claim is a
      >2x/<0.5x outlier against the plan's own median, using each beat's own claim density as
      the yardstick rather than a fixed word-count band. Wired into `pipeline.py`'s existing
      diagnostics list.

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
- [x] Unit tests for sub-item #1 (`test_beat_word_budget.py`: deadline caps and redistributes,
      no-op with no deadlines/no matching role/already-satisfied, floor never breached;
      `test_pacing.py`: outlier flagged, even allocation clean, zero-claim beats excluded, too
      few beats is GREEN not a crash; `test_story_planner.py`: prompt-content test, a spy test
      confirming `retention_deadlines` actually reaches the allocator). **Sub-items #2
      (preview completeness) and #3 (mechanism scope) remain fully unimplemented** -- not
      started this pass; scoped out to keep this change reviewable, tracked below as still open.
- [x] `.venv/bin/python3 -m pytest -q` green (820 passed, up from 809) -- for sub-item #1 only
- [ ] **Live-verify** (sub-item #1 only): re-run against the same real source; confirm
      per-section outlier detection fires on a deliberately-bloated section -- not yet run
- [ ] Sub-item #2 (preview completeness) -- not started: `planning/scene_expander.py` extend
      `scene_function=preview`'s guidance to be explicit about which exact values (if any) it
      reveals; `narration/generator.py` require derivation scenes to frame an already-previewed
      exact value as confirming/explaining, never as a fresh reveal
- [ ] Sub-item #3 (mechanism scope) -- not started: `planning/models.py` add a lightweight
      `mechanism_scope` concept to `ViewerLedger` (or a sibling), e.g.
      `{"causal_mask_required": bool}`, set once a beat like B10 establishes it;
      `narration/generator.py`/`review/story_critic.py` flag a recap/summary stating a scoped
      mechanism as if unconditional, using the ledger's own recorded scope
- [ ] Unit tests + live-verify for sub-items #2 and #3, once built

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
- [x] **Live-verify** (`video-01-attention-coldhook-verify/runs/v01`, 2026-09-11): `C4a`
      appears exactly once per review cycle (4/4, including through a full replan) --
      `lane=subscription`, `model=claude-haiku-4-5-20251001`, `billed_microusd=0` each time, as
      designed. No `C4b` escalation across any cycle (a clean, confident verdict every time)
      and zero `category="hook"` issues in `review_bundle.json` -- consistent with this
      source's real hook (the "cat couldn't climb the stairs" pronoun example) being genuinely
      strong, not evidence the check is inert. Escalation path (C4b firing on a real weak hook)
      still not observed live -- would need a source with an actually weak opening to trigger
      it. See ERROR_LOG.md.
- [x] **Built 2026-09-11.** `review/cold_viewer_critic.py` (C4c) — same Haiku->Gemini-flash
      cascade as C4s/C4a. `select_cold_viewer_checkpoints(plan)` samples a few evenly-spaced
      scenes from the MIDDLE beats only (excludes first beat -- C4a/C4b's job -- and last beat
      -- a resolved-payoff context), reusing C3's own sampler (`visual_sample.py`) with
      `sample_fraction=1.0` so `max_images` alone bounds it (the sampler's own 20%-of-total
      default would round to zero checkpoints for a short video's few middle scenes). Each
      checkpoint judged independently on just the title + that one narration snippet.
- [x] Wired C4c into `_run_review_block`; findings route through the existing `CritiqueIssue`
      `category="pacing"`/`"cognitive_load"` values -- no schema change needed.
- [x] Unit tests: `tests/review/test_cold_viewer_critic.py` (checkpoint selection, full
      cascade behavior, category mapping); `tests/orchestration/test_pipeline.py` (C4c fires
      with the real title, a flagged verdict produces a real bundle issue). Fixed a fixture gap
      this surfaced (worker FakeAgent needed a `ColdViewerVerdict` queue too).
- [x] `.venv/bin/python3 -m pytest -q` green (835 passed, up from 820)
- [ ] **Live-verify**: not yet run -- confirm `C4c` appears in a real run's `usage.jsonl`
      against real middle-beat scenes, and (ideally) confirm an escalation to Gemini on a
      genuinely disorienting mid-video section

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

- [x] **Fixed 2026-09-11.** `verification/hard/structure.py` — added
      `check_learning_gate(plan, source_brief)`: `central_insight` non-empty; every beat
      carrying an `archetype_role` has a non-empty `learning_objective`; `ending.viewer_can_now`
      has real word-overlap with at least one beat's `learning_objective` (reused
      `check_promise_chain`'s existing word-overlap heuristic rather than writing a second one).
      `check_structure()` gained an optional `source_brief` param (default `None` skips the
      gate -- backward compatible); both real call sites in `orchestration/pipeline.py` pass it.
- [x] `verification/diagnostics/retention.py::check_novelty_coverage(plan, source_brief)` --
      the soft part: does any beat's `learning_objective` actually reflect the stated
      `novelty_statement`, banded AMBER (never a hard failure), wired into
      `_run_review_block`'s existing diagnostics list.
- [x] Unit tests: `tests/verification/hard/test_structure.py` (9 new tests covering
      `check_learning_gate` directly and `check_structure`'s opt-in/opt-out behavior);
      `tests/verification/diagnostics/test_retention.py` (4 new tests for
      `check_novelty_coverage`)
- [x] Fixed a real fixture-realism gap this surfaced: `tests/orchestration/test_pipeline.py`'s
      shared `make_plan()`/`make_structure()` had no beat `learning_objective` and a
      non-overlapping `viewer_can_now` ("do x") -- the new gate correctly flagged every test
      using them. Updated to realistic, overlapping values rather than weakening the check.
- [x] `.venv/bin/python3 -m pytest -q` green (766 passed, up from 753)
- [x] **Live-verify** (`video-01-attention-batch2-verify/runs/v01`, 2026-09-11): a real run
      where every beat had a real `learning_objective` produced NO `no_central_insight`/
      `beat_missing_learning_objective`/`viewer_can_now_unreachable` hard failure -- confirms
      the gate is not over-strict/inert-in-the-wrong-direction on a genuinely well-formed plan.
      `retention.novelty_coverage` (the soft half) fired **GREEN** with real evidence:
      `novelty_statement='...how the attention mechanism avoids saturation issues in softmax by
      scaling dot product scores...'` matched against beat B4's `learning_objective`
      (`'Understand the necessity of scaling in scoring.'`) -- confirms it actually reads and
      compares real content, not a stub that always passes. The blank-`learning_objective`
      firing case is covered by the 9 unit tests in `test_structure.py` (harder to force live
      without deliberately corrupting a real A2 output).

### 8.4 — Retention diagnostics grade the planner's own homework

`verification/diagnostics/retention.py::_is_state_change()` reads
`beat.new_information or beat.payoff or beat.visual_mode_change or beat.question_progress != "none"`
-- **every one of those is a boolean A2 sets about its own plan.** `check_driver_coverage`
only checks `forward_driver.strip()` is non-empty; it never checks the driver actually drives
anything. A model that dutifully fills in its fields passes by construction. Confirmed live:
run C returned GREEN on all three retention diagnostics (`driver_coverage`, `valley`,
`payoff_gap`) while the human review scored retention/pacing as that run's *weakest*
dimension. These currently measure schema compliance, not viewer experience.

- [x] **Fixed 2026-09-11 (see BUG-3 above for the original shape).**
      `verification/diagnostics/retention.py::_introduces_new_concept(plan, beat)` is now the
      primary state-change signal: did any of the beat's own scenes carry a real
      `ScenePlan.new_concepts` entry (Phase 1's ledger, populated per-scene during A2b) --
      instead of trusting `beat.new_information`. `payoff`/`visual_mode_change`/
      `question_progress` are unchanged (nothing scene-level captures those yet). Falls back to
      the old boolean only when a beat has zero scenes at all (a malformed plan).
- [x] Kept the self-reported field as a SECONDARY signal:
      `check_new_information_disagreement(plan)` turns a beat claiming `new_information=True`
      with zero `new_concepts` into its own AMBER diagnostic finding, wired into
      `check_retention()`'s aggregate.
- [x] Unit tests: `tests/verification/diagnostics/test_retention.py` (7 new tests) -- a beat
      declaring `new_information=True` with no `new_concepts` is not treated as a state change
      (and is separately flagged as a disagreement); a beat with real `new_concepts` counts
      even if the boolean is `False`; a beat with zero scenes falls back to the boolean and is
      never flagged as a disagreement.
- [x] Fixed a real fixture-realism gap this surfaced across TWO shared fixtures
      (`tests/orchestration/test_pipeline.py`'s `make_plan()` and `make_good_expansions()`):
      beats claiming `new_information=True` had zero scenes with any `new_concepts` in either
      fixture. Updated to carry a real entry consistent with the claim, not weakening the check.
- [x] `.venv/bin/python3 -m pytest -q` green (773 passed, up from 766)
- [x] **Live-verify** (`video-01-attention-batch2-verify/runs/v01`, 2026-09-11): real
      disagreement found and surfaced -- `retention.new_information_disagreement` fired
      **AMBER** with evidence `"beat(s) claim new_information=True but no scene lists a
      new_concepts entry: ['B9']"`. Confirms the secondary self-report signal is live and not
      silently inert, exactly the "sometimes disagree with the planner's own booleans" case
      this item asked to confirm.

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

- [x] **Fixed 2026-09-11.** `orchestration/pipeline.py` — before accepting a revision cycle's
      output, compares the new hard-failure/issue counts (`_badness()`, hard failures dominate
      the comparison) against the pre-rewrite baseline; if a `TARGETED_REWRITE` cycle made
      things strictly worse, reverts `narration`/`bundle` to the pre-rewrite state before the
      next decision is made, rather than letting the regression become the accepted state.
      Deliberately scoped to one rewrite cycle at a time, not across a `REPLAN` -- a replan
      starts the plan over for a real structural reason, so "reverting" to the pre-replan
      state would just reintroduce the defect that motivated it.
- [x] **Fixed.** `editing/targeted_rewrite.py` — added a genuinely scene-scoped tool,
      `RewriteScene`/`RevisionPlan.rewrite_scenes` (`editing/models.py`), alongside the
      existing whole-beat `RewriteBeat`. `editing/revision_planner.py`'s `TASK_PROMPT` now
      instructs A3 to choose the NARROWEST tool that covers a finding -- `rewrite_scenes` is
      the default for a critique naming specific `scene_ids` (repetition, pacing, a bad
      transition), `rewrite_beats` reserved for a problem that genuinely spans every scene in
      that beat. `orchestration/routing.py::decide_action` and
      `targeted_rewrite.py::_touched_scene_intents` both updated to recognize it.
- [x] **Decision recorded**: B3 (precision editor) and B4 (humanize) are dropped as separate
      passes, not built later. The newly-added `rewrite_scenes` tool already gives A3 a
      properly-scoped, generic lever for ANY narrative-level finding -- including a C5 voice/
      style finding -- routed through the same B2 pass, not a specialized one; a dedicated
      B3/B4 module would duplicate that machinery for no clear benefit. **C6 (entailment
      check)** is kept as a real, still-open idea (verifying a `technical_fixes`-driven
      rewrite didn't silently change a claim's meaning) -- genuinely useful as a narrow safety
      gate, but not blocking anything else here; tracked as a future addition, not built now.
- [x] Unit tests: `tests/orchestration/test_pipeline.py` --
      `test_a_regressing_targeted_rewrite_is_reverted_to_the_pre_rewrite_state` (cycle 1: 1
      critical issue -> rewrite #1 makes it 2, worse, reverted -> rewrite #2 clears it, kept);
      `test_an_improving_targeted_rewrite_is_accepted_not_reverted`. `tests/orchestration/
      test_routing.py`, `tests/editing/test_targeted_rewrite.py` (3 new tests for
      `rewrite_scenes`' narrower blast radius), `tests/editing/test_revision_planner.py`
      (prompt-content test for the narrowest-tool guidance).
- [x] `.venv/bin/python3 -m pytest -q` green (780 passed, up from 773)
- [x] **Live-verify** (`video-01-attention-batch2-verify/runs/v01`, 2026-09-11), `final/
      status.json`'s own log, both confirmed on the SAME real source used to originally
      diagnose the "6 beats rewritten for 1 fix" pattern:
      - **`rewrite_scenes` preferred**: `"targeted rewrite #1: 0 beat(s), 8 scene(s), 1
        fix(es), 0 delete/compress"` and `"targeted rewrite #2: 0 beat(s), 6 scene(s), 0
        fix(es), 0 delete/compress"` -- zero whole-beat rewrites across both cycles, exactly
        the narrower blast radius this fix was for.
      - **Revert-on-regression fired for real**: `"targeted rewrite #2 made things worse (6
        hard failures, 4 issues vs 4/3 before) -- reverting"` -- the exact mechanism (not a
        hypothetical) caught a real regression mid-run and reverted it before the next A3
        decision, then correctly reported `"revision budget exhausted -> emit best
        candidate"` rather than shipping the worse state.

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

## Phase 9 — Move CM/C5 off Gemini flash to a Sonnet subscription agent (proposed, deferred)

**Status: not started -- decision deliberately deferred by the user (2026-09-12), tracked here
so it isn't lost, not yet approved for implementation.**

**Motivation:** user asked whether the flash-tier Gemini agent could be replaced by a Sonnet
(subscription-lane, free) agent, after a live-verification session burned through the
project's Gemini prepayment credits (`ERROR_LOG.md`'s cost tally: $5.20 across 203 Gemini
calls in one session, dominated by the strong tier -- C1 $1.64, C2b $1.32, C2a $1.16 -- but
every Gemini call, flash included, draws from the same prepayment balance).

**What "flash" actually covers** -- one Gemini-flash `Agent` (`gemini-3.6-flash`), constructed
once in `run_pipeline.py` and reused across three distinct roles:
1. **CM** (claim mapper) + **C5** (style critic) -- via `PipelineAgents.cm_agent`
2. **C3** (visual critic) -- passed directly as `visual_auditor` to `synthesize_and_repair_video_html`
3. **Shorts' cold-hook escalation** (C4s's second tier) -- passed directly as `review_agent` in the shorts pipeline

**Proposed scope, if/when approved**: add a new `agents/cm_agent.py` (Sonnet, subscription
lane) and swap it in for role 1 ONLY (CM + C5). Roles 2 and 3 must stay on Gemini regardless:
- **C3 is a hard technical block, not a preference**: the Claude CLI subscription backend has
  no multimodal support at all -- `agents/base.py::Agent.run()` already raises if a
  subscription-lane agent is given images. It cannot run on Sonnet.
- **Shorts' C4s escalation is a design choice, not a cost optimization**: its whole point (per
  `review/cold_hook_critic.py`'s own docstring) is a genuinely independent, cross-family
  second opinion after Haiku. Moving it to Sonnet would make both cascade tiers the same model
  family, defeating the escalation's purpose entirely.

**Trade-off to weigh before approving the CM/C5 swap itself:**
- CM is a safe swap -- its independence comes from never being shown the writer's own
  `sentence_type` (a payload-level separation per its own docstring: "never let the producer
  define its own validation boundary"), unrelated to which model family reads it.
- C5 is a softer concern -- its entire job is detecting narration that "sounds model-written,"
  and a Sonnet judge reviewing Sonnet-written narration is a real (if soft) self-family blind
  spot. Not a blocker, just a real cost of accepting a free check over a paid, more
  independent one.

**Mechanically, if approved**: new `agents/cm_agent.py::make_cm_agent(client)` (Sonnet,
subscription); add `"cm_agent"` to `llm/usage.py`'s `VALID_AGENTS` (currently missing --
needed regardless, since CM/C5 calls are today mislabeled `agent="review_lead"` in cost
reports, a pre-existing open item noted elsewhere in `ERROR_LOG.md`); wire it into
`run_pipeline.py` in place of `review_lead_flash` for the `PipelineAgents.cm_agent` field
only; leave the other two call sites (`synthesize_and_repair_video_html`'s `visual_auditor`,
shorts' `review_agent`) untouched; new/updated tests mirroring `tests/agents/test_factories.py`'s
existing pattern.

- [ ] Decision: approve, reject, or approve with modified scope
- [ ] If approved: implement `agents/cm_agent.py`, wire it in, update tests
- [ ] `.venv/bin/python3 -m pytest -q` green
- [ ] Live-verify: confirm CM/C5 calls now show `agent="cm_agent"`, `lane="subscription"` in a
      real run's `usage.jsonl`, and that no Gemini spend occurs for those two passes

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
      (not yet done -- do this once Phases 5-8 are resolved, so the summary covers the whole
      fix, not just the first half)
- [x] `ERROR_LOG.md` updated with the concrete before/after (the specific repeated phrase
      found vs. gone, hook-pacing seconds measured, the residual within-beat gap found) —
      not just "improved quality"

---

## Open ERROR_LOG.md findings not yet scheduled into a phase

Carried over from `ERROR_LOG.md` so they aren't lost between sessions. All predate most of
this file's own phases (2026-09-10) and are genuine open design questions, not live blockers.

- [ ] **ERR-022 / ERR-025** (same finding, confirmed live 3x): C1's `critical`/`archetype`
      critiques unconditionally force a replan, with no mechanism to weigh how well-supported
      either side's evidence actually is. Three live runs showed C1 disputing a `build`
      resolution that every other signal agreed was correct, and the forced replan made things
      worse each time. **Partially mitigated**: `orchestration/pipeline.py::_legitimately_dismissed_issue_ids`
      (ERR-026) lets A3 dismiss such a critique only when A2 already rejected that exact
      alternative archetype in its own `rejected_archetypes` -- a bounded, code-enforced
      override, not a general fix for the asymmetry. Real open design questions, not yet
      decided: should A2 be allowed to push back with its own `source_evidence`? should a
      critical archetype issue require a second independent opinion before forcing a replan?
- [ ] **ERR-027** (partially addressed): two residual gaps found while fixing the stale-claims
      noise that was the real dominant blocker at the time (now fixed). (a) The validation
      harness script doesn't persist each revision round's intermediate review bundle, so some
      historical dismissal decisions can't be fully audited after the fact -- an observability
      gap in the harness, not the pipeline itself. (b) `_legitimately_dismissed_issue_ids`
      verifies an alternative archetype is ALREADY a key in `rejected_archetypes`, but never
      judges whether A2's original rejection REASON was itself sound -- a confidently-wrong A2
      could still get a bad dismissal legitimized this way. Not yet built: any check that
      evaluates rejection-reason quality itself (likely a C1-style judgment call, not a
      deterministic one).
- [ ] **ERR-023 status correction**: `ERROR_LOG.md` still labels this "open," but it was
      actually fixed by the very next entry, ERR-024 (A2 split into structure + per-beat scene
      expansion), live-verified twice. Tracked here only so a future pass fixes the stale label
      in `ERROR_LOG.md` itself, not because the underlying issue is still open.
