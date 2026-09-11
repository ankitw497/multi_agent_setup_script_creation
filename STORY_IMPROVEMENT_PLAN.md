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

- [ ] `html_synth/synthesizer.py` — thread `plan.running_example` into `synthesize_beat_visual()`
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
- [ ] **Technical invariants** (item #10): add an optional `invariants` section the source can
      declare (or S2a/S2b can extract deterministically, similar to how `AssumptionLedger`
      already captures source-declared constants) -- e.g. equation form, operation order
      ("mask applied before softmax, not after"), tensor/data orientation. Validate narration
      and H's screen prose against these as a new `verification/hard/` check (Python string/
      pattern matching against the declared invariant, not model judgment) where the invariant
      is concrete enough to check mechanically; fall back to flagging for C1's OVERCLAIM check
      otherwise. Scope narrowly at first -- start with whatever invariant the real source
      material actually states explicitly, not a speculative general framework
- [ ] **Numeric state tracking** (item #9): distinct from entity consistency -- when a
      calculation genuinely spans multiple scenes (raw values -> scaled -> normalized -> final),
      the SAME numbers must reuse, not just the same named objects. `RunningExample.values`
      already holds arbitrary key/value pairs -- extend `narration/generator.py`'s prompt to
      explicitly require reusing prior numeric values already established for the same
      calculation, rather than inventing new illustrative numbers at each step. No new schema
      needed; this is a prompt-strength and validation gap, not a modeling gap
- [ ] Unit tests: `synthesizer.py` payload carries `running_example` and actual narration text;
      the new entity-overlap diagnostic (clean case, mismatch case, ambiguous case treated as
      AMBER not a crash)
- [ ] `.venv/bin/python3 -m pytest -q` green
- [ ] **Live-verify**: re-render the same real source; confirm `score_s02`/`score_s03`-style
      diagrams now reuse the locked running example instead of inventing `dog/park/bone`;
      confirm the new diagnostic actually fires on a deliberately-reintroduced mismatch (so we
      know it isn't silently inert) before trusting it clean on a real run

---

## Final verification (Phases 1-4 done; Phases 5-6 still open)

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
