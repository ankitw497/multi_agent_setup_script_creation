# Error log

A running record of every real bug or design gap found while building this pipeline —
distinct from `BUILD_PLAN.md` (which tracks *progress*) and `IMPLEMENTATION_PLAN.md`
(which is the frozen *design*). Almost every entry here was found by actually running
code against real data (the `project/attention_series/` source, or a live paid call),
not by inspection alone — that's deliberate: unit tests with fake agents can't surface
most of these, since a fake never produces the malformed, incomplete, or surprising
output a real model does.

**Convention:** append new entries at the bottom with the next `ERR-NNN` id. Each entry
should be able to stand alone: what broke, the concrete evidence (real numbers/output,
not "it didn't work"), the root cause, the fix, and the regression test that now locks
it in. Mark `Live cost` when a paid call was involved. Keep `Status` accurate — a bug
found and not yet fixed is still worth logging.

| Field | Meaning |
|---|---|
| **Severity** | `critical` (wrong output shipped silently), `major` (pipeline crash / real gap), `minor` (cosmetic, caught before it shipped) |
| **Status** | `fixed` / `open` |

---

## ERR-001 — Chrome-stripping deleted real content
**Date:** 2026-09-10 · **Severity:** critical · **Status:** fixed · **Component:** `extraction/html_parser.py`

A bare `"footer"` chrome-stripping selector was meant to remove only the page footer,
but this design system also renders `.diagram-caption` and `.math-block` as `<footer>`
tags — so every diagram caption and equation block in the real source was silently
deleted before extraction ever saw them.

**Fix:** scoped the selector to `.page-footer` specifically.
**Test:** `tests/extraction/test_profiles.py::test_guide_extraction_recovers_footer_tagged_diagrams_and_equations`

---

## ERR-002 — Number-sweep regex vocabulary too narrow
**Date:** 2026-09-10 · **Severity:** minor · **Status:** fixed · **Component:** `extraction/profiles/base.py`

Realistic domain phrasing ("128 dimensions") wasn't recognized as a number because
`dimensions`/`dims` weren't in the accepted-unit list.

**Fix:** added `dimensions?|dims?` to `_NUMBER_RE`.

---

## ERR-003 — Formula parser rejected the "~" approximation marker outright
**Date:** 2026-09-10 · **Severity:** major · **Status:** fixed · **Component:** `facts/seeds.py`

A real source formula (`"~40.4M × 2 bytes"`) failed to parse at all — the parser had no
handling for a leading `~`, so an author's own explicit "this is approximate" signal
caused a hard failure instead of a looser check.

**Fix:** `~` now parses normally, with a wider tolerance (0.05 vs 0.01) and a note
(`"one or more factors were marked approximate (~)"`) rather than being ignored or
rejected. `facts/seeds.py`.

---

## ERR-004 — Gemini 1.5-flash/1.5-pro fully retired
**Date:** 2026-09-10 · **Severity:** major · **Status:** fixed · **Component:** `config/models.yaml`, `llm/backends/litellm_backend.py`

A live call 404'd. Google's own error response named the exact replacements.

**Fix:** repinned to `gemini-3.6-flash` (cheap tier) / `gemini-3.1-pro-preview` (strong
tier). `config/models.yaml` documents the `ListModels` probe used to find this, for next
time an id 404s.

---

## ERR-005 — Gemini flash reasons by default, silently consuming the entire output budget
**Date:** 2026-09-10 · **Severity:** critical · **Status:** fixed · **Component:** `llm/backends/litellm_backend.py`

A small `max_tokens` cheap-tier call returned **empty `content`** for real money
($0.0003645) — the model spent its whole allowance on hidden reasoning tokens with
nothing left for visible output.

**Fix:** `reasoning_effort` support added to `LiteLLMBackend.call()` (`"none"` for the
cheap tier); `CallResult.reasoning_tokens` now tracked separately from `output_tokens`
so this failure mode is visible, not silent, if it recurs elsewhere.
**Test:** `tests/llm/test_litellm_backend.py::test_call_result_reports_reasoning_tokens_separately_from_output_tokens`

---

## ERR-006 — Multi-model `modelUsage` envelope: wrong model identified
**Date:** 2026-09-10 · **Severity:** critical · **Status:** fixed · **Component:** `llm/backends/claude_cli.py`

A single `claude -p --model sonnet` call was observed to log **two** entries in the
envelope's `modelUsage`: `claude-sonnet-5` (182 in / 9 out — the real answer) *and* an
internal `claude-haiku-4-5-20251001` entry (525 in / 12 out — an internal sub-step, even
in headless `-p` mode). The original parser took `modelUsage`'s first dict key, which
happened to be Haiku — every Sonnet call would have silently mis-attributed its
resolved model.

**Fix:** `_identify_resolved_model()` now matches token counts against the envelope's
top-level `usage` block instead of trusting dict key order.
**Tests:** `test_identifies_resolved_model_from_multi_model_envelope`,
`test_dict_key_order_alone_would_have_picked_the_wrong_model` (`tests/llm/test_claude_cli_backend.py`).

---

## ERR-007 — Subscription CLI 120s timeout too tight for real batched calls
**Date:** 2026-09-10 · **Severity:** major · **Status:** fixed · **Component:** `llm/backends/claude_cli.py`

An 11-source-unit (~3300-word) batched Haiku claim-extraction call exceeded the 120s
default subprocess timeout and was killed mid-call.

**Fix:** default raised to 300s, with a per-call `timeout_s` override threaded through
`agents/base.py` → `llm/client.py` → the backend, since larger real payloads over a
complex schema legitimately need more wall-clock (subscription lane = quota, not
billed time, so a generous default costs nothing but patience).

---

## ERR-008 — CM and C1/C2b were collapsed onto one `review_lead` agent
**Date:** 2026-09-10 · **Severity:** major · **Status:** fixed · **Component:** `orchestration/pipeline.py`

`PipelineAgents` originally had a single `review_lead` field serving both the Claim
Mapper (CM — mechanical, meant to be cheap/flash-tier by design, plan §2.2) and C1/C2b
(correctness-critical, meant to be strong-tier, no cheap fallback). Collapsing them
meant CM was either run at strong-tier cost or C1/C2b at flash-tier
quality — neither intended.

**Fix:** split into a separate `cm_agent` (flash tier) field alongside `review_lead`
(strong tier).

---

## ERR-009 — `LLMClient` built by hand without a repair function
**Date:** 2026-09-10 · **Severity:** major · **Status:** fixed · **Component:** `llm/client.py`

The first live end-to-end orchestrator run crashed with a plain `JSONDecodeError` from
C2b's response — not a schema mismatch, malformed JSON outright, plausible given the
payload size (61 claims + a full narration draft). The architecture always specified
that malformed paid-lane output gets repaired on Haiku, free, before reaching a later
stage (plan §3.4) — but the e2e script constructed `LLMClient` directly, without a
`repair_fn`, so that safety net was never wired in. This is exactly the class of gap
that only running the *whole* pipeline surfaces: every stage's own unit tests use a
`FakeAgent` that never produces malformed output.

**Fix:** `llm/repair.py::make_haiku_repair_fn` + `llm/client.py::make_llm_client` — now
**the one correct way** to construct a real `LLMClient`; it always wires the repair
function in, so this mistake can't be made by a future caller.
**Test:** `tests/llm/test_client_factory.py` (both cases: repair_fn always present, and
it actually uses the subscription backend).

---

## ERR-010 — A2 could not satisfy an aggregate word-budget constraint through prompting alone
**Date:** 2026-09-10 · **Severity:** critical · **Status:** fixed (worked around structurally, not prompt-tuned) · **Component:** `planning/story_planner.py`, `verification/hard/structure.py`

Three separate live A2 runs against the same real source (~1670-word / 600s target)
returned scene plans totaling 320, then 460, then 480 words — even after the prompt was
given the exact arithmetic (`target_duration_seconds / 60 * 167`) and an explicit
expected scene-count range. **This is not a prompt-wording problem**: LLMs are
reliably unreliable at satisfying an aggregate constraint (a sum across many generated
items) through instruction alone, however precisely stated.

**Fix:** a deterministic hard check, `verification/hard/structure.py::check_word_budget_matches_target`,
catches this mechanically every time instead of relying on a better prompt. Validated
against both real saved plans on disk (ratios 0.19, 0.28 — both correctly flagged).

**Update (ERR-024):** the check above only ever caught the defect after the fact; it kept
recurring live (see ERR-023) until the actual generation was restructured — see ERR-024
for the real preventive fix (splitting A2 into a structure call plus small, independently
-achievable per-beat scene-expansion calls). This check remains in place as the
safety net regardless.

---

## ERR-011 — A2 beats returned `source_unit_ids: []`
**Date:** 2026-09-10 · **Severity:** major · **Status:** fixed · **Component:** `planning/story_planner.py`

Every beat in a real run came back with an **empty** `source_unit_ids` — not because the
model ignored an instruction, but because the prompt never actually asked for that
field to be populated at all. Silently dropped most of an 11-section source's content
from ever being covered.

