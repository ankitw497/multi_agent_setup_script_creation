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

- [ ] Run one live A2/A2b comparison on the same real source: `story_lead` on `gpt-4o`
      (`openai_story_strong`, current default) vs. `gpt-5.6-sol` (`openai_story_strong_gpt56`,
      already configured in `config/models.yaml`)
- [ ] Compare specifically for less structural redundancy / a tighter causal chain, **using
      the Phase 1 ledger machinery** (both runs should have it available)
- [ ] Decision: promote `gpt-5.6-sol` to the new `openai_story_strong` default **only if** the
      live comparison shows a real difference — record the comparison result in `ERROR_LOG.md`
      either way
- [ ] Confirm no change to `narration_lead` (Sonnet, subscription lane — free, already strong;
      Phase 1's richer input is the actual lever, not a model swap)
- [ ] Confirm no change to claim extraction / fact verification / HTML generation tiers

---

## Final verification (Phases 1-3 done; Phase 4 still open)

- [x] `.venv/bin/python3 -m pytest -q` green throughout (checked after each phase; 731 passed
      as of the overfitting fix, up from 689 before this work began)
- [x] Two full live runs via `run_pipeline.py` against `video-01-attention-coherent-story`
      (`runs/v17`, `runs/v18`) -- see the detailed ERROR_LOG.md entry for what each confirmed:
      cross-beat repetition prevented, hedge-language bug gone, `pacing.hook_tension` wired
      and firing correctly, C1's new REPETITION check catching a real residual case.
- [ ] `BUILD_PLAN.md` updated with a "V2 — Narrative continuity" section pointing back here
      (not yet done -- do this once Phase 4 is resolved, so the summary covers the whole fix)
- [x] `ERROR_LOG.md` updated with the concrete before/after (the specific repeated phrase
      found vs. gone, hook-pacing seconds measured, the residual within-beat gap found) —
      not just "improved quality"
- [ ] Phase 4 (model-tier comparison) — still open, needs another live run + a real decision;
      not started yet
