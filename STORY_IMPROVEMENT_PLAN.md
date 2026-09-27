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
| 9 | ~~Airtime by narrative role, not source volume~~ [x] all 3 sub-items code-complete, live-verify pending | 7 | Real fix for section bloat, but touches allocation for every run |
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
- [x] **Original decision (2026-09-11): do NOT promote `gpt-5.6-sol` to the default
      `openai_story_strong`.** The config fix was worth keeping (it now works instead of
      catastrophically failing), but on this real comparison it produced a structurally less
      coherent plan for 65% more cost -- the opposite of what the feedback doc predicted.
      Matched the plan's own explicit criterion: promote only if the comparison shows a real
      improvement; it showed the opposite. See ERROR_LOG.md for full detail.

  **Superseded 2026-09-16 (explicit user decision):** `story_lead`'s "strong" tier now
  defaults to `openai_story_strong_gpt56` (gpt-5.6-sol) anyway (`agents/story_lead.py`,
  `config/models.yaml`) -- the user was shown this section's own finding (worse coherence,
  65% higher cost) directly before deciding, and chose to proceed. Not a re-evaluation with
  a different `reasoning_effort` or prompt change (the condition this entry originally set
  for reconsidering) -- a direct override of the documented recommendation. `gpt-4o`
  (`openai_story_strong`) remains fully configured for rollback via
  `--story-lead-alias openai_story_strong`. No new live run has confirmed how this plays out
  under today's fuller pipeline (Phases 1-3's ledger machinery, etc.) beyond what's already
  documented above from the original comparison.
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
- [x] **Sub-item #2 (preview completeness) -- implemented 2026-09-14.** Pure prompt fix,
      reusing existing fields: `planning/scene_expander.py` (A2b) instructs naming an EXACT
      value a preview reveals as its own `new_concepts` entry, not just the general concept;
      `narration/generator.py` (B1) instructs framing a `derivation` scene that reaches an
      already-previewed exact value as CONFIRMING it, never as a fresh discovery.