**Fix:** `TASK_PROMPT` now explicitly instructs populating it ("never leave this
empty").
**Test:** `tests/planning/test_story_planner.py::test_prompt_instructs_populating_source_unit_ids`

---

## ERR-012 — Archetype instability: three live runs, three different (wrong) answers
**Date:** 2026-09-10 · **Severity:** critical · **Status:** fixed (root cause: ERR-013 + ERR-014) · **Component:** `planning/story_planner.py`

Three live A2 runs against the identical real source returned three different
archetypes (`foundation`, `foundation`, `derivation`) — none of them `build`, which the
user's own separate, existing render pipeline had already independently determined was
correct for this exact source. This was the symptom; ERR-013 and ERR-014 were the root
cause, found by investigating *why* A2 kept missing evidence that should have been
decisive.

---

## ERR-013 — Root cause of ERR-012: extraction silently deleted the strongest archetype evidence
**Date:** 2026-09-10 · **Severity:** critical · **Status:** fixed · **Component:** `extraction/html_parser.py`

The source's `<footer class="page-footer">` held an author-written "Production notes ·
target pacing" section — a timestamped `.pipeline-step` plan (`Problem → Mini payoff →
... → Score creates a new problem → ... → New limitations → ... → Payoff and Part 2
bridge`), i.e. the author's own account of the story's `build` shape. `.page-footer` is
chrome-stripped wholesale (correctly, per ERR-001's fix — it's *mostly* nav-adjacent
captions on this source) — but that one blanket rule discarded the production notes
right along with the chrome, before A1 or A2 ever saw them.

**Fix:** `_extract_production_notes()` runs on the *unstripped* soup, pulls any
`.pipeline-step` content into its own `production_notes` `SourceUnit` (via a new shared
`extract_pipeline_steps()` helper), and only then lets `_strip_chrome()` remove the
rest. Gracefully absent (returns `None`, adds nothing) on sources with no such section —
**this will not exist on every source**, and nothing downstream (hard checks, archetype
specs) depends on it existing.
**Tests:** `tests/extraction/test_html_parser.py` — three tests, including one against
the real source file and one confirming a plain footer with no pipeline steps produces
no such unit.

---

## ERR-014 — A2 and C1 only ever saw compressed summaries, never the source's real content
**Date:** 2026-09-10 · **Severity:** critical · **Status:** fixed · **Component:** `planning/story_planner.py`, `review/story_critic.py`, `orchestration/pipeline.py`

Even with ERR-013 fixed, `plan_story()` (A2) only received A1's `SourceBrief` — a lossy
distillation — and `critique_story()` (C1) received **no source content at all**, only
the plan's own self-description. Neither could independently weigh direct evidence
(like the production notes) against A1's or A2's own summarization choices.

**Fix:** both now take a `source_units: list[SourceUnit]` parameter with the real
content; `orchestration/pipeline.py` threads it through the initial A2 call, the A2
replan call, and the C1 critique call. Both prompts instruct treating an author's own
production notes / storyboard plan as strong direct evidence **when present** — phrased
conditionally, since most sources won't have one.
**Live cost:** $0.0505 for one targeted validation call — re-ran A2 with the fix and it
correctly resolved `archetype: build`, matching the user's independent pipeline.
**Tests:** `tests/planning/test_story_planner.py`, `tests/review/test_story_critic.py`,
`tests/orchestration/test_pipeline.py::test_source_units_reach_both_a2_replan_and_c1_critique`.

---

## ERR-015 — Strong-tier Gemini reasoning was unbounded, driving up real cost
**Date:** 2026-09-10 · **Severity:** major · **Status:** fixed · **Component:** `config/models.yaml`

`gemini_review_strong` (C1/C2a/C2b) had `reasoning_effort: null` — "provider default,"
which is unbounded reasoning depth, not a deliberately-sized one. A completed live e2e
run spent $0.218 across 11 paid calls partly because of this.

**Fix:** `reasoning_effort: "low"`. Verified with two minimal calls (not a full
re-run): a `max_tokens=20` test was caught as **misleading** (too small a budget for a
fair comparison) before drawing a conclusion; a `max_tokens=300` retest showed `"low"`
used fewer reasoning tokens (261 vs 285) *and*, more importantly, actually completed its
answer, while default ran out of budget mid-sentence.
**Test:** `tests/agents/test_factories.py::test_review_lead_strong_tier_caps_reasoning_to_low`

---

## ERR-016 — A2's replan was blind: no feedback from C1/A3 was ever given back to it
**Date:** 2026-09-10 · **Severity:** major · **Status:** fixed · **Component:** `orchestration/pipeline.py`, `planning/story_planner.py`

The disagreement-resolution path (C1 raises a critical issue → hard failure → REVISE →
A3 decides `story_replan_required` → orchestrator reruns A2) reran `plan_story()` with
the **exact same inputs** as the first attempt — `source_brief`, `claims`,
`source_units`, unchanged. A2 never learned *why* its previous plan was rejected, so a
second wrong answer on replan was just as likely as a corrected one; the only thing
protecting correctness was A2 getting lucky (or the ERR-014 fix already being enough
that replan rarely triggers for this specific defect).

**Fix:** new `ReplanFeedback` contract (`planning/models.py`) carrying the previous
archetype, C1's critique issues, and the structural findings; `plan_story()` takes it as
an optional `replan_feedback` parameter and the prompt instructs directly addressing
every item rather than silently repeating the same plan. `orchestration/pipeline.py`
builds it from `bundle.issues` and the just-computed `structural` findings on every
REPLAN action.
**Tests:** `tests/planning/test_story_planner.py::test_replan_feedback_is_passed_through_on_a_replan`,
`tests/orchestration/test_pipeline.py::test_a2_replan_receives_the_prior_rejection_reason_not_a_blind_retry`.

---

## ERR-017 — Dead code: `MAX_MAX_MAJOR_REVISIONS if False else ...`
**Date:** 2026-09-10 · **Severity:** minor · **Status:** fixed (caught before it shipped) · **Component:** `orchestration/pipeline.py`

A leftover editing artifact from an earlier draft of the bounded-loop logic. Never
actually caused a wrong result (Python's conditional expression laziness meant the
`if False` branch was simply dead), but confusing and sloppy. Cleaned up on sight.

---

## ERR-018 — `pydantic` `.model_fields` deprecation warning
**Date:** 2026-09-10 · **Severity:** minor · **Status:** fixed · **Component:** test suite

`issues[0].model_fields` (instance access) is deprecated in pydantic 2.11+ in favor of
`type(issues[0]).model_fields` (class access). Fixed at both call sites
(`tests/review/test_story_critic.py`, `tests/review/test_models.py`).

---

## ERR-019 — Test fixture violated the model's own hard bound
**Date:** 2026-09-10 · **Severity:** minor · **Status:** fixed · **Component:** test suite

An early version of a pipeline test used `scene_words=10`, but `ScenePlan.word_budget`
has a hard floor of 30 (plan §9: 30-100 hard, 40-80 preferred) — pydantic correctly
rejected it. Not a product bug; the test itself was invalid. Fixed to use `scene_words=30`.

---

## ERR-020 — e2e validation script bugs (tooling, not pipeline defects)
**Date:** 2026-09-10 · **Severity:** minor · **Status:** fixed · **Component:** ad-hoc validation scripts (not committed)

Two slips in throwaway e2e scripts used to drive live validation, not in the pipeline
itself: (1) a v02 re-run script forgot to save `source_brief.json`, worked around by
loading v01's instead; (2) see ERR-009 — the script constructed `LLMClient` by hand,
which is what surfaced that gap in the first place. Logged here for completeness since
they're what led to a real product fix (ERR-009), not because the scripts themselves
matter.

---

## ERR-021 — A2's output truncated mid-string by a global 2048-token cap
**Date:** 2026-09-10 · **Severity:** critical · **Status:** fixed · **Component:** `llm/backends/litellm_backend.py`, `planning/story_planner.py`

The first live re-validation of the ERR-013/ERR-014 fix crashed: A2's response failed
JSON parsing (`Unterminated string starting at: line 1 column 9298`) — a genuine
truncation, not a malformed-schema issue — and even the Haiku repair path couldn't
recover it (a response cut off mid-string isn't repairable; the repair call itself then
also failed outright: `claude -p failed (exit 1)`). Root cause: `LiteLLMBackend`'s
`max_tokens` defaulted to 2048 for **every** paid-lane call, but a full `StoryPlan` (a
title, hook, CTA, beats, ending, and 20-30 `ScenePlan` entries — the largest structured
output anywhere in the system, and larger than ever now that the word-budget prompt fix
correctly asks for 20-30 scenes instead of 4-6) routinely needs far more than that.

**Fix:** `max_tokens` threaded through as an optional per-call override
(`agents/base.py` → `llm/client.py::call_structured_paid` → `llm/backends/litellm_backend.py::call`),
mirroring the existing `timeout_s` override pattern (ERR-007) exactly. The shared
default was also raised 2048 → 4096 (safe for every other paid call, which output far
less), and `plan_story()` (A2) explicitly requests `max_tokens=8000` given it's
structurally the largest output by a wide margin.
**Live-verified:** the same real-source re-run that first hit this crash completed
cleanly after the fix (see ERR-022's run for the full trace) — cost $0.2813/12 calls.
**Tests:** `tests/llm/test_litellm_backend.py::test_default_max_tokens_is_4096_not_2048`,
`::test_max_tokens_override_is_forwarded_when_given`,
`tests/planning/test_story_planner.py::test_requests_a_generous_max_tokens_override`.

---

## ERR-022 — C1 disputed a correct archetype, and the replan loop obediently made it worse
**Date:** 2026-09-10 · **Severity:** open finding, not a code bug · **Status:** open · **Component:** `review/story_critic.py`, the disagreement-resolution design itself

The same live re-run (after ERR-021's fix): A2's **first** attempt correctly resolved
`archetype: build` — matching the user's own independent render pipeline's
classification, exactly reproducing the earlier $0.0505 single-call validation (ERR-014).
But C1 then raised a `category: archetype, severity: critical` issue disputing `build`
anyway. Per the disagreement-resolution design (see the "how is the disagreement
solved" conversation, 2026-09-10): a critical C1 issue is *unconditionally* promoted to
a hard failure (`review/aggregator.py`) regardless of how well-supported A2's original
choice was, forcing a REVISE → A3 → REPLAN. A2's replan — now correctly given C1's
critique via `ReplanFeedback` (ERR-016's fix, working exactly as designed) — dutifully
switched to `archetype: derivation`, which was structurally *worse*: it introduced a
`cta_references_unknown_beat` failure (the new plan's CTA pointed at a beat id that
didn't exist), failed 3 of `derivation`'s own core roles, and still didn't fix the
original word-budget shortfall. `MAX_STORY_REPLANS=1` then correctly exhausted and the
run `FAIL`ed cleanly — the bounded loop did exactly its job (no infinite flailing, no
silently-shipped bad script) — but the run still failed on a source A2 had actually
gotten right the first time.

**Why this is left open, not "fixed":** the current design is asymmetric by
construction (see the disagreement-resolution explanation above) — a critical
disagreement from C1 always wins over A2's own confidence, with no mechanism to weigh
*how well-supported* either side's evidence actually is, and no independent tie-breaker.
That is a real architectural question (should A2 be allowed to push back with its own
`source_evidence`? should a critical archetype issue require a second independent
opinion before forcing a replan? should A3 be able to judge C1's critique against the
plan's own cited evidence before acting on it?), not a bug fixable by changing a
threshold or a prompt line. Recorded here as a genuine open finding for a future
session to design deliberately, not patched reactively under time pressure.

---

## ERR-023 — Two full live re-runs, two FAILs: ERR-010 (word-budget under-generation) is still the primary blocker, not ERR-022
**Date:** 2026-09-10 · **Severity:** open finding, not a code bug (yet) · **Status:** fixed (corrected 2026-09-14 -- see ERR-024, the very next entry, which fixed exactly this) · **Component:** `planning/story_planner.py` (A2)

Two live e2e runs against the real source (`runs/v05`, `runs/v06`, ~$0.28 + $0.26 = $0.54
combined) after ERR-014/ERR-021's fixes, both attempting one clean PASS. Both FAILed, and
both times A2's **first** attempt correctly resolved `archetype: build` (ERR-014's fix is
solid and reproducible) — but both times A2 generated a drastically under-scoped
`scene_plan`: `v06` returned only **5 scenes / ~525 words** against the ~1670-word target
for a 600s video, even with the explicit calibration text already in the prompt
(`target_duration_seconds / 60 * 167`, "20-30 scenes... NOT 4-6 scenes"). This is
`ERR-010` recurring, not a new defect — the deterministic word-budget hard check
(`check_word_budget_matches_target`) caught it correctly both times, exactly as
designed, and that structural failure is what actually forces the replan — the
archetype dispute (ERR-022) is a **secondary, compounding** problem that shows up once a
replan is already underway, not the primary blocker to a clean PASS.

**Why this isn't being patched reactively:** ERR-010's own original conclusion already
ruled out further prompt tuning as the fix ("LLMs are reliably poor at satisfying an
aggregate constraint... The correct fix, applied: a deterministic check, never another
round of prompt tuning") — and that check is doing exactly its job. Reaching a clean
live PASS reliably would need an actual structural change to A2 (e.g., splitting scene
expansion into a second, per-beat call so each individual call's aggregate-counting
burden is much smaller — the same principle behind why a smaller, scoped call succeeds
where a big aggregate one doesn't), not another retry. That is a real design decision
with cost/scope implications of its own, left for deliberate discussion rather than
built unprompted mid-validation.

---

## ERR-024 — Split A2 into structure + per-beat scene expansion (the ERR-010/ERR-023 fix)
**Date:** 2026-09-10 · **Severity:** critical · **Status:** fixed · **Component:** `planning/story_planner.py`, `planning/beat_word_budget.py` (new), `planning/scene_expander.py` (new), `planning/models.py`

Following the open finding logged above: two live re-runs both FAILed primarily on
`ERR-010` recurring (A2 under-generating `scene_plan`), not the archetype dispute. Built
the actual structural fix rather than another retry: `StoryPlan` split into
`StoryStructure` (archetype, hook, CTA, beats, ending -- no scene_plan) plus a separate
per-beat scene-expansion pass. `beat_word_budget.py::allocate_beat_word_budgets()`
computes each beat's own word target deterministically (proportional to how many source
units it covers, exact by construction -- Python's sum can't drift the way an LLM's own
aggregate sum did); `scene_expander.py::expand_beat_scenes()` (A2b) asks one small,
well-scoped call per beat to hit that much smaller, independently-achievable target.

**Live-verified, twice:**
1. Standalone `plan_story()` call at a 900s (15-min) target — chosen deliberately larger
   than earlier 600s tests, per a direct request to get a representative cost estimate
   for real future usage, not just a small-target figure: **8 beats, 44 scenes, 2573
   words against a 2505-word target — ratio 1.03** (previously as bad as 0.19-0.31).
   Cost: **$0.0953 across 9 calls** (1 structure + 8 per-beat expansion).
2. Full pipeline run at the same 900s target (`runs/v07`): **zero `word_budget_mismatch`
   failures in either the first ("build") or replanned ("foundation") attempt** --
   completely eliminated, confirming the fix generalizes beyond the standalone test.
   Cost: $0.3979 across 27 records (2 full structure+expansion cycles plus B1/CM/C1/C2b).

**Tests:** `tests/planning/test_beat_word_budget.py` (6 tests, including exact-sum and
minimum-floor guarantees), `tests/planning/test_scene_expander.py` (5 tests),
`tests/planning/test_story_planner.py` (updated for the two-call flow),
`tests/orchestration/test_pipeline.py` (4 tests updated to mock both calls).

---

## ERR-025 — Third live occurrence of ERR-022: C1 disputes a correct "build" archetype, now the sole confirmed blocker
**Date:** 2026-09-10 · **Severity:** open finding, not a code bug · **Status:** open, now the sole confirmed blocker · **Component:** `review/story_critic.py`, the disagreement-resolution design itself (see ERR-022 for the original finding)

With ERR-010/ERR-023 fixed, `runs/v07`'s live re-run isolated the remaining problem
cleanly: A2's first attempt again correctly resolved `archetype: build` with **zero
word-budget failures** -- and C1 disputed it anyway (`critical/archetype`), forcing a
replan to `foundation`, which then failed for different reasons (`source_units_uncovered:
production_notes`, a CTA landing at **100%** through the story, more grounding
violations). This is the **third** live run in a row (`v05`, `v06`, `v07`) where C1
disputes a `build` resolution that every other signal -- the user's own independent
pipeline, two separate single-call validations (ERR-014, this file's own earlier entry),
and now a clean, well-budgeted first attempt -- agrees is correct. With ERR-010 no longer
a confound, **this is now the single confirmed blocker to a live PASS** on this source,
not one of two compounding issues.

**Still not patched reactively:** the reasoning from the original ERR-022 entry stands --
this needs a deliberate design decision (can A2 push back on a critique with its own
`source_evidence`? does a critical archetype dispute need a second independent opinion
before forcing a replan? should A3 weigh C1's critique against the plan's own cited
evidence rather than accepting it at face value?), not a prompt tweak or another retry.
Secondary, smaller finding from the same run worth tracking separately: `production_notes`
was left uncovered by both attempts' beats despite ERR-011's fix instructing every source
unit to be referenced -- plausibly because it's meta-commentary rather than teaching
content, so no beat naturally claims it; may need its own explicit instruction if it
recurs.

---

## ERR-026 — A3 can now dismiss a re-raised archetype dispute (the ERR-022/ERR-025 fix), narrowly and mechanically enforced
**Date:** 2026-09-10 · **Severity:** critical · **Status:** fixed · **Component:** `editing/models.py`, `editing/revision_planner.py`, `review/aggregator.py`, `orchestration/pipeline.py`

Designed deliberately, not patched reactively, per the original ERR-022/ERR-025 finding. The
core problem: A2 is required to give a real reason for rejecting every other archetype on
every plan, so C1 (a different model family, Gemini vs GPT, specifically for adversarial
independence) re-arguing for one of those five without adding anything new is expected
noise -- but the pipeline had no way to recognize that, and unconditionally promoted any
critical C1 issue to a hard failure with no path back.

**The design tension this had to resolve:** simply letting A3 (same family as A2) overrule
C1 on its own say-so would make the independent critic decorative -- exactly the
"producer != validator" failure mode the plan guards against elsewhere (Appendix G #3/#5).
The fix therefore has TWO layers, deliberately redundant:

1. **A3 gets the plan's own evidence** (`selection_reason`, `source_evidence`,
   `rejected_archetypes` -- previously never passed to it at all) and an explicit procedure:
   before accepting a `category: archetype` critique at face value, check whether the
   alternative it names is already a key in `rejected_archetypes` with a real reason: if so
   and the critique adds nothing new, dismiss it (`RevisionPlan.dismissed_issues`, a new
   field) citing the specific prior reason it fails to add to; only treat it as needing a
   replan if it's genuinely new. The FIRST prompt draft (unconditional "critic raised a
   critical archetype issue -> replan" instruction, still present from before this fix)
   silently overrode this new paragraph -- a live test confirmed A3 still replanned every
   time ($0.0049, 0 dismissals). Fixed by rewriting the archetype-dispute criterion itself
   to require the check as step 1, not an afterthought appended later. Re-tested live:
   correct dismissal, citing the exact matching prior rejection reason ($0.0063).
2. **The dismissal is only honored in CODE, never on the model's word alone**
   (`orchestration/pipeline.py::_legitimately_dismissed_issue_ids`): a mechanical check
   requires the disputed issue to be `severity=critical, category=archetype`, and the
   archetype it names (other than the plan's own current one, which is naturally mentioned
   in any dispute of it) must already be a key in `plan.rejected_archetypes`. This is a
   narrow, imperfect proxy (word matching, not real semantic judgement) -- deliberately
   conservative, so a genuinely novel critique can never be waved away. A real bug caught
   during test-writing: the first version of this check didn't exclude the plan's own
   current archetype from the "must already be considered" set, so a dispute phrased as
   "not a build arc" (mentioning the current archetype, as any dispute naturally would)
   failed the check even when legitimate -- fixed before it ever reached a live call.

**Live-verified end to end**, not just the isolated dismissal call above: a full pipeline
run at the 900s target completed with **`story_replans_used: 0`** -- `build` resolved once
and held through two rounds of targeted rewrite (99 -> 87 -> 73 hard failures, real
incremental progress from B2), the first live run in four attempts (`v05`, `v06`, `v07`,
`v08`) where the archetype dispute didn't derail the plan. The run still `FAIL`ed, but for
reasons unrelated to today's fix: every remaining `grounding_policy_violation` traces to
reusing `runs/v01`'s claims, all still `UNVERIFIED` (C2a was never run against this exact
dataset in this validation harness -- confirmed by inspection, not assumed), plus a real
but secondary `source_units_uncovered`/`cta.position` gap. Cost: $0.4651/24 records.
**Tests:** `tests/editing/test_models.py`, `tests/editing/test_revision_planner.py`,
`tests/review/test_aggregator.py`, `tests/orchestration/test_pipeline.py` (3 new tests:
legitimate dismissal resolves to PASS, illegitimate dismissal is ignored, dismissal leaves
unrelated hard failures intact).

---

## ERR-027 — C2a verification was the dominant remaining noise; a real limitation found in ERR-026's dismissal check
**Date:** 2026-09-10 · **Severity:** major finding + one open design limitation · **Status:** partially addressed · **Component:** validation harness, `orchestration/pipeline.py`

Ran C2a for real against `runs/v01`'s 61 claims (never actually verified before in any
live run this session -- confirmed all `UNVERIFIED` by inspection) rather than continuing
to validate against stale data: 54 VERIFIED, 4 UNVERIFIED, 3 CONTEXT_DEPENDENT, 0 REJECTED,
for $0.0841/2 calls. Re-ran the full pipeline (`runs/v09`) against these real verified
claims: **hard failures dropped from 73-111 (every prior run) to 4-5 per round** --
confirming the stale-claims artifact really was the dominant source of noise once
ERR-026 stabilized the archetype.

**A genuinely new, more subtle scenario surfaced:** this time A2's first attempt resolved
`foundation` (wrong), C1 disputed it, A3's log line read "dismissed 1 critique issue(s)
already ruled out in the plan's own rejected_archetypes" -- and A3 *also* set
`story_replan_required=true` for a separate reason, and the replan correctly landed on
`build`. The final archetype was correct, but **the validation harness doesn't persist
each round's intermediate review bundle**, only the final one -- so it's not actually
possible to confirm from this run's saved artifacts whether the dismissed issue was
itself the (correct) "should be build" critique, or an unrelated, genuinely re-raised one.
Not fabricating certainty either way: this is an honest observability gap in the harness
script, not a claim that ERR-026 misfired.

**What IS a real, standing limitation, independent of this specific run:** ERR-026's
mechanical check verifies only that an alternative archetype is ALREADY a key in
`rejected_archetypes` -- it has no way to judge whether A2's *original rejection reason*
was itself sound. If A2 rejects the correct archetype with a real-sounding but wrong
reason, and C1 later correctly re-argues for it, the mechanical check would currently
treat that as "already considered" and could let A3 legitimately dismiss a correct
critique. This wasn't caught happening in this run (the correct archetype won out
regardless, via a separate signal), but it's a real gap in the design, not fully closed --
verifying reasoning QUALITY, not just reasoning EXISTENCE, would need a genuinely harder
semantic check than word-matching can provide. Flagged for the same "deliberate future
design" treatment as the original finding, not patched under time pressure.

Remaining `runs/v09` failures were otherwise legitimate, not defects: 3 of 4 hard failures
are the grounding policy correctly refusing to narrate claims C2a genuinely could not
verify (exactly the intended behavior); the 4th (`core_role_missing`) plus a CTA landing
at 100% are real, secondary gaps in that specific replanned attempt, within
`MAX_STORY_REPLANS=1`'s bound (correctly failed rather than looping further). Cost:
$0.5791/40 records.

---

## ERR-028 — V1A-S: CM/C2b saw the full claim registry instead of a short's scoped fact set
**Date:** 2026-09-10 · **Severity:** major · **Status:** fixed · **Component:** `orchestration/shorts_pipeline.py`

First live end-to-end validation of the new V1A-S short pipeline (SC → A2s → B1s → CM → C2b
→ C1s → C4s → hard checks → diagnostics, $0.0101/7 calls against the real, verified
attention-series source): the run correctly FAILed, but on `claim_outside_allowed_fact_set`
-- narration cited claim `C034` in two segments, and it was genuinely outside the short's
`allowed_fact_ids`. `narration/short_generator.py::generate_short_narration()` already
scopes the claims it *offers* B1s to `allowed_fact_ids`, but `orchestration/shorts_pipeline.py`
passed the **full**, unscoped `claims` list to `map_claims()` (CM) and `verify_grounding()`
(C2b) -- so CM, doing its own job correctly, was free to ground a sentence to any claim in
the whole registry, including ones outside this specific short's verified scope.

**Fix:** scope `claims` to `allowed_fact_ids` once, before EITHER narration generation or
CM/C2b -- consistent scoping applied at the single point every downstream call reads from,
so CM/C2b never even have the option to cite an out-of-scope claim, rather than only
detecting the violation after the fact via `check_grounding_scope`.
**Live-verified:** re-ran end to end after the fix ($0.0192/15 calls, a different candidate
this time) -- zero `claim_outside_allowed_fact_set` failures; the run still correctly FAILed,
but now on entirely different, genuine findings (a real title/hook mismatch, a 71.9s
narration exceeding the 62s cap, and C1s correctly catching that the narration didn't
actually execute its own declared `problem_fix` micro-arc) -- confirming every check in the
new pipeline catches real issues on real data.
**Test:** `tests/orchestration/test_shorts_pipeline.py::test_cm_and_c2b_never_see_a_claim_outside_the_allowed_scope`

---

## ERR-029 — V1B: grid component item shape assumed, not specified -- crashed twice on real data
**Date:** 2026-09-11 · **Severity:** major · **Status:** fixed · **Component:** `html_synth/component_library.py`

First live validation of the new H stage (`html_synth/synthesizer.py` + `assembler.py`,
free/subscription-lane Sonnet, against the real verified attention-series plan/narration):
crashed twice in a row, each on a different assumption about what shape a `grid_2`/`grid_3`
component's `items` slot would contain -- `design_system.yaml`'s own comment said "list of
pre-rendered component snippets", but nothing in the prompt or schema actually told the model
that, or gave it any inner shape to follow.

1. First crash: the model returned `items` as a list of `{title, value, desc}` dicts (a
   sensible, safe choice -- it never has to produce markup at all, matching the
   established "the LLM supplies data, Python renders it" principle used everywhere else in
   this codebase). Fixed by rendering each dict through the existing `card` component.
2. Second crash, immediately after: a *different* beat's `grid_3` (a grid of short
   observations) returned `items` as plain strings, not dicts -- because nothing pins the
   inner shape, the model reasonably chose a simpler shape for simpler content.

**Fix:** `_render_grid_item()` handles both shapes (dict -> rendered as a mini-card; string
-> rendered as a minimal card with just a description) rather than assuming one -- crashing
on a reasonable model output is worse than rendering it slightly differently. Applied the
same defensive handling to `step_list` preemptively, since it has the identical
unconstrained-item-shape structure.
**Live-verified:** a third run after both fixes completed with **zero render_issues**: a
real 59.7KB `video_script.html` / 34.3KB `page.html`, 3218 visible words (inside the plan's
own ~2,000-3,200 target band), 24 cards / 14 defboxes / 8 grid-3s rendered, 3 numbers
correctly traced to real claim ids via `data-numeric-claim-id`. Cost: $0 (Sonnet,
subscription lane).
**Tests:** `tests/html_synth/test_component_library.py` -- `test_grid_3_handles_plain_string_items_without_crashing`,
`test_step_list_handles_plain_string_items_without_crashing`, plus escaping tests for both shapes.

---

## ERR-030 — Embedded narration JSON could break out of its `<script>` block
**Date:** 2026-09-11 · **Severity:** major (real security gap, never actually triggered by live content) · **Status:** fixed · **Component:** `html_synth/assembler.py`, `html_synth/vertical_assembler.py`

Found while writing a security-conscious test for the new vertical shorts template, not
live: `<script id="narration-data" type="application/json">{narration_json}</script>` embeds
the canonical narration text verbatim. `<script>` content is normally never HTML-parsed
(unlike every other tag, which is why component slots are HTML-escaped and this text
deliberately isn't) -- EXCEPT that the raw byte sequence `</script` always closes the tag
regardless of what a JS/JSON string literal contains. Real narration text can legitimately
contain that exact substring (a sentence discussing HTML tags, "the `</script>` tag", etc.),
which would otherwise terminate the block early and let the remainder of the JSON -- or an
attacker-supplied sentence riding along with it -- render as live page markup.

**Fix:** `html_synth/component_library.py::escape_script_json()` replaces `"</"` with
`"<\\/"` before embedding -- the standard mitigation: valid JSON permits escaping `/`
optionally, so `JSON.parse()` still decodes it back to `</` correctly, while the HTML parser
no longer recognizes a closing tag. Applied at the embed site only, never to the value
`narration_hash()` computes (which must stay byte-identical to the real `narration.json`
file written to disk).
**Tests:** a real DOM-parse-based regression test in both `test_assembler.py` and
`test_vertical_assembler.py` (confirms no `<img>` ELEMENT is ever parsed, not just a
substring search, since the raw exploit text legitimately still appears as inert data
inside the now-correctly-closed script block) plus two direct unit tests for
`escape_script_json` itself.

---

## ERR-031 — `check_payoff_closes` too unreliable for a mechanical word-match, downgraded
**Date:** 2026-09-11 · **Severity:** open finding, not a code bug in the content itself · **Status:** fixed (by removing it from the hard gate, not by chasing a threshold) · **Component:** `verification/hard/render.py`

Live validation of the new content-level HV checks against the real, C2a-verified
attention-series output surfaced this twice, on two separate live H regenerations of the
*same* source:

1. First run: the final scene correctly bridged to "Part 2" via `ending.next_video_bridge`
   ("explore alternative attention mechanisms...") rather than restating
   `capstone_payoff`/`compressed_mental_model` -- both are valid endings per
   `EndingContract`'s own shape (the bridge field exists specifically for a series that
   continues). Fixed by including `next_video_bridge` in the comparison text.
2. Second run, same source, freshly regenerated (H is non-deterministic): a differently
   -worded but equally valid bridge sentence ("teams are testing different bets on how much
   ... can be approximated or skipped...") STILL scored below threshold against the one-
   sentence `next_video_bridge` summary, because the two texts are topically related but
   share almost no literal vocabulary -- an LLM is free to reword a bridge however it
   likes each time, and a mechanical word-overlap check can't reliably follow that the way
   it can for a title/hook/central-topic restatement (which naturally repeats the same key
   terms).

**Not fixed by relaxing the threshold** -- that would be chasing one observed run, the exact
anti-pattern this project already ruled out for ERR-010's word-budget problem. Instead,
`check_payoff_closes` is kept as a real, tested, available function but removed from
`check_render_content`'s hard-gate aggregate: "does the payoff genuinely close the story" is
a genuine semantic judgment call, better suited to a cheap LLM check (C1-style) than a
mechanical proxy, when this gets built out further.
**Tests:** `tests/verification/hard/test_render_content.py::test_ending_on_a_next_video_bridge_is_clean_not_a_false_positive`
locks in the first fix; the function itself remains fully unit-tested for future reuse.

---

## ERR-032 — No retry on transient paid-API errors; a real ~45-min/~$0.71 run died on one Gemini 503
**Date:** 2026-09-11 · **Severity:** major (pipeline crash, real money/time lost) · **Status:** fixed · **Component:** `llm/backends/litellm_backend.py` · **Live cost:** yes (~$0.71 sunk, run lost)

The first-ever live run of the new `orchestration/run_pipeline.py` CLI entry point (see
BUILD_PLAN.md's cross-cutting orchestrator item) ran S0 through H/HV/SC/A2s for real —
71 claims, A1, the full story+narration loop, 10 H beats — then crashed inside
`run_short`'s `map_claims` call with `litellm.exceptions.ServiceUnavailableError`: a 503
from Gemini ("This model is currently experiencing high demand. Spikes in demand are
usually temporary."). The entire run (~45 minutes wall-clock, ~$0.71 of real paid-lane
spend already recorded in `usage.jsonl`) was lost to a single transient upstream error
with no run-state recovery.

Root cause: `LiteLLMBackend.call()` invoked `litellm.completion(...)` with no
`num_retries`, and litellm does not retry by default — `num_retries` must be passed
explicitly to activate its own tenacity-backed retry classification (which already knows
to retry `RateLimitError`/`Timeout`/`ServiceUnavailableError`-class failures and never
retry a genuine `AuthenticationError`/`BadRequestError`).

**Fix:** `LiteLLMBackend.__init__` gained `num_retries: int = 3`, forwarded into every
`litellm.completion(...)` call. Deliberately reuses litellm's own already-tested retry
policy rather than hand-rolling exception-type matching.
**Tests:** `tests/llm/test_litellm_backend.py::test_num_retries_defaults_to_3_and_is_forwarded_to_litellm`,
`::test_num_retries_is_configurable`.
**Not yet fixed:** a run still can't resume mid-pipeline after a fatal crash (that needs
`orchestration.state.PipelineState` actually wired through `run_pipeline.py`, which it
isn't yet — see BUILD_PLAN.md). Retries reduce how often this matters; they don't remove
the gap.

---

## ERR-033 — `diagram_card` rendered an empty placeholder; headline components used a non-Apple serif font
**Date:** 2026-09-11 · **Severity:** major (every "figure" in the final HTML was visually blank) · **Status:** fixed · **Component:** `html_synth/component_library.py`, `config/design_system.yaml`, `html_synth/synthesizer.py`

User-reported after inspecting a real rendered `page.html`: (1) the page didn't look like
the source's own Apple-style white theme, and (2) every figure/visualization from the
source was missing. Root-caused to two separate, real gaps:

1. `diagram_card`'s design-system skeleton was, by its own docstring, *"A labeled
   placeholder for a visual the render stage will eventually draw"* — `slots: [caption]`
   only, rendering `<div class="diagram-placeholder"></div>`: a permanently empty gray
   box. The H pass (Sonnet) had no slot to put actual diagram content into even when it
   picked this component — the schema itself made a real figure impossible, not a model
   failure.
2. `design_system.yaml`'s `fonts.sans`/`fonts.serif` were `'DM Sans'`/`'DM Serif Display'`
   (external Google Fonts), and `component_library.py`'s `BASE_STYLESHEET` used
   `font-family:var(--serif)` for `.hero-title`/`.section-title`/`.card-value` — headline
   elements rendered in a serif face the source itself never uses for headlines (the
   source's real `--font` is the Apple system stack; its one `--serif` use is a small
   italic editorial subtitle, never a headline).

**Fix:**
- `diagram_card` gained a real `content` slot (rendered as `<pre class="diagram-pre">`,
  monospace, matching the source's own `.code-pre` ASCII-art pattern) alongside `caption`;
  `synthesizer.py`'s H task prompt now explicitly requires a real compact ASCII-art
  diagram in `content`, never blank, never a prose restatement of the caption.
- `fonts.sans` is now the real Apple system stack (`-apple-system, BlinkMacSystemFont,
  'SF Pro Display', 'SF Pro Text', 'Helvetica Neue', sans-serif`, matching the source
  corpus verbatim); `fonts.serif` is `'Literata'` (also matching the source), kept
  available for a future editorial-accent component but no longer used by any headline
  selector — `.hero-title`/`.section-title`/`.card-value` now use `var(--sans)`.

**Live-verified:** a real CLI run (`runs/v11`) confirms no `DM Serif`/`DM Sans` anywhere in
the emitted HTML and `-apple-system` present; that specific run's H pass happened not to
select `diagram_card` for any of its 10 beats (component choice is deliberate per-scene
LLM judgment, "never force a component onto every scene" — not itself a bug on one run),
so real ASCII-art `diagram_card` content is unit-tested but still pending a live sample —
flagged below as a follow-up, not chased by forcing the prompt (ERR-010/ERR-031's own
precedent against over-fitting to one observed run).
**Tests:** `tests/html_synth/test_component_library.py::test_diagram_card_renders_real_content_not_an_empty_placeholder`,
`::test_diagram_card_content_is_html_escaped`, `::test_headline_components_use_the_sans_apple_system_stack_not_serif`.

---

## ERR-034 — Shorts' own `visual` field (dominant_object/states) was authored by a real LLM call and then never rendered
**Date:** 2026-09-11 · **Severity:** major (every short was bare prose, no visual at all) · **Status:** fixed · **Component:** `html_synth/vertical_assembler.py`

User-reported: "Shorts script is only few sentences no diagram, nothing." A short's brief
narration length (45-60s, plan §20.4's own "no narrative oxygen for a recap") is by
design, not a bug — but the complete absence of any visual was a real gap: A2s
(`planning/short_planner.py`) already asks the model to design `ShortPlan.visual`
(`dominant_object` + `states` + `safe_zones`) for every short, and `vertical_assembler.py`'s
`_render_screen` simply never read that field — every short screen rendered bare
`.short-prose` text only, regardless of what A2s had designed. Same root-cause shape as
ERR-033: real content collected, then silently dropped before rendering. Also carried the
same serif-vs-Apple-sans font mismatch as ERR-033's headlines (`.short-prose` used
`var(--serif)`).

**Fix:** a new deterministic (zero-extra-LLM-cost) `_dominant_object_flow()` renders
`dominant_object` + `states` as an arrow-joined flow string (e.g. "attention weights →
uniform → peaked → dominant") on the short's `mechanism` screen only, styled as a
monospace `.short-visual` block matching the long-form diagram language; omitted entirely
when `states` is empty (no diagram forced onto content that has none, matching
`diagram_card`'s own optionality rule). `.short-prose` now uses `var(--sans)`.
**Tests:** `tests/html_synth/test_vertical_assembler.py::test_visual_dominant_object_and_states_render_as_a_diagram_on_the_mechanism_screen`,
`::test_no_visual_states_renders_no_diagram_block_not_a_crash`,
`::test_dominant_object_alone_with_no_states_renders_no_diagram`,
`::test_diagram_content_is_html_escaped`, `::test_short_prose_uses_the_sans_apple_system_stack_not_serif`.

---

## ERR-035 — `archetype_role` (the field that gates visual-component choice) has been unreachable in EVERY real run to date
**Date:** 2026-09-11 · **Severity:** critical (silently made most of the component library dead code in every real run) · **Status:** fixed · **Component:** `planning/story_planner.py` · **Live cost:** yes (~$0.31 across 2 confirmatory A2-only calls)

While investigating ERR-033's "missing figures" report, checked every real plan produced
this session (`v01`, `v09`, `v10`, `v11`) for what `StoryBeat.archetype_role` actually
contained — the field `html_synth/synthesizer.py` reads to decide which components
(`components_for_story_role(beat.archetype_role or "observations")`) a beat's scenes may
use. Found: **every beat, in every one of the 4 real plans, resolved to exactly
`(grid_3, defbox)`** — never `diagram_card`, `math_block`, `hero` (beyond page 1), `card`
as a standalone choice, any `callout_*`, `metric_table`, or `step_list`. Root cause: A2's
`TASK_PROMPT` (`story_planner.py`) only ever explained `archetype_stage` (the resolved
archetype's OWN vocabulary, e.g. "justified_step" for derivation) — it never mentioned
`archetype_role` at all (a separate field holding the FIXED, generic, cross-archetype
vocabulary — hook/contradiction/investigation/problem_fix/mechanism/comparison/
derivation/observations/payoff — that `design_system.yaml`'s `story_roles` table actually
keys on). Two real plans (v01, v09) show the LLM filling `archetype_role` with
`archetype_stage`-shaped values anyway (schema field present, never explained); two (v10,
v11) show it left entirely blank. Either way, `components_for_story_role()` never
recognized the value (or got none), fell back to `"observations"` every single time, and
every beat in every real run to date got the same two components regardless of content.
This is a much larger, more systemic finding than ERR-033's placeholder bug — it explains
why figures/visuals were missing far more completely: even a correctly-filled
`diagram_card` (ERR-033's fix) could never be *chosen* for any beat, because `mechanism`
(the role that includes it) was unreachable.

**Fix, in two passes (both live-verified):**
1. First pass: explained `archetype_role` as a field separate from `archetype_stage`,
   listing the 9-term vocabulary. Live result: 1/10 beats correct, 9/10 still swapped the
   two fields (put the archetype-specific term in `archetype_role`, left `archetype_stage`
   blank) — the field NAMES alone ("role" vs "stage") didn't disambiguate which vocabulary
   went where.
2. Second pass: added a concrete worked example directly in the prompt (`archetype =
   "derivation"` → `archetype_stage = "justified_step"`, `archetype_role = "mechanism"`,
   explicitly "NOT justified_step"). Live result: **7/7 beats correct** on a fresh real A2
   call (archetype=build) — every beat got a valid, vocabulary-correct `archetype_role`
   (`problem_fix`/`mechanism`) distinct from its own `archetype_stage`
   (`problem_to_solution_pair`/`further_limitation_fix_round`/`assembled_system`).
**H-stage confirmation (live, $0.0986, free/subscription lane):** ran H on the same fresh
`archetype_role`-correct plan (11 beats, 8 now tagged `mechanism`/`problem_fix`). Component
usage across all beats: `{card: 11, math_block: 5, diagram_card: 9, callout_warn: 2,
step_list: 2, callout_success: 2, defbox: 2, grid_3: 1, hero: 1}` — every component family
in the library is now actually reachable and chosen, not just `grid_3`/`defbox`. The 9 real
`diagram_card` instances are genuine, well-formed ASCII-art diagrams matching the source's
own visual language (e.g. `build_matrix_s04`: `"Q1 --\\  /-- K1\nQ2 ---- ALL-TO-ALL ----
K2\nQ3 --/  \\-- K3"`; `build_heads_s02`: a per-head Q/K/V fan-out diagram), and the 5
`math_block` instances carry real equations (`q = x W_Q, k = x W_K, v = x W_V`,
`softmax(QK^T / sqrt(d_k))`, `MultiHead(Q,K,V) = Concat(head_1, ..., head_n) * W_O`). This
confirms ERR-033's `content`-slot fix and this entry's `archetype_role` fix together fully
resolve the "missing figures" report — the placeholder fix alone was necessary but not
sufficient; the role-gating fix is what actually made the component reachable at all.
**Residual minor gap:** one of the 11 beats (`build_origin`) still got `role='context'`, a
term outside the fixed 9-word vocabulary despite the explicit instruction — `components_for
_story_role("context")` returns `[]`, so Python's own `or components_for_story_role
("observations")` fallback (already in place, not new) absorbed it gracefully rather than
crashing. 10/11 correct on this run is a large, real improvement over 0/11 before; not
chased further per the ERR-010/ERR-031 precedent against over-fitting a prompt to one
observed run — worth revisiting only if a future run shows this recurring often.
**Tests:** `tests/planning/test_story_planner.py::test_prompt_instructs_populating_archetype_role_with_the_render_vocabulary`.

**Full e2e confirmation (2026-09-11, `runs/v12`, $0.5036, no retry needed):** the committed
`orchestration/run_pipeline.py` CLI ran genuinely fresh start to finish -- S0 (12 units) →
S2/C2a (68 claims) → A1 → the loop (archetype=derivation) → H/HV (8 beats, **0 render
issues**) → shorts (SC/A2s/run_short/vertical HV, **0 issues**) -- with all of ERR-032
through ERR-035's fixes in play together for the first time. Result: **8/8 beats** got a
valid `archetype_role` (7 `mechanism`, 1 `observations`); the emitted `page.html` contains
**12 real `diagram_card` instances** (e.g. a query/key matching diagram for "it", an
unrestricted-attention diagram showing every position attending every other) and **8 real
`math_block` equations** (e.g. "Query-key similarity score", "Variance of an unscaled dot
product"); zero `DM Serif`/`DM Sans`, `-apple-system` present; the short's own
`.short-visual` block rendered a real state-flow diagram ("Softmax gradient visualizations
→ Saturated gradients without √d_k → Stable gradients with √d_k") with no serif font. Final
status was `FAIL` and correctly not promoted -- on three real, pre-existing content-quality
findings unrelated to any of this session's fixes: two source units never covered, a
title/hook promise mismatch, and C1 correctly catching that the source's own production
notes dictate `build` while A2 chose `derivation` (an archetype-classification dispute the
review loop is specifically designed to catch, not a bug in this fix set).

---

## ERR-036 — `<header class="hero">` was structurally invisible to extraction; the hook's own concrete example never reached A1/A2
**Date:** 2026-09-11 · **Severity:** major (the single most carefully-written hook material in the source was never available to ground on) · **Status:** fixed · **Component:** `extraction/html_parser.py`

User-reported, comparing the generated hook against the source directly: the source's hook
uses a concrete minimal-pair example ("the cat couldn't climb the stairs because it was too
**tired**" vs "...too **steep**" — same pronoun, opposite referent), while the generated hook
stayed abstract ("Understanding the seemingly complex mechanism of how Transformers retrieve
context"). Root cause: `<header class="hero" id="hook">` sits BEFORE any `<section
class="section">` in the document, so every profile's `section.select("section.section")`
walk (the shape all real profiles share) is structurally blind to it — the exact same gap
`_extract_production_notes` already fixed once for `.page-footer` (ERR-013), just never
mirrored for the header. The example was never missing from the source, only from every
`SourceUnit` ever built from it.

**Fix:** `_extract_hero_hook()` mirrors `_extract_production_notes()` — pulls `<header
class="hero">`'s `h1` + `.hero-sub` into its own leading `SourceUnit` (id from the header's
own `id` attribute, "hook" on the real source), profile-agnostic like its footer
counterpart. Live-verified deterministically (S0 has no LLM in it): the real source now
yields 13 units (was 12), with unit `hook` containing both "too tired" and "too steep".
**Tests:** `tests/extraction/test_html_parser.py::test_hero_header_is_extracted_as_its_own_unit`,
`::test_plain_source_with_no_hero_header_produces_no_hook_unit`,
`::test_real_source_hero_header_carries_the_concrete_hook_example`.
**Related, not fixed here:** the source's own recap-section callout already names three
specific next-video techniques (Sparse attention, linear-attention, FlashAttention) and
already reaches A2's payload (confirmed: it's a real section callout, not header/footer-
excluded) — yet a real generated ending still bridged generically. That's an LLM
specificity gap, not a data-availability one; not chased this round (single observed
run, ERR-010/ERR-031 precedent).

---

## ERR-037 — `.reveal` elements were invisible at rest, dependent on JS + scroll to ever appear
**Date:** 2026-09-11 · **Severity:** critical (every page this pipeline has ever produced was affected) · **Status:** fixed · **Component:** `html_synth/component_library.py`, `html_synth/assembler.py`, `html_synth/vertical_assembler.py`

User-reported "lot of empty space" on a real `short.html`. Investigating found `.reveal{
opacity:0; ...}` with visibility added only by an `IntersectionObserver` once an element
scrolled into view — meaning every long-form scene/section and every shorts screen (`hook`,
`setup`, `mechanism`, `payoff` all carry class `reveal`) rendered **completely blank** in
any viewer that doesn't execute JS, or doesn't scroll every element into view first (a
static preview, a thumbnail capture, an IDE's sandboxed HTML viewer). This affected BOTH
`assembler.py` (long-form) and `vertical_assembler.py` (shorts) identically — a
previously-undetected, pipeline-wide bug, because every earlier live check in this session
inspected the emitted HTML via text/grep, never an actual browser render.

**Fix:** replaced the JS/IntersectionObserver-gated reveal with a pure-CSS `@keyframes`
fade-in that plays automatically on load, no JS or scroll dependency at all: `.reveal{
opacity:1; animation: revealIn 0.5s ease;}` — base `opacity:1` means content is visible
even if the animation itself never runs (unsupported browser, `prefers-reduced-motion:
reduce`, anything). `REVEAL_SCRIPT` and its `<script>` tag are removed entirely from both
assemblers as dead code, not left as an unused stub.
**Tests:** `tests/html_synth/test_component_library.py::test_reveal_is_visible_at_rest_with_no_js_or_scroll_dependency`.

---

## ERR-038 — Shorts' own visual redesign overshot into "not Apple style"; a required spoken bridge line was silently skipped
**Date:** 2026-09-11 · **Severity:** major · **Status:** fixed · **Component:** `html_synth/vertical_assembler.py`, `narration/short_generator.py`

Two more real findings from the same shorts investigation, both user-reported directly
against a rendered `short.html`:

1. **"weird big font", "not apple style"** — my own first pass at filling the empty space
   (ERR-037's real cause, not yet found at the time) overcorrected: 52px bold prose, four
   different rainbow accent colors (one per segment), and a giant 640px low-opacity
   background numeral. Real Apple pages use size contrast between an actual headline and
   body copy, not uniform 52px-bold paragraphs, and one consistent accent color throughout
   (the source's own `--blue:#0071e3` used everywhere), never a different hue per section.
   **Fix:** dialed back to 36px/weight 600 prose, one consistent `var(--accent)` label
   color, watermark removed entirely.
2. **"no mention of subscribe channel in the end"** — a real generated short had
   `bridge.mode="SPOKEN"` (A2s correctly decided a follow-up line belonged here) but the
   actual payoff narration had no such line at all. Root cause: `narration/short_generator.py`'s
   own opening framing ("no reserved subscribe slot -- there is no narrative room for any
   of that") is a blanket rule stated BEFORE the later conditional instruction, and
   evidently dominated the model's behavior even when `bridge.mode` explicitly called for
   one. **Fix:** rewrote the payoff-segment instructions to break out all four `bridge.mode`
   values explicitly, marking the SPOKEN case's follow-up sentence as REQUIRED with a
   concrete example, and rescoped the opening "don't invent one" framing to the other three
   modes only.
**Tests:** `tests/html_synth/test_vertical_assembler.py` (existing diagram/font tests still
green against the dialed-back CSS), `tests/narration/test_short_generator.py::test_prompt_requires_a_spoken_bridge_line_when_mode_is_spoken`.

---

## Full e2e confirmation (2026-09-11, `runs/v13`, $0.6575) -- ERR-036/037/038 combined

A fresh CLI run with every fix from ERR-032 through ERR-038 in play together (the first
run since the hook-extraction and reveal-visibility fixes landed):

- **S0: 13 units** (was 12 pre-ERR-036) -- the `hook` unit is real this run, and
  `source_units_uncovered` no longer lists it (only `origin`/`production_notes` remain
  uncovered, both expected: production_notes is meta-commentary for planning, never meant
  to become its own beat).
- **archetype_role: 8/8 beats valid** (hook/problem_fix/mechanism/derivation/payoff), third
  consecutive live confirmation of ERR-035's fix.
- **H/HV: 0 render issues**, 3 real `diagram_card`s + 4 real `math_block`s + 3 `step_list`s
  in the emitted `page.html`; correct Apple font; `.reveal{opacity:1;...}` present (ERR-037
  visible-at-rest fix confirmed).
- **Hook narration is qualitatively better** even without quoting the source's exact
  example sentence: "Take a simple sentence with the word 'it' in it... change just one
  other word in that same sentence, and 'it' can suddenly point somewhere completely
  different" -- genuinely conveys the source's own minimal-pair insight, versus the prior
  generic "understanding the seemingly complex mechanism" framing.
- **Shorts**: this short's own `bridge.mode` was `NONE` (a different, also-valid choice
  than the SPOKEN case ERR-038 fixed) -- payoff correctly has no forced subscribe line;
  `visual.states` populated and rendered as a real `.short-visual` diagram on the mechanism
  screen; dialed-back 36px font confirmed; no leftover watermark/per-segment-accent markup.
- **FAIL was correct**, on real, legitimate findings unrelated to this fix set: two
  grounding-policy violations (a REJECTED claim narrated, several UNVERIFIED CORE claims
  narrated without a hedge), a missing `build`-archetype core role, and a promise-chain
  mismatch -- exactly what the hard gate exists to catch.
- **New soft observation, not fixed:** `ending.next_video_bridge` in the StoryPlan named
  the source's specific follow-up techniques ("sparse, linear, flash attention"), but the
  actual spoken narration's ending stayed generic ("So where does attention go from
  here?") -- narration generation isn't tightly grounding the ending on the plan's own
  bridge field, a similar shape of gap to ERR-038's shorts case but for long-form B1. Not
  chased this round (one observed run, and the ending still functions as a real bridge,
  just a softer one) -- worth a targeted fix if a future run shows this recurring.

---

## ERR-039 — Concrete claims were abstracted into vague restatements by A2/A2b; shorts' layout/type/diagram treatment was still not "up to the mark"
**Date:** 2026-09-11 · **Severity:** major · **Status:** fixed (hook/scene prompts); shorts redesigned per direct user feedback · **Component:** `planning/story_planner.py`, `planning/scene_expander.py`, `html_synth/vertical_assembler.py`

Two more real findings, both user-reported directly against generated output:

1. **Concrete example still missing from the hook, even after ERR-036's extraction fix.**
   Verified precisely: S2b correctly extracts a crisp, literal claim from the source's own
   hook ("changing 'it was too tired' to 'it was too steep' causes 'it' to refer to a
   different entity") -- confirmed via a live, free claim-extraction check. Yet a real
   generated `hook.tension` still read as a generic abstraction ("the same pronoun can
   refer to different things depending on context"). The data reaches A2 correctly; A2 and
   A2b were never told to prefer a concrete illustration already in the claim registry over
   their own paraphrase of one. **Fix:** both `story_planner.py`'s hook-writing guidance and
   `scene_expander.py`'s scene guidance now explicitly require using a concrete
   illustration (an actual example, number, or named scenario) directly when an available
   claim already is one, with a worked contrast ("the kind of vague restatement to avoid").
   **Tests:** `tests/planning/test_story_planner.py::test_prompt_instructs_using_a_concrete_example_when_the_source_gives_one`,
   `tests/planning/test_scene_expander.py::test_prompt_instructs_using_a_concrete_illustration_when_a_claim_has_one`.

2. **Shorts still not "up to the mark" after the ERR-038 restraint pass.** Asked the user
   directly what specifically felt off (no way to render/screenshot HTML in this
   environment) -- answer: too plain/boring, wrong layout/composition (not a colour/font
   issue), and needed a real visual rather than text. Root cause: every screen used the
   exact same flat 36px prose regardless of role, and the "diagram" was one line of
   monospace arrow-joined text -- neither reads as a designed video mockup. **Fix:** real
   type-scale hierarchy per screen role (hook 58px/700-weight and payoff 44px/700-weight
   bookend the piece; setup/mechanism drop to 30-32px/500-weight body copy for their longer
   sentences -- deliberate size contrast, not one size everywhere), and the mechanism
   diagram is now a genuine connected node-flow (a labelled accent-coloured dot per stage
   joined by a connecting line, HTML/CSS -- reuses the long-form `step_list` visual idiom)
   instead of monospace arrow-text; HTML text wraps naturally regardless of label length,
   which hand-authored SVG text would not have done without manual line-breaking.
   **Tests:** `tests/html_synth/test_vertical_assembler.py::test_visual_dominant_object_and_states_render_as_a_flow_diagram_on_the_mechanism_screen`
   and the surrounding diagram/escaping tests, updated for the new markup.

**Also tried, not adopted:** `gpt-5.6-sol` as a one-off `openai_story_strong` alternative
for A2 (user-requested experiment) -- confirmed real and callable via litellm, reasoning-
capable but not a hidden-reasoning-burn trap (69/272 completion tokens on a moderate real-
shaped prompt). On the one real A2 call tried, it returned a WORSE result than the existing
`gpt-4o`: `hook.tension`/`viewer_problem`/`promise` all came back completely empty rather
than merely generic. Logged as `openai_story_strong_gpt56` in `config/models.yaml` for
future reference, not wired into any default agent -- not chased further on one bad sample
per this project's own established precedent, but a caution against adopting it without
more evidence.

---

## ERR-040 — Multimodal calls need `tenacity`; Gemini/Vertex rejected a PNG but accepted an identical-content JPEG
**Date:** 2026-09-11 · **Severity:** major (would have silently blocked V1C's C3 visual critic) · **Status:** fixed · **Component:** `llm/backends/litellm_backend.py`, `pyproject.toml` · **Live cost:** yes (a few tiny multimodal test calls, <$0.01 total)

Building V1C-1's multimodal prerequisite (threading `images` through
`Agent.run()` → `call_structured_paid()` → `LiteLLMBackend.call()`), the very first live
test call failed before ever reaching Gemini: `Exception: tenacity import failed`. Root
cause: `litellm.completion(..., num_retries=3)` (ERR-032's retry fix) only routes through
its tenacity-backed retry wrapper for the multimodal content-block message path — a
plain-string call with the identical `num_retries=3` never needed it and had been working
correctly in every real run so far, so this gap was completely invisible until the first
real multimodal call. **Fixed** by adding `tenacity>=8.0` as an explicit dependency
(litellm's own soft dependency for this feature, not bundled).

Second, separate finding on the same live check: a degenerate 1x1 PNG, and then a real
64x64 solid-color PNG generated via Pillow, were BOTH rejected by Gemini/Vertex with `400
"Unable to process input image"` — while an equivalent solid-color JPEG succeeded
immediately. Root cause not fully isolated (could be litellm's Vertex-path PNG handling,
or Vertex's own image validation), but the practical, live-confirmed fix is clear:
**C3's real screenshots must be captured/sent as JPEG, never PNG** (Playwright supports
`page.screenshot(type="jpeg")` directly, so this costs nothing to adopt).
**Tests:** `tests/llm/test_litellm_backend.py::test_live_gemini_multimodal_smoke` (now
JPEG, passing — confirmed real content: asked "what color is this image", a solid blue
JPEG, got back "Blue."), plus the two new non-integration unit tests
(`test_no_images_sends_a_plain_string_user_message`,
`test_images_become_an_openai_style_multimodal_content_block_list`) locking in the
content-block shape without needing a real call.

---

## ERR-041 — V1C's rendered checks had two real false-positive bugs, found on the first full live run
**Date:** 2026-09-11 · **Severity:** major (would have burned the entire H-repair budget on non-issues, every run) · **Status:** fixed · **Component:** `verification/hard/render_rendered.py` · **Live cost:** yes (~$0.56, `runs/v14`)

The first-ever live run of the complete V1C loop (Playwright -> repair -> C3) against the
real source hit its repair budget (2/2) without ever reaching a clean render, leaving 17
unresolved `render_issues`. Investigating each one found two genuine measurement bugs in
the checks themselves, not real problems in the generated page:

1. **`rendered_clipping` false positives on every `<pre class="diagram-pre">` at mobile
   width.** `diagram-pre` deliberately has `overflow-x:auto` (added specifically so a wide
   ASCII diagram scrolls horizontally on a narrow viewport instead of being cut off --
   exactly the "wide content gets its own `overflow-x:auto` container" pattern). The check
   treated ANY of `hidden|clip|scroll|auto` as "clipping," so this working, intentional
   scroll behavior was flagged as broken every single time, and the H-repair loop spent a
   real repair attempt trying to fix something that was never actually a bug.
2. **`rendered_low_contrast` false positive on `.callout-success`.** Its background is
   `rgba(52,199,89,0.06)` -- a pale mint wash over the page's white background, which
   composites to roughly `rgb(243,252,245)` and gives dark-green text a real ~7.7:1
   contrast ratio. The check's `bgOf()` instead treated any non-fully-transparent
   background as "found, done" and used the raw, un-composited `rgba(52,199,89,0.06)` as
   if it were the fully opaque `rgb(52,199,89)` it interpolates toward -- measuring a false
   ~3.6:1 "failure" against a genuinely vivid green that was never actually on screen.

Together these consumed BOTH real repair attempts in `runs/v14` on non-bugs, meaning the
budget was exhausted before the loop ever got a chance to fix anything real -- a
significant finding about the checks' own trustworthiness, not just two isolated bugs.

**Fix:**
1. `check_rendered_clipping` now only treats `overflow:hidden`/`overflow:clip` as genuine
   clipping -- `auto`/`scroll` are excluded entirely, since content behind them stays fully
   reachable and is often a deliberate, working design choice.
2. `check_rendered_contrast`'s `bgOf()` now walks up collecting every semi-transparent
   background layer and alpha-composites them (outermost ancestor first) against a white
   page-default base, instead of stopping at the first non-transparent value and using it
   unmodified.
**Live-verified** against real Chromium with two new fixture scenes added to the existing
deliberately-broken fixture (a `diagram-pre`-style scrollable scene, and a
`callout-success`-style pale-wash scene) -- both now correctly stay unflagged, while the
three original genuine defects (real clipping, real invisible content, real low contrast)
still fire exactly as before.
**Tests:** `tests/verification/hard/test_render_rendered.py::test_overflow_x_auto_is_not_flagged_as_clipping`,
`::test_semi_transparent_background_is_alpha_composited_not_treated_as_opaque`.

---

## ERR-042 — The subscription lane (Claude CLI) had zero retry logic; the same class of gap as ERR-032, other side
**Date:** 2026-09-11 · **Severity:** major (crashed a full real pipeline run) · **Status:** fixed · **Component:** `llm/backends/claude_cli.py` · **Live cost:** subscription quota only, no billed cost

A second live full-pipeline run (validating ERR-041's fixes) crashed with `claude -p failed
(exit 1):` and empty stderr, inside the Haiku repair path (`llm/repair.py`) that itself was
trying to fix a malformed Gemini JSON response during CM's claim-mapping pass. Manually
re-running the EXACT same `ClaudeCliBackend.call()` invocation immediately afterward
succeeded, confirming the failure was transient (a one-off CLI hiccup), not a real bug —
but `ClaudeCliBackend.call()` had no retry logic at all, so a single transient failure
crashed the entire run. This is the same shape of gap ERR-032 already fixed for the paid
API lane (`litellm`'s `num_retries`); the subscription lane was never given the equivalent.

**Fix:** wrapped `ClaudeCliBackend.call()` in a `tenacity.Retrying` loop (3 attempts,
exponential backoff, reusing the `tenacity` dependency already added for ERR-040) that
retries only `ClaudeCliInvocationError` (non-zero exit, non-JSON stdout — the transient-
shaped failures) and never `ModelMismatch` (a real, deterministic bug — the CLI resolved a
different model than requested — that retrying can never fix, so it must surface on the
first attempt, not be masked by identical failures first). `max_attempts`/
`retry_wait_min_s`/`retry_wait_max_s` are constructor params (not hardcoded) specifically
so tests can shrink the backoff instead of incurring real multi-second sleeps in the
default fast suite — the two existing always-fails fixtures were updated to
`max_attempts=1` for exactly this reason (their real slowdown, ~4s -> ~10s for the whole
suite, is what caught this before it became a habit).
**Tests:** `tests/llm/test_claude_cli_backend.py::test_a_transient_failure_is_retried_and_can_still_succeed`,
`::test_a_deterministic_model_mismatch_is_never_retried`.

---

## V1C full confirmation (2026-09-11, `runs/v16`, $0.7958) + ERR-043 (text3/bg3 design fix)

A full live e2e run with ERR-041/ERR-042's fixes in place completed cleanly, no crash: 2
repairs used, `degraded=[]` (Playwright ran fine), the ERR-041 false positives (clipping on
`diagram-pre`, the `.callout-success` contrast) are confirmed gone. The remaining 11
`render_issues` were all real: the reader-standalone word-band (a legitimate, already-known-
strict gate) and `rendered_low_contrast` on `text3`/`bg3` (`#6e6e73` on `#e8e8ed`, 4.15:1) --
correctly surviving both repair attempts, since a content regeneration can never fix a CSS
color choice (exactly the design tension flagged when the H-repair loop was built).

**ERR-043 (fixed):** `text3` was a real, systemic 4.15:1 contrast against `bg3` -- just under
WCAG AA's 4.5:1 for normal text, and would have fired on every real run forever, not a per-run
fluke. Darkened to `#64646a` (4.81:1 against `bg3`), a barely-perceptible change that can only
improve contrast against this system's other, lighter backgrounds too.
**Tests:** `tests/html_synth/test_component_library.py::test_text3_on_bg3_clears_wcag_aa_contrast`
locks in the corrected token against the same contrast math the rendered check itself uses.

V1C's Playwright/C3/H-repair-loop checklist item is now marked done in `BUILD_PLAN.md` --
code-complete AND live-verified end to end, not just code-complete.

---

## V1D voice-corpus refit (2026-09-11) -- real data-quality finding, corrupted transcripts excluded

User authorized fitting `voice/fingerprint.py`'s real bands against the 10 real YouTube
transcripts in `docs/corpus/transcripts/` ("You may use these 10 transcripts then."), a
higher-leverage item for actual script quality than the remaining infrastructure checklist
items, per the user's own explicit push-back on prioritization.

**Real finding (data quality, not a code bug):** 4 of the 10 transcripts (`video_2.txt`,
`video_6.txt`, `video_7.txt`, `video_10.txt`) are raw, unedited auto-caption dumps with
almost no real sentence-ending punctuation -- 1-2 periods across thousands of words each,
producing degenerate "one giant sentence" fingerprints (one file alone reports a "sentence"
5,249 words long) that would have badly skewed every fitted band had they been included in
`tools/voice_fit.py`'s prototype aggregate naively. Confirmed via direct inspection
(per-document period counts, words/sentence ratios: 899-5249 for the corrupted four vs
16-32 for the real six). **User confirmed the fix directly: "Use only valid transcripts."**

**Fix:** `voice/fingerprint.py::compute_metrics()` returns `None` (excluded and recorded in
`VoiceFingerprint.excluded_documents`, never silently zero-filled or included) for any
document where `words / len(sentences) > MAX_PLAUSIBLE_WORDS_PER_SENTENCE (100.0)` -- a
wide-margin threshold, not a close call. `fit_fingerprint_from_corpus_dir()` fitted the
remaining 6 valid transcripts into 5 metrics (`burstiness`, `contractions_per100w`,
`you_per100w`, `we_per100w`, `causal_per100w`), each individually inspected against the
per-document values to confirm the fitted bands reflect genuine document-to-document
variation, not an artifact.

**A separate real gap found proactively (before it could break anyone else's run):**
`docs/` is gitignored (`git check-ignore -v` confirms `.gitignore:5:docs/` matches
`docs/corpus/transcripts/video_1.txt`) -- so production code can never depend on
`docs/corpus/` existing at runtime. Fixed by fitting once locally and persisting the
**result** as a checked-in `config/voice_fingerprint.yaml` (matching the existing
`design_system.yaml` pattern, loaded via `config.loader.load_yaml`), read at runtime by the
new `voice/fingerprint.py::load_fitted_fingerprint()` -- never recomputed from the raw
corpus. `verification/diagnostics/voice.py`'s old provisional single-dimension placeholder
(`check_burstiness`, an unfitted stdev threshold) is replaced by `check_voice()`, wired into
`orchestration/pipeline.py` unchanged otherwise -- still gates C5 the same way, still
deliberately never returns RED (a 6-document corpus doesn't license an automatic hard
failure, matching the placeholder's own original design intent, just with real bands now).

**Tests:** `tests/voice/test_fingerprint.py` (corpus fitting, exclusion, scoring, config
loading), `tests/verification/diagnostics/test_voice.py` (rewritten against `check_voice`,
monkeypatched fingerprints for GREEN/AMBER/too-little-text, plus one test against the real
checked-in config with no monkeypatch).

**Live-verified:** ran `check_voice()` against real, saved production narration
(`project/attention_series/video-01-attention-coherent-story/runs/v09/final/narration.json`)
-- loads the real config correctly and reports a real, specific AMBER
(`burstiness=0.35 outside 0.44-0.66; contractions_per100w=2.94 outside 0.79-2.26;
causal_per100w=1.87 outside 0.44-1.61`), not a crash or a silent GREEN. Full suite: 701
passed (up from 689), 16 deselected.

---

## Run-directory structure: `final/` could hold shorts from a run that FAILed; three subfolders were always empty (2026-09-11, user-reported)

User inspected a real run dir (`runs/v16`) and asked why `extraction/`, `facts/`, and
`revisions/` were always empty, and why `final/` was inconsistent -- it held `shorts/1/`
(real short deliverables) but none of the long-form's own files (`script.md`,
`narration.json`, `quality_report.json`, etc.), because that run's `final_status` was FAIL.

**Two real gaps, both in `orchestration/run_pipeline.py` / `orchestration/paths.py`:**

1. `run_pipeline.py` wrote each short's deliverables directly into
   `run_dir/final/shorts/<i>/` as soon as `run_short()` returned -- before the overall
   `final_status` was even computed, and with no check on the *short's own* `final_status`
   either. So `runs/vNN/final/` could (and did, in `v16`) contain real-looking short output
   from a run that explicitly failed and was never promoted, and could equally contain a
   short that itself failed its own hard gate while the long-form passed. `final/` stopped
   meaning "the finished deliverable" and started meaning "whatever happened to get written."
2. `paths.py::RUN_SUBDIRS` scaffolds `extraction/`, `facts/`, and `revisions/` in every
   run (plan §16 names them for S0's parse output, the verified claim registry, and
   per-attempt revision diffs) but nothing has ever written into them -- `run_pipeline.py`
   threads all of that forward in memory only, never to disk. Three guaranteed-empty
   folders in every single run, forever.

**Fix:** shorts are now computed into an in-memory list (`short_artifacts`) and only
written under `run_dir/final/shorts/<i>/` inside the same `final_status in ("PASS",
"PASS_WARN")` branch that already gates the long-form's `emit_final_deliverables` --
and only for the shorts whose *own* `short_result.final_status` also passed (excluded ones
are logged, not silently dropped). Net effect: whenever a run's `final/` exists at all, it
holds the long-form deliverables and every short that passed together, consistently --
never a partial mix, never a failed run's output masquerading as final. `RUN_SUBDIRS`
drops the three dead entries; nothing currently persists that data, so nothing currently
needs the folders (see `paths.py`'s own updated docstring -- add them back if/when
something actually writes into them).

**Tests:** `tests/orchestration/test_run_pipeline.py` — `test_a_passing_short_is_written_into_final_when_the_run_passes`,
`test_a_failed_short_is_excluded_from_final_even_when_the_run_passes`,
`test_no_shorts_are_written_into_final_when_the_overall_run_fails`. Full suite: 704 passed
(up from 701), 16 deselected.

---

## V2 narrative-continuity fix -- Phases 1-3 live-verified (2026-09-11, `runs/v17`/`v18`)

Implemented `STORY_IMPROVEMENT_PLAN.md`'s Phases 1-3 against real feedback
(`multi_agent_script_and_model_feedback.md`): a Viewer Knowledge Ledger threaded
through A2b (Phase 1), a deterministic hook-tension pacing diagnostic (Phase 2), and
strengthened C1 repetition/pacing/overclaim checks + a narration hedge-language fix
(Phase 3). Full details and the file-by-file diff are in `STORY_IMPROVEMENT_PLAN.md`;
this entry records what two live runs actually confirmed.

**Phase 1 (`runs/v17`):** the ledger genuinely prevents cross-beat repetition. "queries"/
"keys"/"values" are each tagged as a `new_concept` exactly once (`beat_2_s03`) and every
later touch across beats 3/4/5/6/7/9/10 is correctly tagged into `must_not_repeat`, never
re-listed as new. The actual narration text for those `derivation`-tagged scenes
references the concept in one clause without re-deriving it (e.g. `beat_9_s02`: "each
with its own query, key, and value projections"). `running_example` was populated
correctly from the hook's own concrete illustration. The `runs/v13` hedge-language bug
("is then believed to pass through...") does not recur in either run.

**Phase 2 (`runs/v18`):** `pacing.hook_tension` appears in `review_bundle.json` and fired
a genuine RED -- "hook scenes take 172s of narration before the central tension is
established" (target ≤30s) -- independently reproducing almost the exact magnitude the
original feedback complained about (~180s observed there). Confirms the diagnostic is
wired correctly end to end and catches a real, present defect, not just a synthetic one.

**Phase 3 (`runs/v18`):** the new REPETITION check on C1 fired a real, correct catch:
"The narration explains the exact same softmax concept using nearly identical sentences
back-to-back: beat_4_s01 states 'Softmax turns that whole row into positive weights that
add up to exactly one' ... beat_4_s02 [restates the same]." Inspecting `plan.json`
explains why Phase 1's ledger didn't already prevent this: both scenes belong to the SAME
beat's own A2b expansion call, and the model tagged `beat_4_s01`'s `new_concepts` as
`["softmax for attention"]` but never carried that same-call concept into `beat_4_s02`'s
own `must_not_repeat` list (`beat_4_s02` is tagged `scene_function=derivation` but lists
unrelated concepts). This is a real, legitimate residual gap: the ledger reliably tracks
concepts ACROSS beats (proven in Phase 1's evidence above) but doesn't guarantee a beat's
own expansion call perfectly self-tracks new concepts introduced earlier in that SAME
call. Not treated as a bug to chase further right now -- this is exactly the two-layer
defense the phased design intended (Phase 1 prevents most repetition structurally, Phase
3's C1 check is the safety net for what slips through), and it worked as designed here.
The narration also visibly reflects the OVERCLAIM soft-language guidance unprompted:
`beat_4_s02` reads "a blend across all the values, weighted by relevance, not a single
pick."

**Full suite:** 731 passed, 16 deselected (up from 689 before this fix began).

---

## Real running-example drift confirmed via visual HTML audit (2026-09-11) -- STORY_IMPROVEMENT_PLAN.md Phase 6

Rendered `project/attention_series/video-01-attention-model-a-gpt4o/runs/v01/html/video_script.html`
with Playwright (the same approach `verification/hard/render_rendered.py` already uses for
C3), screenshotted individual scenes, and read them directly -- the first time this session
actually looked at rendered HTML rather than JSON/text output.

**Real finding:** `hook_s01`, `origin_s01`, `matrix_s01`, `heads_s01`, `recap_s01` all
correctly use the plan's locked running example ("the cat couldn't climb the stairs because
it was too tired"). `score_s02` and `score_s03` invent an entirely different one --
`q(it) . k(dog)`, `k(park)`, `k(bone)`, `yard` -- isolated to those two adjacent scenes;
`score_s04` onward drops named entities again. `render_report.json` for this run shows only
the known `reader_standalone_word_count_out_of_band` hard-check hit -- nothing caught the
example drift, because it's a semantic/entity-consistency defect, not a structural one.

**Root cause, traced in `html_synth/synthesizer.py`:** `synthesize_beat_visual()` (H --
generates the `diagram_card`/component content actually shown on screen) is a call completely
separate from `generate_narration()` (B1) and receives **none** of Phase 1's shared state --
no `running_example`, no `viewer_knows`, not even the scene's actual narration text, only the
pre-narration `visual_description` field and the beat's claims. Two independently-generated
artifacts (narration, on-screen diagram) can each be locally self-consistent while diverging
from each other and from the plan's own locked example -- exactly the class of gap
`STORY_IMPROVEMENT_PLAN.md`'s Phase 6 now targets (threading `running_example` + real
narration text into H's payload, plus a new entity-overlap diagnostic).

**Not yet fixed** -- this is Phase 6 planning, not a completed fix. Logged here because the
finding is real and reproducible, not because the defect is resolved yet.

---

## Phase 4 conclusion: gpt-5.6-sol config fixed, but NOT adopted (2026-09-11)

Three live runs total for this comparison, same real source
(`video-01-attention-coherent-story.html`), `story_lead` on each model:

1. `video-01-attention-model-b-gpt56sol` (unfixed config): catastrophic failure, `beats=0`,
   ~$0.28 wasted -- see the earlier Phase 4 entry above.
2. `video-01-attention-model-a-gpt4o` (baseline): worked properly -- 10 beats, 49 scenes,
   narrowed from 2 hard failures down to 1 (a source-coverage gap, not a coherence defect)
   across 2 revision rounds. Cost **$0.6645** for the full run.
3. `video-01-attention-model-c-gpt56sol-tuned` (`reasoning_effort="medium"`,
   `max_tokens=10000`): **the config fix worked** -- A2 produced a real 12-beat, 42-scene plan
   using only 820 of its 10000-token ceiling on reasoning (confirmed via the newly-persisted
   `reasoning_tokens` field: no truncation this time, on A2 or any of the 12 A2b calls).

**But the quality comparison came out against adopting it.** Run 3 ended FAIL with 3 hard
failures, two of them a genuine story-architecture coherence break `gpt-4o`'s run never had:

- `title_promise_unrelated_to_hook` -- the title and hook share almost no content
- `hook_promise_unpaid_by_ending` -- the hook's own promise is never resolved by the ending

Plus `cta.position` RED (CTA landed at 100% through the story, not 20-40%) and
`pacing.hook_tension` RED (143s vs. the 30s target -- worse than not measured at all, since
this is exactly the defect the whole V2 fix exists to catch). Across its 2 revision rounds,
hard failures went from 2 up to 3, not down -- `gpt-4o`'s run went from 2 down to 1 over the
same 2 rounds. Phase 3's C1 REPETITION check did fire correctly on this run too (the same
raw-score-to-weight arithmetic re-explained 3 times), confirming the V2 machinery works
identically regardless of which model sits under `story_lead` -- the difference is real
model-quality, not V2 wiring.

**Cost**: Run 3 cost **$1.0974** for the full run -- 65% more than `gpt-4o`'s $0.6645.

**Decision: `gpt-5.6-sol` is NOT promoted to the default `openai_story_strong`.** The exact
opposite of the external feedback's prediction happened on this real test: worse story
coherence, for significantly more money. The config fix (per-alias `max_tokens`,
`reasoning_effort="medium"` pinned explicitly, `reasoning_tokens` visibility) is kept because
it's independently correct and reusable, but the alias itself stays a documented, tested,
available option -- not the default -- per `STORY_IMPROVEMENT_PLAN.md` Phase 4's own
explicit "only if it demonstrably helps" criterion.

---

## Second visual HTML audit confirms two real accuracy bugs + a zero-coverage critique gap (2026-09-11)

Independently verified an external review's specific claims against
`video-01-attention-model-c-gpt56sol-tuned/runs/v01`'s real HTML/narration (same
render-with-Playwright-and-read-the-screenshots approach as the first audit) rather than
taking the review at its word. Both headline "accuracy" bugs are real:

- **Raw vs. scaled score confusion**: `B2_s02` narration states *"'Cat' scores 4.8, 'tired'
  scores 2.6, 'stairs' only 1.2"* as the initial match score. `B7_s01` narration: *"Take the
  **scaled** scores for 'it' — cat 4.8, stairs 1.2, tired 2.6"* -- the identical three numbers,
  now called "scaled." Scaling divides by `√d_k`, so scaled values should differ from raw.
- **Missing scaling term regresses a later equation**: `B7_s03` narration correctly states the
  full equation verbally ("softmax of QK-transpose over square root of d_k, times V"). `B8`'s
  own rendered `math-block-equation` is `softmax(QK^T)_row` -- no `/√d_k` -- one beat later,
  reusing the same 4.8/1.2/2.6 numbers and calling them "raw scores against every key" in its
  diagram caption.

**Bigger structural finding**: two of the review's other flagged sentences (an
architecture-universality overclaim in the position section: *"a position signal gets fused
into every token's representation before attention runs"*; an unnecessary empirical claim in
the multi-head section: *"Heads start out with unremarkable, largely uncommitted attention
patterns"*) are **not in the spoken narration at all** -- confirmed via direct text search of
`narration_final.json` (absent) vs. the rendered HTML (present, in `subsection-body` /
`screen_prose`, `html_synth/synthesizer.py`'s own separately-generated on-screen article
text). `review/story_critic.py` (C1) only ever receives spoken narration -- **the on-screen
text a viewer actually reads has zero critique coverage today**, including Phase 3's own
OVERCLAIM check. Not "the checker used a weak model and missed it" -- there is no checker for
this artifact at all. See `STORY_IMPROVEMENT_PLAN.md` Phase 6 for the fix (extend C1's payload
to include H's screen prose) and the explicit recommendation against reaching for "more
passes" or "a stronger model" as the first response to this class of miss.

Also verified the review's own timing table is precise, not estimated: computed real
word-count-based durations from `narration_final.json` per beat and got 12:39 total vs. the
review's stated ~12:40, with individual beats matching almost exactly (B1 1:04, B11 1:20).

**A real bug found in this project's own code while doing this verification**: cross-checking
the review's correct "hook = 64s" against this run's own `pacing.hook_tension` diagnostic
(which reported 143s) surfaced a genuine bug in `verification/diagnostics/pacing.py`'s
`check_hook_tension_pacing()` -- it sums every scene tagged `narrative_beat="hook"` **anywhere
in the plan**, but A2b tags "hook" onto the first scene of many different beats
(`B1_s01, B2_s01, B3_s01, B4_s01, B9_s01, B10_s01, B11_s01` in this real plan) as a
per-section rhetorical device, not exclusively the video's true opening -- so the diagnostic
accidentally summed hook-tagged scenes scattered near the end of the video too. Fix tracked in
`STORY_IMPROVEMENT_PLAN.md` Phase 2: restrict the scan to the plan's first beat only.

Not yet fixed -- all of the above are now tracked as concrete `STORY_IMPROVEMENT_PLAN.md`
Phase 2/6/7 items, logged here because the findings are real and reproducible.

---

## Code audit: B2 discards the Viewer Knowledge Ledger + four structural quality gaps (2026-09-11)

User report: *"the pipeline is ready but the script is not coming out to be good -- narration
has mistakes, viewer retention and interest aren't taken into account, story building, causal
link, viewer should learn something new."* Audited the code against `IMPLEMENTATION_PLAN.md`'s
own design rather than against the external feedback docs. Five confirmed findings, all now
tracked as `STORY_IMPROVEMENT_PLAN.md` Phase 8:

**1. Real bug -- every revision cycle silently discards Phase 1's ledger.**
`editing/targeted_rewrite.py` (B2) regenerates a flagged scene's narration from scratch using
B1's own schema, but its payload contains NONE of `scene_function`, `new_concepts`,
`must_not_repeat`, `running_example` (grep returns empty). The anti-repetition and
example-lock machinery is live in A2b and B1, then thrown away by the exact pass most likely
to reintroduce those defects -- and every real run hits B2 (both comparison runs ran it
twice). Most likely mechanism behind repetition issues that never clear across revision
rounds, and a plausible one for the confirmed `dog/park/bone` drift.

**2. No cold-viewer critique exists for long-form.** `review/cold_hook_critic.py` (C4s) is
built, tested and wired -- but ONLY into `orchestration/shorts_pipeline.py`.
`orchestration/pipeline.py::_run_review_block` never calls it, so a 60-second short's hook is
judged by a cold viewer and a 12-minute video's hook is not. `IMPLEMENTATION_PLAN.md` §8/§10.2
also specifies C4c (mid-video cold viewer, *"do you know why this is being discussed?"*) --
unbuilt entirely.

**3. The §9 Learning hard gate is entirely unbuilt.** `IMPLEMENTATION_PLAN.md:669` specifies
it (no `central_insight`; a major beat with no `learning_objective`; `viewer_can_now` not
reachable from the beats' objectives). `verification/hard/structure.py` has no such check.
`SourceBrief.novelty_statement` is collected by A1, explicitly requested in its prompt, and
then never read by anything downstream -- it exists only as a field. Shorts have
`check_central_insight_present`; long-form has no equivalent.

**4. Retention diagnostics grade the planner's own self-report.**
`verification/diagnostics/retention.py::_is_state_change()` reads
`beat.new_information or beat.payoff or beat.visual_mode_change or beat.question_progress`
-- all booleans A2 sets about its own plan; `check_driver_coverage` only checks
`forward_driver` is a non-empty string. A model that fills in its fields passes by
construction. Confirmed live: run C returned GREEN on all three retention diagnostics while
the human review scored retention/pacing as that run's weakest dimension.

**5. The revision loop does not converge and can regress.** Across both comparison runs,
critique issues went 4→3→3 and 5→3→3 (plateau, never clear); hard failures went 2→2→1 and
2→2→**3**. Run C rewrote 6 beats to apply 1 fix and finished worse than it started.
`orchestration/routing.py` has only `REPLAN`/`TARGETED_REWRITE`/`NONE` -- the design's
dedicated B3 (precision edit), B4 (humanize) and C6 (entailment) paths have no modules, so
voice, verbosity and factual findings all funnel into one generic narration rewrite.

**Also noted**: `beat_word_budget.py` allocates airtime proportionally to
`len(beat.source_unit_ids)` -- airtime tracks how much source material a beat cites, not its
narrative importance. Run C's allocation: B1-B9 each exactly 193 words, B10/B11 ~290. The
hook got the same budget as the multi-head section. Every review's "hook too long / masking
too long" complaint is therefore decided at allocation time, not in narration. Tracked in
Phase 7.

**Pattern underneath all five**: the pipeline is strong at verifying FACTS (claims, grounding,
numeric fidelity, render integrity -- all real and working) and has almost no independent
measurement of whether the result is a good WATCH. Every retention/learning signal is either
self-reported by the planner or absent. Phase 4 already demonstrated that a stronger model
does not move this ceiling.

Not yet fixed -- logged here because the findings are real and code-confirmed.

---

## BUG-1 fixed and live-verified; cold-hook critic wired into long-form (Phase 8.1/8.2, 2026-09-11)

**BUG-1 fix**: `editing/targeted_rewrite.py` (B2) now carries `scene_function`, `new_concepts`,
`must_not_repeat`, and `running_example` into every targeted rewrite -- payload- and
prompt-only, no signature change (`scene` and `plan` were both already in scope). 4 new
tests, full suite green.

**Live-verified**, not just mocked: ran `video-01-attention-bug1-verify/runs/v01` against the
real source. This run hit `TARGETED_REWRITE` twice; its final cycle rewrote all 7 of the
plan's beats (36 scenes), so every scene in the accepted narration passed through the fixed
B2. Checked 15 `scene_function=derivation` scenes carrying a real `must_not_repeat` list --
every one correctly compresses the reference into a bridging clause instead of re-deriving
it:

- `build_step_1_s02` (mnr=`pronoun_resolution_example`): *"Since we already know 'it' could
  mean either word, the model needs a way to check every candidate."*
- `build_step_1_s05` (mnr=`pronoun_resolution_example, unrestricted_attention, query_key_value`):
  *"Since queries and keys are already doing the matching, the connection between 'it' and
  'cat' strengthens..."*
- `build_step_2_s03` (mnr=`pronoun_resolution_example, query_key_value`): *"Transformers kept
  that retrieval idea but rewired it... the same retrieve-what-you-need logic we just saw."*

This is direct confirmation the fix works outside mocked tests -- the ledger survives a real
B2 rewrite cycle, not just a FakeAgent-based one.

**Also noted from this same run** (not yet acted on): critique issue count stayed flat at 3
across all three review cycles (3 -> 3 -> 3) despite a full replan and two targeted rewrites --
the exact non-convergence pattern already tracked as Phase 8.5.

**Cold-hook critic wired into long-form (Phase 8.2)**: `PipelineAgents` gained a `worker`
field; `_hook_context()` extracts the first beat's narration/visual for the critique;
`critique_cold_hook()` gained optional `haiku_pass_id`/`gemini_pass_id` params so long-form
logs as `C4a`/`C4b` (cost-report label only). 3 new pipeline-level tests plus 1 in
`test_cold_hook_critic.py`. Not yet live-verified -- the run above predates this commit;
needs its own live run to confirm a real `C4a`/`C4b` entry appears in `usage.jsonl`.

Full suite: 752 passed, 16 deselected.

---

## Cold-hook critic live-verified in long-form (2026-09-11)

Ran `video-01-attention-coldhook-verify/runs/v01` against the real source (the same
attention-series pronoun-resolution source used throughout this fix). `C4a` fires exactly
once per review cycle -- confirmed 4/4 across a run that included a full replan (A2 →
targeted_rewrite → replan → targeted_rewrite), each on `lane=subscription`,
`model=claude-haiku-4-5-20251001`, `billed_microusd=0`, matching the cascade's design (a
clean, confident Haiku pass costs nothing). No `C4b` escalation fired in any of the 4 cycles,
and `review_bundle.json` carries zero `category="hook"` issues -- consistent with this
source's real hook being genuinely strong (a concrete "the cat couldn't climb the stairs..."
pronoun example), not evidence the wiring is inert; the short-circuit-on-clean-verdict
behavior the unit tests assert is exactly what a real, good hook should produce.

**Not yet observed live**: the `C4b` escalation path itself, since no run so far has had a
genuinely weak hook to trigger it. Would need a deliberately weak source (or a mutated
title/hook) to confirm live, tracked as a residual gap in Phase 8.2, not blocking.

---

## ERR-044 — H's screen prose had zero critique coverage; C3's non-structural findings were silently dropped

**Date:** 2026-09-11 · **Severity:** major (a whole artifact the viewer reads was never reviewed at all; a second, independent bug then discarded the fix's own output) · **Status:** fixed, live-verify pending · **Component:** `review/visual_critic.py`, `orchestration/html_pipeline.py`, `reporting/emit_html.py`

**Where:** BUG-4 (STORY_IMPROVEMENT_PLAN.md Phase 6) established that C1
(`review/story_critic.py`) cannot review H's `screen_prose` -- C1 runs inside the story/
narration loop, which completes *before* `synthesize_and_repair_video_html()` (H) is ever
called, so extending C1's payload is not implementable as written. Confirmed by a second
independent visual audit (`video-01-attention-model-c-gpt56sol-tuned/runs/v01`): two real
overclaim sentences existed only in H's on-screen article prose, invisible to every existing
critic.

**Fix:** folded a repetition/overclaim check into C3 (`review/visual_critic.py`), which
already runs post-H with an existing H-repair route -- cheaper than a new pass, per BUG-4's
own analysis. `TASK_PROMPT` gained REPETITION (checked against `must_not_repeat`/
`running_example`) and OVERCLAIM sections, both capped at major/minor severity
(`repair_owner="html_author"`, `layer="NARRATION"`) so they never trigger H's structural
repair loop on their own, only get surfaced. `scene_payload()` gained optional
`scene_function`/`must_not_repeat`/`running_example` params; `html_pipeline.py` threads
`plan.scene_plan[i]`'s metadata and `plan.running_example` into each call.

**A second, separate real bug found while wiring this in:** `html_pipeline.py`'s C3-invocation
block computed the full `visual_issues` list but only ever extracted the `structural`
(critical-severity, RENDERER-layer) subset into `render_issues` via
`_visual_critique_to_render_issues()` -- every ordinary `visual_mismatch` and every major/minor
finding, including the new repetition/overclaim findings this same fix adds, was silently
discarded: never returned in `HtmlSynthesisResult`, never written to `render_report.json`,
never visible anywhere. Fixed by adding `HtmlSynthesisResult.visual_critique_issues:
list[CritiqueIssue]`, capturing C3's full output, now written to `render_report.json` by
`reporting/emit_html.py`.

**Tests:** `tests/review/test_visual_critic.py` -- payload/prompt coverage plus the usual
no-hardcoded-topic-vocabulary guard. `tests/orchestration/test_html_repair_loop.py` -- two new
tests that force the real C3 code path via direct `monkeypatch.setattr` on
`verification.hard.render_rendered.run_rendered_checks`/`capture_scene_screenshots` (both are
function-local imports, so the usual module-attribute patch used elsewhere in this file
doesn't reach them); confirmed necessary because every pre-existing test in this file either
blocks Playwright or opts out of rendered checks, so none of them exercised this code path at
all before. `tests/reporting/test_emit_html.py` -- one new test for the report field. Full
suite: 786 passed, 16 deselected.

**Coverage caveat, not a bug:** C3 only reviews its own *sampled* scenes
(`review/visual_sample.py::select_scenes_for_visual_audit`), not every scene H generates --
an accepted, deliberate limitation of reusing C3 rather than building a dedicated
full-coverage pass.

**Not yet live-verified**: no real pipeline run has exercised this change yet. Needs a run
with `enable_rendered_checks=True` reaching a clean rendered state (so C3 actually executes)
to confirm a real `category="repetition"`/`"clarity"` finding appears in a real
`render_report.json`'s `visual_critique_issues`.

---

## Phases 8.3/8.4/8.5 live-verified together (2026-09-11, `video-01-attention-batch2-verify/runs/v01`)

A long-running background pipeline invocation against the real attention-series source (13
source units, 69 claims, archetype=build, 9 beats, 43 scenes) completed with real evidence for
three checklist items at once. **Process note**: this run was launched BEFORE this session's
Phase 6 (C3 screen-prose / formula-consistency) commits, so its code predates both of those --
it is valid evidence for 8.3/8.4/8.5 only, not for the later Phase 6 work (confirmed: its
`render_report.json` has no `visual_critique_issues` key at all, since that field didn't exist
yet when this Python process started). A duplicate re-launch of the same run was mistakenly
started mid-session after this run's `runs/v01` directory was checked too early (only 16
`usage.jsonl` lines, all folders empty) and wrongly read as "crashed" -- it had simply not
reached its next usage-logged call yet on a real, slow, multi-cycle run. The duplicate
(`runs/v02`) was stopped once the original's completion notification arrived; no results were
taken from it.

**8.3 (§9 Learning gate):** `reviews/review_bundle.json` shows zero
`no_central_insight`/`beat_missing_learning_objective`/`viewer_can_now_unreachable` hard
failures against a real plan where every beat had a genuine `learning_objective` -- confirms
the gate isn't over-strict on well-formed input. The soft half,
`retention.novelty_coverage`, fired **GREEN** with real matched content: A1's
`novelty_statement` ("...how the attention mechanism avoids saturation issues in softmax by
scaling dot product scores...") against B4's `learning_objective` ("Understand the necessity
of scaling in scoring.") -- a genuine, non-trivial overlap, not a stub always passing.

**8.4 (retention self-report disagreement):** `retention.new_information_disagreement` fired
**AMBER**: `"beat(s) claim new_information=True but no scene lists a new_concepts entry:
['B9']"` -- a real, previously-invisible planner/narration disagreement surfaced on a genuine
run, confirming the diagnostic is live signal, not dead code.

**8.5 (revision-loop convergence + narrower blast radius):** `final/status.json`'s own log is
direct proof of both fixes on the SAME source that originally showed the "6 beats rewritten
for 1 fix" pattern:
```
"targeted rewrite #1: 0 beat(s), 8 scene(s), 1 fix(es), 0 delete/compress"
"targeted rewrite #2: 0 beat(s), 6 scene(s), 0 fix(es), 0 delete/compress"
"targeted rewrite #2 made things worse (6 hard failures, 4 issues vs 4/3 before) -- reverting"
"revision budget exhausted -> emit best candidate"
```
Zero whole-beat rewrites across both cycles (narrower blast radius confirmed); a real
regression was caught mid-run and reverted rather than accepted, and the run correctly shipped
its best-seen candidate (still `FAIL` overall, on pre-existing, unrelated hard failures --
`source_units_uncovered`, `core_role_missing`, `title_promise_unrelated_to_hook`, a
`masking_logical_paradox` clarity issue -- none of which this session's fixes targeted).

---

## ERR-045 — B1 never received claim `importance`, and the prompt never said what to do with an UNVERIFIED/REJECTED claim

**Date:** 2026-09-11 · **Severity:** critical (61 hard failures on one real run -- the dominant cause of that run's FAIL) · **Status:** fixed · **Component:** `narration/generator.py` · **Live cost:** yes (found via `video-01-attention-phase-e2e-verify/runs/v01`, part of that run's $0.7596)

**Where:** live e2e verification of this session's Phase 5/6/7/8.2 work (user-requested) surfaced
61 `grounding_policy_violation` hard failures in one run's `review_bundle.json`, all from
`verification/hard/grounding.py`'s policy table: `UNVERIFIED` + importance `CORE`/`SUPPORTING`
must never be narrated (no hedge can save it); `UNVERIFIED` + `OPTIONAL` needs an explicit
hedge; `REJECTED` never narrated at all.

**Root cause, confirmed by reading the actual code, not assumed run-to-run variance:**
`narration/generator.py::_claim_payload()` sent the model `claim_id`/`claim`/
`verification_status` but **never `importance`** -- B1 could not have applied the
CORE/SUPPORTING/OPTIONAL distinction even if told to, the field never reached it. Separately,
`TASK_PROMPT` only ever instructed "state a VERIFIED claim as plain fact" -- nothing told the
model what to do for `UNVERIFIED`/`CONTEXT_DEPENDENT`/`REJECTED` claims, so it just narrated
all of them as if verified. This is a deterministic gap, not LLM randomness -- every run with
any UNVERIFIED claims would hit this the same way, and this source's real C2a verification
pass legitimately returned many UNVERIFIED claims.

**Fix:** `_claim_payload()` now includes `importance`; `TASK_PROMPT` gained an explicit policy
paragraph mirroring `grounding.py`'s own rule table verbatim (REJECTED never narrated;
UNVERIFIED+CORE/SUPPORTING never narrated regardless of hedging; UNVERIFIED+OPTIONAL only with
an explicit hedge; CONTEXT_DEPENDENT narrated as context-scoped, not universal).

**Also confirmed, not fixed (accepted as a known limitation):** the same run's one
`hook_promise_unpaid_by_ending` hard failure was a false positive from `check_promise_chain`'s
deliberately crude word-overlap proxy -- `hook.promise` and `ending.resolve_hook` were
semantically matched (both about pronoun resolution via learned context) but shared almost no
literal words. The check's own docstring already documents this as "not real semantic
judgement"; not worth a special case.

**Tests:** `tests/narration/test_generator.py` -- `importance` reaches the payload; prompt
mirrors the full policy table. Full suite: 837 passed, 16 deselected.

**Not yet live-verified**: this fix landed after the run that found it; needs a fresh run to
confirm the grounding-violation count actually drops.

---

## ERR-046 — The story+narration loop shared every other stage's $1.00 hard cap

**Date:** 2026-09-12 · **Severity:** major (blocked a user-requested model comparison from completing at all) · **Status:** fixed · **Component:** `orchestration/run_pipeline.py`

**Where:** a user-requested gpt-5.6-sol vs. gpt-4o `story_lead` comparison run hit
`BudgetExceeded` mid-loop at ~$1.09 spent (pre-flight estimate $1.0029, over the $1.00 hard
cap), never completing A3's second revision cycle.

**Root cause:** `run_full_pipeline()` gives `facts_budget`/`planning_budget`/`loop_budget`/
`html_budget` each their OWN independent `BudgetCounter(tier=DEFAULT_TIERS["longform"])` --
all four capped at $1.00 -- with no way to raise just one. A reasoning-capable `story_lead`
alias (`gpt-5.6-sol`) costs roughly 10-15x more per call than `gpt-4o` for the same A2/A2b/B2
calls (confirmed: A2 $0.22 vs. ~$0.02-0.03; A2b ~$0.03/call vs. ~$0.007-0.009/call; one B2
rewrite $0.39 vs. a few cents), so it cannot complete even one loop within the shared default.

**Fix:** new optional `loop_budget_usd` param on `run_full_pipeline()` (and a `--loop-budget-usd`
CLI flag) scales a custom `BudgetTier`'s target/warning proportionally against the longform
tier's own ratio, touching only `loop_budget` -- the other three stages keep their independent
$1.00 caps unchanged.

**Tests:** `tests/orchestration/test_run_pipeline.py` -- `loop_budget_usd` reaches
`run_story_and_narration_loop`'s own budget object with the right `hard_cap_usd` (and a still-
ordered tier); defaults to $1.00 when unset. Full suite: 839 passed, 16 deselected (at the time
of this fix).

---

## ERR-047 — The paid-API lane had no request timeout at all; a real run hung 6+ hours

**Date:** 2026-09-12 · **Severity:** critical (a real run silently hung indefinitely, discovered only because a human noticed) · **Status:** fixed · **Component:** `llm/backends/litellm_backend.py`, `llm/client.py`, `agents/base.py` · **Live cost:** the hung run itself burned no further API cost while stuck (it was blocked on one never-returning call), but wasted 6+ hours of wall time before being found and killed by hand

**Where:** a user-requested gpt-5.6-sol vs. gpt-4o model comparison run (`video-01-attention-
phase-e2e-verify-gpt56/runs/v02`) stalled after several successful A2b calls -- `usage.jsonl`'s
last write was at 23:01, still zero progress at 05:26 the next day. No error, no crash, no
retry logged -- the process was simply blocked forever on one call.

**Root cause, confirmed by reading the actual call path:** `agents/base.py::Agent.run()`'s
paid-lane branch never forwarded its own `timeout_s` argument to `call_structured_paid()`,
which didn't even accept the parameter; `llm/backends/litellm_backend.py::LiteLLMBackend.call()`
never passed a `timeout` to `litellm.completion()` at all. ERR-032's `num_retries=3` fix only
classifies and backs off an ALREADY-RAISED exception (`RateLimitError`/`Timeout`/
`ServiceUnavailableError`) -- a connection that simply never responds raises nothing, so
`num_retries` never even engages. This affects every paid_api call (GPT-4o, GPT-5.6-sol,
Gemini) equally; the reasoning-model comparison run just happened to be the one that hit it.

**Fix:** `LiteLLMBackend` gains a `timeout_s` constructor param (default 300s -- above the
longest real call observed, a 149s gpt-5.6-sol A2 call, but loud: a genuinely slower call now
raises `litellm.Timeout`, one of the classes `num_retries` already retries), forwarded to
`litellm.completion(timeout=...)` and overridable per call. Threaded end-to-end:
`LLMClient.call_structured_paid()` gained `timeout_s`; `Agent.run()`'s paid-lane branch now
actually forwards its own `timeout_s` instead of silently dropping it.

**Tests:** `tests/llm/test_litellm_backend.py` (default/override/per-call forwarding),
`tests/llm/test_client.py` (`call_structured_paid()` forwards `timeout_s`), `tests/agents/
test_base.py` (`Agent.run()` forwards it on the paid lane). Full suite: 844 passed, 16
deselected.

**Not yet live-verified**: needs a fresh run (ideally the same gpt-5.6-sol comparison, now with
`--loop-budget-usd` raised too, per ERR-046 above) to confirm no further indefinite hangs.

---

## ERR-048 — Raw LaTeX shown on screen; H silently echoed whatever notation A2b wrote

**Date:** 2026-09-12 · **Severity:** major (visibly broken text on every affected scene) · **Status:** fixed · **Component:** `planning/scene_expander.py`, `html_synth/synthesizer.py`

**Where:** user-reported, found on the gpt-5.6-sol comparison run's actual rendered `page.html`
-- literal `\operatorname{softmax}\left(\frac{QK^{\top}}{\sqrt{d_k}}\right)` style text visible
in both `.math-block-equation` blocks and ordinary prose.

**Root cause:** `planning/plan.json` confirmed A2/A2b (`gpt-5.6-sol` on this run) wrote
`visual_description` using real LaTeX escape syntax. `html_synth/synthesizer.py`'s H pass
(always Claude Sonnet, regardless of `story_lead` alias) then copied that notation straight
into `screen_prose`/`component_data` with no instruction to reformat it -- and the page loads
no MathJax/KaTeX renderer at all, so raw LaTeX source is exactly what a viewer sees.

**Fix:** both `planning/scene_expander.py` (A2b, the likely source) and
`html_synth/synthesizer.py` (H, the last line of defense) gained explicit prompt instructions
to use plain notation only ("a / sqrt(b)", never `\frac{}{}`/`\sqrt{}`/`\operatorname{}`/
`\left`/`\right`/`\cdot`/`\top`), including converting through any LaTeX already present in a
given field rather than copying it forward.

**A real bug in this session's OWN fix, caught before commit:** writing the LaTeX command
examples directly into a normal (non-raw) triple-quoted Python string silently turned
`\f`/`\r`/`\t` into an actual form-feed/carriage-return/tab character (Python's own valid
escape sequences) -- caught by a `SyntaxWarning` during the test run, fixed by doubling every
backslash, with a regression test guarding against the same mistake recurring.

**Tests:** prompt-content tests in both files; control-character regression guards in both.
Full suite: 860 passed, 16 deselected.

**Not yet live-verified**: needs a fresh gpt-5.6-sol run to confirm A2b actually stops
producing LaTeX (a prompt instruction, not a hard gate -- nothing currently blocks a plan with
LaTeX in it from proceeding if the model doesn't comply).

---

## ERR-049 — Component slots silently rendered blank; not model-specific

**Date:** 2026-09-12 · **Severity:** major (visibly broken empty boxes on every affected scene) · **Status:** fixed · **Component:** `verification/hard/render.py`, `html_synth/synthesizer.py`

**Where:** user-reported alongside ERR-048, same gpt-5.6-sol run's `page.html` -- several
visibly empty boxes (`step-desc`, `card-title`, `card-value`, `card-desc` divs with no
content). **Confirmed NOT specific to gpt-5.6-sol**: the earlier gpt-4o run's `page.html` has
the identical defect, 14 empty divs each -- H (which writes `component_data`) always runs on
`narration_lead` (Claude Sonnet), regardless of which model plans the story.

**Root cause:** `html_synth/component_library.py::render_component()`'s generic rendering
path does `data.get(slot, "")` for every component slot -- a slot the model's `component_data`
never filled in (or filled with an empty string) silently renders as nothing, rather than
failing loudly. Nothing checked for this: `check_every_scene_has_prose` only verifies a scene
has SOME screen prose, never that its chosen component is actually complete.

**Fix:** new `verification/hard/render.py::check_component_slots_filled(beat_visuals)` --
flags a scene whose `component_data` is missing (or has a present-but-blank) any of that
component's own `component_slots()`, including nested `{title, desc}` items inside
`step_list`/`grid_2`/`grid_3` (while correctly NOT flagging a plain-string grid item, a
legitimate shape `render_component()` already supports). Wired into `check_render_content()`,
so it drives the same H-repair route as every other content-level check -- a run with this
defect now gets it fixed automatically within the existing repair budget, not shipped silently.
Also reinforced in `synthesizer.py`'s own prompt ("a component with even one slot left blank
renders as a visibly broken empty box").

**Tests:** `tests/verification/hard/test_render_content.py` -- clean fully-filled card, slot
missing entirely, slot present-but-blank, `diagram_card` missing `content`, a `step_list`
item's own blank `desc`, plain-string grid items correctly NOT flagged, scene-scoped for the
repair loop. Full suite: 860 passed, 16 deselected.

**Not yet live-verified**: needs a fresh run reaching the C3/repair stage to confirm the new
check actually fires on a real incomplete component and drives a real repair.

---

## ERR-050 — Subscription-lane timeout crashed the whole run instead of being retried

**Date:** 2026-09-12 · **Severity:** critical (killed a full live run outright, no partial output saved) · **Status:** fixed · **Component:** `llm/backends/claude_cli.py`

**Where:** the "fair" gpt-4o re-run (relaunched to compare against gpt-5.6-sol using the same
grounding-policy fix) crashed with an unhandled `subprocess.TimeoutExpired` during a B2
targeted rewrite -- a legitimately large payload (a full beat's scenes/claims serialized to
JSON, visible in the traceback) took longer than the subscription lane's default 300s timeout.

**Root cause:** `ClaudeCliBackend.call()`'s tenacity retry wrapper only classifies
`ClaudeCliInvocationError` as retryable (by design -- `ModelMismatch` must never be retried,
it's a real deterministic bug). `_call_once()`'s `subprocess.run(..., timeout=effective_timeout)`
raises `subprocess.TimeoutExpired` on a timeout -- a completely different, never-caught
exception class -- so it propagated straight past the retry classification and killed the
entire run on one slow-but-transient call. This is the same bug FAMILY as ERR-047 (the paid
lane had no timeout at all) but the inverse case: here a timeout exists, it just isn't
retried -- exactly the class of failure this backend's own docstring says its retry logic
exists to handle.

**Fix:** `_call_once()` now catches `subprocess.TimeoutExpired` and re-raises it as
`ClaudeCliInvocationError`, routing it through the existing retry classification like any
other transient failure.

**Tests:** `tests/llm/test_claude_cli_backend.py` -- a timeout that recovers on retry succeeds
(mirrors the existing transient-exit-1 retry test); a timeout that never recovers still raises
a clear `ClaudeCliInvocationError`. Full suite: 862 passed, 16 deselected.

**Not yet live-verified**: needs a fresh run that actually hits a slow subscription-lane call
to confirm the retry now succeeds instead of crashing.

---

## ERR-051 — B2's own 180s timeout was too short for a real rewrite payload

**Date:** 2026-09-14 · **Severity:** critical (crashed two separate live-verify runs outright) · **Status:** fixed · **Component:** `editing/targeted_rewrite.py`

**Where:** confirmed live TWICE, on two separate runs launched to verify other fixes (the fair
gpt-4o comparison, then the gpt-5.6-sol LaTeX/blank-box verify) -- both crashed inside B2's
targeted-rewrite call. The first crash predated ERR-050's fix (a raw, unretried
`subprocess.TimeoutExpired`). The second happened AFTER ERR-050 landed -- the timeout was
correctly converted to a retryable `ClaudeCliInvocationError` and retried up to 3 times, but
every attempt hit the identical 180s ceiling and failed the same way, so the run still crashed
once retries were exhausted.

**Root cause:** `editing/targeted_rewrite.py`'s B2 call used `timeout_s=180`, chosen (no
comment explaining why) presumably assuming a "targeted" rewrite's smaller scope would always
finish faster than B1's full-narration call. Not true in practice -- a `rewrite_beats` payload
still carries a whole beat's scenes and claims, and `narration/generator.py`'s own B1 call
already uses `timeout_s=300` for the same class of Sonnet call.

**Fix:** raised B2's timeout to `300` to match B1.

**Tests:** confirms the call uses `timeout_s=300`. Full suite: 863 passed, 16 deselected.

**Also observed, not a code bug:** the same gpt-4o run session separately hit
`litellm.APIConnectionError: ... [Errno 8] nodename nor servname provided` (a DNS resolution
failure) on a Gemini call -- a transient local network issue, not a pipeline defect. No fix
applied; simply re-running is the correct response to this class of failure.

**Not yet live-verified**: needs a fresh run that actually exercises a `rewrite_beats` cycle to
confirm 300s is sufficient in practice.

---

## ERR-052 — ERR-049's fix didn't actually resolve the blank-box bug; the real defect was one level deeper

**Date:** 2026-09-14 · **Severity:** major (live-verify of a claimed fix found the count got WORSE, not better) · **Status:** fixed · **Component:** `src/config/design_system.yaml`, `html_synth/component_library.py`

**Where:** live-verifying ERR-048/049's fixes on a real gpt-5.6-sol run
(`video-01-attention-latex-blankbox-verify/runs/v02`) confirmed ERR-048 (LaTeX) worked -- zero
LaTeX in the output. ERR-049 (blank component boxes) did NOT: the same run had **36** empty
`step-desc`/`card-title`/`card-value`/`card-desc` boxes, MORE than the 14 seen before that fix.

**Root cause, confirmed by reading the actual template:** `card` and `step_list`'s own
skeletons in `design_system.yaml` unconditionally emit every slot's wrapper div (`<div
class="card-value">`, `<div class="step-desc">`) regardless of whether that slot has real
content. A partial shape -- a `grid_2`/`grid_3` item with only `title`+`desc`, no `value`; a
`step_list` item with only a `title`, or a plain string -- is a LEGITIMATE, already-supported
shape (`render_component()`'s own docstring: "the exact SHAPE of that data varies... handled
for both rather than assuming one"), but the skeleton still rendered a visibly empty box for
the missing piece every time.
`verification/hard/render.py::check_component_slots_filled` (ERR-049's fix) only scans
present-but-BLANK keys on nested dict items, never keys missing entirely -- so it never had a
chance to catch this. Tightening the check would only have forced the model to always supply
every field, fighting the renderer's own accepted flexibility instead of fixing the renderer's
actual bug.

**Fix:** fixed at the source. `card`'s skeleton and `component_library.py`'s `card`/`step_list`
rendering branches now build each slot's div conditionally, omitting it entirely when there's
no real content, instead of rendering it empty. `check_component_slots_filled` is unchanged
and still independently catches a genuinely incomplete STANDALONE `card` (where all three
slots are meant to be meaningful) -- a second, defense-in-depth layer, not replaced.

**Lesson**: a hard check that returns clean on a real run is not proof the underlying bug is
fixed -- it can mean the check itself is looking in the wrong place. Always inspect the actual
rendered output, not just whether the new check fires.

**Tests:** `tests/html_synth/test_component_library.py` -- card/step_list render all slots when
present; omit a blank value/desc individually and together; a step_list item with no desc at
all (or a plain-string item) never emits an empty `step-desc` div; a real desc still renders.
Full suite: 899 passed, 16 deselected.

**Not yet live-verified**: needs a fresh run to confirm zero empty boxes in real output.

---

## ERR-053 — A Gemini/Vertex call raised "Timeout: ... None seconds" (likely transient, not confirmed as a code bug)

**Date:** 2026-09-14 · **Severity:** major (crashed a real run) but **unconfirmed root cause** · **Status:** defensive mitigation applied, not a confirmed fix · **Component:** `llm/backends/litellm_backend.py`

**Where:** during the same end-to-end verification session, a separate gpt-4o comparison run
(`video-01-attention-phase-e2e-verify-fair/runs/v04`) crashed with `litellm.Timeout: Connection
timed out after None seconds` on a Gemini/Vertex call -- despite ERR-047's `timeout_s=300`
per-call kwarg being in place and confirmed (by reading litellm's own source) to be a real,
respected parameter for `litellm.completion()`.

**Investigation:** traced the exception through litellm's own Vertex AI Gemini code path
(`_complete_vertex_ai_beta` -> `vertex_and_google_ai_studio_gemini.py`) -- the local `timeout`
variable IS threaded through multiple call sites in that file, so there is no obvious, confirmed
bug in litellm's own handling for this provider. The "None seconds" in the exception message may
just be a cosmetic formatting gap in litellm's own error path, not proof no timeout was applied.
**Notably**: a CONCURRENT run against the same source, same models, same time window
(`video-01-attention-latex-blankbox-verify/runs/v02`) completed cleanly with no timeout issue at
all -- this points toward transient network/API flakiness at that moment rather than a
systemic, reproducible defect in our request.

**Mitigation applied (defensive, not a confirmed fix):** `LiteLLMBackend.__init__` now also sets
`litellm.request_timeout` (litellm's own global default, otherwise 6000s) to the same
`timeout_s` value, closing any gap in a code path that might not reflect the per-call value.
Harmless either way.

**Tests:** confirms the global is set to the configured value. Full suite: 900 passed, 16
deselected.

**Not yet resolved**: if this recurs on a future run with the defensive fix in place, the root
cause is NOT what was guessed here and needs further investigation (possibly a genuine litellm/
Vertex integration gap, or real API-side rate limiting/instability).

---

## ERR-054/055/056 — Three real bugs found live-verifying today's Phase 6/7 work on a fresh run

**Date:** 2026-09-14 · **Status:** all fixed · **Component:** `verification/diagnostics/entity_consistency.py`, `verification/hard/render.py`, `html_synth/synthesizer.py`

A freshly-launched gpt-4o run (`video-01-attention-phase6-7-verify/runs/v02`, launched only
after all Phase 6/7 commits landed, to avoid the stale-process artifact noted separately)
surfaced three real, distinct issues in the SAME diagnostic/repair machinery this session had
just built or fixed.

**ERR-054 -- entity_consistency false-positive flood.** The real plan's `running_example.values`
used abstract slot labels as dict keys (`"pronoun"`, `"noun_1"`, `"noun_2"`) whose VALUES were
the actual concrete quoted words every scene correctly reused (`"'it'"`, `"'cat'"`,
`"'stairs'"`). `check_running_example_entity_consistency` only ever locked the dict KEYS as
allowed entities, so it flagged 17 of the video's scenes as inventing content -- when they were
all correctly reusing the locked example, just via its values rather than its keys. Fixed: both
the keys and the (quote-stripped) values now count as locked entities.

**ERR-055 -- `check_component_slots_filled` missed entirely-empty nested items.** ERR-052's
template-level fix (blank slots render nothing instead of an empty div) exposed a different
shape of the same underlying problem: a `grid_2`/`grid_3` item that is a completely empty dict
(or has every key blank) now renders as a totally empty `<div class="card"></div>` wrapper with
nothing inside at all. The hard check's field-by-field scan only ever flagged a key that was
actually PRESENT in the item, so a fully empty `{}` slipped through untouched -- confirmed on
the same real run: 6 empty card wrappers. Fixed: flags an item with zero non-blank `card` slots
as `item_entirely_empty`.

**ERR-056 -- H's own prompt wording discouraged using components at all.** User-reported after
comparing runs: the new run had noticeably fewer computation/diagram blocks than an earlier
one. Confirmed by direct component-count comparison on the same real source: **6 diagram-card +
3 math-block -> 0 of either**, while simpler components (`card`, `step_list`) were unaffected.
Root cause: ERR-049's own fix phrased the completeness requirement as *"a component with even
one slot left blank... is worse than not choosing a component at all"* -- language that reads
as "the safe default is skip it," and Sonnet (H) responded exactly as instructed, avoiding the
more effortful multi-slot components (`diagram_card`, `math_block`) it would otherwise have
used for this source's obviously diagrammatic/mathematical content. Fixed: reworded to require
completeness ("fill in EVERY slot... this means filling every slot in completely, not avoiding
components") without implying components themselves are risky.

**Lesson (adds to ERR-052's own):** a prompt instruction's SIDE EFFECTS on unrelated behavior
(here: overall component richness, not just slot completeness) need the same live-verify
scrutiny as the defect it was meant to fix -- comparing before/after content on the same real
source caught this in a way no unit test could have.

**Tests:** locked entities include `running_example` VALUES not just keys; a completely-empty
grid item is flagged, a partial-but-non-empty one isn't; a regression guard asserting the
discouraging phrase is gone and `math_block`/`diagram_card` are still named as valid choices.
Full suite: 904 passed, 16 deselected.

**Not yet live-verified**: needs a fresh run to confirm diagram/math component usage returns to
a level comparable with pre-regression runs, and that entity_consistency no longer over-fires.

---

## Open items (not yet bugs, flagged for future attention)

- **A2b's per-beat expansion doesn't always self-track its own new concepts within one
  call** (see the V2 Phase 3 entry above) -- a beat's own multiple scenes can still repeat
  a concept introduced earlier in the SAME beat's expansion, even though the ledger
  correctly prevents repetition ACROSS beats. Currently relied on C1's new REPETITION
  check as a safety net (confirmed working live) rather than a structural fix; a future
  pass could have `expand_beat_scenes()` feed each scene's own prior sibling scenes'
  `new_concepts` back into the same call's later scenes if this recurs often enough to
  matter after more real runs.

- **V1B's HV static checks are now the full plan §13 list** (updated 2026-09-11; the note
  below is superseded). `verification/hard/render.py` covers parsing, unique ids, scene
  presence/order, narration-hash match, numeric-claim-id traceability, text-level page
  parity, `renderer_compat` (Gate 1: >=3 sections, >=1,500 words), the reader-standalone
  word-count band (2,000-3,200, the plan's own stated figure, used as written), every scene
  carrying real prose, hero-states-the-problem, and a narrow deictic-reference check. All
  rendered checks (Playwright, clipping, contrast, C3) remain V1C by design, not a V1B gap.
  One check (`check_payoff_closes`) was built, live-tested, and then deliberately excluded
  from the hard gate -- see ERROR_LOG ERR-031. The reader-standalone band is a real,
  legitimately strict gate in practice: two live runs on the same source landed at 3,212 and
  3,240 words, both right at or just over the 3,200 cap -- correctly flagged both times, not
  a check bug; V1D may still recalibrate the band once more channels' real output exists.
- **`review_lead` and `cm_agent` share one `agent` name in cost reporting.**
  `make_review_lead()` always sets `Agent.name="review_lead"` regardless of tier, so
  `cost_report.json`'s `by_agent` breakdown blends strong-tier C1/C2b spend together
  with flash-tier CM/C5 spend under one bucket (noticed in ERR-022's real
  `cost_report.json`: one `"review_lead"` row covering 6 calls across both tiers). Each
  `UsageRecord` still carries the exact `pass_id` (so nothing is actually lost), but
  `CostReport` has no `by_pass_id` breakdown yet to surface it — `by_stage` exists in
  the model but is never populated either.
- **Production notes (ERR-013) is markup-specific.** The fix looks for
  `.page-footer .pipeline-step` — the exact shape found on one real source. A
  differently-marked-up "author's own plan" section on a future source would need its
  own extraction rule; nothing generalizes this automatically yet.
- **Voice bands are fitted against only 6 documents** (see the V1D voice-corpus refit entry
  above) — real, but a small sample. `check_voice` is deliberately capped at AMBER (never
  RED) for exactly this reason, so it can nudge C5 on but never force a real revision cycle
  on its own. More channel-specific transcripts (once the channel has published real videos)
  would let the bands tighten and eventually license a real RED, per V1D's own "bands
  tighten against the channel's own data" done-when criterion.
- **`delete_or_compress` has no delete semantics in V1A** (see `editing/targeted_rewrite.py`'s
  own docstring) — it's always executed as a scoped compress-rewrite, never an actual
  removal from `plan.scene_plan`, to avoid leaving the plan's own word-budget target
  inconsistent with what was actually narrated.