- [x] **Sub-item #3 (mechanism scope) -- implemented.** `ViewerLedger.mechanism_scope:
      dict[str, bool]` accumulates beat-to-beat like `viewer_knows` (no new LLM call --
      `scene_expander.py`'s existing per-beat loop); `ScenePlan.mechanism_scope` stores the
      scope AS OF that scene (a per-scene snapshot, set scene-by-scene). A2b's `TASK_PROMPT`
      lets it record a scope-establishing scene's own `mechanism_scope_updates`.
      `narration/generator.py` requires a recap to honor the recorded condition rather than
      state it as unconditional. `review/story_critic.py`'s OVERCLAIM check (C1 already
      receives `scene_plan` from Phase 5) treats a scene contradicting its own recorded
      `mechanism_scope` as a CONFIRMED overclaim, not a suspected one.
- [x] Unit tests for sub-items #2/#3: `tests/planning/test_scene_expander.py` (payload
      threading, accumulation, per-scene snapshot, carries forward from an earlier beat
      unchanged, prompt-content); `tests/narration/test_generator.py` and
      `tests/review/test_story_critic.py` (payload threading, prompt-content). Full suite:
      893 passed, 16 deselected -- **Phase 7 is now fully code-complete** (sub-item #1's own
      live-verify below is still the only open item).
- [ ] Live-verify for sub-items #2 and #3 (sub-item #1's own live-verify tracked above)

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

- [x] **Scoped and implemented 2026-09-14, the cheap-80% version.** Full bidirectional
      feedback (regenerating narration after H/C3 run) was deliberately NOT built -- a real
      architectural change, not attempted without evidence it's needed. Instead: Phase 6's "C1
      reviews H's screen prose" (already done) plus a new
      `orchestration/html_pipeline.py::_visual_critique_to_narration_level_issues()`: a
      CRITICAL C3 finding whose own `repair_owner` is `narration_lead` (a genuine
      narration-vs-visual factual CONTRADICTION, not a rendering break -- H-repair can't fix
      wrong facts) now routes straight to the blocking `render_issues` list instead of being
      silently absorbed into `visual_critique_issues` with no consequence. Also found and fixed
      the actual blocker to this ever firing: `review/visual_critic.py`'s own prompt explicitly
      forbade `severity: critical` with `repair_owner: narration_lead` -- added an explicit
      carve-out for a genuine contradiction (a different example, a disagreeing number, a
      mechanism shown working differently than claimed), distinct from an ordinary
      suboptimal-choice finding (still major/minor, unaffected).
- [x] Unit tests: `tests/orchestration/test_html_repair_loop.py` (a critical narration-owned
      finding blocks promotion and is never sent to repair; an ordinary major one is
      unaffected); `tests/review/test_visual_critic.py` (prompt-content test for the carve-out).
      Full suite: 907 passed, 16 deselected -- **Phases 6, 7, and 8 are all now fully
      code-complete.**
- [ ] Live-verify: confirm a real run's C3 pass can actually produce a critical+narration_lead
      finding (not yet observed live) and that it correctly blocks promotion when it does

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

## External review: `multi_agent_pipeline_deep_improvement_plan.md` (2026-09-15)

A user-supplied deep-review document was checked section-by-section against the actual
codebase (not just read at face value) before turning it into phases below. Verdict: **mostly
agree** — several of its "current weakness" claims are independently confirmed by reading the
real implementation, not just inferred from prompts, and two of them (CM's silent
fail-open and B1's unplanned CTA clause) are genuine bugs, not stylistic preferences. A few
proposals are already implemented and the document doesn't know it; a couple are pushed back
on below.

**Confirmed real, previously unknown (net-new findings from this review):**
- `review/claim_mapper.py::map_claims()` has no coverage invariant. When CM's structured
  output omits a sentence (or the whole call fails to return every entry), the missing entry
  silently falls through to `if m is None: new_sentences.append(sentence)` — the sentence
  keeps `grounding_required=False` (the pydantic default), which is indistinguishable from CM
  having actually checked it and found nothing factual. This is exactly the doc's §4 failure
  mode, verified in code, not hypothesized.
- `review/grounding_verifier.py` (C2b) returns only a sparse `CritiqueIssue[]` — no positive
  per-sentence record exists anywhere that C2b actually looked at sentence N. The doc's §5
  complaint is accurate.
- `verification/hard/structure.py::check_source_coverage()` is a **hard failure** (not a
  diagnostic) if any source unit is never referenced by any beat — confirming the doc's §8
  claim that "every source unit must appear in a beat" is enforced, not just suggested.
- `narration/generator.py`'s own `TASK_PROMPT` literally says a scene becomes the CTA scene
  "if this scene ... is the final scene" — confirming the doc's §25 claim that the narrator,
  not the planner, can decide to add a CTA.
- `html_synth/synthesizer.py::synthesize_beat_visual()`/`synthesize_hero()` run under the
  `narration_lead` identity, whose `BASE_SYSTEM_PROMPT` (`agents/narration_lead.py`) says
  *"You turn a validated story plan into natural spoken narration... Write for listening"* —
  directly contradicted by H's own `TASK_PROMPT`: *"NOT spoken narration."* Confirming the
  doc's §21 finding.
- `orchestration/pipeline.py::_badness()` = `(len(hard_failures), len(issues))`. Since
  `review/aggregator.py` already promotes every `severity="critical"` issue into
  `hard_failures` too, the doc's own worked example (1 critical → 0 critical + 2 minor) is
  *already* handled correctly by the existing tuple (hard_failures dominates first). The doc's
  §26 complaint is only partially right: the gap is real but narrower than claimed — it only
  shows up comparing major-vs-minor severity when hard_failures is tied on both sides (e.g. 3
  major → 0 major + 5 minor currently reads as "worse" under raw issue counts). Scoped down
  accordingly in Phase 13 below.
- The doc's §13 concern (`rejected_archetypes` shielding A2 from a legitimate C1 disagreement)
  is not new — it's the exact open question already tracked above as **ERR-022/025**
  ("should a critical archetype issue require a second independent opinion... should A2 be
  allowed to push back with its own source_evidence?"). The external doc doesn't propose
  anything ERR-022/025 hadn't already flagged as unresolved, but its framing ("different
  interpretation of the same evidence is a valid disagreement") is a useful sharpening of it.

**Already implemented — the doc doesn't know this codebase's current state:**
- Most of its §6 `Claim` field wishlist already exists (`facts/models.py`): `scope`,
  `importance`, `provenance_status`, `verification_status`, `evidence`,
  `derived_from_claim_ids`, `inference_kind` are all there today. Only `required_qualifiers`
  is genuinely missing (Phase 10 below).
- Its §35 model-routing table is mostly already `config/models.yaml`'s current state: A3
  already escalates `openai_story_mini → openai_story_strong`; C3/C4b/C5 already escalate
  `gemini_review_flash → gemini_review_strong`; A2 on `gpt-5.6-sol` is already wired
  (`openai_story_strong_gpt56`) and deliberately not yet the default, matching the doc's own
  "not adopted blind" framing (this is literally Phase 4 above, already done).
- Cross-scene repetition (§14's "filler to hit word budget" concern) already has real
  machinery fighting it (`ViewerLedger`, `scene_function`, `must_not_repeat`, Phases 1/5-7) —
  the doc's specific ask (a `needs_rebudget` escape valve + deterministic reallocation instead
  of prompt-only pressure) is still a real, un-built gap, kept in Phase 12.

**Pushed back on / de-scoped:**
- **§12 (evidence-scored archetype table replacing first-match order).** Not scheduled. It
  swaps one LLM judgment (an ordinal walk) for another (a scored table) — both are still
  "the same model decides," and a numeric score table is *more* prone to run-to-run noise than
  an auditable ordinal check that already requires a real, specific rejection reason for every
  archetype not chosen (checked independently by C1 against the raw `source_units`). Better
  ROI: strengthen the existing rejection-reason requirement (Phase 13's archetype-dismissal
  fix) than replace the classifier shape.
- **§13, taken literally (remove the `rejected_archetypes` shield).** Disagree with removing
  it outright — it exists specifically because A2 and A3 share a model family
  (`story_lead`), so an ungated "A3 may always overrule C1's dismissal" would let the same
  family rubber-stamp itself, which is precisely what Appendix G's "producer != validator"
  principle (cited in this codebase's own docstrings) exists to prevent. Phase 13 tightens the
  guard's precision instead of deleting it.
- **§19, Option B (drop Haiku from cold-hook screening, always use Gemini Flash).** Keep the
  Haiku-first cascade. The two-tier cheap→escalate pattern is proven and reused elsewhere in
  this codebase (C3, C4b) specifically for cost control; the actual fix needed is Option A —
  updating the documented Haiku rule to acknowledge sampled subjective screening — which is a
  doc/comment-level fix, folded into Phase 13, not a code change.
- **§22, taken literally (a full `VideoScreen`/`ReferencePage` two-contract schema split).**
  Downgraded to a lighter prompt/slot-weighting pass first (Phase 14). This session's own
  `ERR-056` entry in `ERROR_LOG.md` already found that a *prompt-only* fix restored healthy
  diagram/math-block usage, and a later run showed good component diversity even before that
  fix's causal story was fully confirmed — meaning the magnitude of the "too text-heavy"
  problem this doc assumes is currently uncertain, not settled. Re-measure on a live run
  before committing to a schema rewrite that touches `synthesizer.py`, `html_repair.py`,
  `assembler.py`, `component_library.py`, and every H/H-repair test.
- The doc's own §28 flow diagram routes findings to `A3 / B3 / B2`, but `B3` is never defined
  anywhere else in the document. Not building anything for it — flagged here as a gap in the
  source document, not a missed requirement.

Phases 10-16 below cover everything from the agree list, sequenced by dependency (grounding
correctness first, since every other review pass downstream trusts the claim registry; scope
contracts second, since the doc's own real A/B finding — GPT-5.6 Sol's title narrowing — traces
directly to a missing contract; narration/CTA/review-split cleanups third; visual work fourth,
after re-measuring; benchmarking last, since it should run against the corrected pipeline, not
before).

---

## Phase 10 — Grounding pipeline: fail-closed coverage + dense verdicts (P0)

**Status: implemented and unit-tested (2026-09-15); live-verify deliberately deferred (see
note below) — to be done as part of the Phase 10-13 combined e2e run, per the user's
"minimize API costs" instruction for this work.**

**Motivation:** the two confirmed bugs above (`claim_mapper.py`'s silent `None` fallback,
`grounding_verifier.py`'s sparse-issues-only output) mean a truncated or incomplete CM/C2b
response is currently indistinguishable from "checked and clean." Both generated scripts in
the source doc's own A/B comparison showed factual sentences with `grounding_required=false`
appearing *later* in the script than earlier — exactly the shape a truncation/coverage bug
produces, and it reproduced across two different Story Lead models, which rules out a
Story-Lead-specific cause (the doc's own reasoning here is sound and independently checks out).

**Changes:**
- `narration/models.py::SentenceNarration`: add a stable `sentence_id: str` (e.g.
  `"{scene_id}:{index}"`), computed once when narration is produced, not re-derived downstream.
- `review/claim_mapper.py`: key `MappedSentence` by `sentence_id`. After the call, compute
  `missing = input_ids - output_ids`; if non-empty, **fail closed** (raise, matching this
  project's own "arithmetic is deterministic, not model-voted" discipline for anything a
  Python `assert` can verify) rather than silently defaulting those sentences to
  `grounding_required=False`. Add a batching wrapper — one CM call per beat (or a fixed
  15-25 sentence chunk for very long beats), run in parallel via the existing `Agent`
  machinery — both to shrink truncation risk on a single giant structured output and to
  localize which batch a failure belongs to.
- Add a third CM verdict, `UNCERTAIN` (alongside `FACTUAL`/`NON_FACTUAL`), so CM is not forced
  to guess `NON_FACTUAL` under ambiguity — `UNCERTAIN` routes to C2b for a real look rather
  than being silently dropped either way.
- `review/grounding_verifier.py` (C2b): change output from `GroundingReview.issues` only to a
  dense `GroundingVerdict` per sentence — `sentence_id`, `factual`, `supported`,
  `verified_claim_ids`, `qualifier_preserved`, `scope_preserved`, `violation_code: str | None`.
  Enforce `len(verdicts) == len(sentences)` the same fail-closed way as CM. Keep emitting
  `CritiqueIssue`s too (derived from verdicts with a real violation) so existing routing
  (`_run_review_block`, `aggregate_review`) doesn't need to change shape.
- `facts/models.py::Claim`: add `required_qualifiers: list[str] = Field(default_factory=list)`.
  `facts/verify.py` (C2a)'s `TASK_PROMPT` gains one line: populate it whenever a
  VERIFIED/CONTEXT_DEPENDENT claim only holds under a stated condition (the mechanism this
  session's own `mechanism_scope` machinery already validated at the plan level, extended down
  to individual claims).
- New: when C2b's dense verdict shows a sentence IS actually supported (a verified claim
  covers it) despite CM having mis-tagged it as `grounding_required=false`, patch the
  sentence's `grounding_refs` metadata directly in the narration object — do **not** route
  this through A3/B2. Only route to A3/B2 when C2b's verdict shows a REAL defect: no verified
  claim supports the sentence, meaning drifted from the cited claim, a required qualifier was
  dropped, or scope broadened. This directly implements the doc's §5.3 example (a CM mistake
  should not trigger a narration rewrite when the underlying sentence was already fine).

**Actually implemented — and where it deviates from the plan above:**
- `narration/models.py`: `SentenceNarration.sentence_id: str = ""`, left blank by every
  narration-producing pass. Added `stamp_sentence_ids(narration)` instead of computing it once
  at B1 time as originally planned — it's called *defensively* inside `map_claims` and
  `verify_grounding` themselves (`f"{scene_id}:{index}"`), so no producer (B1, B2,
  `short_generator`, a future humanize pass) has to remember to set it, and a rewrite that
  replaces a scene's sentences can never end up with a stale id.
- `review/claim_mapper.py`: `MappedSentence` now keyed by `sentence_id`; `factual_status`
  (`FACTUAL`/`NON_FACTUAL`/`UNCERTAIN`, `UNCERTAIN` treated as `grounding_required=True`,
  conservative by design) replaces the old bare `grounding_required: bool`. Coverage enforced
  via a new shared `review.models.ReviewCoverageError`, raised with the exact missing
  `sentence_id`s. **Deviation**: batching is a flat `CM_BATCH_SIZE=20` chunk over ALL sentences
  (not grouped by beat) and calls run **sequentially**, not in parallel — parallelism doesn't
  reduce API $ cost (only wall-clock), and this codebase has no existing concurrent-LLM-call
  infrastructure to build on safely, so it was left out rather than added speculatively; can
  revisit if a live run shows batching alone isn't enough. When a narration has zero sentences,
  `map_claims` makes **zero** calls (a real cost saving, not just a test convenience).
- `review/grounding_verifier.py`: `GroundingReview.issues` → `GroundingReview.verdicts`
  (`GroundingVerdict` per sentence: `factual`, `supported`, `verified_claim_ids`,
  `qualifier_preserved`, `scope_preserved`, `violation_code`, `explanation`). `verify_grounding`
  now returns `list[GroundingVerdict]`, not `list[CritiqueIssue]` — a new
  `grounding_verdicts_to_issues()` derives the `CritiqueIssue`s callers previously got
  directly. **Deviation**: issues are derived in a fixed priority order (unsupported >
  qualifier dropped > scope broadened > named `violation_code`) rather than emitting one issue
  per failing dimension — a model-supplied `violation_code` is usually its own explanation for
  whichever structured flag it already set false, so treating it as a *second*, independent
  defect double-counted the same problem in testing. Same zero-sentences-skips-the-call
  optimization as CM, added here too for consistency (not in the original plan text, but a
  natural extension once CM already did it).
- `facts/models.py::Claim.required_qualifiers` added; `facts/verify.py` (C2a)'s `TASK_PROMPT`
  and `ClaimVerdict` schema both extended to populate it. `review/grounding_verifier.py`'s
  `_claim_payload` now also sends `scope`/`required_qualifiers` to C2b so it has something real
  to check `qualifier_preserved`/`scope_preserved` against.
- New `review/grounding_verifier.py::apply_grounding_metadata_repairs(narration, verdicts)`:
  the metadata-only repair path from §5.3 — only ever moves a sentence `grounding_required`
  False → True (using the claim ids C2b itself found), never touches a sentence C2b flags as a
  real problem. Wired into both `orchestration/pipeline.py::_run_review_block` and
  `orchestration/shorts_pipeline.py::run_short`, and reordered so C2b's verdicts + the metadata
  repair run **before** the deterministic `check_grounding_policy`/`check_numeric_fidelity`
  checks — a CM false negative C2b already disproved no longer trips a false
  `ungrounded_factual_sentence` hard failure.

**Tests** (mirrors the doc's own §30.1-§30.3 mutation tests): `tests/review/test_claim_mapper.py`
and `tests/review/test_grounding_verifier.py` fully rewritten for the new schema, covering —
coverage-invariant fail-closed for both CM and C2b (`ReviewCoverageError`, matching the exact
missing `sentence_id`), `UNCERTAIN` treated as grounding-required, CM batching (a
`CM_BATCH_SIZE + 5`-sentence narration split across 2 calls), qualifier-drop → critical,
scope-broadened → major, a named `violation_code` (soft-stated-as-hard style) → major, and both
metadata-repair tests (a CM false negative gets silently corrected with no issue raised; a real
C2b-confirmed defect is left untouched and still produces an issue). Also updated
`tests/orchestration/test_pipeline.py` (3 tests using real narration sentences across
multi-cycle revision loops) and `tests/orchestration/test_shorts_pipeline.py` (default CM/C2b
fixtures now cover the 4-segment short narration by default, plus one scope-violation test
migrated to the new schema) so every existing test still reflects a real, coverage-complete
CM/C2b exchange rather than an empty placeholder. Full suite: **924 passed, 16 deselected**
(up from 916 before this phase — 8 new/rewritten tests net).

- [x] `sentence_id` added to `SentenceNarration` (via defensive `stamp_sentence_ids`, not
      computed once at B1 time as originally sketched)
- [x] CM batched (flat 20-sentence chunks, not per-beat; sequential, not parallel — see
      deviation note above), coverage-invariant fail-closed, `UNCERTAIN` verdict added
- [x] C2b emits dense `GroundingVerdict[]` with enforced 1:1 sentence coverage
- [x] `Claim.required_qualifiers` added; C2a populates it
- [x] Metadata-only repair path for CM mistakes C2b confirms are false positives
- [x] Mutation-style tests added (coverage, qualifier, soft-to-hard) and passing
- [x] `.venv/bin/python3 -m pytest -q` green (924 passed, 16 deselected)
- [x] Live-verify against a real run — done 2026-09-15, combined with Phases 11-12 (see the
      "Phase 10-12 live-verification summary" in `ERROR_LOG.md`, right after ERR-062).
      Confirmed working AND valuable, not just non-crashing: real live model output produced
      two genuine, technically specific `qualifier_dropped` critical findings via the new
      `Claim.required_qualifiers`/`GroundingVerdict.qualifier_preserved` machinery -- exactly
      the class of defect this phase was built to catch, not a synthetic test case. Also
      surfaced a real gap this phase's own design didn't anticipate: C2b needed the same
      `CM_BATCH_SIZE`-style batching CM got, since a single unbatched 58-sentence call
      genuinely came back with 16 missing verdicts on the very first live attempt -- fixed as
      ERR-062, tested, and confirmed fixed on the next attempt. Reading the actual rendered
      HTML (not just JSON artifacts) then surfaced a second real gap: `required_qualifiers`
      was wired into C2b (narration) only -- H's screen prose and C3 had no access to it at
      all, and a qualifier C2b correctly flagged as dropped from narration was independently,
      silently reproduced in the visible on-screen text too. Fixed as ERR-063: both H's
      `_claim_payload` (first pass and repair) and C3's `scene_payload` now carry
      `required_qualifiers`/`scope`, with matching prompt instructions in all three places.

---

## Phase 11 — StoryScopeContract + source-unit disposition (P0/P1)

**Status: implemented and unit-tested (2026-09-15); live-verify deliberately deferred, same
reasoning as Phase 10 — see note below.**

**Motivation:** this is the doc's own headline real finding — GPT-5.6 Sol's generated title
became narrower than the story it actually told, while GPT-4o's `check_source_coverage` hard
gate (see above — a confirmed, real hard gate today) forces peripheral source content into
some beat even when it should be deferred. Both trace to the same missing contract: nothing
today declares, up front, what the video is allowed to promise vs. what it's allowed to merely
touch on.

**Changes:**
- `facts/models.py::SourceUnit`: add `kind: Literal["CONTENT", "PRODUCTION_META",
  "VISUAL_GUIDANCE", "REFERENCE", "OTHER"] = "CONTENT"`, set during `extraction/html_parser.py`
  (a deterministic classification pass — production notes/storyboard intent are usually
  structurally distinguishable, e.g. an author's own callout block vs. body prose; fall back
  to an LLM classification only where that's genuinely ambiguous).
- `facts/claim_extract.py` (S2b): only extract from `SourceUnit.kind == "CONTENT"`. Add one
  prompt line: never convert production notes/pacing/storyboard/visual guidance into a
  factual claim.
- `planning/models.py`: new `StoryScopeContract` — `title_promise`, `central_question`,
  `must_cover: list[str]`, `supporting: list[str]`, `deferred: list[str]`,
  `title_must_not_imply: list[str]`. Added to `StoryPlan`, populated by A2 before beats.
- `planning/models.py`: new `SourceCoverageDecision` — `source_unit_id`,
  `disposition: Literal["MUST_COVER", "SUPPORTING", "DEFERRED", "REDUNDANT", "META_ONLY"]`,
  `reason: str`.
- `verification/hard/structure.py`: replace `check_source_coverage`'s current rule ("every
  unit must be referenced by a beat") with `check_source_disposition` — every unit must
  receive a disposition (still a hard gate: nothing is silently dropped without a reason), but
  only `MUST_COVER` and disposition-justified `SUPPORTING` units require an actual beat.
  `DEFERRED`/`REDUNDANT`/`META_ONLY` are legitimate outcomes that do not fail the check.
- `planning/story_planner.py` (A2): replace "every source unit should appear in a beat" with
  the disposition instruction; add: build `StoryScopeContract` before beats; the title must
  promise the same semantic scope as the story actually tells; once the central promise is
  fully paid, don't introduce adjacent technical concepts unless explicitly `SUPPORTING`.
- `review/story_critic.py` (C1): add a numbered **PROMISE / SCOPE** check — does each beat
  advance the central question or have a real `SUPPORTING` classification; is anything
  `DEFERRED` sneaking back in; has the title promise become narrower than the actual story.
  New finding codes: `TITLE_TOO_NARROW`, `BEAT_OUT_OF_SCOPE`, `IMPORTANT_SOURCE_CONTENT_DROPPED`,
  `SUPPORTING_BEAT_TOO_LONG`.

**Actually implemented — and where it deviates from the plan above:**
- `facts/models.py::SourceUnit.kind` added exactly as specified. **Deviation**: only
  `CONTENT` (default) and `PRODUCTION_META` are ever actually SET anywhere in this codebase —
  `extraction/html_parser.py::_extract_production_notes()` is the one real, already
  structurally-distinguished site (an author's own `.page-footer` storyboard plan). No
  deterministic or LLM-based classifier was built for `VISUAL_GUIDANCE`/`REFERENCE`/`OTHER` —
  nothing in this codebase currently extracts a source unit that would need them, and building
  a classifier ahead of a real case would be exactly the kind of speculative design this
  project's own discipline avoids. The `Literal` still declares all five values so a future
  real case can use them without a schema change.
- `facts/claim_extract.py` (S2b): filters `SourceUnit.kind == "CONTENT"` deterministically
  BEFORE units ever reach the worker (not just a prompt instruction) — matches this project's
  existing "prompt + deterministic backstop" pattern (e.g. the LaTeX/entity-consistency
  checks). The prompt line was added too, as defense in depth.
- `planning/models.py::StoryScopeContract` and `SourceCoverageDecision` added exactly as
  specified, both on `StoryStructure` (so `StoryPlan` inherits them) — populated by A2 before
  beats, per the plan.
- `verification/hard/structure.py::check_source_coverage` → `check_source_disposition`,
  exactly as specified: every unit must appear in `plan.source_coverage`
  (`source_unit_missing_disposition` if not), and only `MUST_COVER`/`SUPPORTING` units need an
  actual beat (`required_source_unit_uncovered` if not) — `DEFERRED`/`REDUNDANT`/`META_ONLY`
  units pass cleanly with no beat at all.
- `planning/story_planner.py` (A2)'s `TASK_PROMPT` extended with the scope-contract and
  disposition instructions, replacing the old blanket "every source unit should appear in a
  beat" guidance.
- `review/story_critic.py` (C1): new numbered **PROMISE / SCOPE** check (naming all four
  finding codes from the plan), payload extended with `title`, `scope_contract`,
  `source_coverage`. `review/models.py::Category` gained `"scope"` as a new valid category
  value for these findings (there was no existing category that fit).

**Tests:** `tests/verification/hard/test_structure.py`'s `check_source_coverage` tests
rewritten for the disposition semantics (missing-disposition, a MUST_COVER unit left
uncovered, a DEFERRED unit correctly passing with no beat, full MUST_COVER/SUPPORTING
coverage passing) — plus its shared `make_plan()` fixture and the two `check_structure()`
full-pass tests updated to carry a matching `source_coverage`.
`tests/orchestration/test_pipeline.py`'s `make_plan()`/`make_structure()` fixtures likewise
updated (every test in that file goes through `check_structure()`, so a plan/structure with an
undeclared `source_coverage` would now hard-fail every single test in the file — confirmed by
running the suite before writing the fixture fix and watching 16 tests fail this exact way).
New `tests/review/test_story_critic.py` tests: the PROMISE/SCOPE check text is present in the
prompt, the payload carries `title`/`scope_contract`/`source_coverage` correctly, and a fake
`category="scope"` issue (replaying the doc's own headline title-narrowing finding) flows
through `critique_story()` unmodified — this is a prompt-only judgment call, so "testing" it
means confirming the right data reaches the model and a verdict routes correctly, the same way
every other C1 check (archetype fit, hook, pacing, ...) is tested in this file. New
`tests/extraction/test_html_parser.py` assertion: the real production-notes fixture is
classified `PRODUCTION_META`. New `tests/facts/test_claim_extract.py` tests (doc §30.8's
source-meta-contamination mutation, built as specified): a `PRODUCTION_META` unit never even
reaches the worker (zero calls, not just zero claims), and a mixed batch correctly excludes it
while still extracting from a real `CONTENT` unit alongside it. Full suite:
**931 passed, 16 deselected** (up from 924 after Phase 10 — 7 new tests net, offset by 0
removed).

- [x] `SourceUnit.kind` added and populated (`CONTENT`/`PRODUCTION_META` only — see deviation
      note above for why the other three declared values aren't set anywhere yet)
- [x] S2b only extracts claims from `CONTENT` units (deterministic filter + prompt line)
- [x] `StoryScopeContract` + `SourceCoverageDecision` added to `planning/models.py`
- [x] `check_source_disposition` replaces the old hard "every unit in a beat" gate
- [x] A2 prompt updated (scope contract, disposition, title-scope discipline)
- [x] C1 PROMISE/SCOPE check added (new `"scope"` category, all four finding codes named)
- [x] Mutation tests added and passing (source-meta contamination built exactly per doc §30.8;
      the title/scope mutation is a payload+routing test, not a deterministic assertion, since
      the actual judgment is an LLM call — see test notes above)
- [x] `.venv/bin/python3 -m pytest -q` green (931 passed, 16 deselected)
- [x] Live-verify against a real run — done 2026-09-15 (see `ERROR_LOG.md`'s "Phase 10-12
      live-verification summary"). A2 populated `scope_contract` and `source_coverage`
      completely and sensibly on real output — all 13 real source units classified with real
      reasons, including correctly marking `production_notes` `META_ONLY`, confirming the
      `SourceUnit.kind` classification from extraction actually informs A2's downstream
      judgement. `check_source_disposition` passed cleanly (no disposition/coverage hard
      failures). **Open, inconclusive**: the chosen title arguably read narrower than
      `must_cover` (framed around the hook's pronoun example while `must_cover` promised the
      full mechanism), but C1's PROMISE/SCOPE check did not fire on it this run — genuinely
      ambiguous (a concrete-example framing isn't automatically a scope violation), not
      claimed as a confirmed miss; worth watching on future runs rather than acted on now.

---

## Phase 12 — Narration factual invariants, CTA ownership, word-budget pressure (P1)

**Status: implemented and unit-tested (2026-09-15); live-verify next (clubbed with Phases
10-11, see the combined live-run entry once it lands).**

**Motivation:** three independent, cheap, mostly prompt-level fixes that share a theme —
letting B1/B2 drift from the same rules, or letting the narrator make decisions that belong to
the planner.

**Changes:**
- New shared prompt fragment (e.g. `narration/factual_invariants.py::NARRATION_FACTUAL_INVARIANTS`)
  containing the "NEVER UPGRADE" table (`possible→actual`, `weighted→selected`,
  `illustrative→literal`, `conditional→universal`, `one contributor→sole cause`,
  `assumption→guaranteed fact`, `conceptual descendant→identical mechanism`) plus the
  "any sentence with a checkable factual proposition needs `claim_refs`, regardless of
  `sentence_type`" rule. Inject it into `narration/generator.py` (B1), `editing/targeted_rewrite.py`
  (B2), and `narration/short_generator.py` — one source of truth instead of B1 carrying rules
  B2 doesn't repeat (confirmed gap: B2's current `TASK_PROMPT` has no hedging/upgrade language
  at all, so a targeted rewrite can reintroduce exactly what B1 was told to avoid).
- `planning/models.py::CTAContract`: add `final_enabled: bool = True`. `narration/generator.py`'s
  `TASK_PROMPT`: remove the "or is the final scene" clause — a scene is the CTA scene only when
  it matches `plan.cta.primary_after_beat`, full stop. The narrator never invents a CTA the
  planner didn't place.
- `planning/scene_expander.py` (A2b): add `needs_rebudget: bool` to `ExpandedScene`/`ScenePlan`;
  prompt change — use the minimum words needed for the learning objective; if `target_words`
  can't be filled without repeating already-taught material, set `needs_rebudget=true` instead
  of padding. New deterministic pass (likely in `planning/story_planner.py`, after the A2b
  loop): redistribute words from beats that flagged `needs_rebudget` to beats with real
  remaining depth, rather than leaving the pressure on the model to invent filler.

**Actually implemented — and where it deviates from the plan above:**
- New `narration/factual_invariants.py::NARRATION_FACTUAL_INVARIANTS`, containing exactly the
  NEVER UPGRADE table and the "any factual sentence needs `claim_refs` regardless of
  `sentence_type`" rule specified above. **Deviation**: B1's own existing, more detailed
  hedge/verification-status policy (REJECTED/UNVERIFIED/CORE/OPTIONAL/CONTEXT_DEPENDENT
  narration rules) was left in place in `narration/generator.py` unchanged, rather than
  folded into the shared fragment — it's already correct and already tested; the shared
  fragment adds the two rules B2/shorts were genuinely missing, appended via simple string
  concatenation (`TASK_PROMPT = "...""" + NARRATION_FACTUAL_INVARIANTS`) to all three of B1,
  B2 (`editing/targeted_rewrite.py`), and shorts (`narration/short_generator.py`).
- `planning/models.py::CTAContract.final_enabled: bool = True` added. `narration/generator.py`'s
  TASK_PROMPT changed as specified: a scene is the CTA scene ONLY when it matches
  `primary_after_beat`, full stop. **Deviation**: rather than the `final_enabled` flag having
  no effect at all once the automatic clause was removed, it was wired into a narrower,
  explicit rule -- when the video's true final scene is a DIFFERENT scene than the one
  matching `primary_after_beat`, `final_enabled=true` (default) permits ONE short, soft
  closing line reinforcing the payoff (never a second full CTA ask); `final_enabled=false`
  forbids any CTA-adjacent language on that final scene at all. This gives the field a real
  purpose instead of becoming dead configuration once the bug it was originally scoped to fix
  was resolved by the "full stop" prompt change alone.
- `planning/scene_expander.py` (A2b): `ExpandedScene.needs_rebudget: bool = False` added and
  threaded into `ScenePlan.needs_rebudget`; prompt changed to ask for the minimum words needed
  and to signal `needs_rebudget=true` (on the beat's last scene) instead of padding when the
  target can't be filled without repetition.
- New `planning/beat_word_budget.py::redistribute_rebudgeted_words()` (**deviation**: placed
  in the existing deterministic-allocator module rather than `story_planner.py` itself, to
  keep the arithmetic testable in isolation the same way `allocate_beat_word_budgets` already
  is) -- computes the total deficit across every beat that flagged `needs_rebudget`, then
  distributes it across scenes in NON-flagged beats, each capped at `ScenePlan.word_budget`'s
  own 30-100 hard bound (a waterfilling pass, same shape as the existing
  `_apply_retention_deadlines`/`_redistribute` logic in the same module). A no-op when nothing
  flagged it, when there's no actual deficit, or when every other scene is already at its
  100-word ceiling (the excess simply goes unabsorbed rather than violating any bound). Wired
  into `planning/story_planner.py::plan_story()` immediately after the per-beat A2b loop.

**Tests:** `tests/planning/test_beat_word_budget.py` gained 6 new deterministic tests for
`redistribute_rebudgeted_words()` covering the no-op cases, the real redistribution case, the
100-word hard-cap enforcement, and the no-eligible-recipient case -- fully unit-testable
without any LLM, unlike the doc's own framing of this as a "mutation test" (there's no mutation
needed; the algorithm itself is deterministic Python). `tests/planning/test_scene_expander.py`
gained 3 tests confirming `needs_rebudget` threads through and the prompt asks for it.
`tests/planning/test_story_planner.py` gained one true end-to-end integration test (via the
existing `SequencedStoryLead` harness) confirming `plan_story()` itself wires the
redistribution into its real multi-beat loop, not just that the function works in isolation.
`tests/narration/test_generator.py` gained tests for `final_enabled` reaching the payload and
the old automatic-final-scene clause being gone from the prompt. `tests/narration/
test_generator.py`, `tests/editing/test_targeted_rewrite.py`, and `tests/narration/
test_short_generator.py` each gained a test confirming `NARRATION_FACTUAL_INVARIANTS` is
present verbatim in their `TASK_PROMPT`. Full suite: **945 passed, 16 deselected** (up from
931 — 14 new tests, 0 regressions).

- [x] `NARRATION_FACTUAL_INVARIANTS` shared fragment created and injected into B1/B2/shorts
- [x] `CTAContract.final_enabled` added; B1's "or is the final scene" clause removed (given a
      narrower, real purpose rather than left as dead configuration -- see deviation note)
- [x] `needs_rebudget` added to A2b's scene contract + prompt
- [x] Deterministic word-reallocation pass added (`redistribute_rebudgeted_words`, in
      `beat_word_budget.py`, wired into `story_planner.py`)
- [x] Mutation/ownership tests added and passing (the word-budget case is a real deterministic
      unit test, not a mutation test, since the redistribution algorithm itself is pure Python)
- [x] `.venv/bin/python3 -m pytest -q` green (945 passed, 16 deselected)
- [x] Live-verify against a real run — done 2026-09-15, combined with Phases 10-11 (see
      `ERROR_LOG.md`'s "Phase 10-12 live-verification summary"). `needs_rebudget` fired on 10
      of 12 real beats' final scenes — strong evidence A2b is genuinely using the escape valve
      rather than padding, not a mechanism that only looks fine in tests. The CTA sentence
      appeared exactly once, on the scene matching `primary_after_beat`, in proper
      value-linked phrasing, with no invented second CTA anywhere in the 35-scene script.
      **Not exercised**: this run's `primary_after_beat` beat happened to also be the video's
      final beat, so the new "different final scene gets one soft closing line" branch of the
      CTA logic never actually ran — remains unverified live, worth checking on a future run
      where the CTA beat and the final beat genuinely differ.

---

## Phase 13 — Review responsibility split, revision-comparison precision, continuing-viewer check (P1)

**Status: implemented and unit-tested (2026-09-15); live-verify pending, to be clubbed with
Phase 14+ per the same cost-minimization approach as Phases 10-12.**

**Motivation:** cleans up three separate but related review-layer issues once Phase 10's dense
C2b verdicts exist to receive the responsibility C1 currently over-owns.

**Changes:**
- `review/story_critic.py` (C1): remove the OVERCLAIM check (#9) — soft-vs-hard mechanism
  language, multi-component causality, architecture-specific overgeneralization all move to
  C2b, which now has the dense per-sentence verdict machinery (Phase 10) to check them
  precisely instead of via a whole-script read. C1 keeps: archetype fit, hook, causal flow,
  mini-payoffs, cognitive load, ending, repetition, pacing, and the new PROMISE/SCOPE check
  from Phase 11.
- `review/grounding_verifier.py` (C2b): extend the dense verdict's checks to cover soft-vs-hard
  mechanism language and architecture-specific overgeneralization directly against each
  sentence's cited claim's `scope`/`required_qualifiers` fields (both now real, per Phases 10-11).
- `orchestration/pipeline.py::_badness()`: replace `(len(hard_failures), len(issues))` with a
  full severity-ordered tuple — `(len(hard_failures), critical_count, major_count, minor_count,
  red_diagnostic_count, amber_diagnostic_count)`. Confirmed gap: today's tuple already handles
  the doc's own worked example correctly (criticals are already folded into `hard_failures` by
  `aggregate_review`), but doesn't distinguish major-vs-minor when hard-failure counts tie.
- `orchestration/pipeline.py::_legitimately_dismissed_issue_ids`: tighten, don't remove.
  Today's guard requires either a genuinely new alternative archetype (not already in
  `rejected_archetypes`) or new textual evidence beyond the rejection reason — resolving
  **ERR-022/025**'s open question partially: keep requiring A2's rejection to be genuinely
  addressed, but explicitly allow a *different, well-argued interpretation of the same cited
  evidence* to count as legitimate disagreement (not just a brand-new fact) — matching the
  doc's own framing — checked by having A3 quote the specific piece of `rejected_archetypes`
  reasoning it's refuting, verified as present in `problem`, rather than the current crude
  archetype-name keyword match alone.
- `review/cold_viewer_critic.py`: add a **continuing viewer** check alongside (not replacing)
  the existing cold-midpoint check. Input: `viewer_knows`, previous beat's payoff, the last
  20-30 seconds of narration, the current scene, the next promised payoff. Ask: does this feel
  caused by what came before; does the viewer know why it's being discussed; has progress
  stalled; is something new being earned. Keep the existing cold-midpoint check (it targets a
  real, different KPI — random-seek/scroll-stopping hookability, a real YouTube viewing
  behavior) but note explicitly in both docstring and this plan that it stays diagnostic-only
  in spirit (it already can't become a hard failure — `severity="major"`, never `"critical"` —
  no code change needed there, just don't raise its severity in any future edit).
- Documentation-only: fix `agents/worker.py`'s Haiku-rule docstring/comment to acknowledge that
  C4a/C4s's cold-hook first tier is sampled subjective screening against a Gemini second
  opinion, not a violation of "Haiku never judges quality" — the cascade itself is correct and
  stays as-is (per the pushback above on the doc's §19 Option B).

**Actually implemented — and where it deviates from the plan above:**
- `review/story_critic.py` (C1): the OVERCLAIM check (#9) is gone as a *generic* check, but
  its `mechanism_scope`-specific sub-bullet was kept and renamed to its own **MECHANISM
  SCOPE** check (still #9) — **deviation**: the plan text didn't call this out explicitly,
  but `mechanism_scope` is `ScenePlan`-level data (Phase 7) C1 already receives and C2b does
  not, and it's a genuinely different mechanism than Phase 10's claim-level
  `required_qualifiers` (planner-established conditional scope vs. a claim's own stated
  condition) — dropping it entirely would have silently regressed a real, already-tested
  Phase 7 check for no reason connected to this phase's actual goal. The PROMISE/SCOPE check
  (Phase 11) is untouched.
- `review/grounding_verifier.py` (C2b): no new schema fields needed — `qualifier_preserved`/
  `scope_preserved` (Phase 10) already covered "architecture-specific detail stated as
  universal" and "absolute claim where the source is conditional" once the prompt explicitly
  said so. The two genuinely new patterns (hard-selection language for a soft mechanism;
  one component credited with a multi-component outcome) were added as two new named
  `violation_code` values (`soft_stated_as_hard`, `partial_contribution_overstated`) — no
  schema change, just prompt text plus two new test cases confirming they map to `major`
  severity via the existing priority-ordered `grounding_verdicts_to_issues()`.
- `orchestration/pipeline.py::_badness()`: implemented exactly as specified —
  `(hard_failures, critical, major, minor, RED, AMBER)`, using `collections.Counter` over
  `bundle.issues`/`bundle.diagnostics`.
- `orchestration/pipeline.py::_legitimately_dismissed_issue_ids`: tightened as specified,
  using the existing `verification/hard/text_overlap.py::overlap()` heuristic (the same one
  the promise-chain gate already uses) rather than inventing a new comparison mechanism — a
  dismissal for an already-considered archetype is legitimate only when A3's own `reason`
  text substantively word-overlaps (`DEFAULT_OVERLAP_THRESHOLD`) with what A2 actually wrote
  in `rejected_archetypes` for that archetype, not merely naming it. A genuinely new
  alternative (never in `rejected_archetypes`) is still never dismissable, regardless of
  wording.
- `review/cold_viewer_critic.py`: new C4d continuing-viewer check added exactly as specified
  (`viewer_knows`, previous beat's payoff, last scene's narration, current scene, next
  question), alongside the unmodified C4c. **Deviation**: `viewer_knows` isn't stored
  anywhere on the finished `StoryPlan` (`ViewerLedger` is transient, live only during A2b) —
  reconstructed instead by walking `plan.scene_plan` in order and accumulating
  `new_concepts` from every scene before the checkpoint, the same accumulation A2b itself
  does live. "Last 20-30 seconds of narration" is approximated as the immediately-preceding
  scene's narration text (the same kind of pragmatic single-scene proxy this codebase already
  uses elsewhere, e.g. `_hook_context()`'s "first beat = the opening").
- `agents/worker.py`: module docstring extended to explain the C4a/C4c/C4d sampled-screening
  nuance, `BASE_SYSTEM_PROMPT` (the actual text sent to the model) left untouched per the
  plan's own "documentation-only" framing.

**Tests:** `tests/review/test_story_critic.py` updated (removed the generic-overclaim prompt
assertion, replaced with one confirming that language is GONE and the narrower MECHANISM
SCOPE check remains). `tests/review/test_grounding_verifier.py` gained tests for both new
`violation_code` values mapping to `major`. `tests/orchestration/test_pipeline.py` gained
3 direct `_badness()` unit tests (including the doc's own 3-major-vs-5-minor case) and 3
direct `_legitimately_dismissed_issue_ids()` unit tests (a rubber-stamp reason rejected, a
reason that genuinely engages with the rejection honored, a genuinely new alternative still
never dismissable) — plus fixture updates (`ContinuingViewerVerdict`/`ContinuingViewerCritique`
registered in the shared `make_agents()` schema-dispatch fixture, since C4d now runs every
review cycle the same as C4c). New `tests/review/test_cold_viewer_critic.py` tests (12) cover
the full C4d cascade: checkpoint reuse, `viewer_knows`/`previous_payoff`/`next_question`
payload construction, the first-beat edge case, all three flag-to-category mappings, low
confidence escalating even when otherwise clean, and pass-id defaults. Full suite:
**971 passed, 16 deselected** (up from 952 — 19 new/updated tests, 0 regressions).

- [x] C1's overclaim check removed; C2b's dense verdict covers it instead (mechanism_scope
      sub-check kept in C1 — see deviation note above for why)
- [x] `_badness()` uses a full severity-ordered tuple
- [x] Archetype-dismissal guard tightened per ERR-022/025, not removed (word-overlap check
      against A2's actual rejection text, not just the archetype name)
- [x] Continuing-viewer check (C4d) added alongside the existing cold-midpoint check (C4c)
- [x] Haiku-rule docstring corrected
- [x] Tests added and passing; `.venv/bin/python3 -m pytest -q` green (971 passed, 16 deselected)
- [ ] Live-verify against a real run — pending, to be run combined with Phase 14 (or later)
      rather than spending a separate paid run on wiring/logic already fully covered by unit
      tests; C4d in particular is worth watching live for whether it produces genuinely useful
      findings distinct from C4c's, and whether the tightened dismissal guard ever actually
      changes a real run's outcome (no live run so far has exercised the dismissal path with a
      dismissal reason worth testing against the new bar).

---

## Phase 14 — HTML authorship identity + visual-density re-measurement (P1/P2)

**Status: implemented and unit-tested (2026-09-15); live density re-measurement pending,
to be clubbed with a future live run.**

**Motivation:** the confirmed `narration_lead`/H base-prompt contradiction (above) is a real,
cheap-to-fix identity-boundary bug. The bigger `VideoScreen`/`ReferencePage` schema split is
deliberately deferred pending re-measurement (see pushback above) — this phase does the cheap
identity fix plus a lighter prompt-level visual-first rebalancing first.

**Changes:**
- New `agents/html_author.py::make_html_author(client)` — same model/lane as `narration_lead`
  (Sonnet, subscription), new `BASE_SYSTEM_PROMPT`: *"You convert a validated technical story
  and narration into visual-first screen content for a YouTube explainer. You do not write
  spoken narration. Your job is to communicate each scene visually: large teaching objects,
  minimal text, clear hierarchy, accurate numbers, render-safe components. Prefer diagrams,
  transformations, comparisons, and annotated objects over paragraphs whenever the idea can be
  shown rather than read."* Swap it in for every `synthesize_hero`/`synthesize_beat_visual`/
  `repair_hero`/`repair_beat_visual` call site currently using `narration_lead`.
  `PipelineAgents`/`run_pipeline.py` gain an `html_author` field.
- `html_synth/synthesizer.py` / `editing/html_repair.py` `TASK_PROMPT`s: lighten the
  "1-3 sentences of article prose" framing toward "the minimum text needed to support one
  dominant visual object" — a prompt-weighting change, not a schema change, so it's cheap to
  try and cheap to revert.
- Re-run a live comparison (component-type histogram, screen-text word count per scene) against
  the last confirmed-healthy run from this session (the one that showed good diagram/math
  diversity after ERR-056's fix) before deciding whether the full `VideoScreen`/`ReferencePage`
  split is actually still needed.

**Actually implemented — and where it deviates from the plan above:**
- New `agents/html_author.py::make_html_author(client)`, exact `BASE_SYSTEM_PROMPT` specified
  above. **Discovery, not deviation**: `agents/__init__.py`'s own docstring already listed
  `html_author` as one of "5 agent identities" since before any agent existed (a stale
  "Not yet implemented" placeholder) — the identity was always the intended design, just
  never built; `RepairOwner` and every C3/H-repair routing decision already used the string
  `"html_author"` for years, only the real `Agent` object was missing.
- Swapped into `synthesize_hero`/`synthesize_beat_visual`/`repair_hero`/`repair_beat_visual`
  and both `orchestration/html_pipeline.py` functions by renaming their `narration_lead: Agent`
  parameter to `html_author: Agent` (a pure rename -- every real call site already passed
  positionally, so this changed no calling code's behavior, only its self-documentation) and
  wiring a real `make_html_author(client)` into `run_pipeline.py` in place of reusing
  `narration_lead` for the one call site that needed it (`synthesize_and_repair_video_html`).
  **Left deliberately untouched**: the UNRELATED `repair_owner == "narration_lead"` string
  literal in `_visual_critique_to_narration_level_issues` (Phase 8.6) -- a routing label
  meaning "this finding belongs to spoken narration, not HTML," semantically distinct from
  the agent identity and never meant to change.
- `html_synth/synthesizer.py` / `editing/html_repair.py` prompts rebalanced as specified:
  "the minimum text needed to support one dominant visual object," explicitly still requiring
  real, non-blank prose per scene (`verification/hard/render.py::check_every_scene_has_prose`'s
  existing hard gate) -- an early draft of this rewrite briefly suggested screen_prose could be
  entirely blank when a component was "self-explanatory," caught before landing since that
  directly contradicts the existing hard gate; the final wording is explicit that a component
  is never a substitute for real screen text, only that the text shouldn't be padded.
- Live density re-measurement (component-type histogram, screen-text word count) — **deferred**
  to a future live run rather than spending a separate paid run on a prompt-only change fully
  covered by unit tests; the actual decision on the `VideoScreen`/`ReferencePage` schema split
  depends on that re-measurement and is deferred with it.

**Tests:** `tests/agents/test_factories.py` gained a dedicated `html_author` factory test and
its "distinct base prompts" sanity check now covers all 5 identities (was 4). `tests/editing/
test_html_repair.py`'s fake agent class and every local variable renamed `FakeHtmlAuthor`/
`html_author` (was `FakeNarrationLead`/`narration_lead`) for 24 occurrences -- purely
cosmetic since all real call sites are positional, but the plan's own test instructions
explicitly asked for this, and leaving the old names would have been actively misleading
about which identity these tests exercise. `tests/orchestration/test_run_pipeline.py` gained
a real wiring-bug test (`test_html_synthesis_uses_the_html_author_identity_not_narration_lead`)
confirming `run_pipeline.py` actually passes the `html_author` stub, not `narration_lead`, to
`synthesize_and_repair_video_html` -- exactly the class of bug this test file's own docstring
says it exists to catch. New prompt-content tests in `test_synthesizer.py`/`test_html_repair.py`
confirm the visual-first rebalancing landed AND that it never contradicts the
never-blank-screen-prose hard gate. Full suite: **975 passed, 16 deselected** (up from 971).

- [x] `agents/html_author.py` created; wired into all H/H-repair call sites
- [x] H/H-repair prompts rebalanced toward visual-first (without contradicting the existing
      never-blank-prose hard gate)
- [x] Tests updated for the new identity
- [x] `.venv/bin/python3 -m pytest -q` green (975 passed, 16 deselected)
- [ ] Live-verify: identity confirmed in `usage.jsonl`; density re-measured — **pending**,
      deferred to a future live run
- [ ] Decision recorded: is the full `VideoScreen`/`ReferencePage` schema split (doc §22) still
      warranted after re-measurement, or does the prompt-level fix hold? — **pending** the
      live re-measurement above

---

## Phase 15 — Sequence-level visual review + bounded late narration repair (P2)

**Status: implemented and unit-tested (2026-09-15); live-verify pending.**

**Motivation:** two real gaps C3 doesn't cover today: compositional monotony across a sequence
of individually-fine scenes, and a genuine screen/narration factual contradiction that no
existing repair path can fix (H only regenerates prose/component data, never the underlying
fact it's asked to represent — confirmed by `review/visual_critic.py`'s own `TASK_PROMPT`,
which explicitly reserves this case as a permanently-blocking finding today).

**Changes:**
- New `review/visual_sequence_critic.py` (`C3-sequence`): input a contact sheet of 8-12 scene
  screenshots plus their `component_id`s; ask whether composition is becoming predictable,
  whether important moments are visually larger, whether diagrams occupy enough of the frame,
  whether the same card/grid structure repeats too often. Wire into
  `orchestration/html_pipeline.py` after the existing per-scene C3 pass, same
  flash→strong escalation pattern.
- `orchestration/html_pipeline.py`: add `MAX_LATE_NARRATION_REPAIRS = 1`. When C3 raises a
  `severity="critical"`, `repair_owner="narration_lead"` finding (a genuine screen/narration
  contradiction, not a style critique — same distinction `visual_critic.py` already draws),
  run exactly one bounded cycle: `apply_targeted_rewrite` (B2, scoped to only that scene) →
  `verify_grounding` (C2b, that scene) → regenerate that scene's H output → re-run C3 on it.
  This is a narrow, explicitly-bounded exception to "HTML render issues never route through
  B2" (Phase 8.6's own invariant) — the one case where nothing else in the architecture can
  ever resolve the finding.

**Actually implemented — and where it deviates from the plan above:**
- New `review/visual_sequence_critic.py` (C3-sequence, pass_id `C3seq`), exactly as specified:
  a contact sheet of scene screenshots + `component_id`s, judging composition across the
  sequence (repeating layouts, visual weight not matching importance, static-feeling
  sequences). **Deviation**: reuses the SAME sampled screenshots the per-scene C3 pass
  already captured (`select_scenes_for_visual_audit`'s existing ~8-scene budget) rather than
  a separate 8-12-scene capture — no second Playwright render pass, and the doc's own "8-12
  scenes" is close enough to the existing `DEFAULT_MAX_IMAGES=8` that a second sampling pass
  would mostly just re-fetch the same scenes at extra cost. The contact sheet is explicitly
  re-sorted into true video order before sending (`select_scenes_for_visual_audit` puts
  flagged scenes first, which would scramble sequence order for this specific check).
  Never a hard gate: `sequence_critique_issues` is reported on `HtmlSynthesisResult`, exactly
  like the existing non-structural `visual_critique_issues`, never routed into repairs.
- `orchestration/html_pipeline.py`: `MAX_LATE_NARRATION_REPAIRS = 1` added as specified, and
  the bounded cycle runs exactly as described (B2 scoped to the one named scene → C2b sanity
  check scoped to that scene's rewritten sentence(s) → `repair_beat_visual` regenerates that
  scene's H output using the corrected narration → a fresh screenshot + one more `critique_visuals`
  call re-checks just that scene). **Deviation**: `synthesize_and_repair_video_html()` gained
  a new `narration_lead: Agent | None = None` keyword parameter (needed for the B2 call,
  since this function previously only ever touched `html_author`) — defaulting to `None`
  means every existing caller/test keeps the exact pre-Phase-15 behavior (a narration-owned
  critical finding blocks, no repair attempted) unless a caller explicitly opts in by passing
  it; `run_pipeline.py` now does. The bound is enforced as ONE attempt **total per run**, not
  one per finding — if multiple narration-level contradictions are found in the same run,
  only the first gets the bounded attempt; the rest surface as blocking findings exactly as
  before, matching the plan's own singular framing ("one bounded late narration repair").
  The C2b sanity check reuses `visual_auditor` (already paid for in this function) rather
  than threading in a separate strong-tier `review_lead` — a deliberate, narrow simplification
  for this single-scene, already-exceptional path, documented in code as not a substitute for
  the main loop's own C2b pass.

**Tests:** new `tests/review/test_visual_sequence_critic.py` (7 tests) covers the module in
isolation (payload shape, image ordering, issue passthrough, prompt content, no hardcoded
vocabulary). `tests/orchestration/test_html_repair_loop.py` gained 7 tests: sequence-critique
scenes arrive in true video order with `component_id`s attached and never become a hard gate;
the late-repair cycle actually resolves a fake contradiction (recheck comes back clean, the
finding stops blocking, the corrected text appears in the final HTML); an unresolved case
(recheck still finds a contradiction) still blocks exactly as before; and the `narration_lead
=None` default preserves the exact pre-Phase-15 behavior for every existing caller. `tests/
orchestration/test_run_pipeline.py` gained a wiring test confirming `run_pipeline.py` actually
passes the real `narration_lead` through as a keyword argument (without this, the whole
capability would silently stay inert in production despite being fully implemented and
tested). Full suite: **988 passed, 16 deselected** (up from 975).

- [x] `review/visual_sequence_critic.py` created and wired in (reusing existing screenshots,
      re-sorted into true video order)
- [x] `MAX_LATE_NARRATION_REPAIRS` bounded repair loop added, wired into `run_pipeline.py`
      (opt-in via `narration_lead`, defaulting to the pre-Phase-15 behavior when omitted)
- [x] Tests added and passing; `.venv/bin/python3 -m pytest -q` green (988 passed, 16 deselected)
- [ ] Live-verify against a real run — pending. This phase is a strong candidate for the next
      live run: it's the first phase whose behavior genuinely depends on real model judgement
      in a way unit tests can only simulate (does C3-sequence actually catch real compositional
      monotony; does a real late-repair cycle actually resolve a real contradiction, or does it
      just churn one bounded attempt and still block).

---

## Phase 16 — Multi-source benchmark suite + manual-edit-time KPI (P2, ongoing)

**Status: not started.**

**Motivation:** the doc's own closing argument is correct and matches this project's existing
discipline (live-verify against real output, not just passing checks): the real product metric
is creator time between generated HTML and a publishable video, not agent count, check count,
or token usage. This phase should run **after** Phases 10-13 land, not before — re-running the
GPT-4o vs. GPT-5.6 Sol comparison today would just reproduce the same contract-enforcement
gaps the doc's own executive assessment already diagnosed as the real bottleneck.

**Changes:**
- Assemble a small benchmark suite beyond `video-01-attention-*` (the doc suggests
  Attention/KV-Cache/OOM-style sources — pick whatever real source material is on hand that
  stresses a genuinely different story shape per source, e.g. one comparison-heavy, one
  build-chain-heavy, one foundation-heavy).
- Run each source under identical contracts (same claim registry, same review pipeline) across
  both `story_lead` configurations, post-Phase-13.
- Track `manual_minutes_to_publish` and categorize any manual edit still needed:
  `FACTUAL / STORY / REPETITION / VOICE / VISUAL / CTA / GROUNDING / RENDER`.
- Adopt the doc's §33 acceptance rubric (story/teaching/technical/narration/retention/visuals
  checklists) as the actual live-verify checklist for this benchmark round, replacing ad hoc
  spot-checking.
- Only after this: revisit whether `gpt-5.6-sol` should become the default `story_lead` alias
  (Phase 4's own explicit condition — "only promote it if the live comparison shows a real
  difference").

- [ ] Benchmark suite assembled (Attention + at least 2 other real sources)
- [ ] Each source run under identical contracts, both `story_lead` configs, post-Phase-13
- [ ] `manual_minutes_to_publish` tracked and categorized per run
- [ ] Doc §33 acceptance rubric adopted as the live-verify checklist
- [ ] Decision recorded: promote `gpt-5.6-sol` to default, or keep `gpt-4o` default

---

## Phase 17 — Resume a run from its last checkpoint instead of restarting from S0 (P1, operational reliability)

**Status: 17.1 implemented, unit-tested, and live-verified (2026-09-16). 17.2 still
deliberately deferred, now with real evidence behind that call -- see the update at the end of
this phase.**

**Motivation:** confirmed as a real, repeated operational cost during this session's own
Phase 13-15 gpt-4o/gpt-5.6-sol live-verification round, not a hypothetical: a `BudgetExceeded`
or a real crash partway through `run_full_pipeline()` currently means the next attempt starts
over from S0 — five relaunches in one afternoon (ERR-064's two coverage-gap crashes plus three
separate `BudgetExceeded` stops) each re-paid for S0/S2b (free)/C2a (paid, ~$0.07-0.09) and A1
(paid, ~$0.02-0.07) from scratch, on top of whatever had already run in the story loop before
the failure. This isn't a gap anyone has to go looking for either — the codebase's own code
already names the intended fix in three separate places and never finished wiring it up:
- `orchestration/run_pipeline.py`'s own module docstring: *"`orchestration.state`'s
  `PipelineState` is the plan's own designed checkpoint/resume format but is not threaded
  through here yet — this entry point runs a single attempt start to finish and is not itself
  resumable (a real gap, tracked in BUILD_PLAN.md, not silently glossed over)."*
- `orchestration/state.py::PipelineState`'s own docstring: *"what makes a rate-limited run
  resumable rather than a re-pay."*
- `llm/budget.py::BudgetCounter.record_spend()`'s own `BudgetExceeded` message, raised at the
  exact moment a run dies today: *"stop and checkpoint, do not fail over to another model."*

Both `PipelineState` (a single typed checkpoint object, `model_dump_json()` round-trip already
confirmed by `tests/orchestration/test_state.py`) and `DiskCache` (a content-addressed cache
keyed by input hashes + prompt/schema version + resolved model, `tests/orchestration/
test_cache.py`) already exist and are unit-tested in isolation — grepping the real codebase
confirms neither is referenced anywhere outside its own definition and test file. The building
blocks are built; only the wiring into `run_pipeline.py`'s actual execution path was never done.

**Scope note:** this phase is orthogonal to Phases 1-16 — it doesn't change anything about
story/narration/HTML quality, only how much of a run has to be redone (and re-paid for) after
an interruption. Split into two sub-phases by risk/complexity, matching this project's own
"don't build ahead of evidence" discipline (the same reasoning that kept shorts single-pass and
C4c/C4d as a cascade rather than always escalating):

### 17.1 — Stage-level checkpoint/resume (the high-value, low-complexity win)

Checkpoints after each of the 5 major stage boundaries `run_full_pipeline()` already has —
S0+S2+C2a (claims + `AssumptionLedger`), A1 (`SourceBrief`), the full story+narration loop
result (`PipelineResult`), H+HV (`HtmlSynthesisResult`), and each short's result — covers every
crash this session actually hit EXCEPT one still stuck mid-loop (that's 17.2). Directly
addresses the confirmed waste: re-verifying claims and re-running A1 on every relaunch.

- Extend `orchestration/state.py::PipelineState` with the fields it's currently missing to
  actually round-trip a real `run_full_pipeline()` attempt: `all_source_unit_ids`,
  `target_duration_seconds`/`audience`/`run_shorts`/`shorts_count` (currently a loose `config:
  dict`, worth typing explicitly rather than trusting a dict round-trip), `html_result`
  (`HtmlSynthesisResult` — entirely absent today), `story_replans_used`/`major_revisions_used`
  (the loop's own bounded counters), and per-stage `spent_microusd` (so a resumed run's budget
  tracking reflects TRUE cumulative spend across both the original and resumed attempt, not a
  silent reset to zero that could let the combined spend quietly exceed what the cap was meant
  to bound).
- `run_full_pipeline()`: after each stage call returns successfully, write (not just return) a
  `PipelineState` snapshot to `run_dir/checkpoint.json` via a small `save_checkpoint()`/
  `load_checkpoint()` pair in `orchestration/state.py` (mirroring `save_result()`'s existing
  pattern in `pipeline.py`, just incremental instead of once-at-the-end).
- New `--resume <run_dir>` CLI flag on `run_pipeline.py`. When given: load `checkpoint.json`
  from that path, verify its `source_hash` matches a fresh hash of the given `--source` file
  (refuse to resume into a mismatched/stale checkpoint — a real correctness safeguard, not
  just a convenience), then skip straight to the first stage the checkpoint doesn't already
  have a result for, seeding that stage's `BudgetCounter` with the checkpoint's recorded
  `spent_microusd` rather than starting it at zero. Writes into a NEW `runs/vNN` directory
  (matching this project's own "a run directory is never mutated after the fact" convention)
  rather than continuing to write into the crashed attempt's own directory.

### 17.2 — Cycle-level checkpoint inside the story+narration loop (only if 17.1 isn't enough)

All 5 of this session's own crashes happened INSIDE `_run_review_block()` (CM/C2b calls,
budget exhaustion mid-cycle) — 17.1 alone would still replay the ENTIRE story loop (A2 through
whatever cycle had been reached) on a resume, just skipping the free/cheap S0-A1 stages before
it. This sub-phase checkpoints after each individual review cycle completes, so a resume can
skip straight to "we already have this plan/narration/bundle as of cycle N."

- `orchestration/pipeline.py::run_story_and_narration_loop()`: add an optional
  `on_cycle_checkpoint: Callable[[StoryPlan, list[SceneNarration], ReviewBundle, int, int], None]
  | None = None` parameter, called once per completed cycle (after `_run_review_block` returns,
  before deciding the next action) — keeps this module a pure function with no real I/O of its
  own (still testable exactly as it is today), while letting `run_pipeline.py` wire in an actual
  disk-write callback.
- `run_pipeline.py`: on `--resume`, if the checkpoint has a mid-loop cycle snapshot newer than
  the loop's own final result, seed `run_story_and_narration_loop()`'s `initial_plan` and an
  equivalent "resume from cycle N" entry point (a new parameter, since the loop currently only
  accepts an `initial_plan` and always starts its cycle counters at zero) rather than calling
  `plan_story()` fresh.
- Explicitly deferred pending real evidence 17.1 alone doesn't cover enough of the actual waste
  — do not build this ahead of a live-run cost comparison showing 17.1's savings versus the
  remaining mid-loop replay cost.

**Tests:**
- `PipelineState` round-trip test extended to cover every new field (17.1).
- A resume test: a fake/stubbed `run_full_pipeline()`-style harness confirms stages before the
  interruption point are never re-invoked when a valid checkpoint exists, and their recorded
  cost is folded into the resumed run's own budget counters.
- A safety test: `--resume` against a checkpoint whose `source_hash` doesn't match the given
  `--source` file refuses to resume (fails loudly, does not silently trust a stale checkpoint).
- `.venv/bin/python3 -m pytest -q` green.
- Live-verify: deliberately interrupt a real run (a tight `--loop-budget-usd` or a manual kill)
  partway through, then `--resume` it, and confirm via `usage.jsonl`/log output that the
  already-completed stages are not re-billed — compare total cost of (crashed attempt +
  resumed attempt) against a single uninterrupted run of the same source as the real proof.

- [x] `PipelineState` extended with the missing fields — loop counters
      (`story_replans_used`/`major_revisions_used`/`story_final_status`) and per-stage
      `spent_microusd` (`claims_spent_microusd`/`source_brief_spent_microusd`/
      `loop_spent_microusd`), plus `completed_stages`. **Deviation:** `html_result` and typed
      config fields were NOT added — see "Actually implemented" below.
- [x] `save_checkpoint()`/`load_checkpoint()` added; `run_full_pipeline()` writes incrementally
      after each of the 3 stages it now checkpoints (claims, source_brief, story_loop)
- [x] `--resume <run_dir>` CLI flag added, with the source-hash mismatch safety check
- [ ] 17.2 (cycle-level checkpoint) scoped and either built or explicitly deferred with a
      recorded reason, based on what 17.1's live-verify actually shows — **still deferred,
      unchanged**: 17.1 has not yet been live-verified against a real interrupt, so there's no
      evidence yet on whether it's enough.
- [x] Tests added and passing; `.venv/bin/python3 -m pytest -q` green (999 passed, 16
      deselected at the time 17.1 landed)
- [ ] Live-verify: a real interrupt-then-resume cycle confirmed cheaper than two full runs —
      **not done yet**. The two live comparison runs in flight when 17.1 was built were left
      running rather than deliberately interrupted to test `--resume`, per explicit instruction
      not to touch them; a dedicated interrupt-then-resume live-verify is still pending.

**Actually implemented — and where it deviates from the plan above (2026-09-15):**

- Checkpointed exactly 3 stages, not 5: **claims** (S0+S2+C2a), **source_brief** (A1), and
  **story_loop** (the full story+narration loop result, reconstructed from checkpoint fields
  into a `PipelineResult` on resume). H+HV and shorts were deliberately left OUT of scope for
  17.1 — no real failure this session ever reached that far downstream, so there's no confirmed
  waste to fix there yet, matching this project's own "don't build ahead of evidence" rule
  cited in the plan's own Scope note. If a future live run crashes during H+HV or shorts, that's
  the trigger to extend checkpointing to cover them, not a reason to build it speculatively now.
- `config: dict` was left as a loose dict rather than split into typed
  `target_duration_seconds`/`audience`/`run_shorts`/`shorts_count` fields — round-tripping it
  through `model_dump_json()`/`model_validate_json()` already works correctly for a plain dict
  of JSON-serializable values, so the typed-field version would have been a refactor for its own
  sake, not something the resume feature actually needed to work.
- `all_source_unit_ids` was not added — nothing built in 17.1 needed it; the claims stage
  already reuses `state.claim_registry`/`state.assumption_ledger` directly.
- Resume safety: `--resume` compares the checkpoint's `source_hash` against a freshly-computed
  hash of the `--source` file passed to the resuming invocation (reusing S0's own
  `ExtractionResult.source_hash`, not new hashing logic) and raises `ValueError` on any mismatch
  — implemented exactly as scoped.
- New run directory: confirmed by test (`test_resume_writes_into_a_fresh_run_dir_not_the_old_one`)
  that `--resume` always writes into a new `runs/vNN`, never mutating the resumed-from run's own
  directory.
- Tests: 6 new tests in `tests/orchestration/test_run_pipeline.py` (`TestResume` class) covering
  full-skip, partial-skip, hash-mismatch refusal, fresh-run-dir, no-resume-flag-means-no-load,
  and per-stage checkpoint writes on a fresh (non-resumed) run; 4 new tests in
  `tests/orchestration/test_state.py` covering the new fields' defaults and the actual
  save/load round-trip (not just the schema's own `model_dump_json` round-trip).
- **Found and fixed one real bug while building this** (not a pre-existing pipeline bug, a bug
  in my own first draft of the checkpoint-write test): the generic `record()` test helper used
  throughout `test_run_pipeline.py` stores a reference to the same mutated `state` object across
  calls, not a snapshot — so a naive assertion reading `completed_stages` back from 3 recorded
  `save_checkpoint` calls would see the SAME final list on all 3, silently making the test
  incapable of ever failing. Fixed by writing a dedicated monkeypatch that snapshots
  `list(state.completed_stages)` at call time for that one test.
- **Not yet live-verified.** The two live gpt-4o/gpt-5.6-sol comparison runs that motivated this
  phase were both already past their claims/source_brief stages by the time 17.1 landed, and
  were left running rather than restarted against the new code (per explicit instruction not to
  relaunch them) — so 17.1's actual resume path has only been exercised by unit tests so far,
  not a real crash-and-resume on a live run. The gpt-5.6-sol run subsequently failed with a
  timeout, not a `BudgetExceeded` (see ERR-065) — a genuine future opportunity to `--resume` it
  once ERR-065's chunking fix is live-verified, rather than a dedicated synthetic interrupt test.

**Update (2026-09-16) — live-verified, real interrupt-and-resume cycle:** deliberately
interrupted a fresh run (new slug `video-01-attention-phase17-resume-verify`) via a
deliberately tight `--loop-budget-usd 0.15`, which correctly raised `BudgetExceeded` right
after claims ($0.0873) and source_brief ($0.0783) completed, before the story loop's own first
A2 call finished. `--resume`-ed twice (once at `--loop-budget-usd 2.0`, which also hit the cap
mid-loop; once at `5.0`, which completed) -- **both resumes correctly logged "S2/C2a: resumed
from checkpoint... (already spent, not re-billed)" and "A1: resumed from checkpoint...
(already spent, not re-billed)"**, confirming 17.1's own core value proposition works exactly
as designed: claims and source_brief were never re-paid across 3 total attempts.

**Found and fixed a real bug in the process (ERR-078, ERROR_LOG.md):** the first interrupt's
own `usage.jsonl` was missing the exact call that crashed the run ($0.266102) -- `llm/client.py`
was logging AFTER the budget-cap check could raise, so the single most expensive call in a
crashed run vanished from its own cost audit trail. Fixed and confirmed on the second interrupt
(logged total now exactly matches the exception's own reported cumulative spend).

**17.2 decision, now backed by real evidence:** the crash-to-resume waste actually incurred was
bounded -- v02's crash happened inside a C2b call within the loop's first review cycle (not
deep into multiple revision cycles), so the "wasted" replay cost when v03 restarted the whole
loop from `plan_story()` was the cost of re-running up through that point once, not repeated
revision cycles' worth of paid work. Total real spend across all 3 attempts: $4.4744 (v01
$0.1656 interrupted + v02 $2.0505 interrupted mid-loop + v03 $2.2583 to completion) -- v01's
$0.166 (claims+partial A1) was the only piece 17.1 actually saved from being re-paid, and it
did save it, twice. **Decision: keep 17.2 deferred.** This one real data point doesn't show
mid-loop replay cost dominating total waste the way stage-level re-pay (claims/A1) would have
without 17.1 -- revisit only if a future crash is confirmed to happen deep into multiple paid
revision cycles, not near the start of the first one.

---

## Phase 18 — Budget/coverage/latency hardening after a full cross-run audit (P0, user-reported)

**Status: implemented, unit-tested, and live-verified (2026-09-16) -- see the update at the end
of this phase.**

**Motivation:** direct user report — "the final HTML looks incomplete, no mention of cross
attention... phase 10 onwards changes have messed up the pipeline, we are getting multiple
errors and budget overshoot" — followed by an explicit request for a deep, evidence-based
analysis rather than a guess. Investigated with real data (every `plan.json`/`usage.jsonl`
since 2026-09-11, 18 runs) rather than speculation; full findings in `ERROR_LOG.md`'s ERR-066.
Two distinct, separately-rooted problems, neither a systemic Phase 10-17 regression:

1. **Missing source content is a real, reproducible failure MODE, not a systemic content-loss
   regression.** 17 of 18 runs since 2026-09-11 (including one launched THIS MORNING, after
   Phase 10-12 landed) have complete source-unit coverage. Only one run — today's gpt-4o
   comparison — is missing content, and it's missing 3 whole sections (`heads` = multi-head +
   cross-attention, `origin`, `recap`), not cross-attention specifically. Root cause: A2's
   first attempt AND its one-and-only replan (`MAX_STORY_REPLANS = 1`) both left the same 3
   sections uncovered; the `required_source_unit_uncovered` hard-check correctly caught this
   and was correctly never dismissed by A3, but with the replan budget already spent, the loop
   had zero recourse and fell through to FAIL — which still ran full H/HV and shorts (real $
   spent on content that could never be complete) and produced an HTML draft complete-looking
   enough to be mistaken for a real deliverable, even though it was correctly excluded from
   `promote_to_final()`.
2. **Budget overshoot is real and quantified.** C2b's per-run cost jumped from $0.08-$0.20
   (pre-Phase-10) to $0.46-$0.79 (post-Phase-10) — a deliberate, documented ~3-5x increase from
   Phase 10's sparse-issues -> dense per-sentence verdict redesign, compounded by Phase 13's
   C4d (a second full cold/continuing-viewer cascade). Neither change was ever reconciled
   against `DEFAULT_TIERS["longform"].hard_cap_usd = 1.00`, a constant ERR-046 (2026-09-12,
   *before* either phase) had already flagged as tight for reasoning-tier models but kept for
   the default gpt-4o path because it "still completes fine" — no longer true: today's default
   gpt-4o loop cost $1.2604, 26% over the unmodified default hard cap, on the DEFAULT model
   with zero CLI override.

Separately, the user asked to shorten wall-clock time and asked whether C2b/CM's per-sentence
grounding checks could be coarsened to per-section/per-scene/per-beat.

**Changes:**
- `llm/budget.py` / `src/config/budget.yaml`: `DEFAULT_TIERS["longform"]` raised 2x
  (target/warning/hard_cap: $0.40/$0.60/$1.00 -> $0.80/$1.20/$2.00).
- `orchestration/pipeline.py`: `MAX_STORY_REPLANS` raised 1 -> 2 — a coverage-type hard failure
  can ONLY be fixed by a replan (`apply_targeted_rewrite` never adds a new beat, only rewrites
  existing scenes), so one bad replan used to be a dead end with no second chance.
- `orchestration/run_pipeline.py`: new structural-coverage gate right after the story loop —
  if `final_status == "FAIL"` AND a `required_source_unit_uncovered`/
  `source_unit_missing_disposition` hard failure survived, skip H/HV and shorts entirely
  instead of spending on them before failing to promote anyway. `PipelineRunOutput.html_result`
  changed to `HtmlSynthesisResult | None` to represent this honestly.
- New `llm/concurrency.py::run_concurrently()`: CM's and C2b's batch loops (the biggest,
  slowest structured-output calls in a review cycle, and the ones the user specifically named
  as slow) now dispatch their independent batches concurrently via a `ThreadPoolExecutor`
  instead of sequentially — cuts wall-clock time roughly by the batch count with **zero cost
  increase**. `BudgetCounter`/`UsageLedger` both gained an internal lock around their small
  bookkeeping sections so sharing one budget/ledger across threads is safe.
- **Explicitly declined**: coarsening C2b/CM from per-sentence to per-section/per-scene/per-beat
  granularity, despite the user floating it as an option. Phase 10's per-sentence dense verdict
  already caught 2 real, live, critical `qualifier_dropped` findings that a sparser check would
  have missed by construction — that's the entire reason Phase 10 exists ("no issue" used to be
  indistinguishable from "never actually checked"). Parallelizing the existing per-sentence
  batches gets the wall-clock win without reopening that gap.

**Tests:** `tests/llm/test_budget.py` (tier values updated), `tests/llm/test_concurrency.py`
(new — 8 tests: result ordering, genuine wall-clock overlap via real `time.sleep`, single-item
bypass, exception propagation, concurrent `record_spend` never loses an update, concurrent
`UsageLedger.append` never corrupts a line), `tests/orchestration/test_pipeline.py` (replan-
exhaustion test extended from 1 to 2 replans), `tests/orchestration/test_run_pipeline.py` (2
new tests: uncovered-source-content skips H/HV+shorts entirely; an ordinary non-coverage FAIL
still runs H/HV as before), `tests/review/test_claim_mapper.py` /
`test_grounding_verifier.py` (batch-order assertions changed to order-independent multiset
checks now that batches genuinely dispatch concurrently; the shared `FakeReviewLead` test
double made thread-safe and content-matching, with a position-based fallback for the
deliberately-partial responses the retry tests rely on). Full suite: **1012 passed, 16
deselected** (up from 1001), re-run 15x to confirm the new real-thread tests aren't flaky.

- [x] `DEFAULT_TIERS["longform"]` raised 2x in both `llm/budget.py` and `src/config/budget.yaml`
- [x] `MAX_STORY_REPLANS` raised 1 -> 2
- [x] Structural-coverage gate skips H/HV/shorts on an unresolved coverage FAIL
- [x] `llm/concurrency.py::run_concurrently()` built; wired into CM and C2b
- [x] `BudgetCounter`/`UsageLedger` made thread-safe (lock around bookkeeping only, not the I/O)
- [x] Tests added and passing; `.venv/bin/python3 -m pytest -q` green (1012 passed, 16
      deselected), re-run 15x for flakiness
- [x] **Live-verified (2026-09-16), via the same interrupt-and-resume run built for Phase 17
      (`video-01-attention-phase17-resume-verify/runs/v03`):**
      (a) **cross-attention coverage confirmed**: the final plan's 12 beats cover all 12 real
      source units including `heads` (multi-head + cross-attention), `origin`, and `recap` --
      the exact 3 sections ERR-066's one bad run was missing -- and `story_replans_used: 0`
      (full coverage on A2's first attempt, no replan even needed this time);
      (b) **budget default is now tight for gpt-5.6-sol specifically, not for gpt-4o**: the
      story loop hit the (already-doubled) $2.00 default hard cap TWICE before completing at
      $2.2369 with `--loop-budget-usd 5.0` -- gpt-5.6-sol is now the default `story_lead`
      (separate 2026-09-16 decision, see Phase 4's own override note), and its real per-call
      cost is high enough that $2.00 is no longer a safe default for the loop it's used in,
      independent of whether the original gpt-4o-focused sizing was ever wrong;
      (c) **concurrency confirmed working on a real run, not just synthetic sleeps**: C2b's own
      `usage.jsonl` timestamps show batches genuinely overlapping (multiple calls starting
      within 1-5 seconds of each other, two calls sharing the exact same start timestamp),
      not the ~30s-apart pattern sequential dispatch would produce.
      Real run also FAILed on genuine content-quality grounds (a hook/ending promise mismatch,
      an UNVERIFIED CORE claim, several qualifier-dropped findings surviving 2 revision
      cycles) -- unrelated to Phase 18's own scope, a residual judgment-quality signal like
      the ones Phase 20's shorts work has repeatedly found, not a coverage or budget defect.
- [ ] Cold/continuing-viewer cascade (C4a-d) parallelization — deliberately deferred (see
      `ERROR_LOG.md`'s Open items): Haiku-CLI/subprocess-based, not paid-API/HTTP, and this
      session's own latency investigation already found real subprocess contention when two
      pipelines ran in parallel. Revisit only if CM/C2b's fix alone proves insufficient.
- [ ] **New, live-found (2026-09-16): `DEFAULT_TIERS["longform"].hard_cap_usd` may need
      raising again now that gpt-5.6-sol is the default `story_lead`**, separately from
      Phase 18's own original gpt-4o-focused sizing -- not fixed here, since it's a consequence
      of the Phase 4 model-default override, not this phase's own scope. Flagged for whoever
      picks up the gpt-5.6-sol default's own follow-up, not folded into Phase 18's own status.

---

## Phase 19 — Shorts pipeline: fix 3 systematic bugs found via all-candidates + persisted debug logs (P0)

**Status: implemented, unit-tested, and live-verified (2026-09-15).**

**Motivation:** direct follow-up to Phase 18 — the user asked to (a) generate all shorts
(`--shorts-count` matching however many SC finds, not a fixed guess of 1) and (b) actually see
why each one fails, since the pipeline only ever logged `final_status=FAIL` and a dollar
figure with nothing durable to inspect afterward. Both were real, closeable gaps.

**Changes:**
- `orchestration/run_pipeline.py`: `--shorts-count 0` now means "one per candidate SC actually
  finds" (`effective_shorts_count = len(candidates) if shorts_count <= 0 else shorts_count`).
- `orchestration/shorts_pipeline.py`: new `save_short_debug()` writes every short's
  `final_status`/`hard_failures`/`issues`/`diagnostics`/`log` to `run_dir/shorts/<i>/
  status.json` unconditionally — unlike `final/shorts/<i>/`, which stays promotion-only,
  matching the long-form side's own "never a partial/failed artifact" rule.
- Using both of the above on a real `--resume`'d run against all 5 candidates it found
  surfaced 3 systematic bugs (not model randomness — see ERROR_LOG.md's ERR-067 for the full
  evidence and root-cause trace): a critic (C1s) enforcing rules the generator (B1s) was never
  told about, in three different places.
  - `review/short_critic.py::critique_short()` now receives `bridge_mode`; its
    no-reserved-outro rule no longer flags the single required follow-up line
    `bridge.mode="SPOKEN"` correctly demands.
  - `narration/short_generator.py`'s prompt gained explicit structural guidance for all 7
    `MicroArc` values (the critic already judged against these; the generator never knew them).
  - `ShortNarration.word_band` is now actually sent to the model (it existed but was never
    wired into the payload); both `word_band` and `target_duration_seconds` recalibrated
    against real TTS evidence (~130wpm actual vs. ~167wpm assumed), with real margin below the
    60s hard cap.

**Tests:** `tests/orchestration/test_run_pipeline.py` (shorts_count=0 matches candidate count;
a positive count passes through unchanged; every short gets a debug status written regardless
of pass/fail), `tests/orchestration/test_shorts_pipeline.py` (`save_short_debug()` writes
correctly for pass/fail and multiple indices; `run_short()` forwards `bridge.mode` to C1s),
`tests/review/test_short_critic.py` (bridge_mode plumbing + prompt conditional language),
`tests/narration/test_short_generator.py` (word_band plumbing + all 7 arc types covered in
prompt). Full suite: **1024 passed, 16 deselected** (up from 1017).

- [x] `--shorts-count 0` matches the number of candidates SC actually finds
- [x] Every short's review detail persisted to disk regardless of pass/fail
- [x] `bridge_mode` reaches C1s; reserved-outro rule made conditional on it
- [x] Per-`MicroArc` structural guidance added to B1s's prompt (all 7 types, not just the 2
      that happened to fail live)
- [x] `word_band` wired into B1s's payload; both duration/word bounds recalibrated against
      real TTS measurement evidence
- [x] Tests added and passing; `.venv/bin/python3 -m pytest -q` green (1024 passed)
- [x] **Live-verified** across 2 more `--resume` rounds after the initial 3 fixes (a 4th and
      5th real bug -- empty hook narration, and the title check's diagram-description fallback
      -- were found and fixed along the way; see ERROR_LOG.md's ERR-067 for the full trace).
      Final round: title-mismatch, duration-overrun, reserved-outro, and empty-hook all
      confirmed at 0/5 occurrences, holding across the verification round. `micro_arc`
      (naive-attempt) dropped from 5/5 to 1/5 -- real improvement, not full elimination; see
      Phase 20 for what that residual number triggered.

---

## Phase 20 — Bounded targeted-rewrite cycle for shorts (B2s) (P1)

**Status: implemented, unit-tested, and live-verified (2026-09-15/16, v08/v09/v10 runs; header
corrected 2026-09-16 -- the checklist below already recorded this, this line had gone stale).**

**Motivation:** `orchestration/shorts_pipeline.py`'s own module docstring had pre-committed to
this exact escalation since it was first written: *"A bounded rewrite loop for shorts can be
added later if real runs show it's needed -- the same way the long-form loop only grew a
revision cycle after real failures demonstrated one was necessary."* Six live verification
rounds (Phase 19's fixes plus this same day's earlier rounds) produced that evidence: two
failure categories (`critical/micro_arc` naive-attempt, `critical/ending`
repetition-or-recap) kept resurfacing in NEW shapes after each prompt-only fix closed the
previous one, instead of trending to zero the way title-mismatch/duration/empty-hook all did.
Concretely: `ending` was 100% "reserved outro" (fixed, stayed at 0% for 3 rounds), then
reappeared as verbatim mechanism-repetition or full-recap payoffs (40% of a later round) --
the SAME underlying weakness (the model doesn't reliably know what makes a payoff "land")
wearing a different specific costume each time. `micro_arc` dropped from 100% to 20% but
resisted three separate rounds of prompt-strengthening at the wrong layer before the real fix
landed, and even then didn't reach 0%. This is the exact signature that made the long-form
pipeline itself outgrow pure prompting early in this project (ERR-022 through ERR-026) --
judgment-quality problems that a single-shot generation's prompt can keep improving but never
fully close, versus the OTHER three bugs (title, duration, empty hook), which were genuinely
"the model was never told X" and stayed fixed the moment they were told.

**Design, deliberately smaller than long-form's A3+B2 pair** (see
`editing/short_targeted_rewrite.py`'s own module docstring for the full reasoning):
- **No separate "A3" planning call.** `review/short_critic.py`'s own `CritiqueIssue.
  recommended_intent` + `scene_ids` (newly required by its prompt, not previously) already
  constitute the plan -- a short has no archetype-dispute complexity, no replan-vs-rewrite
  choice, no beat structure. There is nothing left for a planner to decide that the critique
  hasn't already decided.
- **No plan-level fix at all.** A short's `ShortPlan` (title, micro_arc, hook/setup/mechanism/
  payoff summaries from A2s) is never touched -- only its spoken narration. No real run has
  ever shown a plan-level defect a narration rewrite couldn't reach.
- **Bounded to exactly ONE attempt** (`MAX_SHORT_REVISIONS = 1`) -- a short is cheap enough
  that a second full regeneration (a fresh SC/A2s/B1s cycle on the next run) is a better use
  of a persistent miss than an unbounded in-run loop.

**Changes:**
- `review/short_critic.py`: prompt now requires every issue to carry `scene_ids` naming
  exactly which segment(s) are at fault -- previously optional/unused for shorts, making a
  targeted rewrite impossible to aim.
- New `editing/short_targeted_rewrite.py` (B2s): given the current narration and the critical
  issues found, rewrites ONLY the named segment(s), addressing each one's `recommended_intent`
  -- untouched segments survive byte-for-byte. Prompt explicitly names the recurring failure
  patterns confirmed live (verbatim mechanism-repetition, full-recap payoffs, jargon-first
  hooks, a missing naive-attempt sentence) rather than a generic "fix it" instruction.
- `orchestration/shorts_pipeline.py::run_short()`: after the initial narration + review, if any
  critical issue names an actionable segment and the bounded budget remains, applies ONE
  targeted rewrite, re-runs the full review block (CM/C2b/C1s/C4s) on the result, and keeps
  whichever version (original or rewritten) has the lower `_badness` (fewer hard failures,
  tie-broken on fewer total issues) -- mirrors long-form's own Phase 8.5 "never accept a
  rewrite that made things worse" precedent, scaled down (no severity/diagnostic-band
  breakdown, no evidence yet that shorts need that granularity). Real TTS measurement now runs
  once, on whichever narration is final, after the revision decision -- not before it (the
  compare step uses the free WPM estimate, not a live TTS call, to decide whether the rewrite
  helped).
- `ShortRunResult.revisions_used` (0 or 1) added and persisted in `save_short_debug()`'s
  `status.json`, mirroring long-form's `major_revisions_used`.
- Two complementary, lower-risk fixes applied alongside (reduce how often the rewrite cycle is
  even needed, not a substitute for it): `verification/diagnostics/shorts.py`'s
  `SETUP_LENGTH_TARGET_SECONDS` raised 10.0 -> 13.0 (confirmed live: 4 of 5 real shorts hit RED
  at 15-17.6s once `setup` legitimately grew a second job carrying the per-arc required beat --
  advisory only, never a hard gate, so recalibrating doesn't change what ships, only whether
  the signal stays useful); `narration/short_generator.py`'s hook instruction now explicitly
  warns against opening on jargon or flatly stating the outcome before any tension exists
  (confirmed live: 4 of 5 real shorts got a major hook-framing finding).

**Tests:** `tests/editing/test_short_targeted_rewrite.py` (new, 11 tests -- no-op when no
scene_ids named, only named segments touched, untouched segments byte-for-byte, multiple
issues on one segment combine, one issue naming multiple segments touches all of them, a
segment name that doesn't exist in the narration is skipped gracefully, pass_id/mode, bridge
mode reaches the payload, factual invariants + the recurring failure patterns are in the
prompt), `tests/orchestration/test_shorts_pipeline.py` (5 new tests -- a critical issue with
scene_ids triggers exactly one rewrite and it's kept when not worse, an issue with no
scene_ids cannot trigger one, no critical issues means no attempt, a rewrite that regresses is
reverted but still counts as used, a second revision is never attempted even if still
failing), `tests/verification/diagnostics/test_shorts.py` (setup carrying its new required
beat reads AMBER not RED), `tests/narration/test_short_generator.py` (hook-jargon warning
present). Full suite: **1052 passed, 16 deselected** (up from 1034).

- [x] `review/short_critic.py` requires `scene_ids` on every issue
- [x] `editing/short_targeted_rewrite.py` (B2s) built -- segment-scoped, no plan-level fix,
      names the specific recurring failure patterns confirmed live
- [x] `run_short()` wired with a bounded (`MAX_SHORT_REVISIONS=1`) revise-compare-keep-or-
      revert cycle; TTS measurement moved to run once on the final narration
- [x] `ShortRunResult.revisions_used` added and persisted
- [x] Setup-length target and hook-jargon guidance recalibrated as complementary fixes
- [x] Tests added and passing; `.venv/bin/python3 -m pytest -q` green (1052 passed)
- [x] **Live-verified (2026-09-16, `--resume` re-run):** the rewrite cycle fired and
      `revisions_used` persisted correctly in `status.json`; that same run's own findings (a
      "kept, not worse" rewrite that still measured over the duration cap once real TTS ran)
      are exactly what led to the word-budget gap fixed in ERR-070 below.

**Update (2026-09-16) — see ERR-070 (ERROR_LOG.md):** a dedicated 3-round static review
(requested specifically to gate whether another live run was warranted) found one real bug per
round on top of this phase's own work: the cold-hook critic's Gemini escalation had no severity
constraint (could defeat this phase's own "never a hard gate" design for cold-hook findings);
`short_targeted_rewrite.py`'s prompt had no word-budget awareness at all (the direct cause of
the duration-cap miss noted above), which also surfaced a session-wide `PLANNING_WPM` staleness
(167 vs. the already-recalibrated ~130wpm evidence); and `RewrittenSegment.segment` was an
unconstrained `str` (same silent-drop class already fixed once in `GeneratedSegment`). All
fixed and unit-tested; no live run has followed these fixes yet, since all 3 review rounds
found a bug and none passed clean.

---

## Phase 21 — v08 live re-verification, plus a visual-density and subscribe/bridge pass (P1, user-reported)

**Status: implemented and unit-tested (2026-09-16).**

**The v08 run:** `--resume` against the same v01 checkpoint, after ERR-070's fixes. 3 of 5
shorts landed `PASS_WARN` (up from Phase 20's 2/5), 0 duration-cap overruns (measured 87.9-102.0s,
all comfortably under the 120s cap -- direct confirmation ERR-070's word-budget-aware rewrite
fix closed the exact gap that caused one previously). Mid-verification, found and fixed one more
real bug (ERR-071, ERROR_LOG.md): a short's TTS synthesis degradation could silently force
`PASS_WARN` with the reason recorded nowhere -- neither `result.log` nor the persisted
`status.json`.

**User review of the run's own `short.html` files surfaced two more gaps, neither a pipeline
"bug" in the hard-failure sense, both real:**

1. **Visual density.** Each of the 4 segments rendered as ONE merged paragraph, vertically
   centered in a full 1080x1920 screen. Real numbers: a hook's ~40 words at 58px font fills
   maybe 300-400px of a 1920px-tall screen -- 75-85% blank. Only `mechanism` ever got a visual
   (the existing flow diagram); `hook`/`setup`/`payoff` were bare centered text the entire time.
   Short #2's mechanism narrated 47.5s of continuous speech against one single static screen
   with zero visual change. The underlying SCRIPT was never thin (176-209 words, ~90-100s, a
   complete 4-part arc, confirmed by direct inspection) -- but the rendered preview looked like
   "just a few sentences" because of how little of each screen the merged-paragraph layout
   actually used.

   **Fix (`html_synth/vertical_assembler.py`):** each sentence now renders as its own visually
   distinct "beat" -- a colored bar sized to that sentence's own share of the segment's words
   (a real pacing cue, not decoration) above its own text block, with a short staggered fade-in
   on load. A `~Ns` duration badge (from the segment's own already-computed `est_seconds`, no
   new LLM call) now sits next to each screen's label. No new data, no new infrastructure --
   purely a richer render of what `SceneNarration` already carried. Rendered a real short (#2)
   through Playwright before/after to confirm: the mechanism screen went from one flat paragraph
   to a diagram plus 5 distinct beats filling most of the frame.

2. **Subscribe/bridge gap.** In the v08 run, all 5/5 shorts landed `goal=DISCOVERY` and
   `bridge.mode=NONE` -- literally none of them gave a viewer a follow-up ask or pointed back to
   the parent video. Plan §20.1's own table says all three goals (`DISCOVERY`/`BRIDGE`/`SERIES`)
   "grow the channel, but differently" -- a batch landing 100% `DISCOVERY` forgoes two of the
   three growth levers, directly working against the stated goal of a short ("should help me get
   more subscribers").

   **Fix (`planning/short_planner.py`, A2s's `TASK_PROMPT`):** two additions, both framed as
   corrections to a demonstrated batch-level bias rather than a hard quota (preserving the
   existing, still-correct "don't force a bridge that weakens the ending" principle) --
   (a) the `goal` bullet now names the live 100%-DISCOVERY evidence and asks the model to
   honestly check whether a candidate's own payoff already gestures at a bigger question or a
   next piece before defaulting to DISCOVERY; (b) the `bridge` bullet now explicitly says NONE
   for every short in a batch is its own bias, and that a single <=8-word SPOKEN/ONSCREEN follow
   line is cheap when the payoff genuinely supports it (subscribe is explicitly allowed to be
   "earned" here per §20.1).

**Tests:** `tests/orchestration/test_shorts_pipeline.py` (ERR-071 -- TTS degradation reaches
`result.log`; `degraded_capabilities` round-trips through `save_short_debug`'s persisted JSON),
`tests/html_synth/test_vertical_assembler.py` (3 new -- each sentence renders as its own beat,
not merged; beat-bar width reflects each sentence's real share of the segment's words; each
screen shows its own estimated duration), `tests/planning/test_short_planner.py` (2 new -- the
100%-DISCOVERY evidence and the "two of three growth levers" framing are in the prompt; the
follow-line encouragement and its 8-word cap are in the prompt). Full suite: **1076 passed, 16
deselected** (up from 1071).

- [x] ERR-071 fixed and unit-tested
- [x] Per-sentence "beat" rendering + duration badge built and unit-tested; visually confirmed
      via a real Playwright render of short #2 before/after
- [x] A2s's goal/bridge prompt strengthened against the live 100%-DISCOVERY/NONE evidence
- [ ] **Live-verify not yet done** -- the next `--resume` run is the natural way to confirm the
      goal/bridge prompt change actually produces variety (not just a plausible-sounding prompt
      edit) and that the denser rendering looks right across all 5 real shorts, not just #2.

**Update (same day) — see ERR-073 (ERROR_LOG.md):** requested as 3 more rounds of review,
specifically to find bugs blocking good shorts scripts. Found one signal-loss bug per round, all
three feeding the same subscriber-growth goal this phase started fixing:
1. `ShortsCandidate.bridge_question` (a real signal SC already computes for exactly this
   purpose) was never named in A2s's own prompt -- reached A2s only as inert JSON.
2. SC's own `micro_arc_suggestion` had the same `problem_fix`-over-selection bias A2s's prompt
   was already fixed for one stage downstream (ERR-067) -- SC never got the same caution.
3. **The big one:** ONSCREEN/PLATFORM_LINK bridge modes rendered NOTHING anywhere. The narration
   prompt correctly withholds the bridge from spoken narration for these two modes on the
   promise it "will render as on-screen text elsewhere" -- but no field ever captured that text
   and no renderer ever drew it. Fixed with a new `ShortBridge.cta_text` field, a prompt
   requirement to fill it in, real rendering in `vertical_assembler.py` (a badge on the payoff
   screen), and a new advisory diagnostic (`check_bridge_cta_present`) for the case where the
   model still forgets. Without this fix, today's earlier goal/bridge prompt push (which
   actively encourages ONSCREEN as a good option) would have made things WORSE, not better,
   every time the model actually followed it.

Also confirmed, per explicit user request, that none of today's shorts-only changes touch
long-form (import-graph check + long-form's own test suites, all unchanged). Full suite:
**1086 passed, 16 deselected** (up from 1076).

**Update (same day) — see ERR-074 (ERROR_LOG.md):** requested as 3 more rounds of review,
this time explicitly aimed at bugs blocking good shorts SCRIPTS (not rendering/plumbing). Found
one real content-quality gap per round: (1) `grounding_verifier.py`'s C2b-sourced issues gave
the shorts rewrite one vague, three-option `recommended_intent` no matter which specific
problem fired -- fine for long-form (A3 re-synthesizes its own plan regardless), but shorts'
B2s sends `recommended_intent` to the rewrite verbatim, so vagueness there directly costs
rewrite quality; (2) `micro_payoffs` reached B1s as raw payload data with zero placement
guidance, a real plausible contributor to the recap/reserved-outro failure shape this pipeline
has repeatedly fought; (3) the shared `NARRATION_FACTUAL_INVARIANTS` fragment's own docstring
claimed it gave B2/shorts "equivalent language" to long-form B1's hedge rules, but only ever
ported the overclaim direction, never B1's "never hedge a verified claim" direction -- a real
documented-vs-actual gap, now closed. Confirmed both shared-file changes
(`grounding_verifier.py`, `factual_invariants.py`) are safe for long-form too. Full suite:
**1090 passed, 16 deselected** (up from 1086).

**Update (same day) — see ERR-075 (ERROR_LOG.md):** one more thorough review round. Found that
`verification/hard/grounding.py::check_grounding_policy`'s own "UNVERIFIED never in the
hook/ending" rule -- real, working, unit-tested logic -- was never actually enforced anywhere in
the pipeline's history: every call site (shorts' own `_run_review()`, and BOTH of long-form's
call sites in `orchestration/pipeline.py`) left its `hook_scene_ids`/`ending_scene_ids` params
at their empty defaults, silently disabling it. Fixed for shorts (unambiguous: a short's
segments are always exactly hook/setup/mechanism/payoff). Long-form's own two call sites have
the same gap but need real dynamic scene-id lookup logic to fix correctly -- deliberately left
as an open item (ERROR_LOG.md) rather than guessed at in a shorts-focused pass. Also found the
policy's own docstring names 5 protected locations but the function only ever implemented 2
(hook, ending) -- "central insight" and "important numeric result" have no code path at all, on
either format -- flagged as a second open item. Full suite: **1091 passed, 16 deselected** (up
from 1090). None of today's fixes (ERR-072/073/074/075) have been live-verified yet.

**Update (same day) — the v10 live-verification run:** `--resume` against v01 again, after
ERR-072 through ERR-076. 3 of 5 shorts landed `PASS_WARN` (same rate as v08), $0.09 total, no
crashes, no TTS/duration issues. Confirmed working correctly on real (not synthetic) output:
the revision cycle correctly reverted a rewrite that made things worse (short #3), and the
visual-density fix rendered correctly (screenshot-verified on short #4's mechanism screen).
Two of ERR-072/073's own prompt nudges did NOT visibly change behavior this run -- goal/bridge
stayed 100% DISCOVERY/NONE across all 5 shorts, and `problem_fix` micro_arc stayed
dominant (4 of 5) -- inconclusive from one run, not evidence the nudges failed, but not
evidence they worked either. The run surfaced one new, concrete bug: short #1 FAILed with 4
`ungrounded_factual_sentence` hard failures and `revisions_used: 0` -- the targeted rewrite
never even attempted a fix, because `GroundingViolation`s were never converted into the
`CritiqueIssue` shape the rewrite trigger actually checks. Fixed same-day as **ERR-077**
(ERROR_LOG.md) -- full suite **1092 passed, 16 deselected**.

---

## Phase 22 — Gemini cost reduction: escalation-gate the review stack instead of routing Pro by default (P1, not adopted blind)

**Status: steps 1-2 implemented and unit-tested (2026-09-16); steps 3-6 not started;
live-verify pending -- next real run should exercise both together (escalation-gating +
`--c2b-audit-sample-rate`) before continuing to step 3.**

**Motivation, grounded in real spend data (2026-09-16 cost audit, all 42 `usage.jsonl` files
across every run in `project/`):** total spend across this project's history is $31.48; $18.33
of that (58%) is Gemini. Of the Gemini spend, `gemini-3.1-pro-preview` (`gemini_review_strong`)
alone is $15.20 (83% of all Gemini spend) across 430 calls, against `gemini-3.6-flash`
(`gemini_review_flash`)'s $3.13 across a similar 439 calls -- the gap isn't primarily list
price (pro-preview is ~2.7x flash on input, ~3.2x on output) but that pro-preview is the
**unconditional default**, not an escalation, for long-form's C1 (story critic), C2b
(grounding fidelity), C2a (claim verification), and the Gemini side of C4b/c/d -- unlike C3/C5,
which already default to flash. Compounding this: even at `reasoning_effort: "low"`,
pro-preview burned 450,857 reasoning tokens across those 430 calls (54% of its own output,
~$5.41) -- flash's own `reasoning_effort: "none"` config avoids this entirely. Shorts already
runs its whole review stack (CM, C2b, C1s, C4s) on flash only and was not part of this finding.

**Non-goal:** this is a cost change, not a quality change. Every step below keeps an
independent-model-family review in the loop (the reason `review_lead` is Gemini and not
Sonnet/Haiku in the first place, per `agents/review_lead.py`'s own docstring) -- the goal is
routing *which* Gemini tier handles the routine case, never removing the review itself.

### Ordered plan

- [x] **1. Escalation-gate C2b first -- implemented 2026-09-16.**
      `review/grounding_verifier.py::verify_grounding()` gained an optional `escalate_to: Agent
      | None = None` parameter: when given, `review_lead` (now `agents.cm_agent`, flash) runs
      the dense first pass over every sentence as before, then `_needs_escalation()` (mirroring
      `grounding_verdicts_to_issues`'s own branching -- `not supported`, `not
      qualifier_preserved`, `not scope_preserved`, or a set `violation_code`) selects the
      flagged subset, which gets a second, independent pass through `escalate_to` (now
      `agents.review_lead`, strong) -- the strong tier's own verdict wins outright for those
      sentences. `None` (the default) preserves the original single-tier behavior exactly, so
      `html_pipeline.py`'s own `verify_grounding` call (already flash-only via `visual_auditor`)
      and shorts' own call (flash-only by design, nothing to escalate FROM) are both untouched.
      The retry-once-then-fail-closed coverage guarantee (Phase 10) was extracted into a shared
      `_run_c2b_pass()` helper so the escalation pass gets the IDENTICAL guarantee, not a
      weaker one -- a missing escalation verdict raises `ReviewCoverageError` too, just as a
      missing first-pass one always has.
      **Resolved the "uncertain" gap**: didn't add a distinct state -- the existing four
      boolean/violation fields already cover every case `grounding_verdicts_to_issues` would
      otherwise turn into a hard/critical finding, and escalating exactly those (no more, no
      less) keeps the two decisions -- "does this need a human-legible finding" and "does this
      need a second opinion" -- pointed at the same evidence instead of inventing a second,
      possibly-inconsistent threshold.
      `orchestration/pipeline.py::PipelineAgents`'s own inline comments updated to reflect
      `cm_agent` is now C2b's primary pass, `review_lead` its escalation partner (was
      previously "no cheap tier" per plan §2.2 -- now C1 only, until step 3).
      Tests: `tests/review/test_grounding_verifier.py` (6 new -- a clean pass never calls the
      escalation agent; an escalated verdict wins over flash's own; only the flagged subset is
      re-sent, not every sentence; all three violation-shaped triggers escalate;
      `escalate_to=None` preserves the original behavior; a missing escalation verdict fails
      closed with "escalation" in the error, not silently trusting flash). Full suite: **1099
      passed, 16 deselected** (up from 1093).
      **Not yet live-verified** -- deliberately held until step 2's audit mechanism exists,
      so the first real run against this exercises both the saving and its own safety net
      together, not the saving alone.
- [x] **2. Random-audit mechanism -- implemented 2026-09-16.**
      `review/grounding_verifier.py::audit_clean_verdicts()`: given the final (post-escalation)
      `GroundingVerdict`s, samples `sample_rate` (default `DEFAULT_AUDIT_SAMPLE_RATE = 0.10`,
      matching the cost doc's own suggested starting point) of the sentences flash called
      clean (i.e. NOT already escalated under step 1 -- auditing an already-escalated sentence
      would double-count, not measure anything new), re-runs just that sample through the
      strong tier, and reports `GroundingAudit` (`sampled_count`, `disagreement_count`, a
      `disagreement_rate` property, and per-sentence `GroundingAuditFinding`s carrying both
      opinions side by side). "Disagreement" = the strong tier would itself have flagged
      (`_needs_escalation`) a sentence flash called clean -- exactly the kind of miss
      escalation-gating exists to avoid, now measured instead of assumed. Reuses the shared
      `_run_c2b_pass()` helper from step 1, so the audit gets the identical retry-once-then-
      fail-closed coverage guarantee, not a separate, weaker one.
      **Wired into `run_pipeline.py`** as an opt-in `--c2b-audit-sample-rate` CLI flag
      (default `0.0`, off) -- deliberately NOT on by default, since it's a new, not-yet-proven
      measurement tool, not something that should add cost to every production run before its
      own signal is trusted. When enabled, runs once after the story+narration loop concludes
      (using the final, already-accepted narration's own grounding metadata directly -- no
      second CM pass needed) and writes `reviews/c2b_audit.json`, matching the plan's own
      "review_bundle.json-adjacent artifact" framing as a separate file rather than a new
      `ReviewBundle` field (avoids touching the loop's several distinct exit paths). **Known,
      deliberate scope limit**: only runs alongside a FRESH story-loop computation, not a
      `--resume`-d one that skips straight to a checkpointed result -- acceptable since the
      audit's own point is measuring THIS run's flash-vs-strong agreement, not something a
      resumed run's own already-checkpointed result changes.
      Tests: `tests/review/test_grounding_verifier.py` (7 new -- zero sample rate never calls
      the audit agent; only clean (non-already-escalated) verdicts are sample-eligible; full
      agreement reports zero disagreement; a real disagreement is counted and surfaced with
      both opinions in the finding; sample size rounds to the nearest sentence count; the
      audit's own coverage fails closed too), `tests/orchestration/test_run_pipeline.py` (3
      new -- disabled by default, no call and no file; enabled writes the file with the given
      sample rate; a resumed story loop never runs the audit). Full suite: **1108 passed, 16
      deselected** (up from 1099).
      **Not yet live-verified.**
- [ ] **3. Escalate C1 and C2a the same way, once C2b's audit numbers look clean.**
      Deliberately sequenced after 1-2, not alongside them -- C2b is the pass with the clearest
      per-sentence verdict shape to escalate correctly; C1 (whole-narration story critique, not
      per-sentence) and C2a (claim verification against source/references) each need their own
      escalation criteria worked out (e.g. C1: escalate on `critical` severity or low
      confidence, not per-sentence; C2a: escalate CORE/ambiguous/conflicting claims, matching
      the cost doc's own §4 routing sketch) rather than reusing C2b's exact trigger logic
      unmodified.
- [ ] **4. Move CM to Haiku.** Independent of 1-3, lower risk, frees cost outright rather than
      reducing it. `review/claim_mapper.py`'s own module docstring already states CM's job is
      now "mechanical: is this factual, which claim IDs plausibly support it" (post-Phase-10
      dense/fail-closed redesign) -- exactly the kind of structured-output task Haiku already
      handles elsewhere in this pipeline (S1, S2b, SC). Needs verifying Haiku's own structured-
      output reliability holds up against CM's fail-closed sentence-coverage requirement
      (`ReviewCoverageError` on any missing verdict) before switching -- not assumed identical
      to Gemini flash's behavior just because both are "cheap tier."
- [ ] **5. Context caching -- blocked on a real capability check, done now:** confirmed via
      direct inspection of `llm/client.py` and `llm/backends/*.py` that this pipeline reads
      `cache_read_tokens`/`cache_write_tokens`/`cache_hit` FROM provider responses (for
      reporting) but never REQUESTS caching anywhere -- no cache-control parameter, no
      structured cached-prefix/variable-suffix prompt shape, on any call, to any provider. This
      confirms the real blocker precisely: caching needs new client-level plumbing before any
      prompt restructuring (the cost doc's own §13 CACHED PREFIX / VARIABLE SUFFIX shape) can
      do anything. Sequence this after 1-4 -- it's a real, evidence-backed saving (zero cache
      hits across 869 real Gemini calls to date, against claim-registry payloads that repeat
      near-verbatim across every CM/C2b batch within one run), but it's new infrastructure, not
      a routing change, and shouldn't block the routing wins above.
- [ ] **6. Batch mode -- last.** Real ~50% per-token discount (Gemini's batch pricing), but
      this pipeline calls every agent synchronously (`agent.run()` blocks and returns) --
      adopting batch mode means a genuinely different call pattern (submit, poll for
      completion later), not a config value. Sequenced last because it changes *how* the
      pipeline calls models, not just which model/tier it calls, and mixing that change in with
      1-5 would make it hard to attribute a quality or cost shift to the right cause.

**Explicitly not in scope for this phase:** switching C1/C2b off Gemini entirely (defeats the
adversarial cross-family review design on purpose), and any change to `story_lead`'s own
model/tier (a separate decision, see Phase 4 and its 2026-09-16 override).

**Verification, once implemented:** the hard acceptance criteria from the cost-optimization
doc are the right bar and should become real test/audit assertions, not just numbers to
eyeball -- `missing grounding verdicts = 0`, `unsupported CORE claims = 0`, `REJECTED claims
narrated = 0`, `critical factual errors = 0`, `title/story scope mismatch = 0`. A live
before/after comparison run (same source, same checkpoint via `--resume`) should show total
Gemini spend meaningfully down (informal target: 40-60%, per the cost doc's own §19) with those
five criteria unchanged, before this phase is marked done.

---

## Phase 23 — Script quality: hook/retention/compactness/voice/grounding scored against a real generated script (P0, user-reported)

**Status: every planned item implemented and unit-tested as of 2026-09-16** -- the CTA band,
the hook/ending echo requirement, the one-idea-per-sentence rule, the causal-connector/
rhetorical-device cap in both long-form AND shorts, C5's own prompt gap, the C040/grounding
root-cause fix (ERR-079), the two new diagnostics (`check_time_to_primary_payoff`,
`check_sentence_density`, the latter applied to both long-form and shorts), the B1
airtime-target recalibration (excluded from `beat_airtime_outliers`'s distribution), the
cross-short "the real fix is/works" phrase fix (ERR-080), and the bridge/goal selection
measurement (`check_bridge_selection_defaulted`). Full suite: **1149 passed, 17 deselected**.
**Live-verified 2026-09-16** (`video-01-attention-phase23-verify/runs/v03`, resumed from
`v02`'s checkpoint to avoid re-paying for claims/A1): real wins confirmed --
`cta.position` GREEN (was RED), `pacing.time_to_primary_payoff` GREEN at 11% of runtime (was
45.5%), `compactness.sentence_density` GREEN at 0/115 flagged sentences (was rampant), hook/
ending now genuinely echo each other, and the cross-short "the real fix is/works" phrase is
gone from all 5 shorts sampled. Also surfaced 4 real follow-up problems (one a genuine
regression from this phase's own web-search fix) -- see **Phase 24** for the fixes.

**Motivation:** a full read of a real generated long-form script
(`video-01-attention-phase22-verify/runs/v01/html/video_script.html`, 2026-09-16), scored
against real YouTube-script standards and cross-checked against the run's own
`review_bundle.json` (not just impression): Hook 8.5/10, Retention 5.5/10, Compact writing
6/10, Human narration 5/10, Technical grounding 6/10. User's own framing: shorts are worse
than this baseline, so the long-form script is the right place to fix root causes shared
narration infrastructure means both inherit. Every item below traces to something either
independently measured by an existing diagnostic or directly observed in the real script --
no speculative fixes.

### A. Retention (5.5 -> 9+)

- [x] **CTA position -- implemented 2026-09-16.** `planning/story_planner.py`'s `TASK_PROMPT`
      now states the 20-40% target band directly, citing the real RED finding as evidence
      (mirrors this session's own recurring "the critic knows a rule the generator was never
      told" pattern, e.g. the shorts `bridge_question`/problem_fix fixes). Test:
      `tests/planning/test_story_planner.py::test_prompt_gives_the_cta_position_target_band`.
- [x] **`check_time_to_primary_payoff(plan, target_duration_seconds)` -- implemented
      2026-09-16.** New diagnostic in `verification/diagnostics/pacing.py`, mirroring
      `_hook_scene_seconds`'s own first-occurrence-by-construction pattern: walks cumulative
      narration seconds through the FIRST beat marked `payoff=True` (the same marker
      `verification/hard/structure.py::check_cta_placement` already treats as "the first beat
      that actually earns a payoff"), banded as a fraction of the plan's own
      `target_duration_seconds` (GREEN <=35%, AMBER <=50%, RED beyond) -- calibrated against
      the real ~45.5% (5:00/11:00) example that motivated this item. Wired into
      `orchestration/pipeline.py::_run_review_block`. Tests:
      `tests/verification/diagnostics/test_pacing.py` (8 new).
- [x] **B1 (hook) airtime recalibration -- decided and implemented 2026-09-16.** Confirmed by
      design, not a defect: plan §10.2's own "the interesting event happens immediately" means
      a hook is deliberately brief, not a proportional tour of its claims. Same recalibration
      precedent as shorts' `SETUP_LENGTH_TARGET_SECONDS` (ERR-068) -- decided to EXCLUDE the
      first beat from `check_beat_airtime_outliers`'s distribution entirely (not just exempt it
      from being flagged, which would still let it skew the median every other beat is judged
      against). Test:
      `tests/verification/diagnostics/test_pacing.py::test_the_first_beat_is_excluded_from_the_distribution_entirely_even_as_an_outlier`.

### B. Compact writing (6 -> 9+)

- [x] **`check_sentence_density(narration)` -- implemented 2026-09-16.** New
      `verification/diagnostics/compactness.py` (no deterministic check for sentence density
      existed anywhere before this, confirmed via direct search). Advisory only, AMBER at most
      -- matches `check_voice`'s own permanent AMBER-cap precedent -- flagging sentences
      >= 50 words (the low end of the confirmed real 50-62 word range) that also carry 2+
      independent clauses (a cheap heuristic: a comma before a coordinating/subordinating
      conjunction, a semicolon, or a dash). Wired into both long-form
      (`orchestration/pipeline.py::_run_review_block`) and shorts
      (`verification/diagnostics/shorts.py::check_short_diagnostics`, Phase 23 item 8 --
      reused as-is, no shorts-specific threshold, since a 50-word sentence matters even more in
      a short's much smaller total word budget). Tests:
      `tests/verification/diagnostics/test_compactness.py` (8 new),
      `tests/verification/diagnostics/test_shorts.py::test_check_short_diagnostics_includes_sentence_density`.
- [x] **Prompt fix -- implemented 2026-09-16, shipped before the diagnostic as planned.**
      `narration/generator.py`'s `TASK_PROMPT` now requires exactly one idea per sentence,
      citing the real 60-62 word examples found. Test:
      `tests/narration/test_generator.py::test_prompt_requires_one_idea_per_sentence`.

### C. Human/natural narration (5 -> 9+)

- [x] **Root cause confirmed live, not guessed, and fixed 2026-09-16.** C5 (style critic)
      already runs on this exact script (voice was AMBER) and already caught a real tell
      ("here's the catch" / "there's a problem" / "here's why" transition-crutch repetition,
      `minor` severity) -- but its own `TASK_PROMPT` (`review/style_critic.py`) never named
      causal-connector chains or a repeated antithesis construction as tells to look for, even
      though `verification/diagnostics/voice.py`'s own `check_voice` independently measured
      BOTH as out-of-band on this same script (`causal_per100w=1.93` vs target 0.44-1.61,
      `burstiness=0.29` vs target 0.44-0.66) and this read independently found the "not X, but
      Y" construction repeated 6+ times across the script (B4_s03/s04, B9_s01/s02, B11_s04,
      B12_s04). C5 running and STILL missing what the mechanical diagnostic already measured
      was the same "critic prompt vocabulary gap" shape as ERR-072/074's own findings this
      session. Fixed: both patterns now named explicitly in C5's `TASK_PROMPT`, citing the
      same measured dimensions `check_voice` computes. Also applied the same causal-connector/
      repeated-device cap directly to the GENERATOR prompts (`narration/generator.py` and
      `narration/short_generator.py`) -- addressing this at the source, not only via a critic
      that has to catch it after the fact. Tests:
      `tests/review/test_style_critic.py::test_prompt_names_causal_connector_chaining_and_repeated_rhetorical_devices`,
      `tests/narration/test_generator.py::test_prompt_warns_against_overusing_causal_connectors_and_repeated_rhetorical_devices`,
      `tests/narration/test_short_generator.py::test_prompt_warns_against_overusing_causal_connectors_and_repeated_devices`.
- [ ] **Consider whether a style issue that corroborates a real measured AMBER/RED voice band
      should outrank `minor` severity.** Today's finding (a real, repeated tell) was `minor`
      -- unclear whether `minor` issues ever actually reach a targeted rewrite given a bounded
      revision budget prioritizes higher severities first. Investigate whether this is why the
      pattern survived to the final script despite being caught.
- [ ] **`check_voice`'s permanent AMBER cap** (`verification/diagnostics/voice.py`'s own
      docstring: "a corpus this small (6 documents) doesn't license an automatic hard
      failure") -- revisit only if the corpus has genuinely grown since V1D's original fit,
      not on the strength of this one script alone.

### D. Technical grounding (6 -> 9+)

- [x] **Root cause diagnosed and fixed 2026-09-16 -- see ERR-079 (ERROR_LOG.md).** Claim C040
      (CORE importance, UNVERIFIED, `provenance_status=SOURCE_EXPLICIT`, `evidence=[]`) is a
      well-documented mathematical fact (self-attention's permutation equivariance) --
      confirmed a C2a infrastructure gap, not an A2b content-selection problem:
      `references_dir` is empty and `web_backend` is never passed by the real CLI, so C2a has
      never had a real evidence source on any run, ever. Fixed by enabling native, hosted
      Gemini web search (`tools=[{"googleSearch": {}}]`, confirmed real via
      `litellm.supports_web_search()` and a live smoke test) on C2a's own verification call,
      end to end (`llm/backends/litellm_backend.py` -> `llm/client.py` -> `agents/base.py` ->
      `facts/verify.py`). The live smoke test itself caught a real bug before this ever
      reached the pipeline (an ad-hoc `max_tokens=200` left zero room once reasoning was
      added on top of search, returning empty content -- the same failure shape as ERR-021)
      -- confirmed the REAL production config (default `max_tokens=4096`,
      `reasoning_effort="low"`) works correctly. Full suite: **1122 passed, 17 deselected**.
      **Not yet live-verified against the full pipeline** -- confirmed working in isolation
      via the smoke test; a real C2a run checking whether C040 itself actually moves to
      VERIFIED is still pending.
- [x] **`hook_promise_unpaid_by_ending` -- implemented 2026-09-16.**
      `planning/story_planner.py`'s `TASK_PROMPT` now explicitly requires `ending.resolve_hook`
      to echo `hook.promise`'s own concrete terms, not just stay thematically related --
      citing the real failure directly, the same "shared concrete language" principle already
      used for shorts' own title-alignment check
      (`verification/hard/shorts.py::check_title_hook_payoff_alignment`). Test:
      `tests/planning/test_story_planner.py::test_prompt_requires_the_ending_to_echo_the_hooks_own_concrete_terms`.

### E. Shared benefit for shorts (the user's own explicit concern: "shorts are worse")

- [x] **Implemented 2026-09-16, alongside section C's fix, not as an afterthought.**
      `narration/short_generator.py`'s `TASK_PROMPT` gained the same causal-connector/repeated-
      device cap as long-form, adapted for shorts' own scale ("a repeated tell is far more
      noticeable at 90 seconds than at 15 minutes"). Test:
      `tests/narration/test_short_generator.py::test_prompt_warns_against_overusing_causal_connectors_and_repeated_devices`.
- [ ] Shorts have no style/voice critic at all today (`review/short_critic.py`'s own prompt is
      purely structural -- micro-arc fit, one mechanism, no reserved outro, hook delivery,
      self-containedness -- confirmed via direct read). Given a short's much shorter length
      makes any single repeated tic proportionally more noticeable, decide whether shorts need
      their own lightweight style check, or whether the shared generator-prompt fix (above)
      is sufficient leverage without a new agent call -- don't build a new pass ahead of
      evidence that the prompt fix alone isn't enough.
- [x] **Cross-short "the real fix is/works" template phrase -- fixed 2026-09-16, see
      ERR-080.** Real evidence: 4 of 6 real shorts sampled across two runs (v08, v10), all
      `problem_fix` arc, used this exact transition into the mechanism verbatim or near-
      verbatim, across unrelated topics -- a repetition tell that spans a channel's OUTPUT, not
      just one script's own internal repetition. `short_generator.py`'s `problem_fix` guidance
      now names the phrase directly and requires varying the transition every time. Test:
      `tests/narration/test_short_generator.py::test_prompt_warns_against_the_real_fix_template_phrase`.
- [x] **Bridge/goal selection escalated from a prompt nudge to a real measurement --
      implemented 2026-09-16.** ERR-072's prompt nudge showed 0% variation (100%
      goal=DISCOVERY/bridge=NONE) across two full verification rounds (v08, v10, 10 shorts) --
      real evidence a prompt-only nudge isn't enough, the same shape of evidence that justified
      Phase 20's escalation from prompt-only to a real mechanism. New
      `planning/short_planner.py::check_bridge_selection_defaulted(candidates, plans)`: a
      deterministic, non-LLM check that logs (never overrides) when a batch lands 100%
      DISCOVERY/NONE despite the shortlist having a real `bridge_question` signal available --
      "measure before gating," the same discipline behind Phase 22's own audit mechanism.
      Wired into `orchestration/run_pipeline.py` right after `plan_shorts()`. Tests:
      `tests/planning/test_short_planner.py` (5 new),
      `tests/orchestration/test_run_pipeline.py` (2 new wiring tests).

**Verification:** re-run against the same source (fresh, not `--resume`, since A2/A2b prompt
changes affect the story loop itself) and re-score the resulting script against the same 5
dimensions plus the real diagnostic values (`cta.position`, `pacing.beat_airtime_outliers`,
`voice.causal_per100w`/`burstiness`) -- the numbers should move, not just the subjective read.
Track whether `hard_failures` for `hook_promise_unpaid_by_ending` and the C040-shaped
grounding violation actually clear, not just whether the overall `final_status` looks better
for unrelated reasons.

---

## Phase 24 — Fix the 4 problems Phase 23's live-verify surfaced (P0, one a real regression)

**Status: all 4 items implemented and unit-tested, 2026-09-16.** Full suite: **1163 passed, 17
deselected** (up from 1149). Live-verify pending -- needs one more run (resumed from `v03`'s
own checkpoint per the user's explicit "save API money, resume don't restart" directive) to
confirm the numbers actually move. Plan file: `.claude/plans/precious-brewing-kitten.md`.

**Motivation:** the Phase 23 live-verify run (`runs/v03`) confirmed real wins but also
surfaced 4 concrete problems, one a genuine regression from Phase 23's own web-search fix:

1. **C2a silently dropped 21/80 claims (26%) from verification -- a real regression.**
   Enabling native web search made each claim's verdict far more verbose; a 40-claim batch
   to `gemini_review_strong` hit `output_tokens=4092`, 4 short of `LiteLLMBackend`'s hardcoded
   `max_tokens=4096` default, truncating the JSON response mid-batch. Dropped claims silently
   fell back to their pristine pre-verification defaults (UNVERIFIED, no evidence) with no
   error or log line -- this was very likely the direct cause of most of that run's 12 hard
   failures, and made "technical grounding" unmeasurable.
2. **Voice-repetition issues survived 2 full targeted-rewrite cycles.** `check_voice` was
   AMBER (burstiness 0.34) and C5 caught 12 sentences opening "So/Because/Since" plus 6 uses
   of "not X, but Y" in the FINAL emitted script. Root cause: the causal-connector/repeated-
   device cap shipped to `narration/generator.py` (B1) this same phase was never propagated to
   `editing/targeted_rewrite.py` (B2, the actual rewrite executor) -- same "the critic knows a
   rule the generator was never told" shape as ERR-072/074, except the GENERATOR knew it and
   the REWRITE executor didn't.
3. **Shorts: `setup` segments ran 1.1x-2.4x their diagnostic target** (14.8/25.4/30.9/24.5s
   across 4 arcs), and 3 of 4 FAILs traced directly to setup content (a missing naive-attempt
   beat, an ungrounded sentence). ERR-068's original 13.0s recalibration was based on "15-17.6s,
   observed once" -- a materially smaller sample than this round showed.
4. **Shorts: a title can satisfy the "reuse concrete hook words" rule in spirit and still fail
   the literal hard gate.** `verification/hard/text_overlap.py::overlap()` matches exact tokens
   only (no stemming) -- a title using "Equivariance" scored zero overlap against a hook using
   "equivariant," the same concept in a different grammatical form. Separately, the title
   prompt guarded against "too vague" and "too verbatim" titles but never against a title built
   entirely from jargon in `central_insight` with nothing pulled from the hook's own language.

### Fixes

- [x] **C2a truncation -- fixed.** `facts/verify.py`'s C2a verdict call (and its evidence
      re-verify call) now pass an explicit `max_tokens=12000`, mirroring
      `openai_story_strong_gpt56`'s own precedent that for a reasoning model this is a combined
      ceiling over hidden reasoning + visible output, not just the JSON. Also added
      `find_claims_with_no_verdict(claims)` -- a pure, deterministic check (a claim reaching the
      final registry with BOTH `verification_status="UNVERIFIED"` and `evidence=[]`, `Claim`'s
      own pristine defaults, can only mean no verdict was ever recorded for it) -- wired into
      `run_pipeline.py` right after `_build_claim_registry`, logging any dropped claim ids
      instead of silently degrading (matches ERR-078's "measure and surface" precedent). Tests:
      `tests/facts/test_verify.py` (6 new), `tests/orchestration/test_run_pipeline.py` (2 new
      wiring tests).
- [x] **Voice-repetition propagation -- fixed.** `editing/targeted_rewrite.py`'s `TASK_PROMPT`
      now carries the same causal-connector/repeated-device cap language as `generator.py`,
      plus an explicit note that B2 only sees the handful of scenes in its own batch, not the
      whole script, so a device fine in isolation may already be overused elsewhere.
      `editing/revision_planner.py`'s `TASK_PROMPT` (A3) now also tells the model to carry a
      critique issue's own `recommended_intent` specificity into its `rewrite_scenes` intent
      text rather than generalizing it away. The `_badness()` revision-acceptance comparator
      (ranks hard-failure count above issue-severity when deciding whether to keep a rewrite --
      cycle 2 of the `v03` run accepted a rewrite that dropped hard failures 16→12 while issues
      rose 4→6) is flagged, not fixed -- only one run's worth of evidence, and it's core
      revision-acceptance logic, not a scoped prompt fix. Watch on the next live run. Tests:
      `tests/editing/test_targeted_rewrite.py`, `tests/editing/test_revision_planner.py` (1 new
      each).
- [x] **Shorts setup-length -- recalibrated, plus the real content fix.**
      `verification/diagnostics/shorts.py::SETUP_LENGTH_TARGET_SECONDS` raised 13.0 → 18.0
      (GREEN band now covers the real 14.8-17.6s range confirmed across two live rounds; AMBER/
      RED still correctly separate the genuine 24-31s outliers). Separately, and more
      importantly, `narration/short_generator.py`'s per-`micro_arc` required-beat instructions
      now explicitly require stating that beat as ONE tight sentence, not elaborating it --
      the diagnostic recalibration is a measurement fix, this is the content fix. Tests:
      `tests/verification/diagnostics/test_shorts.py` (updated + 1 new),
      `tests/narration/test_short_generator.py` (1 new).
- [x] **Shorts title-alignment prompt gap -- fixed.** `planning/short_planner.py`'s `TASK_PROMPT`
      now names a third title failure mode (jargon-only, sharing nothing with the hook's own
      concrete language, citing the real "Permutation Equivariance Limitation" example) and
      explicitly warns that the word-overlap check does no stemming -- reuse the same
      grammatical form a word already appears in, not a different form of the same root. Tests:
      `tests/planning/test_short_planner.py` (2 new).

**Verification:** `.venv/bin/python3 -m pytest -q -m "not integration"` green (1163 passed, 17
deselected). Live-verify still pending -- resume from `v03`'s checkpoint (claims/source_brief
stages) once run, per the plan's own "resume, don't restart" directive; confirm `usage.jsonl`
shows no dropped-claim warnings, get the true technical-grounding hard-failure count now that
claims are actually verified, check whether the repetition count drops after a rewrite cycle,
check `short.setup_length` bands against the new target, and check whether the next shorts
batch's titles pass `title_hook_mismatch` cleanly.

---

## Phase 25 — Fix v04's remaining gaps + generalize a detailed external review's findings (P1)

**Status: all 8 items implemented and unit-tested, 2026-09-17** (7 fixes + 1 mitigation). Plan
file: `.claude/plans/precious-brewing-kitten.md`. Implemented phase-wise, one item at a time,
full suite green after each (never dropped below passing) -- one real, unrelated test
regression was caught and fixed mid-implementation this way (a legitimate desc-only card shape
that item 6's first draft would have wrongly flagged). Full suite: **1185 passed, 17
deselected** (up from 1163). Live-verify still pending.

**Motivation:** `v04` (Phase 24's live-verify) was the best long-form result this session --
PASS, 0 hard failures, every claim got a real verdict. It also got a detailed external human
review, written in terms of this script's own content (softmax math, RoPE, specific wording).
Per explicit user instruction, none of that content was hardcoded into any prompt -- every
finding below was traced to its underlying, topic-agnostic pattern and confirmed (or rejected)
by reading the real pipeline code and `v04`'s own `plan.json`/`review_bundle.json` first. Two
findings were rejected as not cheaply generalizable right now and are flagged, not fixed (see
the plan file's own "Flagged, not fixed" section).

- [x] **1a. "The real fix ___" template-phrase ban has a verb loophole -- fixed.** Rewritten to
      name the TEMPLATE ("The real fix ___", any predicate) instead of two literal verbs
      ("is"/"works"). Test: `test_prompt_names_the_template_as_a_pattern_not_just_two_verbs`.
- [x] **1b. Shorts' setup-conciseness instruction isn't landing -- strengthened.** Named the
      real failure shape (justifying/explaining the beat, not just its raw length) and gave a
      concrete word-count anchor (~15-20 words); the WHY now explicitly belongs in `mechanism`.
      Test: `test_prompt_names_justification_not_just_length_as_the_real_failure`.
- [x] **1c. "Fake naive attempt" pattern -- fixed.** `problem_fix` guidance now requires a
      naive attempt a real practitioner would actually try (not a strawman) that is enacted and
      shown failing, not explained away conceptually. Test:
      `test_prompt_requires_a_real_naive_attempt_not_a_strawman`.
      File: `narration/short_generator.py`. Full suite: **1166 passed, 17 deselected.**
- [x] **2. `StoryBeat.payoff=True` cardinality -- fixed.** `story_planner.py`'s `TASK_PROMPT`
      now reserves `payoff=True` for 1-3 truly central, video-level beats and wires the
      previously-dead `MiniPayoff`/`mini_payoffs` field in for the first time (smaller wins go
      there instead). New advisory diagnostic `check_payoff_beat_ratio`
      (`verification/diagnostics/pacing.py`, mirrors `check_beat_airtime_outliers`'s shape)
      measures the real ratio going forward (GREEN <=30%, AMBER <=50%, RED beyond). Tests:
      `tests/planning/test_story_planner.py`,
      `tests/verification/diagnostics/test_pacing.py` (4 new). Full suite: **1170 passed, 17
      deselected.**
- [x] **3. Title-vs-`scope_contract.must_cover` gap -- fixed.** New advisory diagnostic
      `check_title_scope_coverage` (`verification/diagnostics/retention.py`, reuses
      `verification/hard/text_overlap.py::overlap()`) flags when a majority of `must_cover`
      items share no real content with the title -- deliberately advisory (a hard check in
      `verification/hard/structure.py` would have made this an automatic hard failure, which
      single-run evidence doesn't yet justify). Also added `story_planner.py`'s first-ever
      title-selection guidance (`title.chosen` never had any prompt guidance before at all,
      unlike shorts' own hook-echo rule) -- check the chosen title against `must_cover` before
      finalizing it. Tests: `tests/verification/diagnostics/test_retention.py` (4 new),
      `tests/planning/test_story_planner.py` (1 new). Full suite: **1175 passed, 17
      deselected.**
- [x] **4. `mechanism_scope` scope-contradictions -- C1 prompt strengthened.** The existing
      "MECHANISM SCOPE" bullet only ever described a single scene stating its OWN condition
      wrong -- never a LATER scene silently narrating a more restricted/different version of an
      EARLIER scene's established mechanism scope (the real, live-missed shape). Added the
      "other direction" explicitly. No deterministic cross-scene check built (a real NLU
      problem, not attemptable at reasonable cost/risk). Test:
      `tests/review/test_story_critic.py::test_mechanism_scope_check_covers_a_later_scene_narrowing_an_earlier_one`.
      Full suite: **1176 passed, 17 deselected.**
- [x] **5. Ending beat recap-bloat -- fixed.** `scene_expander.py`'s prompt now warns that a
      beat with mostly-recap-remaining content should compress into 1-2 `recap` scenes, not
      allocate its usual scene count -- explicitly calling out the closing beat as where this
      matters most. New advisory diagnostic `check_recap_bloat` (`pacing.py`, mirrors
      `check_beat_airtime_outliers`'s per-beat shape) flags any beat where >50% of scenes are
      `scene_function="recap"` with empty `new_concepts`. Tests:
      `tests/planning/test_scene_expander.py` (1 new),
      `tests/verification/diagnostics/test_pacing.py` (4 new). Full suite: **1181 passed, 17
      deselected.**
- [x] **6. Nested comparison-card rendering bug -- fixed.**
      `verification/hard/render.py::check_component_slots_filled`'s nested-item scan
      (`grid_2`/`grid_3`, exactly the empty "Short/Long source sentence" cards found on `v04`)
      only checked keys ALREADY PRESENT in an item dict, so a title-only item (no "value"/
      "desc" KEY at all, not just blank) slipped through. Fixed narrowly: a title with
      NEITHER value NOR desc filled is now flagged (`title_only_no_supporting_content`) --
      deliberately narrower than "check every slot," since a legitimate desc-only or
      value-only card (already tested, already supported by `render_component()`) must stay
      unflagged. Tests: `tests/verification/hard/test_render_content.py` (2 new). Full suite:
      **1183 passed, 17 deselected.**
- [x] **7. CTA phrasing gap -- fixed.** `story_planner.py`'s CTA prompt section now explicitly
      warns against phrasing a same-video CTA as if the payoff is deferred elsewhere, citing
      the real "subscribe for how they combine" example. Test:
      `tests/planning/test_story_planner.py::test_prompt_warns_against_a_cta_that_implies_the_payoff_is_deferred_elsewhere`.
- [x] **(mitigation only) Narration-invented explanatory content -- prompt nudge added.**
      Confirmed: an incorrect WHY/HOW elaboration never passes through claim extraction/C2a at
      all, catchable only by critic judgment -- a real deterministic fix would need a new
      claim-extraction-from-generated-narration stage, not justified yet by one occurrence.
      `narration/factual_invariants.py` now states an explanation is itself new technical
      content, not exempt from grounding just because it's "explaining"; revisit with a real
      mechanism only if this recurs. Test:
      `tests/narration/test_factual_invariants.py::test_covers_explanatory_elaboration_as_needing_grounding_too`.

**All 8 items (7 fixes + 1 mitigation) implemented and unit-tested, 2026-09-17.** Full suite:
**1185 passed, 17 deselected** (up from 1163 at the start of this phase). Live-verify pending
-- one fresh (non-resumed) run once ready, per the plan's own verification section.

**Verification:** full suite green after each item; one fresh (non-resumed) live run once all
items land, checking the new diagnostics' real numbers and whether the rendering fix actually
eliminates title-only comparison cards in the output HTML.

---

## Phase 26 — Full pipeline audit: 10 confirmed bugs + design tensions + shorts gaps (P1)

**Status: all items complete, 2026-09-17.** Full findings report: `PIPELINE_AUDIT_2026-09-17.md`.
Three rounds of targeted review (core orchestration, shorts pipeline, verification/diagnostics,
then LLM backends/config/HTML synthesis as a fresh area), each confirmed by direct code read before
being recorded. Implementing phase-wise per the audit's own suggested triage order, full suite
green after each item.

- [x] **1. Shorts structural-hard-failure-to-rewrite gap -- fixed.** New
      `_hard_issue_to_critique_issue()` (`orchestration/shorts_pipeline.py`) converts only the
      genuinely narration-fixable codes (`duration_estimate_exceeds_max`,
      `measured_duration_exceeds_max` -> targets the longest segment;
      `claim_outside_allowed_fact_set` -> targets the cited scene) into rewrite-eligible
      `CritiqueIssue`s, kept OUT of `critique_issues` itself so `_format_hard_failures` never
      double-counts them. Plan-level codes (title mismatch, missing parent, no central insight)
      deliberately stay unconverted -- no narration rewrite can fix a bad title or a missing
      plan reference. Tests: `tests/orchestration/test_shorts_pipeline.py` (2 new). Full suite:
      **1187 passed, 17 deselected.**
- [x] **2. "hero" duplicate-DOM-id bug -- fixed at the root.** `config/design_system.yaml`'s
      `story_roles.hook` no longer offers `hero` (page-singleton, already rendered
      unconditionally by `assembler.py`) as a per-scene choice -- now just `[card]`. Root-cause
      fix rather than making the resulting duplicate-id issue repairable after the fact.
      Tests: `tests/html_synth/test_component_library.py` (1 new, 1 updated). Full suite:
      **1188 passed, 17 deselected.**
- [x] **3. `check_title_scope_coverage`'s overlap threshold bug -- fixed.** New
      `_item_reflected_in_title()` computes containment against the must_cover item's OWN word
      count specifically, not the symmetric shorter-side `overlap()` -- closes the exact "one
      incidental shared word clears the bar" hole verified directly (title="Self-Attention" vs.
      a 6-word item, one shared word previously scored 0.5, exactly at the old threshold).
      Tests: `tests/verification/diagnostics/test_retention.py` (2 new). Full suite:
      **1190 passed, 17 deselected.**
- [x] **4. `check_component_slots_filled` non-dict item gap -- fixed.** A new `elif
      isinstance(item, str):` branch flags a genuinely blank string item (`blank_string_item`)
      -- a legitimate non-blank string (the plain-observation shape `render_component()`
      supports) still passes. Tests: `tests/verification/hard/test_render_content.py` (1 new).
      Full suite: **1191 passed, 17 deselected.**
- [x] **5. Resumed-run cost under-count -- fixed, including `cost_report.json`.**
      `run_pipeline.py` now captures `carried_over_microusd` (the checkpoint's own
      claims/source_brief/loop spend) immediately after loading state, before any of this
      run's own stages can overwrite those fields -- always 0 for a genuinely fresh run.
      Both `total_cost_usd` computation points now add it in. Also threaded through to
      `cost_report.json` as a new, explicit `carried_over_usd` field (kept SEPARATE from
      `billed_usd`, preserving that field's own "reflects only this run's ledger"
      reconciliation invariant) and surfaced in `review_summary.md`. Tests:
      `tests/reporting/test_cost_report.py` (2 new),
      `tests/orchestration/test_run_pipeline.py` (2 new, confirming the exact carried-over
      math on a resumed run and zero on a fresh one). Full suite: **1195 passed, 17
      deselected.**
- [x] **6. `red_survived_a_round` -- fixed.** Design decision: "survived a round" means the
      SAME diagnostic dimension was RED immediately before a `TARGETED_REWRITE` attempt and is
      STILL RED once that attempt's review completes (whether kept or reverted -- a reverted
      rewrite trivially still carries the baseline's own REDs, correctly read as "not fixed").
      New `_red_dimensions(bundle)` helper (mirrors `_badness()`'s own precedent) tracked
      across loop iterations the same way `pending_rewrite_baseline` already is, reset on a
      REPLAN (a new plan's RED is a different plan's problem). All 4 `compute_final_status`
      call sites in the loop now pass it. Tests: `tests/orchestration/test_pipeline.py` (2
      new, one a full integration test via a monkeypatched `_run_review_block` proving a
      surviving RED alone -- with zero hard failures and red_count=1 -- forces a second A3
      consultation that would never happen without the fix; verified by temporarily reverting
      the fix and confirming this exact test fails). Full suite: **1197 passed, 17
      deselected.**
- [x] **7. `REPAIR_TASK_PROMPT`'s missing LaTeX-avoidance rule -- fixed.** Added the identical
      plain-notation rule the first-pass H prompt has, with an explicit note that a repair
      call has zero memory of the original ban (every `Agent.run` call is stateless). Test:
      `tests/editing/test_html_repair.py::test_repair_prompt_bans_latex_same_as_a_first_pass`.
      Full suite: **1198 passed, 17 deselected.**
- [x] **8. `LiteLLMBackend` model-pinning -- fixed, with a prefix match not exact.** New
      `LiteLLMModelMismatch`, mirroring `claude_cli.py::ModelMismatch`. Deliberately a PREFIX
      match (`_same_model_family`), not exact equality -- an existing test fixture revealed a
      real false-positive risk first: OpenAI legitimately resolves "gpt-4o-mini" to
      "gpt-4o-mini-2024-07-18" (a fully-dated version of the SAME model), which exact
      comparison would have wrongly raised on. Verified against 3 real live calls (OpenAI,
      Gemini flash, Gemini strong -- $0.0012 total) with the new check active, no false
      positives. Tests: `tests/llm/test_litellm_backend.py` (4 new). Full suite: **1202
      passed, 17 deselected.**
- [x] **9. `gemini_review_strong` max_tokens floor -- fixed.** Set `max_tokens: 12000` at the
      alias level in `config/models.yaml` (matching `openai_story_strong_gpt56`'s own
      precedent) so C1 and C2b's own escalation calls -- previously exposed to the identical
      bare-4096-default truncation risk ERR-081 fixed only for C2a's own per-call override --
      now get the same protection. Test: `tests/config/test_loader.py` (1 new). Full suite:
      **1203 passed, 17 deselected.**
- [x] **10. Schema-repair content-fidelity check -- fixed, opt-in.** New `warn_fn` parameter
      on `validate_with_repair` (default `None`, zero behavior change for any existing
      caller) compares list-field lengths between the original response and the final
      repaired one -- a repair that "fixes" validation by silently shrinking a list (the
      truncated-array-closed-early scenario) now surfaces a warning. `LLMClient._validate`
      wires `warn_fn=print` (no `log` callback threaded this deep; `print` reaches the same
      console `log=print`'s own default already writes to). Tests:
      `tests/llm/test_structured.py` (6 new), `tests/llm/test_client.py` (1 new, confirming
      the real wiring). Full suite: **1209 passed, 17 deselected.**
- [x] **Shorts: B2s "touched" scope -- fixed.** `apply_short_targeted_rewrite`'s merge now
      filters `rewritten_by_id` down to `touched` before applying anything -- a segment the
      model returned but was never requested is discarded, not silently applied. Test:
      `tests/editing/test_short_targeted_rewrite.py::test_an_extra_segment_the_model_returned_but_was_never_requested_is_ignored`.
      Full suite: **1210 passed, 17 deselected.**
- [x] **Shorts: segment completeness/uniqueness gate -- fixed.** New
      `check_segment_completeness()` (`verification/hard/shorts.py`, wired into
      `check_short_structure`'s aggregate) flags a missing or duplicated segment as a real
      `ShortHardIssue` -- not rewrite-eligible (B2s can only rewrite an EXISTING segment's
      text, never create a genuinely absent one from scratch), correctly stays a hard
      failure with no rewrite path, same category as `no_central_insight`/
      `missing_parent_reference`. Tests: `tests/verification/hard/test_shorts.py` (4 new).
      Full suite: **1214 passed, 17 deselected.**
- [x] **Visual monotony -- fixed with a cheap, deterministic, always-available diagnostic.**
      `review/visual_sequence_critic.py`'s existing LLM-based check stays (real, but sampled
      to screenshotted scenes and gated behind playwright). New
      `verification/diagnostics/visual_variety.py::check_consecutive_component_repetition()`
      runs on EVERY scene unconditionally (via `beat_visuals`, no LLM call, no playwright
      dependency), flagging a run of 4+ consecutive scenes sharing the same `component_id` --
      calibrated against the real reported case (8 near-consecutive card scenes). Wired into
      `HtmlSynthesisResult.visual_variety` at both construction sites and surfaced in
      `render_report.json` (same treatment as `entity_consistency`). Advisory only (AMBER at
      most), matching this project's own "layout-rhythm judgement call" precedent. Tests:
      `tests/verification/diagnostics/test_visual_variety.py` (8 new),
      `tests/orchestration/test_html_pipeline.py` (1 new wiring test),
      `tests/reporting/test_emit_html.py` (2 new). Full suite: **1225 passed, 17 deselected.**

**All Phase 26 items (10 numbered bugs + 2 shorts gaps + visual monotony) implemented and
unit-tested, 2026-09-17.** Full suite: **1225 passed, 17 deselected** (up from 1163 at the
start of this phase). Design tensions and improvement opportunities from the audit that were
NOT independently actioned are tracked in `PIPELINE_AUDIT_2026-09-17.md` itself. Live-verify
still pending -- one fresh (non-resumed) run once ready.

**Verification:** full suite green after each item (never dropped below passing); live-verify
once ready.

---

## Phase 27 — v05 live-verify findings: diagram-role bottleneck, intra-beat repetition, major-issue visibility (P1)

**Status: all items complete, 2026-09-17.** Three rounds of review on the real `v05` live-verify run (long-form
visual richness, human-narration score ceiling, shorts visual quality), each finding traced to
its root cause by direct code/data read before any fix was proposed.

**Motivation:** the user's own observation after rating `v05` -- "long form does not have nice
visuals like block diagram and human narration score is also less" -- led to 3 real,
precisely-sourced findings:

1. **Diagram-role bottleneck, not a model-avoidance problem.** Where `diagram_card` is legally
   offered (`archetype_role="mechanism"`), H picks it 83% of the time (5/6 mechanism-role
   scenes in `v05`). But only 3 of 12 beats (14.6% of scenes) got tagged `mechanism` in a video
   whose ENTIRE structure is a chain of mechanism steps -- everything else got tagged `payoff`/
   `comparison`/`derivation`/`problem_fix`, and `config/design_system.yaml`'s `story_roles`
   mapping gives those roles no access to `diagram_card` at all. Confirmed missed opportunity:
   `B07_complete_equation_s03` (role=payoff) narrates a 4-stage pipeline and rendered as a
   plain card purely because payoff's allowlist excludes diagrams.
2. **A real, dual-layer repetition gap.** `B06_sqrt_scaling`'s 3 scenes have genuinely distinct
   `new_concepts` (no planning duplication) -- but `scene_expander.py`'s `must_not_repeat`
   construction only propagates CROSS-BEAT (via `viewer_knows`), never sibling-to-sibling
   WITHIN the same beat's own multi-scene expansion call. Scene 3 was never told scenes 1-2
   (generated in the same call) already covered the setup, so narration fully re-derived it.
   Secondary, narration-level compliance gap: even the one concept correctly flagged in
   `must_not_repeat` (inherited from an earlier beat) still got fully re-derived despite
   `generator.py`'s own existing "one short clause, don't re-derive" instruction.
3. **`compute_final_status` never reads `bundle.issues` at all** -- confirmed by direct code
   read. A `major`-severity issue (repetition, pacing, anything C1/C5 find) can never force a
   fix on its own, no matter how many exist. Real, repeated evidence across this session's own
   runs (v03: 12 causal-openers, v04: 2, v05: 5; `v05` had 4 real uncorrected major issues) --
   the same "evidence across multiple runs" bar this project has used before to justify
   escalating a measurement into a real policy (ERR-072, Phase 20's rewrite cycle).
4. **Shorts have no per-segment visual system at all** (flagged, NOT scoped for this phase --
   see below) -- `vertical_assembler.py`'s own docstring says so explicitly ("no component
   library assembly"). All 5 real shorts in `v05` are structurally identical, one hardcoded
   diagram type on the `mechanism` segment only, regardless of content. `ShortVisual.safe_zones`
   is defined but never populated. This is a real, bigger feature gap (new data model fields +
   new assembler code), not a prompt/config fix -- explicitly deferred, see "Not in this phase."

### Fixes

- [x] **1. Diagram_card allowlist widened -- fixed.** `config/design_system.yaml`'s
      `story_roles` now includes `diagram_card` for `comparison`/`derivation`/`payoff` too,
      alongside their existing options. Test:
      `tests/html_synth/test_component_library.py::test_diagram_card_is_available_to_comparison_derivation_and_payoff_too`.
      Full suite: **1226 passed, 17 deselected.**
- [x] **2. Intra-beat sibling `must_not_repeat` propagation -- fixed, both layers.**
      `planning/scene_expander.py::expand_beat_scenes` now accumulates each scene's own
      `new_concepts` deterministically in Python (mirroring the existing cross-beat
      `viewer_knows` pattern) and merges them into every LATER sibling scene's own
      `must_not_repeat` -- never replacing what the model itself already listed, just adding
      to it. Also strengthened `narration/generator.py`'s existing derivation-scene
      instruction: a sibling scene within the same beat is now explicitly named as "exactly
      as off-limits to re-derive" as a concept from a different beat -- the real,
      live-confirmed secondary gap (compliance failure even where `must_not_repeat` WAS
      already correct). Tests: `tests/planning/test_scene_expander.py` (2 new),
      `tests/narration/test_generator.py` (1 new). Full suite: **1229 passed, 17
      deselected.**
- [x] **3. Major-issue-count visibility -- fixed, measurement only.** New
      `_major_issue_count(bundle)` (`orchestration/pipeline.py`) surfaces how many
      `major`-severity issues survive to the final bundle, logged at all 5 of the loop's own
      terminal exit points -- explicitly NOT wired into `compute_final_status`'s escalation
      logic this pass, matching this project's own "measure before gate" discipline. A real
      policy change (should N+ majors also force REVISE, mirroring "3+ REDs") needs real
      numbers across more runs before deciding, not one run's own 4 majors alone. Tests:
      `tests/orchestration/test_pipeline.py` (2 new -- the pure count function, and an
      integration test confirming a real major issue reaches the log without changing the
      outcome). Full suite: **1231 passed, 17 deselected.**

**All 3 Phase 27 items implemented and unit-tested, 2026-09-17.** Full suite: **1231 passed,
17 deselected** (up from 1225 at the start of this phase). The shorts per-segment visual
system remains explicitly out of scope (see above) pending its own design pass. Live-verify
still pending.

### Not in this phase (real, but bigger scope -- needs its own design pass)

- **Shorts per-segment visual system.** Would need new `ShortVisual` model fields (a visual
  per hook/setup/payoff, not just one hardcoded diagram on `mechanism`) and new
  `vertical_assembler.py` rendering code -- a real feature addition, not a mechanical fix.
  Flagged for a future phase once scoped properly, not attempted here under this phase's own
  narrower mandate.

**Verification:** full suite green after each item; live-verify once landed, checking the real
diagram_card pickup rate across payoff/comparison/derivation roles and whether the
`B06`-shaped repetition recurs.

---

## Phase 28 — Final pre-launch review: promotion, duplicate-scene collision, dead-field parity (P1)

**Status: all items complete, 2026-09-17.** Round 1 of a 3-round final pre-launch review (self-
review of Phase 26+27's own 16 touched files together, a dedicated reporting/emission-layer
audit, and a pre-flight sanity check) surfaced 5 real, confirmed items before the session's
final live-verify run. Each traced to root cause by direct code read against real data
(the real `runs/v04/final/` on disk, real `config/models.yaml` aliases) before any fix.

### Fixes

- [x] **1. `video_script.html`/`page.html` never reached `final/` at all -- critical, fixed.**
      `emit_html_deliverables()` was only ever called once, into `run_dir/"html"`; nothing
      copied those files into `run_dir/"final"` before `promote_to_final()` copies that
      directory verbatim. Confirmed live on real disk: a real promoted run
      (`project/attention_series/.../final/`) had every report *about* the script
      (`cost_report.json`, `plan.json`, `review_summary.md`, ...) but not `video_script.html`
      or `page.html` themselves -- exactly the deliverable "promotion" exists to produce.
      Fixed by writing a second, final-bound copy inside the promotion block
      (`run_pipeline.py`), mirroring how shorts already write directly into
      `run_dir/"final"/"shorts"/<i>`. Tests:
      `tests/orchestration/test_run_pipeline.py::test_html_deliverables_are_written_into_final_when_the_run_passes`,
      `::test_html_deliverables_are_not_written_into_final_when_the_run_does_not_promote`.
- [x] **2. Duplicate-`scene_id` collision in the shorts targeted-rewrite path -- fixed.**
      `editing/short_targeted_rewrite.py`'s `scene_by_id`/`rewritten_by_id` were both keyed
      purely by `scene_id`, with no de-duplication -- the exact anti-pattern Phase 26's own
      `check_segment_completeness()` was written to catch. A narration with a duplicate
      segment (a genuine malformed-output shape) combined with an independent critical
      `CritiqueIssue` naming that segment would silently lose one duplicate's content from the
      rewrite prompt, then overwrite BOTH duplicates with identical text -- "fixing" the named
      issue while leaving the real duplicate-segment defect in place. Fixed with a bail-out
      guard (same shape as the existing `if not touched: return narration` no-op). Test:
      `tests/editing/test_short_targeted_rewrite.py::test_duplicate_scene_ids_in_narration_are_a_no_op_not_a_silent_collision`.
- [x] **3. `sequence_critique_issues`/`late_narration_repairs_used` computed but never
      surfaced -- fixed.** The third recurrence of this exact bug class (already fixed twice
      for `entity_consistency` and `visual_variety`) -- `critique_visual_sequence()`'s
      (Phase 15, compositional-monotony) findings landed on `HtmlSynthesisResult` but
      `emit_html.py` never wrote them into `render_report.json`, and the H/HV log line never
      mentioned either field. Both now wired into `render_report.json` and the console log
      line. Tests: `tests/reporting/test_emit_html.py` (3 new: present-case + defaults-to-
      empty for `sequence_critique_issues`, present-case for `late_narration_repairs_used`).
- [x] **4. `_major_issue_count` parity gap between long-form and shorts -- fixed.** Phase 27
      item 3 gave long-form's `orchestration/pipeline.py` a major-issue-count log line but
      never applied the shorts analogue, despite `run_short` using the identical
      `CritiqueIssue.severity` taxonomy and `short_critic.py`'s own prompt explicitly defining
      "major = a real defect a viewer would notice." Added `_major_issue_count()` to
      `orchestration/shorts_pipeline.py`, wired into `run_short`'s terminal log line --
      measurement only, same as long-form, never wired into `compute_final_status`. Test:
      `tests/orchestration/test_shorts_pipeline.py::test_major_issue_count_counts_only_major_severity`.
- [x] **5. `_same_model_family`'s prefix match collided on two real, already-configured
      models -- fixed.** The Phase 26 fix's `a.startswith(b) or b.startswith(a)` check
      correctly absorbed a provider's dated-suffix response (`"gpt-4o-mini-2024-07-18"` for a
      request of `"gpt-4o-mini"`) but also treated `"gpt-4o"` and `"gpt-4o-mini"` as the same
      family, since one is a literal string-prefix of the other -- yet both are real, distinct
      `resolved:` values in `config/models.yaml` (`openai_story_strong` vs.
      `openai_story_mini`). A silent provider substitution between them, exactly the scenario
      `LiteLLMModelMismatch` exists to catch, would have passed silently. Replaced the bare
      prefix match with `_strip_trailing_version_suffix()` (drops only trailing
      purely-numeric hyphen tokens -- a date or build number, never a real distinguishing word
      like "mini") followed by exact-equality comparison. Test:
      `tests/llm/test_litellm_backend.py::test_a_sibling_model_substitution_sharing_a_string_prefix_raises_model_mismatch`.

**Flagged, not fixed (advisory-only, not a bug):** widening `diagram_card` into more roles
(Phase 27 item 1) combined with the new consecutive-component-repetition diagnostic
(Phase 26) makes a genuine AMBER false-positive-flavored flag somewhat more likely on a
mechanism-heavy video reusing `diagram_card` appropriately across several beats -- advisory
band only (never a hard gate), so watched via the upcoming live-verify's `render_report.json`
rather than pre-emptively tuned against a run that hasn't happened yet.

**Round 2** (verification of the 5 fixes above against real current code, plus a sweep for the
same "computed, never surfaced" bug class elsewhere): all 5 fixes confirmed sound -- correct
call order/placement, no attribute typos, no false-positive/false-negative on the model-family
and duplicate-scene guards, checked pairwise against every real `resolved:` value in
`config/models.yaml`. The sweep found 3 more instances of the same bug class:

- [x] **6. `HtmlSynthesisResult.repairs_used` reached only the console log, never
      `render_report.json` -- fixed.** Same parity gap as item 3, just missed the first pass.
      Test: `tests/reporting/test_emit_html.py::test_repairs_used_is_captured_in_the_report`.
- [ ] `ReviewBundle.run_id` is threaded through but its only call site always passes the
      hardcoded literal `"pipeline"`, never read by any reporting function -- real but inert
      (carries no information today); not fixed this pass, no live behavior depends on it.
- [ ] **Shorts' promoted `final/shorts/<i>/` carries no status at all** --
      `emit_short_deliverables` (`src/reporting/emit_short.py`) reads only `plan`/`narration`/
      `preview_audio` off `ShortRunResult`; `final_status`/`hard_failures`/`issues`/
      `diagnostics`/`degraded_capabilities`/`revisions_used`/`measured_duration_seconds` are
      all persisted only to the WORKING `runs/vNN/shorts/<i>/status.json` (`save_short_debug`),
      never emitted alongside the promoted short itself. Already flagged as known debt in
      `emit_short.py`'s own docstring ("quality/cost reports not wired up yet"). Real, but a
      bigger scope item (a short's own status/quality report, same shape as long-form's
      `review_summary.md`/`quality_report.json`) -- explicitly deferred, not attempted under
      this phase's mandate. Note this is NOT moot for the upcoming live-verify run --
      `--shorts-count 0` means "one short per candidate SC actually finds," not "skip
      shorts" (that's `--no-shorts`), so shorts will run and this gap is real for that run
      too; it's deferred because it's pre-existing, already-documented debt, not something
      Phase 26/27/28's own fixes touched or regressed.

**All 6 Phase 28 items implemented and unit-tested, 2026-09-17.** Full suite: **1240 passed,
17 deselected** (up from 1231 at the start of this phase). Round 3 (final go/no-go sanity
check) precedes the live-verify run.

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

## Phase 29 — Opus 5.5 story_lead comparison: rendering, component variety, and narration voice (P1)

**Status: all 4 items complete, 2026-09-24.** Triggered by adding `claude-opus-5-5` as an
interchangeable `story_lead` "strong"-tier alias (`--story-lead-alias opus`) and running a
real side-by-side comparison against the existing `openai_story_strong_gpt56` (gpt-5.6-sol)
default, both against the identical source (`video-01-attention-coherent-story.html`), same
downstream code. Opus's script was substantially more technically complete (mentions "dot
product" and the √d_k scaling; gpt-5.6-sol's mentions neither, and C1 flagged it as a
critical "vacuous teasers, no payoff" failure) but scored worse on 3 dimensions -- this
phase root-caused and fixed each one. Consulted the bundled `claude-api` skill's Opus 5.5
migration guide for model-specific guidance; its one directly load-bearing finding: Opus
5.5 "responds well to instructions that name specific patterns to avoid" rather than vague
ones (its own example: "avoid a generic AI look" doesn't work; naming exact patterns does)
-- informed items 3 and 4 below.

### Findings and fixes

1. **Visual component variety -- root cause confirmed, fixed.** Opus's plan tagged 6 of 13
   beats (46%) `archetype_role="problem_fix"`, and `problem_fix` in
   `config/design_system.yaml`'s `story_roles` allowed only `[step_list, callout_warn]` --
   zero diagram-capable options, the one role Phase 27 item 1's own `diagram_card` widening
   missed. A build-archetype video's problem->fix chain is very often itself a mechanism/
   pipeline/equation -- exactly Phase 27's own reasoning, just for a role it didn't reach.
   Fix: added `diagram_card` to `problem_fix`. Test:
   `tests/html_synth/test_component_library.py::test_diagram_card_is_available_to_problem_fix_too`.
2. **Formula-stage carry-forward (render issues) -- root cause confirmed, fixed.** H
   (`html_synth/synthesizer.py::synthesize_beat_visual`) never received `formula_stages` or
   any scene's `formula_stage_id` in its payload at all -- `verification/hard/
   formula_consistency.py` checks the rendered content for an earlier-registered stage's
   exact `expression`/`values` afterward, but nothing ever told H what that check would
   require. Not Opus-specific (a latent gap for any story_lead), just exercised harder by a
   plan that engages the running formula more. Fix: `_expected_formula_stage_by_scene()`
   computes the SAME "most advanced stage reached so far" the check itself computes,
   deterministically (duplicated rather than imported -- `formula_consistency.py` already
   imports `BeatVisual` from `synthesizer.py`, so the reverse import would cycle); threaded
   into each scene's payload as `required_formula_stage`, plus an explicit prompt
   instruction to include it verbatim. Tests: 4 new in `tests/html_synth/test_synthesizer.py`.
3. **Rendered page over the word-count band -- root cause confirmed, fixed.** Opus's spoken
   narration (2,249 words) was actually comfortably WITHIN its own deterministic per-scene
   word budgets (90% of the 2,501-word allocation, only 2 scenes >30% over); gpt-5.6-sol's
   narration used only 56% of the identical budget (1,402 words) -- consistent with finding
   1's "vacuous teasers" critique. The render-side word-count band
   (`verification/hard/render.py::READER_STANDALONE_WORD_BAND`, 2000-3200) was tuned against
   scripts shaped like gpt-5.6-sol's thinner ones; H (a stateless per-beat call) had zero
   numeric awareness of that whole-page ceiling at all, only qualitative "minimum needed"
   language. Fix: `_screen_text_word_budget_by_beat()`, a deterministic proportional
   allocator mirroring `planning/beat_word_budget.py`'s own pattern (proportional to scene
   count, band midpoint 2,600 as target), threaded into the payload as
   `beat_screen_text_word_budget` with an explicit prompt instruction to treat it as a hard
   ceiling. Tests: 2 new in `tests/html_synth/test_synthesizer.py`.
4. **Narration voice repetition ("so"-opener chaining) -- confirmed NOT Opus-specific,
   tightened.** Both the Opus run (major: causal_flow + repetition) and the gpt-5.6-sol run
   (major: recurring "so"-openers) hit this -- `narration_lead` is unchanged Sonnet in both,
   so this is a shared `narration/generator.py::TASK_PROMPT` gap, not a story_lead effect.
   The existing instruction ("a script where 'so' opens several sentences in a row reads as
   formulaic") is qualitative and had already proven insufficient on two independent real
   runs. Fix: added a hard numeric cap (no more than 2 "so"-openers and no more than 2
   "because"/"since"-openers across the WHOLE narration, no two consecutive sentences
   sharing a connector or rhetorical device) plus a concrete rewrite example. Test:
   `tests/narration/test_generator.py::test_prompt_gives_a_hard_numeric_cap_on_connector_repetition`.

**Full suite: 1261 passed, 17 deselected** (up from 1253 before this phase). Not yet
live-verified against a real run -- the next comparison run (either alias) is the real test
of whether all 4 fixes hold together.

**Live-verify update, 2026-09-25:** a fresh Opus 5.5 run (`v05`) confirmed all 4 fixes hold
together against a real run: 0 render issues (was 4), 3006 words (was 3377, over the 3200
cap), `diagram-card` usage doubled (30 vs. 15, `problem_fix` beats now use it), and only 1
"so"-opener across 138 sentences (was a flagged major issue). The story loop still FAILed,
but for an unrelated, pre-existing reason (~100 `grounding_policy_violation`s against claims
already sitting UNVERIFIED in the checkpoint's claim registry -- confirmed NOT a regression
from these fixes: both this run and the earlier comparison run resumed the identical,
unchanged claims checkpoint, so the difference is which claims THIS run's plan happened to
cite, not the verification data itself). A genuine, unrelated finding, not yet investigated.

### Item 5 (found via section-by-section scoring, not part of the original 4): hook open_loop

A full section-by-section score of Opus vs. gpt-5.6-sol's real output (12 sections, both
videos) found `hook.open_loop` (set by A2, `planning/story_planner.py`) was never once
referenced by either `planning/scene_expander.py` or `narration/generator.py` -- a real
"computed, never consumed" gap distinct from the report-emission version of this bug class
already fixed 4 times elsewhere this session. One real script happened to close its hook on
the literal `open_loop` question (the stronger hook craft -- ends on real, unresolved
curiosity); the other closed on a declarative restatement of the answer instead, purely by
chance, since nothing ever told the writer which to prefer. Fixed: `narration/generator.py`'s
`TASK_PROMPT` now explicitly instructs the hook beat's last scene to end on `open_loop`,
voiced as a genuine open question, never a resolved answer -- written generically (no
topic-specific quotes baked in, matching this project's own overfitting-guard discipline).
Test: `tests/narration/test_generator.py::test_prompt_instructs_ending_the_hook_on_its_own_open_loop_question`.
Full suite: **1263 passed, 17 deselected.** Applies to either story_lead alias equally
(narration_lead, not story_lead, owns this prompt) -- not Opus-specific, just found via the
comparison. Not yet live-verified.

---

## Phase 30 — Critical review + root-cause plan: retention, content delivery, narration (all items implemented, 2026-09-25)

**Status: all items implemented, 2026-09-25.** Triggered by a critical, evidence-based review of the
real `v05` Opus 5.5 run's long-form video + all 5 shorts, scored for viewer retention,
content delivery, and human narration. Every finding below was then root-caused by a
dedicated investigation (4 parallel deep-dives + direct verification against the real code),
not guessed at. Ordered by priority; each item names the exact fix, not just the symptom.

### P0 -- blocks everything else, fix first

**1. Silent partial-batch claim-verification loss.** Root cause, confirmed against real
`usage.jsonl`/checkpoint data: `facts/verify.py::verify_claims_with_llm` sends a 40-claim
batch (`DEFAULT_BATCH_SIZE`) to Gemini; a real batch1 call came back with only 10 of 40
verdicts -- schema-valid (`ClaimVerdicts.verdicts` has no count constraint tying it to the
batch sent), NOT truncated (completion tokens well under the 12000 ceiling that already
fixed the unrelated ERR-081 truncation bug) -- Gemini just silently stopped early. The 30
un-verdicted claims fall back to `Claim`'s pristine defaults (`UNVERIFIED`, `evidence=[]`).
`find_claims_with_no_verdict` correctly DETECTS this (confirmed: it's wired into
`run_pipeline.py:238-241` right after claim registry construction) but only logs a
`WARNING` and continues -- the corrupted registry gets checkpointed as "claims" complete
immediately after, riding along unchanged into every downstream stage and every future
`--resume` off that checkpoint. This single upstream gap is the direct cause of ~100
long-form `grounding_policy_violation` hard failures and blocked 3 of 5 shorts (2, 3, 4) in
the real `v05` run.
   - [x] `verify.py::_verify_batch_with_retry` (new): re-asks ONLY the missing subset,
         up to `MAX_VERDICT_RETRIES=2` extra attempts (3 total), merging whatever verdicts
         were actually returned across every attempt. Tests: 3 new in `tests/facts/
         test_verify.py` (recovery on retry, the 2 pre-existing "never dropped silently"
         tests updated to confirm the fallback still holds once retries are genuinely
         exhausted, and a payload test confirming a retry only re-sends the missing ids).
   - [x] `run_pipeline.py:238-241` now `raise ValueError(...)` when `find_claims_with_no_
         verdict` is non-empty, instead of only logging -- by this point a claim has
         already survived 3 real attempts, so this is a genuine, rare residual failure
         worth stopping for. Test: `tests/orchestration/test_run_pipeline.py::
         test_no_verdict_claims_now_raises_instead_of_only_logging`.
   - [ ] `DEFAULT_BATCH_SIZE` left at 40, deliberately -- the retry mechanism directly
         addresses the root cause (a batch that comes back incomplete now gets its missing
         subset re-asked, which already shrinks the effective batch each retry), making a
         separate batch-size reduction redundant defense-in-depth rather than a needed fix.
   - [x] Folded into P2 item 5 below (`factual_invariants.py`'s importance-gating rule) --
         same underlying fix, implemented there rather than duplicated here.

### P1 -- structural gaps (a prompt instruction alone won't hold)

**2. Shorts `problem_fix` micro-arc: A2s violates its own explicit instruction.** Not a
writer-prompt weakness -- `narration/short_generator.py`'s writer prompt is already
explicit and mature ("ENACT a failed attempt, don't explain it away conceptually"). The
real bug is upstream: `planning/short_planner.py`'s own `TASK_PROMPT` explicitly requires
`setup` to name a concrete naive attempt and states "if you cannot name that specific
failed attempt... this candidate is NOT a `problem_fix` short" -- but for 3 of 4 real
`problem_fix` shorts, `plan.setup` shipped as a bare rhetorical question (e.g. "What
happens when you calculate softmax on scores from wide vectors?"), violating that
instruction with nothing to catch it. `ShortPlan` (`planning/shorts_models.py`) has one
overloaded `setup: str` field carrying both "context" and "the arc's required beat" -- no
dedicated field. Direct precedent for the fix exists in the same file (`ShortBridge.cta_text`
was added for the identical "no field ever captured what this actually is" reason).
   - [x] Added `naive_attempt: str = ""` to `ShortPlan`/`ShortPlanDraft`.
   - [x] `plan_shorts()` now drops (via `continue`, same style as the existing invalid-beat
         check right above it) any `problem_fix` draft with a blank `naive_attempt`,
         deterministically, before it can reach the writer.
   - [x] `short_planner.py`'s `TASK_PROMPT` now requires `naive_attempt` as its own field,
         reusing the writer's "ENACT, don't explain away" wording.
   - [x] `short_generator.py`'s payload now sends `plan.naive_attempt` explicitly. Tests: 5
         new across `tests/planning/test_short_planner.py` (drop-when-blank, kept-when-real,
         non-problem_fix arcs never need it) and `tests/narration/test_short_generator.py`
         (payload wiring).

**3. Short titles: the concrete, clickable anchor is structurally unreachable.** The
existing prompt already explicitly forbids topic-label titles pulled only from
`central_insight`, with a documented prior failure example -- and it recurred anyway
(`"Self-Attention and Permutation"`, pulled straight from `central_insight`). Root cause:
the title's word-reuse pool is hook/payoff/`central_insight` text only; `ShortVisual.states`/
`dominant_object` (the ACTUAL concrete anchor, e.g. `"'cat chased dog'"` / `"'dog chased
cat'"`) is structurally excluded from that pool. The generator can't reach the good anchor
even when the plan has one.
   - [x] Widened the title's word-reuse pool in `short_planner.py`'s `TASK_PROMPT` to
         explicitly include `visual.states`/`visual.dominant_object`, plus craft guidance
         preferring a concrete visual anchor over an abstract `central_insight` restatement.
   - [x] Also widened the actual mechanical hard-check, `verification/hard/
         shorts.py::check_title_hook_payoff_alignment` -- it only ever compared the title
         against `hook.narration`/`hook.visual` (a prose description) and `central_insight`;
         `plan.visual.states`/`dominant_object` (the real concrete anchor, a DIFFERENT field
         from `hook.visual`) was never in the pool even at the verification layer, not just
         the prompt layer. Tests: `tests/verification/hard/test_shorts.py` (title matching
         only the visual anchor now passes).

### P2 -- prompt-text fixes (lower risk, already have the right precedent to copy)

**4. Title/hook promise mismatch (`title_promise_unrelated_to_hook`).** The constraint is
already documented as a code comment on `TitleContract.promise` in `planning/models.py`
("must be contained in hook.promise") -- but that text was never added to `story_planner.py`'s
actual `TASK_PROMPT`, so the model never sees it. A near-identical gate (`ending` must echo
`hook.promise`'s own terms) was already fixed with explicit prompt language on 2026-09-16.
This exact failure was ALSO seen once before (2026-09-11, different model) and "fixed" by
switching models rather than fixing the prompt -- the gap has been known for two weeks.
   - [x] Added to `story_planner.py`'s `TASK_PROMPT`, mirroring the already-shipped
         ending↔hook fix's own phrasing and severity. Test: `tests/planning/
         test_story_planner.py::test_prompt_requires_the_hook_to_echo_the_titles_own_concrete_terms`.

**5. Hedge-phrase pileup (worst in shorts, ~200-word scripts make it far more visible).**
`narration/factual_invariants.py` (shared by B1/B2/shorts) gives example hedge vocabulary
but no cap or anti-repetition rule -- unlike the connector-repetition cap sitting right next
to it in spirit. A real short used 6 different hedges in 209 words. Separately and more
seriously: some of those hedges were applied to `UNVERIFIED`+`CORE` claims, which the
EXISTING rule already says must be omitted, not hedged -- a compliance miss on top of the
missing style rule.
   - [x] Added the anti-repetition cap to `factual_invariants.py`, mirroring the connector
         cap's own style.
   - [x] Found the gap was bigger than scoped: the CORE/SUPPORTING-must-be-omitted rule
         (this covers P0 item 4 too) EXISTED only in `generator.py`'s own separate copy --
         the SHARED fragment (the only factual-safety text `short_generator.py` ever sees)
         never had it at all, so shorts hadn't just under-followed the rule, they'd never
         been told it. Ported the full CORE/SUPPORTING/OPTIONAL importance-gating rule into
         the shared `NARRATION_FACTUAL_INVARIANTS` fragment. Tests: 2 new in `tests/
         narration/test_factual_invariants.py`.

**6. "The fix:" repetition in long-form (3 uses across 3 consecutive beats).** Same class of
gap as the connector-repetition cap already shipped for causal connectors ("so"/"because"),
just not extended to this specific transitional device.
   - [x] Extended `generator.py`'s existing rhetorical-device-repetition guidance to
         explicitly name "The fix:" (and "So the fix:") as capped under the SAME cap as
         every other device. Test: `tests/narration/test_generator.py::
         test_prompt_names_the_fix_opener_as_a_capped_device`.

**7. Voice burstiness AMBER -- honest two-part answer, not a pure prompt fix.**
`check_voice` is designed to never return RED (small 6-document fitted corpus) -- this has
already been flagged twice before (Phase 23, Phase 24) as possibly structurally inherent,
not a fresh finding. `generator.py`'s only rhythm guidance is "varied rhythm" as two words
buried in a list, with no number or example -- unlike the connector cap, which only got a
hard number after two live failures of qualitative-only guidance. Also found: Phase 24
already root-caused a related, real propagation gap -- the connector cap's fix never made
it into `editing/targeted_rewrite.py`, so a REVISED script isn't held to the same rhythm/
repetition bar as a first-draft one.
   - [x] Gave "varied rhythm" a concrete instruction in `generator.py`: "mix sentence
         lengths within each scene -- at least one short (under 8 words) punch sentence
         alongside longer explanatory ones," naming the "one idea per sentence" rule's own
         side effect as the likely mechanism. Test: `tests/narration/test_generator.py::
         test_prompt_gives_a_concrete_sentence_length_variety_instruction`.
   - [x] Fixed the `targeted_rewrite.py` propagation gap -- it had the OLD, pre-hard-cap
         connector guidance with no device naming and no sentence-length guidance at all;
         both now added, scoped to what B2 can actually control (its own rewritten scenes).
         Test: `tests/editing/test_targeted_rewrite.py::
         test_prompt_names_the_fix_opener_and_sentence_length_variety`.
   - [ ] Not attempted this phase: a targeted rhythm-focused revision pass keyed on AMBER
         `voice` evidence. `check_voice` may remain AMBER-prone on a small corpus regardless
         of prompt wording (per this project's own prior judgment, Phase 23/24) -- flagged
         for a future pass once there's real post-fix data to judge against.

### Not yet root-caused (real findings from the original critique, flagged for a future round)

- **Short 5's `RESERVED_OUTRO_IN_PAYOFF`** (a recap/takeaway lands in the payoff segment
  before the spoken bridge line -- a structural ordering bug, not investigated this round).
- **CTA position at 30%/4.5 minutes into a 900s target** -- not a bug, a design/pacing
  judgment call; worth a real retention-data check before changing the heuristic that
  currently anchors CTA timing to the primary payoff beat.
- **`rep_b6_scaling`** (a scene re-explains a concept its own `must_not_repeat` list already
  named) -- possibly a recurrence/edge case of the sibling-concept propagation fix already
  shipped in Phase 27; needs a direct check against that fix's own scope before concluding
  it's a new gap.

**Implementation order:** P0 -> P1 -> P2, as recommended, each item with its own test and a
full-suite-green check before moving to the next. **Full suite: 1276 passed, 17 deselected**
(up from 1263 before this phase). Not yet live-verified against a real run.

---

## Phase 31 — Reference-HTML gap analysis: page chrome, sustained narrative headings, richer components (items 1-3 implemented, 2026-09-26)

**Status: items 1-3 implemented and tested; item 4 deliberately deferred (see its own
section).** Triggered by a direct comparison against 3 real reference
HTML pages the user supplied (`project/attention_series/input/video-1.1-the-crash-and-the-
six-tenants.html`, `video-1.2-kv-cache-and-the-quadratic-blowup.html`, `video-1.32-watch-it-
crash-live-final-story-connected.html` -- a GPU-memory/training-crash video series, sharing
one reusable CSS design system across all 3). These are a genuinely higher tier of companion
page than our own real output (`video-01-attention-opus55-lead/runs/v05`), and the gap is
structural and narrative, not just polish -- confirmed by direct structural comparison (class
vocabulary, section outlines, real prose) against our own generated HTML. Each item below is
scoped to be directly reflected in the generated script/page itself, per explicit instruction
-- not a design exercise that stops at documentation.

### Item 1 -- page chrome: nav bar + progress tracker (P1, cheap, no LLM risk)

Every reference page has a sticky nav with a progress-tracker row (one dot/label per
chapter, current position highlighted, clickable to jump) plus episode chrome (`series-tag`,
prev/next episode links) and a distinct "Next" bridge section separate from the CTA. Our own
`html_synth/assembler.py::_render_page` (confirmed by direct read) renders only
`hero_html + beats_html + narration_block` -- no nav, no wayfinding, no series-awareness.
This is **entirely templatable from data we already have** (`plan.beats[i].heading`, already
generated) -- no new LLM call, no new content-generation risk, pure deterministic Python +
CSS/minimal JS, matching this project's own "deterministic where possible" precedent
(`beat_word_budget.py`).
   - [x] Added `_render_nav()` + CSS to `assembler.py`/`component_library.py`, built from
         `beat_visuals`/`plan.title`, inserted right after `<body>` (before `hero_html`).
         Each beat's own `<section>` now also carries `id="beat-{beat_id}"` as the anchor
         target. Renders identically in both `video_script.html`/`page.html` (pure chrome,
         no metadata) and renders nothing when there are no beats.
   - [ ] `series_tag`/episode-position chrome still deferred until multi-video series
         metadata exists on `StoryPlan` or its caller.
   - [x] Tests: 5 new in `tests/html_synth/test_assembler.py` (one step per beat linking to
         its section, anchor id present, identical nav in both files, no nav with no beats).

### Item 2 -- sustained narrative headings, not just the hook (P1, cheap, real precedent to extend)

Reference section titles read as the next beat of an unfolding investigation ("It must be a
memory leak", "Six tenants. One of them is a mystery guest.", "Same error. Four different
culprits.") -- narrative momentum sustained across EVERY heading. Our own headings
(`synthesizer.py`'s own instruction: "a real `<h2>`... never generic like 'Section 3'") are
accurate but description-toned ("Query, Key, Value: Splitting One Job Into Three") rather
than narrative-toned. This is the same principle Phase 29's `hook.open_loop` fix already
applied to the hook specifically -- this generalizes it to every heading, for the archetypes
where it fits (`mystery`, `build`; NOT `foundation`/`framework`, where a descriptive heading
is honest and a forced mystery tone would be a worse fit).
   - [x] `synthesize_beat_visual()`'s payload now sends `archetype`, `viewer_question_before`,
         `answer_or_payoff`, `next_question` (previously never sent to H at all), and
         `synthesizer.py`'s `TASK_PROMPT` instructs mystery/build-archetype headings to read
         as the next beat of an investigation using those fields -- every other archetype
         keeps the descriptive instruction, explicitly told not to force a mystery tone.
   - [x] The illustrative examples quoted ("It must be a memory leak.", etc.) are from the
         REFERENCE video's own unrelated GPU-memory topic, not our test video -- safe against
         the overfitting guard by construction (demonstrates the pattern without biasing
         toward our own test topic's specific content).
   - [x] Tests: 2 new in `tests/html_synth/test_synthesizer.py` (the 4 new payload fields
         reach `synthesize_beat_visual`'s call; the prompt names both archetypes and the
         non-forcing rule for others).

### Item 3 -- 2-3 new components matching real devices these references use (P2, moderate effort, follows existing pattern exactly)

Real, distinct devices our 9-component vocabulary (`design_system.yaml`) has no equivalent
for: a "suspect board" (a lineup of candidate causes, each with a one-line description, for a
sustained mystery/investigation format), a "solution grid" (N labeled fix-options compared
side by side, for a payoff that resolves into multiple concrete options rather than one), a
"case card" (a labeled concrete scenario/example block, for "here's a specific instance of
the general rule"). Each maps to a real narrative shape our archetypes already support but
currently render with a generic `card`/`grid_2`.
   - [x] Added all 3 to `config/design_system.yaml` exactly as scoped: `suspect_board` for
         `contradiction`/`investigation`, `solution_grid` for `payoff` only, `case_card` for
         `observations`/`mechanism`.
   - [x] Added dedicated rendering branches in `component_library.py::render_component`
         (list-shaped `suspect_board`/`solution_grid` mirroring `step_list`'s blank-slot-
         omission discipline; `case_card`'s two optional slots mirroring `card`'s own
         conditional-block pattern) + matching CSS.
   - [x] Updated `synthesizer.py`'s `TASK_PROMPT` with per-component guidance (when each
         fits, exact slot shapes, explicit "never the reveal itself" guard on `suspect_board`
         and "never pad one option to look like several" guard on `solution_grid`).
   - [x] Tests: 10 new across `tests/html_synth/test_component_library.py` (rendering +
         blank-slot omission for all 3, `story_roles` allowlist checks) and `tests/html_synth/
         test_synthesizer.py` (prompt mentions all 3).

**Full suite: 1292 passed, 17 deselected** (up from 1276 before this phase). Not yet
live-verified against a real run.

### Item 4 -- interactive, data-driven component (P3, largest scope, needs its own design pass before implementation)

`video-1.1`'s mode-selector component (`Inference`/`LoRA`/`QLoRA`/`Full-Parameter Training`
tabs, each live-recomputing a segmented bar chart + a full breakdown table with real
formulas/values + a color-coded callout) is categorically different from anything we
generate: real client-side interactivity driven by real embedded data, not a single static
LLM-authored blob. This is the highest-payoff, highest-effort item and should NOT be
attempted as a normal `component_data` LLM field -- it needs a templated JS component (fixed
interaction logic, hand-authored once) that the PLAN supplies real scenario/formula data
into, closer in spirit to `StoryPlan.formula_stages` (already a typed, plan-level, Python-
verifiable structure) than to a per-scene visual component.
   - [ ] Scope as its own design pass once items 1-3 land: what new `StoryPlan` field would
         carry N named scenarios, each with a formula + named variable values (mirroring
         `FormulaStage.values`'s own shape)? Which archetype_role/content shape actually has
         multiple comparable scenarios worth toggling between (a real precondition -- most
         videos won't have this; do not force it onto every plan)?
   - [ ] Decide: does A2 populate this data (higher risk -- LLM-authored numbers need the
         same claim-grounding discipline `formula_stages.values` already gets), or is it only
         used when the SOURCE material itself already contains the comparable scenarios as
         claims (lower risk, matches this project's "ground everything in a real claim"
         discipline)?
   - [ ] Not scheduled for implementation this phase -- flagged for a dedicated follow-up once
         1-3 are live and there's a real plan to test it against.

**Implementation order recommendation:** items 1-2 first (cheap, deterministic/prompt-only,
directly and immediately visible in every future generated script). Item 3 next (moderate,
same established pattern as every prior component addition this session). Item 4 last and
separately scoped -- it's a real architecture decision, not a prompt tweak, and forcing it in
before 1-3 are proven would risk the same "big scope change with no real plan to test it
against" mistake this project's own YAGNI discipline already warns against elsewhere. Each
item gets its own test + full-suite-green check before moving to the next, per this project's
established discipline -- no item here has been implemented yet.

---

## Phase 32 — 3-round audit of the fixed pipeline: broken contracts, design gaps, diagnostic artifacts (P0/P1 implemented, 2026-09-26)

**Status: P0 (all 3 items) and P1 (4 of 5 items) implemented and tested; 1 P1 item and all
P2/P3 items deliberately deferred (see their own notes).** Triggered by a genuine apples-to-
apples comparison (same source, same current pipeline, gpt-5.6-sol vs Opus 5.5 as
`story_lead`) that showed a real, specific gap rather than the earlier pre-Phase-30 pipeline
confound, followed by 3 rounds of critical review (4 parallel Round 1 investigations, Round 2
direct code/data verification of the highest-severity claims, Round 3 synthesis) against the
now-mature pipeline (Phase 29-31 + the voice/contraction fix already landed this session).

### P0 — broken contracts: an instruction present in a prompt with no data or destination to obey it

Found by the cross-file consistency audit and confirmed directly (`grep`) against every file
named: the shared `NARRATION_FACTUAL_INVARIANTS` fragment's CORE/SUPPORTING/OPTIONAL
importance-gating rule was included, verbatim, in B1s's (shorts) and B2's (targeted rewrite)
prompts -- but neither pass's own `_claim_payload()` ever sent the `importance` field at all,
making the instruction structurally impossible to follow. B2 additionally had zero access to
`mechanism_scope`, `cta.primary_after_beat`/word-cap/no-second-CTA, or `hook.open_loop` --
data B1's own first-draft prompt has hard rules keyed off, that a rewrite of exactly those
scenes would have no way to honor. H (HTML synthesis) received claims with no
`verification_status`/`importance` at all, unlike every narration-writing pass.
   - [x] `narration/short_generator.py::_claim_payload` and
         `editing/targeted_rewrite.py::_claim_payload` both now include `claim.importance`.
   - [x] `editing/targeted_rewrite.py`: added `_hook_last_scene_id()`; each rewritten scene's
         payload now carries `mechanism_scope`, `is_cta_beat`, `is_hook_last_scene`,
         `is_true_final_scene`; the outer payload now carries `plan.cta`/`plan.hook`;
         `TASK_PROMPT` gained the corresponding mechanism-scope/CTA/hook rules (mirroring
         `generator.py`'s own, adapted to the per-scene boolean flags this pass actually has).
   - [x] `html_synth/synthesizer.py::_claim_payload` now includes `verification_status` and
         `importance`; `TASK_PROMPT` gained a REJECTED/UNVERIFIED gating rule for
         `screen_prose`/`component_data`/`annotated_numbers`, mirroring narration's own rule.
   - [x] Tests: 8 new across `tests/narration/test_short_generator.py`,
         `tests/editing/test_targeted_rewrite.py` (5 new), `tests/html_synth/test_synthesizer.py`.

### P1 — design/policy gaps affecting every run regardless of model

Found by the retention/pacing and HTML-richness audits, each confirmed directly against real
data from two comparable runs (Opus 5.5 and gpt-5.6-sol as `story_lead`, same source, same
current pipeline).
   - [x] **`problem_fix` component starvation**: the single most-repeated story_role in a real
         build-archetype plan (3-4 of ~11-12 beats) could reach `diagram_card`/`step_list`/
         `callout_warn` but not `case_card`, despite "here's a specific problem, here's its
         specific fix" being a near-verbatim match for `case_card`'s own "specific instance of
         the general rule" shape. Added `case_card` to `problem_fix`'s allow-list in
         `config/design_system.yaml`. Test: `test_case_card_is_available_to_problem_fix_too`.
   - [x] **`diagram_card` monopoly**: legal under nearly every role and picked in ~2 of every 3
         components chosen across two real full pages, including `payoff` scenes that never
         once used `solution_grid` despite it being offered. `synthesizer.py`'s `TASK_PROMPT`
         used to only explain what the other components are FOR, never warn against
         `diagram_card` becoming the reflexive default -- added that warning directly after
         the existing three-component guidance. Test:
         `test_prompt_warns_against_defaulting_to_diagram_card`.
   - [x] **`retention.title_scope_coverage` near-unsatisfiable for technical titles**:
         `text_overlap.py::content_words()`'s length filter (`len(w) > 2`) silently erased
         exactly the shorthand a technical title reuses (Q, K, V, n2) -- confirmed live as the
         actual reason two real titles from two different models both scored as failing to
         reflect their own must_cover items, independent of title quality. `content_words()`
         gained an overridable `min_length` parameter (default unchanged at 3, so every other
         caller's behavior is untouched); `retention.py::_item_reflected_in_title` now calls it
         with `min_length=1`. Tests: 2 new in `test_text_overlap.py`, 1 new in
         `test_retention.py`.
   - [x] **`pacing.beat_airtime_outliers` claim double-counting**: a deliberate callback beat
         whose `source_unit_ids` overlap an earlier beat's had those units' claims counted
         AGAIN toward its own words-per-claim ratio, deflating it and falsely flagging the
         callback as an airtime outlier for doing exactly what a callback should (fewer new
         words, because the claims aren't new) -- confirmed live on a real cross-attention
         beat that scored 0.29x median purely from this double-count. Each source unit's
         claims now count toward only the FIRST beat (in story order, including the hook) that
         actually touches it. Test:
         `test_a_callback_beat_reusing_earlier_source_units_is_not_double_counted`.
   - [ ] **Deferred: diagnostic escalation counts bands, never magnitude**
         (`orchestration/policy_gate.py::compute_final_status`). Confirmed live: gpt-5.6-sol's
         run had 2 REDs, each roughly 2x its own target threshold (`cta.position` at 56% vs a
         20-40% target; `pacing.time_to_primary_payoff` at 55% vs a <=35% target) -- the
         current rule (`>=3 REDs, or a RED that survived a round, or >3 AMBERs`) never
         escalates on a single first-pass RED regardless of how far past its threshold it
         lands, by explicit design (documented in the function's own docstring as "plan §10").
         This is a real cost, not a bug -- weighting escalation by magnitude, not just band
         count, is a deliberate policy change affecting every run's `final_status`, not a
         scoped fix, and needs an explicit decision before implementing (a stricter policy
         raises revision cost/frequency across the board). Left for a dedicated decision, not
         bundled into this phase's otherwise-scoped fixes.

### P2/P3 — deliberately deferred, documented for a future round

Real findings, lower severity or higher risk-to-fix-safely than P0/P1 above, not implemented
this phase:
- **Narration voice, round 2**: "That's X"/"It's X" as the default move to land any
  definition or payoff (broader than the derivation-callback pattern already fixed this
  session); a possible new tic from the short-punch-sentence fix (gpt-5.6-sol: 20% of
  sentences are <=5-word verbless fragments); "Nothing ___" negation-openers and "X, not Y"
  antithesis, both named in the prompt as cautionary examples already but with no hard
  numeric cap (unlike so/because/"The fix:"); confirmed live, Opus's own v07 output still had
  3 "so"-openers against its own stated cap of 2 -- the existing cap isn't 100% reliably
  followed even now, worth a follow-up check rather than assuming the qualitative+numeric
  instruction alone is sufficient.
- **`payoff=True` self-labeling variance**: two structurally near-identical plans (same
  source, same pipeline) landed different `pacing.time_to_primary_payoff` bands purely
  because one model additionally flagged an earlier, lesser beat `payoff=True` (content-
  equivalent to a beat the other model correctly left `payoff=False`) -- `check_payoff_beat_ratio`'s
  own over-marking guard doesn't catch it because both ratios clear its 30% GREEN threshold.
  No upstream planning-time guard exists (`retention_deadlines` is optional and
  model-declared, not enforced). Needs either a stricter over-marking check or an explicit
  planning-time rule, not a one-line fix.
- **No design-system support at all for**: a running-total/escalating-ledger scoreboard
  device (reference corpus uses this after every case in one series); real interactivity/
  motion beyond a load-time fade (scroll-triggered reveals, clickable mode toggles); a
  multi-step formula layout (`math_block`'s single-equation slot flattens a genuine
  multi-line derivation onto one line); page-level footer/inter-episode-nav/bridge-transition
  chrome. All confirmed via direct comparison against the 3 reference HTML files. Each is a
  real design-system extension, not a prompt tweak -- scoped out of this phase's P0/P1 fixes.
- **`plan_story()`'s fixed `estimated_usd=0.10` pre-flight budget guess** isn't scaled per
  `--story-lead-alias` -- only affects a pre-flight admission check, not the hard cap itself,
  so ranked below the items above.

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
