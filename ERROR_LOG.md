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

## ERR-057 — ERR-048's LaTeX fix was a real improvement but not a guarantee; added a deterministic backstop

**Date:** 2026-09-14 · **Severity:** major (visibly broken text can still reach the screen) · **Status:** fixed · **Component:** `verification/hard/render.py`, `planning/story_planner.py`

**Where:** re-verifying ERR-048 on a fresh gpt-4o run (`video-01-attention-phase-e2e-verify-fair/
runs/v05`) showed the fix working MOSTLY -- but real `\sqrt`, `\cdot`, `\text`, `\sim` LaTeX
commands were still present in the rendered `page.html`. The same run also usefully confirmed
`check_formula_stage_consistency` (Phase 6 item 7) firing for real for the first time -- A2
registered real `formula_stages` and the check correctly caught two genuine regressions -- but
in the process revealed A2 had registered the stage's own `expression` USING LaTeX too
(`'\( q \cdot k / \sqrt{d_k} \)'`), which would make that check permanently unable to match even
a fully-compliant plain-notation render, since it compares the rendered content against the
registered string verbatim.

**Root cause:** a prompt instruction is a strong nudge to an LLM, never a hard guarantee --
expected, not a logic bug, but still meant a real defect (broken text on screen) could still
reach a promoted video with nothing to catch it.

**Fix:** `verification/hard/render.py::check_no_raw_latex(beat_visuals)` -- deterministic Python
check (a backslash followed by letters essentially never occurs in ordinary English prose, so
this is a low-false-positive signal), wired into the existing `check_render_content()` H-repair
path. Also extended `planning/story_planner.py`'s own `TASK_PROMPT` to require plain notation
for `formula_stages[].expression`, matching the same instruction already given to A2b/H.

**A related finding, not a code change**: the same run showed HEALTHY `diagram_card`/
`math_block` usage (11 + 7), which complicates ERR-056's causal story -- that fix's wording
change is still a real improvement (removing genuinely discouraging phrasing), but whether it
was THE cause of the originally-observed suppression is now uncertain given this second,
contradicting data point. Not re-investigated further; flagged here for honesty rather than
re-asserting the original claim.

**Tests:** plain notation clean; raw LaTeX flagged in both `screen_prose` and `component_data`;
multiple commands all named in one issue; ordinary prose never false-flagged; prompt-content
test for A2's own instruction. Full suite: 913 passed, 16 deselected.

**Not yet live-verified**: needs a fresh run to confirm zero raw LaTeX reaches a promoted page
even when the prompt-only instruction is imperfectly followed.

---

## ERR-058 — entity_consistency's exact-match check missed obvious entity variants (second occurrence of ERR-054's class)

**Date:** 2026-09-14 · **Severity:** major (false-positive AMBER on nearly every scene) · **Status:** fixed · **Component:** `verification/diagnostics/entity_consistency.py`

**Where:** the definitive final-verification run (`video-01-attention-final-verify/runs/v02`,
launched after every other fix this session landed) still showed `entity_consistency` firing
AMBER across 10 scenes. Inspecting the evidence: the plan locked `'entities_cat'` as a dict
KEY (a prefixed name) and `"refers to the cat"` as a full descriptive phrase in `values()`,
while scenes correctly quoted just `'cat'`. ERR-054's fix (lock both keys and values) still
used exact-set membership, so neither the prefixed key nor the embedded phrase ever equalled
the bare word a scene actually quotes -- even though a human glancing at either side would
immediately see they're the same entity.

**Fix:** `_matches_any()` -- substring containment in both directions, replacing exact-set
membership. Deliberately more lenient: this diagnostic is explicitly AMBER-banded, never a
hard gate, precisely because perfect entity resolution from prose isn't achievable by regex
alone (the plan's own original design note). A slightly higher false-negative rate (missing a
genuinely different short word that happens to be a substring) is a better tradeoff than the
false-positive flood exact matching produced on two separate real runs now.

**Tests:** a prefixed locked key matches the bare word; a locked descriptive phrase matches the
bare word; the original confirmed bug (a genuinely different invented example) is still caught
despite the more lenient matching. Full suite: 916 passed, 16 deselected.

**Confirmed by the SAME run this fix responds to** (evidence gathered before the fix, from the
actual live output): zero LaTeX, zero blank component boxes, healthy diagram_card/math_block
usage (6+3, further undermining ERR-056's original causal claim -- see that entry), zero
`render_issues`, `check_formula_stage_consistency` not triggered (this run's A2 registered no
`formula_stages`). Only `entity_consistency` was still noisy, which this fix addresses.

**Not yet live-verified**: needs one more fresh run to confirm the false-positive rate is
actually reduced with the fix in place.

---

## ERR-059 — CM/C2b silently treated a missing verdict as "checked and clean" (confirmed via code review, not a live run)

**Date:** 2026-09-15 · **Severity:** critical (a truncated/incomplete structured response was
indistinguishable from a genuinely clean check) · **Status:** fixed · **Component:**
`review/claim_mapper.py`, `review/grounding_verifier.py`

**Where:** flagged by an external review document (`multi_agent_pipeline_deep_improvement_plan.md`)
describing exactly this failure shape in two independent live GPT-4o/gpt-5.6-sol A/B runs — a
factual sentence with `grounding_required=false` appearing *later* in the script than earlier,
reproducing across two different Story Lead models (ruling out a Story-Lead-specific cause).
Verified against this codebase's actual code (not taken on the doc's word): `claim_mapper.py`'s
`map_claims()` keyed CM's response by `(scene_id, sentence_index)`, and a sentence the response
omitted a verdict for fell through to `if m is None: new_sentences.append(sentence)` — silently
keeping the pydantic default `grounding_required=False`. `grounding_verifier.py`'s C2b returned
only a sparse `CritiqueIssue[]`, so "no issue" was indistinguishable from "every sentence was
actually checked" — there was no positive record C2b had looked at any given sentence at all.

**Fix (STORY_IMPROVEMENT_PLAN.md Phase 10):** both passes now key verdicts to a stable
`sentence_id` (`narration/models.py::stamp_sentence_ids`, `f"{scene_id}:{index}"`, applied
defensively inside CM/C2b rather than trusted to every narration-producing call site) and
**fail closed** — a new `review.models.ReviewCoverageError` is raised, naming the exact missing
sentence ids, whenever a response doesn't cover every sentence given. CM also gained a third
verdict state (`UNCERTAIN`, treated as `grounding_required=True`, never silently dropped either
way) and batches large sentence counts into fixed 20-sentence chunks (`CM_BATCH_SIZE`) to lower
truncation risk on any single call — both CM and C2b skip the call entirely when a narration has
zero sentences (a real cost saving found while implementing this, not just a test convenience).
C2b's `GroundingReview.issues` became `GroundingReview.verdicts` (one dense `GroundingVerdict`
per sentence: `factual`/`supported`/`verified_claim_ids`/`qualifier_preserved`/
`scope_preserved`/`violation_code`), with `grounding_verdicts_to_issues()` deriving the same
kind of `CritiqueIssue`s the rest of the pipeline already routes on. `facts/models.py::Claim`
gained `required_qualifiers` (populated by C2a) so `qualifier_preserved` has something real to
check against. New `apply_grounding_metadata_repairs()` implements the doc's own correct
observation that a CM false negative C2b disproves (the sentence IS factual and IS supported)
is a metadata correction, not a narration defect — it patches the sentence directly rather than
routing an unnecessary rewrite through A3/B2, and runs before the deterministic
`check_grounding_policy`/`check_numeric_fidelity` checks so a since-corrected sentence never
trips a false hard failure.

**Two secondary bugs caught by the new tests before they ever shipped** (worth recording since
they're the kind of thing that would have silently misfired in production otherwise): (1) an
early version of `grounding_verdicts_to_issues()` emitted a *second*, redundant issue whenever a
verdict had both `supported=false` and a `violation_code` set, double-counting one real problem
as two — fixed by deriving exactly one issue per sentence in priority order (unsupported >
qualifier dropped > scope broadened > named `violation_code`) instead of checking each dimension
independently. (2) `apply_grounding_metadata_repairs()` initially matched verdicts against the
CALLER's narration object, which is never the same (already-stamped) object `verify_grounding`
built internally — pydantic's `model_copy` makes stamping non-mutating, so the caller's original
sentences still had blank `sentence_id`s and every lookup silently missed. Fixed by having
`apply_grounding_metadata_repairs()` (and `grounding_verdicts_to_issues()`) call
`stamp_sentence_ids()` defensively themselves, the same way `verify_grounding`/`map_claims` do,
rather than trusting call order.

**Tests:** `tests/review/test_claim_mapper.py` and `tests/review/test_grounding_verifier.py`
fully rewritten for the new schema — coverage-invariant fail-closed for both passes (exact
missing `sentence_id` asserted), `UNCERTAIN` handling, CM batching across multiple calls,
qualifier-drop/scope-broadened/named-violation severity mapping, and both metadata-repair paths
(a CM false negative silently corrected with no issue; a real C2b-confirmed defect left alone
and still flagged). `tests/orchestration/test_pipeline.py` (3 tests) and
`tests/orchestration/test_shorts_pipeline.py` (default fixtures + 1 override) updated so every
existing multi-cycle/real-sentence fixture supplies full coverage instead of an empty
placeholder. Full suite: **924 passed, 16 deselected** (up from 916).

**Not yet live-verified**: every change above is exercised via fake-agent unit tests with
deterministic fixtures, not a real model call — a live run was deliberately deferred (per this
session's cost-minimization instruction) until Phases 11-13 also land, so one combined e2e run
can verify all four together instead of four separate paid runs.

---

## ERR-060 — no contract declared what a video was allowed to promise vs. merely touch on (confirmed via code review, not a live run)

**Date:** 2026-09-15 · **Severity:** major (title/story scope drift, confirmed in an external
A/B review, not yet independently reproduced live in this codebase) · **Status:** fixed ·
**Component:** `planning/story_planner.py`, `verification/hard/structure.py`,
`review/story_critic.py`

**Where:** the same external review document that surfaced ERR-059 (`multi_agent_pipeline_
deep_improvement_plan.md`) reported its own headline finding: a live `gpt-5.6-sol` A2 run
produced a title that promised only the hook's concrete illustration (a pronoun-resolution
example) while the beats it planned went on to teach the full underlying mechanism plus
several supporting topics -- the generated title ended up narrower than the story actually
told. Verified against this codebase's real code: `verification/hard/structure.py`'s
`check_source_coverage()` was a **hard failure** if any source unit was never referenced by
some beat, with no escape valve for legitimately peripheral content -- confirming the
external doc's second claim, that the pipeline had no way to deliberately defer a real topic
without either dropping it silently or cramming it into a beat it didn't belong in. Nothing in
`StoryStructure`/`StoryPlan` declared, up front, what the video was committing to promise
versus what it was allowed to merely touch on -- so neither the title-writing step nor C1's
review had anything concrete to check title scope against.

**Fix (STORY_IMPROVEMENT_PLAN.md Phase 11):** new `planning/models.py::StoryScopeContract`
(`title_promise`, `central_question`, `must_cover`, `supporting`, `deferred`,
`title_must_not_imply`) and `SourceCoverageDecision` (`source_unit_id`, `disposition` ∈
`{MUST_COVER, SUPPORTING, DEFERRED, REDUNDANT, META_ONLY}`, `reason`), both populated by A2
before beats are built. `check_source_coverage` replaced with `check_source_disposition`:
every source unit must receive an explicit disposition (still a hard gate -- nothing is
silently dropped without a stated reason), but only `MUST_COVER`/`SUPPORTING` units actually
require a beat; `DEFERRED`/`REDUNDANT`/`META_ONLY` are legitimate outcomes on their own. C1
gained a new numbered PROMISE/SCOPE check (`TITLE_TOO_NARROW`, `BEAT_OUT_OF_SCOPE`,
`IMPORTANT_SOURCE_CONTENT_DROPPED`, `SUPPORTING_BEAT_TOO_LONG`), with a new `"scope"`
`CritiqueIssue` category (no existing category fit).

**Related, smaller fix bundled into the same phase**: `facts/models.py::SourceUnit` gained a
`kind` field (`CONTENT`/`PRODUCTION_META`/`VISUAL_GUIDANCE`/`REFERENCE`/`OTHER`), and
`facts/claim_extract.py` (S2b) now deterministically filters to `kind == "CONTENT"` before a
unit ever reaches the worker -- closing a real, if narrower, contamination path the same
external doc named (its own §30.8 example: a production note like "Show Q/K/V before 0:30"
must never become a technical Claim about the subject matter). Only `CONTENT` and
`PRODUCTION_META` are actually set anywhere in this codebase today
(`extraction/html_parser.py::_extract_production_notes`, the one real,
already-structurally-distinguished site) -- the other three `kind` values are declared for the
same three-way split the doc calls for, but nothing here extracts a unit that would need them
yet, so no speculative classifier was built ahead of a real case.

**Tests:** `tests/verification/hard/test_structure.py` rewritten for the disposition
semantics (missing-disposition flagged, a MUST_COVER unit left uncovered flagged, a DEFERRED
unit correctly passing with no beat at all, full coverage passing) -- plus every fixture in
that file and in `tests/orchestration/test_pipeline.py` updated to carry a matching
`source_coverage` (confirmed the hard way: running the suite before the fixture fix showed 16
tests failing in `test_pipeline.py` alone, since every one of them exercises the full
`check_structure()` aggregate). New `tests/review/test_story_critic.py` tests confirm the
PROMISE/SCOPE prompt text is present, the payload carries `title`/`scope_contract`/
`source_coverage`, and a fake `category="scope"` finding (replaying the doc's own
title-narrowing example) routes through cleanly. New `tests/extraction/test_html_parser.py`
and `tests/facts/test_claim_extract.py` tests confirm a production note is classified
`PRODUCTION_META` and never reaches the claim-extraction worker at all (zero calls, not just
zero claims returned). Full suite: **931 passed, 16 deselected** (up from 924).

**Not yet live-verified**: like ERR-059, every change here is exercised via fake-agent/fixture
unit tests, not a real model call -- deferred until Phases 12-13 also land, so one combined e2e
run can check whether A2 actually uses `scope_contract`/`source_coverage` usefully in practice
and whether C1's new check fires on a real title-narrowing case, rather than spending a
separate paid run per phase.

---

## ERR-061 — B1 could invent an unplanned CTA on the final scene; B2/shorts had no factual-invariant language at all

**Date:** 2026-09-15 · **Severity:** major (CTA ownership) / minor-to-major (drift risk, not
yet observed live) · **Status:** fixed · **Component:** `narration/generator.py`,
`editing/targeted_rewrite.py`, `narration/short_generator.py`, `planning/scene_expander.py`,
`planning/beat_word_budget.py`

**Where:** the same external review document (`multi_agent_pipeline_deep_improvement_plan.md`)
flagged two more confirmed-in-code issues. (1) `narration/generator.py`'s own `TASK_PROMPT`
literally said a scene becomes the CTA scene "if it matches `plan.cta.primary_after_beat` OR
is the final scene" -- the second clause let the narrator (B1), not the planner (A2), decide
to add a CTA to whatever scene happened to be last, independent of what the plan actually
placed. (2) `editing/targeted_rewrite.py` (B2) and `narration/short_generator.py` had no
hedging/overclaim language at all, while `narration/generator.py` (B1) carried a detailed one
-- a targeted rewrite or a short's own narrator could freely reintroduce exactly the kind of
overclaim B1 was told to avoid, since nothing told them not to. Separately, the same document's
§30.6 scenario (a simple beat given more `target_words` than it has real content for) had no
outlet in `planning/scene_expander.py` (A2b) other than padding -- confirmed by reading its
prompt, which asked for "within about 15% of target_words" with no escape valve.

**Fix (STORY_IMPROVEMENT_PLAN.md Phase 12):** B1's prompt now says a scene is the CTA scene
ONLY when it matches `primary_after_beat`, full stop; a new `CTAContract.final_enabled` flag
(default `true`) separately allows the true final scene, when it's a DIFFERENT scene, to add
one short soft closing line -- never a second full CTA ask, and settable to `false` for a
video that should end with zero CTA-adjacent language. A new shared
`narration/factual_invariants.py::NARRATION_FACTUAL_INVARIANTS` (the NEVER UPGRADE table --
`possible→actual`, `weighted→selected`, `conditional→universal`, etc. -- plus "any factual
sentence needs `claim_refs` regardless of `sentence_type`") is now injected into all three of
B1, B2, and the shorts narrator, so fixing an overclaim pattern here fixes it everywhere at
once. A2b's `ExpandedScene`/`ScenePlan` gained `needs_rebudget: bool`; its prompt now asks for
the minimum words the content actually supports, signaling `needs_rebudget=true` instead of
padding when a target can't be filled honestly. A new deterministic
`planning/beat_word_budget.py::redistribute_rebudgeted_words()` (wired into
`story_planner.py::plan_story()` right after the per-beat A2b loop) redistributes the resulting
deficit to scenes in beats that did NOT flag it, each capped at `ScenePlan.word_budget`'s own
30-100 hard bound -- no second LLM call, pure Python, same waterfilling shape as the module's
existing retention-deadline redistribution logic.

**Tests:** `tests/planning/test_beat_word_budget.py` gained 6 fully deterministic tests for the
new redistribution function (no-op cases, the real redistribution case, the 100-word hard cap,
no-eligible-recipient). `tests/planning/test_scene_expander.py` and
`tests/planning/test_story_planner.py` (a true end-to-end integration test via the existing
`SequencedStoryLead` harness) confirm the whole path from A2b's signal through to the final
`scene_plan`. `tests/narration/test_generator.py` confirms `final_enabled` reaches the payload
and the old automatic-final-scene clause is gone from the prompt. All three narration-writing
test files confirm `NARRATION_FACTUAL_INVARIANTS` appears verbatim in their prompts. Full
suite: **945 passed, 16 deselected** (up from 931).

**Not yet live-verified**: like ERR-059/060, deferred until a combined live run across Phases
10-12 (now ready to run).

---

## ERR-062 — C2b needed the same batching fix CM got in Phase 10 (found live, first real Phase 10-12 verification run)

**Date:** 2026-09-15 · **Severity:** critical (blocked every run past a moderate-sized script)
· **Status:** fixed · **Component:** `review/grounding_verifier.py`

**Where:** the first live run against `video-01-attention-coherent-story` after implementing
Phases 10-12 (`video-01-attention-phase10-12-verify/runs/v01`) crashed immediately, exactly as
Phase 10's fail-closed design intends -- but on a REAL call, not a test fixture:
`ReviewCoverageError: C2b did not return a verdict for 16/58 sentence(s)`. C2b's single,
unbatched call (58 sentences in one structured output) genuinely came back incomplete from
Gemini strong, the same shape of failure CM used to have before Phase 10 gave it
`CM_BATCH_SIZE`-based batching -- C2b was never given the same fix, because the original phase
plan's own text only called out batching for CM (§4.4), not C2b. This is exactly what live
verification is for: the fail-closed check did its job (caught a real incomplete response
instead of silently trusting it), but a fail-closed check with no way to actually succeed on
real input just makes the pipeline permanently unable to progress once a script crosses some
sentence-count threshold.

**Fix:** added `C2B_BATCH_SIZE = 20` to `review/grounding_verifier.py`, mirroring CM's exact
pattern -- `verify_grounding()` now batches the flattened sentence list into chunks, issuing
one `review_lead.run()` call per batch instead of one call for the whole narration, then merges
verdicts before the coverage check. No behavior change for a narration under 20 sentences
(still one call, same as before).

**Tests:** new `test_more_sentences_than_the_batch_size_are_split_across_multiple_calls` in
`tests/review/test_grounding_verifier.py`, mirroring CM's own batching test exactly (a
`C2B_BATCH_SIZE + 5`-sentence narration split across 2 calls, verdicts merged correctly). Full
suite: **946 passed, 16 deselected** (up from 945).

**Confirmed by the next two live-run attempts on the same source, after this fix:**
- `runs/v02`: got past C2b cleanly (no coverage error), advanced into C1, then hit a
  legitimate `BudgetExceeded` at the default $1.00 longform hard cap -- not a bug, the same
  known, correctly-functioning safety mechanism noted elsewhere in this log. Relaunched with
  `--loop-budget-usd 1.5`.
- `runs/v03`: **completed end to end**, `final_status=FAIL`, total cost $1.1467. The FAIL
  itself is the system working correctly, not a bug -- see the Phase 10-12 live-verification
  summary immediately below for the full breakdown of what this run actually confirmed.

---

## Phase 10-12 live-verification summary (`video-01-attention-phase10-12-verify/runs/v03`, 2026-09-15)

The first real run to exercise Phases 10, 11, and 12 together end to end (after the ERR-062
batching fix above). `final_status=FAIL` -- a legitimate outcome, not a bug, explained below.
Total cost across all attempts on this verification (two failed fast, one completed):
~$2.28 -- see ERR-062 for why the first two didn't reach the end.

**Phase 10 (grounding) -- confirmed working, and confirmed VALUABLE, not just passing tests:**
C2b's dense per-sentence verdicts produced two real, substantive `qualifier_dropped` findings
against actual model-written narration -- one citing that "reaching forward only applies to
unmasked (bidirectional) attention, not causal attention used in text generation" being
dropped, the other that a claim's "zero-centered" condition was dropped while its
"independent and unit-variance" part was kept. Both are exactly the class of defect
`Claim.required_qualifiers` + `GroundingVerdict.qualifier_preserved` were built to catch, and
neither is a check-passing formality -- they're real, technically specific, correctly-severed
(`critical`) findings a human reviewer would also flag. The revision loop then behaved exactly
per Phase 8.5's design: two targeted rewrites each made hard failures WORSE (2→6, then 2→4)
and were correctly reverted each time, and once `MAX_MAJOR_REVISIONS` was exhausted the run
correctly reported `FAIL` rather than quietly emitting a broken script as if it had passed.
`entity_consistency` stayed GREEN throughout (Phase 6 machinery unaffected).

**Phase 11 (scope contract) -- confirmed working, fully and sensibly populated:**
`plan.json`'s `scope_contract` came back complete and coherent (`title_promise`,
`central_question`, 6-item `must_cover`, 2-item `supporting`) and `source_coverage` classified
all 13 real source units with real per-unit reasons -- including correctly marking
`production_notes` as `META_ONLY` ("Provides pacing instructions and should not be included in
the content directly"), confirming the `SourceUnit.kind="PRODUCTION_META"` classification from
extraction correctly informed A2's own disposition judgement downstream. The
`check_source_disposition` hard gate passed cleanly (neither of the run's 2 hard failures was a
disposition/coverage issue). **One open, inconclusive item**: the chosen title ("How
Transformers Use Attention to Resolve Pronouns") arguably reads narrower than `must_cover`
(which includes the full QKV/scaling/multi-head/masking mechanism, not just pronoun
resolution) -- the exact shape of finding C1's new PROMISE/SCOPE check exists to catch, but it
did NOT fire this run. Genuinely ambiguous, not a confirmed miss: using the hook's concrete
illustration as the title's framing device is a legitimate narrative technique, not
automatically a scope violation, so this is flagged as unresolved rather than claimed as a bug
in either direction -- worth watching on future runs, not yet acted on.

**Phase 12 (narration invariants / CTA / word-budget) -- confirmed working:**
`needs_rebudget` fired on 10 of 12 beats' final scenes on real A2b output -- strong evidence
the model is genuinely using the new escape valve rather than padding, not a mechanism that
looks fine in tests but never actually triggers live. The CTA sentence appeared exactly once,
on `beat_recap_s02` (the scene matching `cta.primary_after_beat`), phrased as a real
value-linked ask ("You now know how attention resolves 'it' -- subscribe to see this reasoning
applied across full Transformer architectures") -- no second/invented CTA anywhere else in the
35-scene narration. (This run's `primary_after_beat` beat happened to also be the video's last
beat, so it didn't distinctly stress-test the new "different final scene" soft-closing-line
branch -- that specific path remains unexercised live.)

**Not investigated further, unrelated to Phases 10-12**: two `reader_standalone_word_count_
out_of_band` render issues (3613 and 3549 words vs. the existing 2000-3200 band) -- a
pre-existing V1B check, already noted elsewhere in this log as "a real, legitimately strict
gate in practice."

**Follow-up finding from manually reading the actual rendered HTML output** (not just the JSON
artifacts) of this same run, after the user asked directly whether Phase 10-12 changes were
reflected in the final HTML: they mostly were, but one real gap turned up -- see ERR-063 below.

---

## ERR-063 — Phase 10's qualifier-preservation checking never reached H's screen prose or C3

**Date:** 2026-09-15 · **Severity:** major (a defect the pipeline explicitly blocks promotion
for on the narration side can reach the viewer unblocked on the screen side) · **Status:**
fixed · **Component:** `html_synth/synthesizer.py`, `editing/html_repair.py`,
`review/visual_critic.py`, `orchestration/html_pipeline.py`

**Where:** found by directly reading the rendered `video_script.html` from
`video-01-attention-phase10-12-verify/runs/v03` (the same run summarized above), not just its
JSON artifacts -- the user asked directly whether Phase 10-12 changes were actually reflected
in the final HTML. C2b had flagged `beat_preview_s03`'s spoken narration as a **critical**
`qualifier_dropped` finding: it stated attention "can reach forward into the sentence" without
noting this only applies to unmasked/bidirectional attention, not the causal attention used in
text generation. Checking the ACTUAL on-screen prose for that same scene: *"Because every
position can attend to every other position, 'it' can query words that appear later in the
sentence..."*, with a diagram captioned *"Unrestricted attention lets a position look both..."*
-- the identical unqualified claim, independently written by H, completely unflagged. Root
cause, confirmed in code: `html_synth/synthesizer.py::_claim_payload()` sent H only
`{claim_id, claim, numbers}` -- no `required_qualifiers`, no `scope` -- and
`review/visual_critic.py::scene_payload()` never included claim data of any kind. Phase 10's
whole qualifier-checking mechanism (`Claim.required_qualifiers`, `GroundingVerdict.
qualifier_preserved`) was wired into C2b (spoken narration) only; H and C3 (the screen-prose
side) had no access to it at all, by construction, not by an oversight in a check that ran and
missed it.

Notably, this wasn't systematic: `beat_scaling_s02`'s screen prose independently got the
"zero-centered" qualifier right even though B1's narration for the same claim dropped it --
confirming this is inconsistent luck depending on what H happened to write, not any real
protection.

**Fix:** `html_synth/synthesizer.py::_claim_payload()` and `editing/html_repair.py::
_claim_payload()` now both include `scope`/`required_qualifiers`, with a matching instruction
added to `synthesizer.py`'s `TASK_PROMPT` and `html_repair.py`'s `REPAIR_TASK_PROMPT` to
preserve them. `review/visual_critic.py::scene_payload()` gained a `required_qualifiers`
parameter, and its existing OVERCLAIM check (the same one this codebase already uses for
screen-prose repetition/overclaim, `category: clarity`, `layer: NARRATION`,
`repair_owner: html_author`) now explicitly treats stating a qualified mechanism without its
condition as a CONFIRMED overclaim when `required_qualifiers` is given, same severity
convention as the existing check (major/minor, never critical -- H-repair can fix screen prose,
so this was never a candidate for the critical/narration_lead "genuine contradiction" bucket).
`orchestration/html_pipeline.py`'s C3 wiring now aggregates `required_qualifiers` per beat
(same `beat.source_unit_ids` scoping H's own `available_claims` already uses) and passes it
into each scene's `scene_payload()` call.

**Tests:** new tests in `tests/html_synth/test_synthesizer.py`, `tests/editing/
test_html_repair.py`, `tests/review/test_visual_critic.py`, and `tests/orchestration/
test_html_repair_loop.py` confirm `required_qualifiers`/`scope` reach each payload correctly
(H's first pass, H-repair, and C3's real beat-scoped wiring through the full
`synthesize_and_repair_video_html()` loop) and that all three task prompts mention
`required_qualifiers`. Full suite: **952 passed, 16 deselected** (up from 946).

**Not yet live-verified**: the wiring itself (data reaching the right payload) is fully
covered by unit tests; whether C3 actually raises a finding for a real dropped qualifier on
screen prose is a live model-judgment question, deferred to the next live run rather than
spending another paid run on a change that unit tests already confirm is wired correctly.

---

## ERR-064 — Even a bounded ~20-sentence batch can still drop exactly one CM/C2b verdict (found live, Phase 13-15 gpt-4o/gpt-5.6-sol comparison)

**Date:** 2026-09-15 · **Severity:** major (crashed 2 of 2 live-verification attempts) ·
**Status:** fixed · **Component:** `review/claim_mapper.py`, `review/grounding_verifier.py`

**Where:** launching the requested gpt-4o vs. gpt-5.6-sol comparison (with shorts enabled)
against `video-01-attention-coherent-story`, the gpt-4o run crashed with
`ReviewCoverageError: C2b did not return a verdict for 1/57 sentence(s)`. Relaunching fresh
(a new run, new claims, new narration -- not a retry of the same content) crashed again, this
time at CM: `did not return a verdict for 1/71 sentence(s)`. Both are the exact same failure
shape ERR-062 fixed (a coverage gap Phase 10's fail-closed check correctly caught rather than
silently trusting), but ERR-062's fix -- bounding batches to `CM_BATCH_SIZE`/`C2B_BATCH_SIZE`
(20 sentences) -- reduces the failure rate without eliminating it: two independent live runs
each dropped exactly 1 sentence out of a ~20-sentence batch, a real, repeatable ~5%-per-batch
miss rate, not a one-off fluke tied to one run's specific content.

**Fix:** both `map_claims()` and `verify_grounding()` now retry ONCE, with only the missing
sentence(s), before failing closed -- if the initial round of batches leaves any
`sentence_id`s uncovered, one small follow-up call carrying just those sentences (same claim
registry) is made, and only if THAT still leaves gaps does `ReviewCoverageError` fire. This
resolves an isolated, apparently-stochastic miss without paying to redo whole batches or
failing an entire run over one sentence, while still failing closed (never silently trusting
an incomplete response) if the retry itself comes back incomplete too.

**Tests:** new tests in `tests/review/test_claim_mapper.py` and `tests/review/
test_grounding_verifier.py` confirm (a) a missing sentence recovered by the retry never
raises and the retry payload contains only the missing sentence(s), and (b) the existing
fail-closed test now explicitly asserts exactly 2 calls happen (initial + one retry) before
raising, not that it fails on the very first miss. Full suite: **990 passed, 16 deselected**
(up from 988).

**Not fully live-reverified yet**: the gpt-4o run was relaunched with this fix in place as
part of the same verification session; results pending at time of writing. If the same
~5%-per-batch rate holds, a two-batch call (40 sentences, ~2 batches) has roughly a
1-in-10ish chance of needing the retry at least once -- worth watching whether this stays a
rare, cheap escape valve or whether it starts firing on nearly every run, which would suggest
the miss rate is closer to systematic than stochastic and the batch size itself may need
revisiting.

---

## ERR-065 — Even a 300s B2 timeout wasn't enough once ERR-064's CM/C2b retry got a run past coverage errors (found live, Phase 13-15 gpt-5.6-sol comparison)

**Date:** 2026-09-15 · **Severity:** critical (crashed the live gpt-5.6-sol comparison run
outright, no partial output saved) · **Status:** fixed · **Component:** `editing/targeted_rewrite.py`

**Where:** after ERR-064's retry fix let the gpt-5.6-sol run past the coverage-gap crashes,
it ran further and hit a NEW failure: `subprocess.TimeoutExpired: ... timed out after 300s`
inside a B2 targeted-rewrite call. The traceback's payload showed **16 scenes** named in one
revision cycle (a mix of `rewrite_beats` and `technical_fixes` findings across several beats),
each carrying its own `visual_description` and full `available_claims` list serialized into a
single JSON payload.

**Root cause:** ERR-051 raised B2's `timeout_s` from 180 to 300 and explicitly flagged itself
as "not yet live-verified: needs a fresh run that actually exercises a `rewrite_beats` cycle to
confirm 300s is sufficient in practice." This run supplied that missing live verification, and
the answer is no — `apply_targeted_rewrite()` had no upper bound on how many scenes could be
crammed into one call; a revision plan naming 16 scenes (plausible once a story critique finds
several unrelated issues across the video, not a contrived edge case) produces a payload large
enough that even 300s isn't enough. Raising the timeout again would only move the same failure
to a slightly larger revision plan next time, with no ceiling.

**Fix:** chunk `apply_targeted_rewrite()`'s scenes into batches of `B2_BATCH_SIZE = 5` (chosen
conservatively — each B2 scene payload is far heavier per-item than a CM sentence, which
batches at 20), issuing one `narration_lead.run()` call per batch and merging the rewritten
scenes by `scene_id`, mirroring the batching precedent already established in
`review/claim_mapper.py`/`review/grounding_verifier.py`. This bounds every call's payload size
regardless of how large a single revision plan gets, rather than chasing the timeout ceiling
upward indefinitely.

**Tests:** `tests/editing/test_targeted_rewrite.py` — a revision plan spanning
`B2_BATCH_SIZE * 2 + 1` scenes is split into 3 calls of sizes 5/5/1 and every scene still gets
rewritten regardless of which batch it lands in; a small revision plan (all existing tests)
still makes exactly one call, confirming no regression for the common case. Full suite: **1001
passed, 16 deselected** (up from 999).

**Not yet live-reverified**: per explicit user instruction, no fresh comparison run was
launched to confirm this in production — the gpt-5.6-sol run that hit this was not relaunched.
Worth watching on the next live run whether 5 scenes/batch reliably stays under 300s, or
whether an individual scene's own claim list can still be large enough to need a smaller batch
or a per-scene claim cap.

**Also observed, not a code bug:** the parallel gpt-4o run (`v04`, $3.00 cap) in this same
live-verification round got much further — S0/S2/C2a/A1 all completed, the story+narration
loop finished with `final_status=FAIL` (exhausted its revision cycles without clearing the
quality bar, a legitimate outcome, not a crash), H/HV completed (5 beats, 4 render issues, 2
repairs), and shorts selection found 4 candidates — then crashed with
`litellm.exceptions.ServiceUnavailableError` (Gemini `503`, "This model is currently
experiencing high demand") during a short's own CM claim-mapping call. This is the exact
failure class ERR-032 already added `num_retries=3` for; the traceback confirms litellm
actually retried 4 total attempts (1 + 3 retries) and every one hit the same 503 — a sustained
provider-side outage that outlasted the existing backoff window, not a gap in our retry logic.
Matches ERR-051's own precedent ("simply re-running is the correct response to this class of
failure"). Total spend before the crash: $1.354 of the $3.00 cap. **Note:** this run (PID
42744) was already in-flight before Phase 17.1's checkpointing code landed in this same
session, so it wrote no `checkpoint.json` and `--resume` cannot recover it — a run started
after Phase 17.1 landed would have checkpointed past claims/A1/story_loop and only needed to
redo H+HV and shorts on a retry.

---

## ERR-066 — Missing cross-attention content + systematic budget overshoot, root-caused via a full cross-run survey (user-reported, 2026-09-15)

**Date:** 2026-09-15 · **Severity:** major (a real deliverable could ship missing whole
sections; the default model now crashes on its own default budget) · **Status:** fixed ·
**Component:** `orchestration/pipeline.py`, `orchestration/run_pipeline.py`, `llm/budget.py`,
`src/config/budget.yaml`, `review/claim_mapper.py`, `review/grounding_verifier.py`,
`llm/concurrency.py` (new), `llm/usage.py`

**Where:** user reported the final HTML from today's gpt-4o comparison run
(`video-01-attention-phase13-15-verify-gpt4o/runs/v04`) had no mention of cross-attention,
and separately reported "multiple errors and budget overshoot" since Phase 10, asking for a
deep analysis rather than a guess. Investigated with real evidence, not speculation:

1. **Missing content.** The source's own production notes explicitly plan an 11:25
   "Multiple heads + cross-attention" beat. Surveyed every `plan.json` written since
   2026-09-11 (18 runs) for source-unit coverage against each unit's own
   `SourceCoverageDecision.disposition` — 17 of 18 have complete coverage, including a run
   from this morning (`phase10-12-verify`) launched *after* Phase 10-12 landed. Only today's
   `v04` is missing anything, and it's missing three whole sections (`heads`, `origin`,
   `recap`), not just cross-attention. This is NOT a systemic Phase 10-17 content-generation
   regression. Root cause: A2's first attempt AND its one-and-only replan (`MAX_STORY_REPLANS
   = 1`) both left the same three sections uncovered; `check_source_disposition`'s
   `required_source_unit_uncovered` hard-check correctly caught this and was correctly never
   dismissed by A3, but once the sole replan was spent, the loop had zero recourse and fell
   through to `"replan budget exhausted -> FAIL"` — which still ran full H/HV and shorts
   generation (real $ spent) and produced a complete-looking HTML draft that could be mistaken
   for a real deliverable, even though it was correctly excluded from `promote_to_final()`.

2. **Budget overshoot.** Computed real per-run cost from every `usage.jsonl` since 2026-09-11.
   C2b's own cost jumped from $0.08-$0.20/run (pre-Phase-10) to $0.46-$0.79/run (post-Phase-10)
   — a deliberate, documented ~3-5x increase from Phase 10's sparse-issues -> dense
   per-sentence verdict redesign, compounded by Phase 13's C4d (a second full cold/continuing-
   viewer cascade). Neither change was reconciled against `DEFAULT_TIERS["longform"].hard_cap_usd
   = 1.00`, a constant ERR-046 (2026-09-12, *before* either phase) had already flagged as tight
   for reasoning-tier models but explicitly kept for the default gpt-4o path because it "still
   completes fine" — no longer true: today's default gpt-4o loop cost $1.2604, 26% over the
   unmodified default hard cap. This is why every live-verification run this session needed a
   manually-raised `--loop-budget-usd` just to complete at all, even on the default model.

**Fix:**
- `llm/budget.py`/`src/config/budget.yaml`: `DEFAULT_TIERS["longform"]` raised 2x
  (target/warning/hard_cap: 0.40/0.60/1.00 -> 0.80/1.20/2.00), giving headroom above the
  observed $1.0-$1.6 range without a manual override on every run.
- `orchestration/pipeline.py`: `MAX_STORY_REPLANS` raised 1 -> 2 -- a coverage-type hard
  failure can ONLY be fixed by a replan (`apply_targeted_rewrite` never adds a new beat), so
  one bad replan used to be a dead end.
- `orchestration/run_pipeline.py`: new structural-coverage gate right after the story loop --
  if `final_status == "FAIL"` AND a `required_source_unit_uncovered`/
  `source_unit_missing_disposition` hard failure survived, skip H/HV and shorts entirely
  (nothing downstream can fix content that was never planned) instead of spending on them
  before failing to promote anyway. `PipelineRunOutput.html_result` is now `HtmlSynthesisResult
  | None` to represent this skipped-entirely case honestly, rather than fabricating a fake
  result object.
- New `llm/concurrency.py::run_concurrently()`: CM's and C2b's batch loops (the biggest,
  slowest structured-output calls in a review cycle, and the ones the user specifically named
  as "taking a huge time") now dispatch their independent batches concurrently via a
  `ThreadPoolExecutor` instead of sequentially, cutting wall-clock time roughly by the number
  of batches without changing $ cost or the per-sentence correctness guarantee (see
  "Considered and rejected" below). `BudgetCounter` (`llm/budget.py`) and `UsageLedger`
  (`llm/usage.py`) both gained an internal lock around their small bookkeeping sections (the
  actual slow I/O runs unlocked and fully concurrent) so sharing one budget/ledger across
  threads is safe -- confirmed by a dedicated concurrent-`record_spend` test that would have
  caught the un-locked race (a lost update silently undercounting real spend past hard_cap).

**Considered and rejected:** coarsening C2b/CM from per-sentence to per-scene/per-beat
granularity, which the user explicitly floated as a way to cut cost/time further. Rejected for
now: Phase 10's per-sentence dense verdict is what already caught 2 real, live, critical
`qualifier_dropped` findings that a sparser check would have missed by construction (the whole
reason Phase 10 exists — "no issue" used to be indistinguishable from "never actually
checked"). Parallelizing the existing per-sentence batches gets the same wall-clock win without
that regression risk. Revisit only if concurrency alone proves insufficient on a live run.

**Tests:** `tests/llm/test_budget.py` (tier values), `tests/llm/test_concurrency.py` (new --
result ordering, genuine wall-clock overlap, single-item bypass, exception propagation,
concurrent `record_spend` never loses an update, concurrent `UsageLedger.append` never
corrupts a line), `tests/orchestration/test_pipeline.py` (replan-exhaustion test extended to 2
replans), `tests/orchestration/test_run_pipeline.py` (new: uncovered-source-content skips
H/HV+shorts entirely; an ordinary non-coverage FAIL still runs H/HV as before), `tests/review/
test_claim_mapper.py`/`test_grounding_verifier.py` (batch-order assertions changed to
order-independent multiset checks now that batches dispatch concurrently; the shared
`FakeReviewLead` test double made thread-safe and content-matching for genuinely concurrent
calls, falling back to position for the deliberately-partial responses the retry tests rely
on). Full suite: **1012 passed, 16 deselected** (up from 1001), re-run 15x to confirm the new
real-thread tests aren't flaky.

**Not yet live-verified**: no fresh run was launched as part of this fix (matching the
standing "don't start a fresh run" instruction) -- the actual wall-clock speedup and the new
$2.00 default cap's sufficiency are confirmed by unit test and cost-survey math, not yet by a
real end-to-end run.

---

## ERR-067 — Shorts pipeline: 3 systematic bugs found by generating all 5 real candidates and persisting each one's actual review findings

**Date:** 2026-09-15 · **Severity:** critical (100% of shorts failed, 0 ever promotable) ·
**Status:** fixed · **Component:** `review/short_critic.py`, `narration/short_generator.py`,
`planning/shorts_models.py`, `orchestration/shorts_pipeline.py`

**Where:** Phase 18's new `save_short_debug()` (this same day, ERR-066) finally made a FAILed
short's actual `hard_failures`/`issues` inspectable after the run instead of vanishing with the
process. Used it on all 5 real candidates from a `--resume`'d run (`--shorts-count 0`, one per
candidate found) — every one FAILed, and unlike the earlier single-short run, the pattern
across 5 independent generations was too consistent to be model randomness:

1. **5 of 5** flagged `critical/ending [RESERVED_OUTRO]` for a spoken follow-up line.
2. **4 of 5** flagged `critical/micro_arc` for a `problem_fix` short skipping the required
   naive-attempt step.
3. **4 of 5** flagged `measured_duration_exceeds_max` (61.7-76.4s against the 60s hard cap).

**Root causes, one per bug, all the same shape — a critic enforcing a rule the generator was
never told:**

1. `review/short_critic.py::critique_short()` never received `plan.bridge.mode` at all. Its
   "no reserved outro" rule unconditionally flagged ANY spoken follow-up line as a critical
   defect — even though `narration/short_generator.py`'s own prompt explicitly REQUIRES
   exactly one such line when `bridge.mode == "SPOKEN"`. The generator was correctly obeying
   its own instructions; the critic was rejecting correct behavior because it lacked the one
   piece of context (`bridge_mode`) needed to judge it.
2. `short_critic.py`'s prompt already lists structural requirements per `micro_arc` (a naive
   attempt for `problem_fix`, a stated myth for `myth_correction`, ...), but
   `short_generator.py`'s own prompt never mentioned ANY of these — it just says "write hook/
   setup/mechanism/payoff," generic across all 7 arc types, with no idea what its own chosen
   arc structurally requires.
3. `ShortNarration.word_band` (default `(120, 165)`) and `target_duration_seconds` (default
   `52.0`, `le=60.0`) were calibrated against an assumed ~167 words/minute -- but `word_band`
   was never actually sent to the model at all (`generate_short_narration()`'s payload only
   ever included the bare `target_duration_seconds` number, with a vague "45-60 seconds"
   prompt phrase). Back-computing from the worst overrun (165 words measuring 76.4s) implies
   real edge-tts speech runs closer to ~130 words/minute, not 167.

**Fix:**
- `critique_short()` gained a `bridge_mode` parameter, included in its payload; the prompt's
  rule 3 now explicitly says a single required line under `bridge_mode="SPOKEN"` is NOT a
  violation, only a second one/a longer paragraph is. `orchestration/shorts_pipeline.py`'s
  `run_short()` now passes `plan.bridge.mode` through.
- `short_generator.py`'s `TASK_PROMPT` gained explicit structural guidance for all 7
  `MicroArc` values (not just the 2 that happened to fail in this one run — the same "critic
  knows a rule the generator doesn't" bug would recur for the other 5 the next time one of
  them gets picked).
- `ShortNarration.word_band` is now sent to the model (`generate_short_narration()`'s payload),
  with prompt language treating it as a real ceiling, not the old vague seconds-based hint.
  Both `word_band` (120-165 -> 90-115) and `target_duration_seconds` (`le` 60.0 -> 55.0,
  default 52.0 -> 45.0) recalibrated against the ~130wpm real-speech evidence, with real
  margin left below the 60s hard cap rather than aiming at it exactly (an LLM's own word count
  is itself unreliable, the same reasoning that motivated long-form's deterministic per-beat
  word budgets).

**Tests:** `tests/review/test_short_critic.py` (bridge_mode defaults to NONE, is passed
through, prompt explains the conditional rule), `tests/orchestration/test_shorts_pipeline.py`
(`run_short()` forwards `plan.bridge.mode` to C1s), `tests/narration/test_short_generator.py`
(word_band reaches the payload, prompt has ceiling language, all 7 `MicroArc` values have
structural guidance in the prompt). Full suite: **1024 passed, 16 deselected** (up from 1017).

**Not yet live-verified**: no fresh shorts run was launched to confirm these 3 fixes actually
produce a passing short — the next `--resume ... --shorts-count 0` run against this same
checkpoint is the natural way to check, since it's nearly free (~$0.07, ~17 min, per ERR-066's
own resume timing).

**Update (same day, live-verified after two more rounds):** re-ran 3 more times after each
fix. Round 1 (bridge_mode + word_band only): reserved-outro 5/5->0/5, duration 4/5->1/5 --
confirmed. Naive-attempt stayed 4/5 unchanged, revealing the fix was at the wrong layer (B1s
narration) when the real gap was one level up (A2s planning never checked whether a naive
attempt was actually groundable before choosing `problem_fix`). Round 2 (A2s-level arc-content
requirement + title-reuse instruction) found a NEW bug the same live data surfaced: 2 of 5
shorts had a completely empty hook segment (`hook.narration` blank by valid design, and B1s
never being told a hook must have SOME spoken words regardless), which also explained why the
title check kept failing -- it fell back to comparing against `hook.visual` (a diagram
description) for exactly those shorts, a vocabulary domain no title could match. Fixed:
`narration/short_generator.py` now requires the hook segment to never be empty;
`verification/hard/shorts.py::check_title_hook_payoff_alignment` now also accepts a match
against `central_insight` (always populated) so a visual-only hook's diagram-description text
isn't the only anchor available; `short_planner.py`'s title guidance was also toned down after
its first version overcorrected into copying whole sentences as "titles." Round 3 (all 5
fixes): **2 of 5 shorts PASS_WARN with zero hard failures** -- the first passing shorts this
entire session. Reserved-outro/duration/empty-hook/title-mismatch: 0/5 each, fully confirmed
gone. Naive-attempt: 1/5 (down from 4/5) -- genuinely improved, not eliminated, consistent with
it being a probabilistic model-compliance issue rather than a wiring gap. The 3 remaining
failures were distinct, previously-unseen issues (a verbatim mechanism/payoff repetition, a
payoff that reads as a full recap, and legitimate `qualifier_dropped` catches -- the last one
not a bug, C2b correctly catching a real overclaim), not a recurrence of any of the 5 fixed
bugs. Full suite held at 1024-1034 passed throughout (new tests added each round). Total spend
across all 3 verification rounds: ~$0.21 (all near-free resumes reusing the same $2.30
checkpoint).

**Second gap found immediately after, from the user asking to actually see the passing
shorts:** `final/shorts/<i>/` (and its `short.html`) is gated on the OVERALL run's combined
`final_status`, not each short's own -- confirmed live that short #2/#4's PASS_WARN with zero
hard failures never got written anywhere, because the unrelated parent story loop's own FAIL
made the whole promotion block skip, and `synthesize_short_html()`'s in-memory result was
discarded when the process exited with nothing to show for a short that had actually passed.
Fixed: `save_short_debug()` now also always writes `plan.json`, `narration.json`, and (when
given) `short.html` to `shorts/<i>/`, independent of the overall run's status -- the same
"always written, unlike promotion-gated final/" pattern the status.json half of this function
already established. Tests: `tests/orchestration/test_shorts_pipeline.py` (html/plan/narration
written when given, html skipped when not), `tests/orchestration/test_run_pipeline.py`
(`save_short_debug` receives the real generated html even when the overall run doesn't
promote). Full suite: **1034 passed, 16 deselected**. Not yet live-verified with a real run.

**Third update, deeper analysis after a live-verify of all 5 fixes above:** re-ran once more
-- title-mismatch/duration/reserved-outro/empty-hook confirmed at 0/5, **2 of 5 shorts
PASS_WARN with zero hard failures** (the first passing shorts this session). But
`critical/micro_arc` (naive-attempt) was still 1/5, and a full failure-code trend across all 6
generation rounds showed `critical/ending` hadn't gone away either -- it had changed shape
(100% "reserved outro" -> fixed -> reappeared as verbatim mechanism-repetition or full-recap
payoffs). Both are judgment-quality problems a single-shot generation's prompt can keep
improving but not fully close, the same signature that made long-form itself outgrow pure
prompting (ERR-022 through ERR-026). Built the bounded revision cycle
`orchestration/shorts_pipeline.py`'s own module docstring had pre-committed to -- see
STORY_IMPROVEMENT_PLAN.md's new **Phase 20** for the full design and change list. Not yet
live-verified.

---

## ERR-068 — Deep dive on shorts visuals: duration cap raised to 120s, and 3 real bugs found in the HTML/CSS layer (never investigated until now)

**Date:** 2026-09-16 · **Severity:** major (one bug had been silently dropping a CSS
property in every H/short render this whole session) · **Status:** fixed · **Component:**
`verification/hard/shorts.py`, `planning/shorts_models.py`, `narration/short_generator.py`,
`planning/short_planner.py`, `html_synth/component_library.py`, new `verification/hard/
css_lint.py`, `verification/diagnostics/shorts.py`, `orchestration/run_pipeline.py`

**Where:** user reported the actual `short.html` looked sparse ("just two or three lines, no
script like we have long form html") and asked for a deep dive, having only looked at the
narration/critique layer until now. Two real findings, neither previously investigated:

1. **Duration cap raised 60s -> 120s (user decision).** The tight 60s budget was itself a
   likely contributing factor to several of ERR-067's failures beyond direct duration
   overruns -- `setup` had to fit BOTH its original "minimum context" job AND its new
   per-micro_arc required beat (Phase 20) in the same ~90-115 word allowance as everything
   else. Raised `verification/hard/shorts.py`'s `MAX_SHORT_SECONDS` (62.0 -> 122.0) and
   `MAX_MEASURED_SHORT_SECONDS` (60.0 -> 120.0); recalibrated `ShortNarration.
   target_duration_seconds` (default 45.0 -> 95.0, bounds 45-55 -> 60-110) and `word_band`
   (90-115 -> 160-210) against the same ~130wpm real-speech evidence, scaled up.

2. **`plan.visual.states` was empty in 5 of 5 real shorts across a full run** -- likely every
   short ever generated by this pipeline. `html_synth/vertical_assembler.py`'s flow-diagram
   renderer only draws anything on the mechanism screen when `states` is non-empty; A2s
   reliably filled `dominant_object` (self-explanatory) but never `states`, because
   `planning/short_planner.py`'s prompt described it in one throwaway clause ("its states")
   with no explanation of what a "state" actually is, unlike every other field. This is why
   every short's HTML has been plain text only, with the diagram capability completely dead
   in practice. Fixed: prompt now explains states as 2-4 short labels naming the sequential
   stages the object moves through, with concrete examples, and states plainly that an empty
   list is a real content gap, not a valid "no diagram" signal. Added `verification/
   diagnostics/shorts.py::check_visual_states_present` (AMBER when empty, never a hard gate)
   so this can never go silently dead again without at least a visible signal.

3. **Found while reading the actual generated `short.html` byte-for-byte** (not just JSON
   artifacts -- same investigative discipline as ERR-063's own long-form finding):
   `html_synth/component_library.py`'s shared `BASE_STYLESHEET` (used by BOTH long-form H and
   shorts) had `.math-block{...border-radius:var(--r_sm)...}` -- underscore -- while
   `css_tokens()` only ever emits `--r-sm` -- hyphen (`name.replace('_', '-')`). This exact
   bug was already identified in the `video_script_6_html_finetuning_feedback.md` review
   earlier this session (item #20) but never actually fixed at the time, only logged as a
   real, confirmed finding. Fixed the typo, and built the CSS-variable-lint check that same
   review recommended (item #21): new `verification/hard/css_lint.py::
   check_css_variable_references()`, a generic `var(--x)` vs `--x:` declaration check, wired
   into `verification/hard/vertical.py::check_vertical_short()` for shorts (long-form's
   `render.py` is a natural next place to wire the same shared check, not yet done).

4. **Structural gap found while wiring in the new CSS check**: `check_vertical_short()`'s
   result had ALWAYS been computed and logged as a bare count in `run_pipeline.py`, never
   actually consulted for a short's own pass/fail decision -- the exact same class of gap the
   2026-09-11 long-form fix ("the combined status below is what actually gates promotion
   now") already closed for H/HV, just never extended to shorts. A short with a real vertical
   defect (a tampered narration hash, a missing safe zone, an undeclared CSS variable) could
   PASS its narration review and still ship with a broken render, completely undetected.
   Fixed: `run_pipeline.py` now downgrades a short's `final_status` (via the same
   `apply_editorial_downgrade` long-form already uses) whenever `check_vertical_short` finds
   anything, and folds the vertical issues into `short_result.hard_failures` so
   `save_short_debug()`'s persisted `status.json` shows the complete picture.

**Tests:** `tests/verification/hard/test_css_lint.py` (new, 7 tests -- undeclared variable
flagged, the exact historical bug shape caught, declared+used is clean, declared-but-unused
is not flagged, a `var(x, fallback)` doesn't suppress the check, multiple undeclared vars
each reported, underscored names supported), `tests/verification/hard/test_vertical.py` (new
regression test proving the wiring, not just the standalone function, catches the bug shape),
`tests/verification/diagnostics/test_shorts.py` (visual-states AMBER/GREEN), `tests/planning/
test_short_planner.py` (prompt requires states), `tests/orchestration/test_run_pipeline.py`
(vertical issues downgrade final_status and populate hard_failures; no issues leaves it
untouched), plus fixture updates across every shorts test file for the new duration/word
bounds. Full suite: **1065 passed, 16 deselected** (up from 1052).

**Not yet live-verified**: no fresh run was launched to confirm the 120s cap actually relieves
the recurring failure categories, or that a real short's `visual.states` gets populated now.

---

## ERR-069 — Shorts never ran check_grounding_policy/check_numeric_fidelity at all (a real, undocumented gap vs. long-form)

**Date:** 2026-09-16 · **Severity:** major (a whole class of factual-safety check was
silently absent for every short ever generated) · **Status:** fixed · **Component:**
`orchestration/shorts_pipeline.py`

**Where:** a further review round, specifically looking for anything in the shorts pipeline
never yet investigated. `orchestration/pipeline.py`'s own `_run_review_block` (long-form) has
always run `check_grounding_policy` (catches a sentence marked `grounding_required=True` with
no `grounding_refs` at all, or a claim narrated in violation of its own verification-status
policy) and `check_numeric_fidelity` (catches a narrated number that drifted from the claim it
cites, e.g. "256" spoken while the claim itself says "128") right after C2b's metadata repair.
`orchestration/shorts_pipeline.py::run_short()` never called either -- confirmed by reading
`verification/hard/shorts.py`'s own module docstring, which explicitly lists every long-form
gate deliberately switched off for shorts (forward-driver continuity, payoff-gap valleys, the
mid-video cold viewer, the CTA window, the >=1500-word gate) -- these two were never in that
list, meaning this was an oversight, not a documented scope decision.

**Fix:** `_run_review()` (the shared review helper used both for the initial pass and the
post-rewrite re-review) now also calls both checks and returns the resulting
`GroundingViolation`s alongside the existing critique issues; `_format_hard_failures()` folds
them into `hard_failures` the same way long-form's `aggregate_review()` does
(`f"{code} ({scene_id}): {detail}"`). Deliberately NOT yet fed into the Phase 20 targeted-
rewrite mechanism (`GroundingViolation` has no `severity`/`scene_ids` of its own the way
`CritiqueIssue` does) -- extend that once a live run actually shows one of these firing on a
real short, not ahead of that evidence.

**Tests:** `tests/orchestration/test_shorts_pipeline.py` -- a sentence marked FACTUAL with no
`grounding_refs` at all is now a hard failure (`ungrounded_factual_sentence`); a sentence
citing a claim but stating a different number than the claim's own is now a hard failure
(`numeric_drift`). Full suite: **1067 passed, 16 deselected** (up from 1065).

**Not yet live-verified**: no fresh run has confirmed how often either check actually fires on
real shorts content -- both are legitimate correctness gates, and cited claims are already
scoped to the parent's own `allowed_fact_ids` (mostly VERIFIED by the time they reach a
short), so a flood of new failures isn't expected, but this is not yet confirmed live.

---

## ERR-070 — Three more shorts bugs found on a dedicated 3-round static review, requested specifically to gate whether another live run was warranted

**Date:** 2026-09-16 · **Severity:** major (one silently defeated the documented cold-hook
"never a hard gate" design; one silently made every pre-TTS duration estimate ~28% optimistic
all session; one was the exact same silent-drop class of bug already fixed once elsewhere) ·
**Status:** fixed · **Component:** `review/cold_hook_critic.py`,
`editing/short_targeted_rewrite.py`, `narration/short_generator.py`,
`verification/diagnostics/shorts.py`

**Where:** requested explicitly as 3 rounds of static review, one bug budgeted per round, with
the user's own stated condition that another live run should only follow if a round turned up
nothing. All three rounds found a real bug.

**Round 1 — `cold_hook_critic.py`'s Gemini escalation had no severity constraint.**
`_GEMINI_PROMPT` never told the model what severity to use, unlike every other critic in this
codebase, and nothing in code prevented a "critical" cold-hook finding from silently becoming a
hard gate (or, since Phase 20, a targeted-rewrite trigger) -- contradicting the documented
design that cold-hook is feedback, never a mechanical hard gate (plan §20.10). Fixed both ways:
strengthened the prompt to say `severity="major"` explicitly, AND forced it in code
(`[i.model_copy(update={"severity": "major"}) for i in gemini_result.issues]`) so a model that
ignores the prompt anyway still can't produce a "critical" cold-hook issue.

**Round 2 — two related bugs in `editing/short_targeted_rewrite.py`.** (a) Its prompt carried
zero word-budget context, unlike the original B1s generation prompt -- a live, real
contributor to the Phase 20 verification run's own finding that a rewrite could be "kept, not
worse" by hard-failure count yet still measure over the duration cap once real TTS ran, because
nothing ever told the rewrite it had a ceiling to respect. Fixed by adding `word_band` and
`untouched_neighbors_word_count` to both the prompt and the payload. (b) Investigating that fix
surfaced a deeper, pre-existing inconsistency: `PLANNING_WPM = 167` (long-form's own
assumption) was still being used in `narration/short_generator.py` and
`editing/short_targeted_rewrite.py` to compute `est_seconds`, even though `word_band` itself had
already been recalibrated against confirmed ~130wpm real edge-tts evidence
(`planning/shorts_models.py`'s own comment on `ShortNarration`). The cheap pre-TTS duration
estimate that both `check_duration_estimate` and this round's own rewrite decision lean on has
therefore been silently ~28% optimistic (167/130) the entire session, with real TTS being the
only thing that ever caught the gap. Fixed both occurrences to `PLANNING_WPM = 130`. A third
occurrence, in `verification/diagnostics/shorts.py`, was found to be entirely unused dead code
(never referenced) and was deleted rather than "fixed."

**Round 3 — `RewrittenSegment.segment` was an unconstrained `str`.** The exact same class of
bug already fixed once in `narration/short_generator.py::GeneratedSegment` (constraining it to
`Literal["hook", "setup", "mechanism", "payoff"]`, ERR-067) was never applied to
`editing/short_targeted_rewrite.py::RewrittenSegment`, built the following day. An invalid or
typo'd segment name would silently fail to match any real `scene_id` in
`rewritten_by_id.get(...)`, silently dropping the requested fix with the original, unfixed text
surviving byte-for-byte and no error anywhere -- exactly the failure mode a targeted rewrite
exists to prevent, happening invisibly inside the rewrite mechanism itself. Fixed with the same
`Literal` constraint.

**Tests:** one new test per bug --
`test_a_critical_severity_from_gemini_is_forced_down_to_major`
(`tests/review/test_cold_hook_critic.py`),
`test_an_invalid_segment_name_is_rejected_not_silently_dropped`,
`test_prompt_requires_staying_within_the_overall_word_band`, and
`test_word_band_and_neighbor_word_count_reach_the_payload`
(`tests/editing/test_short_targeted_rewrite.py`). Full suite: **1071 passed, 16 deselected**
(up from 1067).

**Not yet live-verified**: per the user's own explicit "confirm before another run" instruction
from earlier in this same investigative arc, no live run has followed these fixes yet -- and
per the user's own stated condition for this review ("if we don't find any more bugs then we
can do another run"), that condition was not met (all 3 rounds found a real bug), so a run was
deliberately not launched off the back of this round without checking back first.

**Follow-up round (same day):** given a choice between running immediately, another 3 rounds,
or one more focused round, the user chose one more round. It covered
`verification/hard/shorts.py` (duration-gate logic itself, confirmed it never had its own stale
WPM constant to begin with), `planning/shorts_models.py` (word_band/target_duration/130wpm
arithmetic cross-checked and consistent), `html_synth/vertical_assembler.py` (CSS custom
properties all resolve against real `design_system.yaml` tokens, no orphaned `var()`),
`review/short_critic.py` (bridge_mode/scene_ids handling matches the generator and rewrite
modules), and `voice/tts_preview.py` (verified against the installed `edge_tts` package's own
source that `Communicate`'s boundary mode defaults to `"SentenceBoundary"` and that the emitted
chunk `type` string matches exactly what this module checks for -- the one place a silent
"always measures ~0s, never trips the duration gate" failure could have hidden). Found no new
bug; full suite still **1071 passed, 16 deselected**, unchanged from the round above.

---

## ERR-071 — A short's own TTS degradation could silently force PASS_WARN with zero visible reason anywhere (found live, v08 verification run)

**Date:** 2026-09-16 · **Severity:** major (defeats the exact "a FAILed/downgraded short's own
reasons are still inspectable" guarantee `save_short_debug()`'s own module docstring commits
to, ERR-formatting precedent from 2026-09-15) · **Status:** fixed · **Component:**
`orchestration/shorts_pipeline.py`

**Where:** the v08 live verification run launched after ERR-070's fixes (`--resume` against the
same v01 checkpoint, 5 candidates). Short #2 came back `PASS_WARN` with `hard_failures: []` and
only two `major` (non-critical) critique issues -- `compute_final_status` (`policy_gate.py`)
never looks at critique issues at all, only `hard_failures` and diagnostic RED/AMBER bands, and
short #2's one diagnostic band (`setup_length` AMBER, 18.9s) is within the default
`pass_amber_allowance=3`, which computes to a plain `PASS`. Yet the persisted status was
`PASS_WARN` -- the only mechanism in `run_short()` that can move a computed `PASS` to
`PASS_WARN` is `apply_editorial_downgrade(status, "PASS_WARN")`, gated on
`degraded_capabilities` being non-empty. Cross-checked against short #4 in the same run (which
DID get a real TTS measurement, confirmed by its own `"TTS preview: measured 87.9s"` log line)
to rule out a diagnostics-driven explanation instead. Conclusion: TTS synthesis genuinely failed
for short #2 (real edge-tts flakiness, most likely), correctly forced the safety-conscious
downgrade (never PASS a short whose real duration was never measured) -- but the reason was
completely invisible: `run_short()`'s two `except` branches around the TTS call only appended to
`degraded_capabilities`, never to `log`, and `save_short_debug()`'s status.json write (added
2026-09-15 specifically so a short's own reasons survive the process exiting) never included the
`degraded_capabilities` field in the first place. Someone reading short #2's real status.json
after the run had no way to learn that its own real spoken duration was never actually measured.

**Fix:** both `except` branches in `run_short()` now also `log.append(...)` the same reason
already recorded in `degraded_capabilities` (`"TTS preview: degraded (edge-tts not installed)"`
/ `"TTS preview: degraded (synthesis failed: {e})"`); `save_short_debug()`'s status.json write
now includes `"degraded_capabilities": result.degraded_capabilities` alongside the other
always-written fields.

**Tests:** extended `test_a_tts_synthesis_failure_degrades_visibly_and_falls_back_to_the_estimate`
to assert the failure reason reaches `result.log`, and
`test_save_short_debug_writes_status_regardless_of_pass_or_fail` to assert
`degraded_capabilities` round-trips through the persisted JSON. Full suite: **1071 passed, 16
deselected** (same count -- both were new assertions on existing tests, not new test functions).

**Live re-verification of the shorts pipeline itself (not just this fix), from the same v08
run:** 3 of 5 shorts landed `PASS_WARN` (up from Phase 20's own 2/5), 2 `FAIL`. The bounded
revision cycle (Phase 20) worked exactly as designed on all three shorts it fired for -- kept a
rewrite that took short #3 from 2 hard failures/4 issues to 0/1 (a clean PASS_WARN), reverted a
rewrite on short #5 that would have made things worse (4 -> 5 hard failures), and kept a
rewrite on short #1 that was real, measured progress (3 -> 2 hard failures) without being
enough to clear FAIL. No duration-cap overruns anywhere in this run (measured 87.9-102.0s, all
comfortably under the 120s cap) -- direct confirmation that ERR-070's word-budget-aware rewrite
fix closed the exact gap that caused one. Short #5's FAIL is `check_grounding_policy` (ERR-069)
firing for the first time on a real run: two sentences made unsupported technical claims not in
the claim registry -- the check working as intended, not a pipeline bug. Short #1's FAIL is a
genuine micro_arc mismatch (declared `contradiction_resolution`, actually enacted
`problem_fix`) -- a real story-planning judgment-quality miss from A2s/SC, not yet investigated
further.

---

## ERR-072 — Shorts read as "just a few sentences" (visual-density gap) and 5/5 landed goal=DISCOVERY/bridge=NONE (both user-reported, v08 run)

**Date:** 2026-09-16 · **Severity:** major (works directly against a short's stated purpose --
"should help me get more subscribers" -- even though neither is a hard-failure-level defect) ·
**Status:** fixed · **Component:** `html_synth/vertical_assembler.py`, `planning/short_planner.py`

**Where:** the user opened all 5 real `short.html` files from the v08 run directly and reported
they looked incomplete, "just a few sentences." Direct inspection of `narration.json` for all 5
showed the underlying scripts were NOT thin (176-209 words each, ~90-100s measured, a complete
hook/setup/mechanism/payoff arc) -- the actual cause was the RENDERED layout: each segment drew
as one merged `<p>` paragraph, vertically centered in a full 1080x1920 screen. A hook's ~40
words at 58px font fills roughly 300-400px of a 1920px screen -- 75-85% blank -- and only
`mechanism` ever got any visual (the existing flow diagram); `hook`/`setup`/`payoff` were bare
centered text the whole time, with no visual change for the entire length of a segment (short
#2's mechanism: 47.5s of continuous narration against one unchanging static screen). Separately,
checking `plan.json` for all 5 shorts in the same run found `goal=DISCOVERY` and
`bridge.mode=NONE` in all 5 of 5 -- not one of them gave a viewer a follow-up ask or pointed back
to the parent video, directly undercutting the user's stated goal for these shorts.

**Fix:**
1. `html_synth/vertical_assembler.py`: each sentence now renders as its own visually distinct
   "beat" (`_render_beats`) -- a colored bar sized to that sentence's own share of the segment's
   total words (a real pacing cue, not decoration), above its own text block, with a short
   staggered fade-in on load. A `~Ns` duration badge (from the segment's already-computed
   `est_seconds` -- no new LLM call, no new data) now sits next to each screen's label. Rendered
   short #2 through Playwright before/after: the mechanism screen went from one flat paragraph to
   a diagram plus 5 distinct beats filling most of the frame.
2. `planning/short_planner.py`'s A2s `TASK_PROMPT`: the `goal` bullet now names the live
   100%-DISCOVERY evidence directly and asks the model to honestly check whether a candidate's
   own payoff already gestures at a bigger question or a next piece before defaulting to
   DISCOVERY. The `bridge` bullet now explicitly names NONE-for-every-short-in-a-batch as its own
   bias (mirroring the existing, still-correct "don't force a bridge that weakens the ending"
   principle) and encourages a single <=8-word SPOKEN/ONSCREEN follow line whenever the payoff
   genuinely supports it -- plan §20.1 already allows subscribe to be "earned... only after
   value" here; nothing forced it, so nothing had ever pointed the model at using it.

**Tests:** `tests/html_synth/test_vertical_assembler.py` (3 new -- each sentence renders as its
own beat rather than one merged paragraph; a beat's bar width reflects its own real share of the
segment's words; each screen shows its own estimated duration), `tests/planning/test_short_planner.py`
(2 new -- the 100%-DISCOVERY evidence and "two of three growth levers" framing reach the prompt;
the follow-line encouragement and its 8-word cap reach the prompt). Full suite: **1076 passed, 16
deselected** (up from 1071).

**Not yet live-verified**: no run has followed these fixes yet. The prompt change in particular
is a judgment nudge, not a hard rule -- the next `--resume` run is the natural way to confirm it
actually produces goal/bridge variety across a real batch rather than just reading as a
plausible prompt edit.

---

## ERR-073 — 3 rounds of review requested specifically to find bugs preventing good shorts scripts; found one signal-loss bug per round

**Date:** 2026-09-16 · **Severity:** major (all three directly undercut the same
subscriber-growth goal ERR-072 was fixed for, one of them completely -- not narration-quality
bugs in the usual "the model wrote something wrong" sense, but pipeline-plumbing bugs where a
real, already-computed signal or field never reached the place that needed it) · **Status:**
fixed · **Component:** `planning/short_planner.py`, `planning/candidate_finder.py`,
`planning/shorts_models.py`, `html_synth/vertical_assembler.py`, `verification/diagnostics/shorts.py`

**Round 1 — `ShortsCandidate.bridge_question` was computed by SC and then silently discarded.**
`planning/candidate_finder.py`'s own SC prompt spends a real LLM call producing
`bridge_question` specifically described as "the larger question this candidate's payoff could
naturally open onto... for a BRIDGE-goal short later." That field reaches A2s only as raw JSON
in the candidate payload (`_candidate_payload(c) -> candidate.model_dump()`) -- A2s's own
`TASK_PROMPT` never named it once. The one upstream signal purpose-built to fix exactly the
100%-DISCOVERY bias ERR-072 documents was being computed and then thrown away. **Fix:** the
`goal` bullet in `short_planner.py`'s `TASK_PROMPT` now explicitly names `bridge_question` and
tells the model a non-empty one is a real, already-judged signal, not something to silently
ignore.

**Round 2 — SC's own `micro_arc_suggestion` had the same `problem_fix`-over-selection bias A2s's
prompt already had to be fixed for, one stage earlier.** A2s's prompt (fixed 2026-09-15, ERR-067)
already warns against defaulting to `problem_fix` for any problem-then-mechanism candidate
"(almost every candidate does)" -- but SC's own prompt, one stage upstream, produces
`micro_arc_suggestion` with zero such caution, and "A2s may override this" doesn't fully
neutralize the anchoring effect of a biased suggestion already sitting in context. **Fix:**
`planning/candidate_finder.py`'s `TASK_PROMPT` now carries the same caution SC's own downstream
consumer already needed, closing the anchoring loop at its source rather than only correcting it
one stage later.

**Round 3 — ONSCREEN/PLATFORM_LINK bridges rendered nothing anywhere; the biggest finding of the
three.** `narration/short_generator.py`'s own prompt has always told the model these two modes
mean "the bridge itself will render as on-screen text elsewhere, not spoken" -- correctly
withholding it from the spoken narration. But `ShortBridge` had no field to capture what that
on-screen text actually says, and `html_synth/vertical_assembler.py` never referenced
`plan.bridge` at all. A short assigned either mode shipped with its CTA correctly absent from
narration and never shown anywhere in its place -- a silent, total loss of the one thing those
two modes exist for, worse than picking NONE. This directly undercuts today's own ERR-072 fix,
which now actively encourages the model toward ONSCREEN as one of two good options alongside
SPOKEN -- without this fix, that encouragement would have made things worse, not better, every
time the model actually took it. **Fix:** added `ShortBridge.cta_text: str = ""` (A2s's own
authored short line, <=8 words, same convention as the SPOKEN case); `short_planner.py`'s
`TASK_PROMPT` now requires filling it in for ONSCREEN/PLATFORM_LINK; `vertical_assembler.py`
now renders it as a real on-screen badge on the payoff screen when present; a new advisory
diagnostic (`check_bridge_cta_present`, AMBER not a hard gate, mirrors the existing
`check_visual_states_present` pattern) flags an ONSCREEN/PLATFORM_LINK short that still shipped
with an empty `cta_text`.

**Tests:** `tests/planning/test_short_planner.py` (2 new -- `bridge_question` reaches the
prompt; `cta_text` is required for ONSCREEN/PLATFORM_LINK), `tests/planning/test_candidate_finder.py`
(1 new -- the `problem_fix` caution reaches SC's own prompt), `tests/html_synth/test_vertical_assembler.py`
(4 new -- `cta_text` renders on the payoff screen for ONSCREEN; SPOKEN renders no separate
badge; an empty `cta_text` renders nothing, not a crash; `cta_text` is HTML-escaped),
`tests/verification/diagnostics/test_shorts.py` (3 new -- NONE/SPOKEN never need `cta_text`;
ONSCREEN with an empty one is AMBER; PLATFORM_LINK with one filled in is GREEN). Full suite:
**1086 passed, 16 deselected** (up from 1076).

**Isolation check (user-requested):** confirmed none of today's shorts-pipeline changes touch
long-form. `html_synth/vertical_assembler.py` is imported only by shorts-specific code
(`verification/hard/vertical.py`, `verification/diagnostics/shorts.py`, the shorts branch of
`run_pipeline.py`); long-form's own HTML pipeline uses the separate `html_synth/synthesizer.py`.
`planning/short_planner.py`/`plan_shorts` is called only inside `run_pipeline.py`'s shorts
block; long-form planning lives entirely in `planning/story_planner.py`. The one file genuinely
shared between both (`html_synth/component_library.py`) has zero changes from this session's
shorts work. Long-form's own test suites (`test_synthesizer.py`, `test_html_repair_loop.py`,
`test_pipeline.py`, `test_story_planner.py`) all pass unchanged.

**Not yet live-verified**: no run has followed any of today's fixes yet (ERR-072's included).

---

## ERR-074 — 3 more rounds of review, requested to find bugs blocking good shorts scripts; found one real content-quality gap per round

**Date:** 2026-09-16 · **Severity:** major (Round 3 is a documented-vs-actual mismatch: a
module's own docstring claimed a gap was already closed when it wasn't) · **Status:** fixed ·
**Component:** `review/grounding_verifier.py`, `narration/short_generator.py`,
`narration/factual_invariants.py`

**Round 1 — C2b-sourced issues gave the shorts rewrite one vague, three-option instruction no
matter which specific problem actually fired.** `grounding_verdicts_to_issues()` set
`recommended_intent` to one fixed sentence ("ground this sentence in a real verified claim,
restore the dropped qualifier, or narrow the claim back to its real scope") regardless of
whether the real problem was `unsupported`, `qualifier_dropped`, or `scope_broadened`. Harmless
for long-form: `editing/revision_planner.py`'s A3 re-synthesizes its own plan from the full
issue (problem + recommended_intent + scene_ids) via its own LLM call, so a more specific
`recommended_intent` can only help it, never hurt it. But shorts' B2s
(`editing/short_targeted_rewrite.py`) has no such intermediate step -- its own docstring says
`recommended_intent` verbatim IS the plan -- so a vague three-option instruction there left the
rewrite genuinely not knowing which of the three to actually do. **Fix:** each of the three
paths (plus the free-text `violation_code` path) now gets its own specific, actionable
`recommended_intent`.

**Round 2 — `micro_payoffs` reached B1s as raw payload data with zero instructions on where it
belongs.** `narration/short_generator.py`'s payload has always included `plan.micro_payoffs`,
but the `TASK_PROMPT` text never mentioned it once -- no guidance on whether to weave it into
`mechanism` (as plan §20.4 intends: "an intermediate micro-payoff is allowed" during the
mechanism beat) or say nothing about it at all. A model given a list of "smaller payoffs" with
zero placement guidance could easily tack them onto the end after the central payoff -- exactly
the recap/reserved-outro failure shape this pipeline has repeatedly had to fight (the entire
motivation for Phase 20's bounded rewrite cycle). **Fix:** the `mechanism` bullet now explicitly
says to weave `micro_payoffs` in there, as intermediate wins, never saved up for the end.

**Round 3 — the shared factual-invariants fragment only delivers half of what its own docstring
claims.** `narration/factual_invariants.py`'s module docstring says the shared
`NARRATION_FACTUAL_INVARIANTS` fragment gives B2 and the shorts narrator "equivalent language"
to long-form B1's own "detailed hedge/verification-status rules" -- but the actual fragment only
ever ported HALF of B1's rules: the "never upgrade a claim's certainty" (overclaim) direction.
B1's other, equally important rule -- "never hedge a verified technical claim with 'is believed
to' / 'is thought to' / 'seems to'" -- was never carried over at all, despite the docstring's own
claim that it was. This is the exact wishy-washy, underclaiming prose that works directly
against the punchy, confident delivery a short needs, and nothing in B2 or the shorts narrator's
own prompts guarded against it. **Fix:** added the missing hedge-on-a-verified-claim rule to
the shared fragment, and corrected the module's own docstring to describe what was actually
missing and now fixed.

**Tests:** `tests/review/test_grounding_verifier.py` (1 new -- all three violation-type
`recommended_intent`s are distinct and specific, none is the old generic catch-all),
`tests/narration/test_short_generator.py` (1 new -- `micro_payoffs` placement guidance reaches
the prompt), `tests/narration/test_factual_invariants.py` (new file, 2 tests -- both the
overclaim and the hedge directions are covered). Full suite: **1090 passed, 16 deselected** (up
from 1086).

**Isolation:** `grounding_verifier.py` and `factual_invariants.py` are genuinely shared with
long-form (unlike ERR-072/073's shorts-only files) -- confirmed both changes are safe there:
the `recommended_intent` change only ever helps long-form's A3 (which re-synthesizes its own
plan regardless of the exact wording it's given), and the added hedge rule is purely additive
guidance matching what long-form's own B1 already enforces separately. Full suite green,
including `tests/editing/test_targeted_rewrite.py` and `tests/narration/test_generator.py`
(long-form's own B1/B2 tests), unchanged.

**Not yet live-verified**: no run has followed any of today's fixes yet (ERR-072/073 included).

---

## ERR-075 — `check_grounding_policy`'s "UNVERIFIED never in the hook/ending" rule was silently disabled everywhere, not just for shorts

**Date:** 2026-09-16 · **Severity:** major (a named, documented, unit-tested policy rule that
has never actually fired once in the entire pipeline's real history, on either format) ·
**Status:** fixed for shorts, confirmed but NOT fixed for long-form (see below) · **Component:**
`orchestration/shorts_pipeline.py`

**Where:** requested as one more thorough review round. `verification/hard/grounding.py`'s own
module docstring states the real policy: "`always -> REJECTED is never narrated; UNVERIFIED
never in the hook / central insight / a payoff / the ending / an important numeric result`" --
and `check_grounding_policy(narration, claims, hook_scene_ids=None, ending_scene_ids=None)`
genuinely implements the hook/ending half of that as real, working, unit-tested logic
(`tests/verification/hard/test_grounding.py` exercises it directly and it works correctly).
But EVERY call site in the entire codebase calls it with those two params left at their empty
defaults: `orchestration/shorts_pipeline.py`'s own `_run_review()` (wired in only hours earlier,
ERR-069), AND both of long-form's own call sites in `orchestration/pipeline.py`. An
OPTIONAL-importance UNVERIFIED claim with a hedge is otherwise legitimately narratable
(`_claim_allows_narration`'s own OPTIONAL+hedge exception) -- but the policy explicitly says
never in the hook or the ending regardless, and nothing has ever enforced that, on any video,
in this pipeline's history.

**Fix (shorts only):** `orchestration/shorts_pipeline.py`'s `_run_review()` now calls
`check_grounding_policy(narration, scoped_claims, hook_scene_ids={"hook"},
ending_scene_ids={"payoff"})` -- unambiguous and free for shorts, since a short's segments are
always exactly these four fixed ids, unlike long-form's dynamic beat/scene ids.

**Deliberately NOT fixed for long-form in this pass:** the same gap is real at both of
`orchestration/pipeline.py`'s call sites, but identifying "the hook scene(s)" and "the ending
scene(s)" for a long-form video requires real lookup logic against `StoryBeat`/`ScenePlan`
(there's a `first_beat_id`-based pattern already used for `_hook_context()` that could inform
this, but getting the ending scene(s) right needs its own care) -- a bigger, separate change
better done as its own reviewed pass with its own live verification, not folded into a
shorts-focused review. Flagged as an open item below rather than guessed at here.

**Deeper, still-open gap, not fixed:** the module's own docstring names FIVE protected
locations (hook, central insight, a payoff, the ending, an important numeric result) but
`check_grounding_policy`'s actual signature only ever had parameters for two of them (hook,
ending) -- "central insight" and "important numeric result" have no corresponding parameter or
enforcement anywhere, and never did. Also an open item below.

**Tests:** `tests/orchestration/test_shorts_pipeline.py` (1 new -- an UNVERIFIED+OPTIONAL claim
with a hedge in the hook segment, which `_claim_allows_narration` alone would permit, is now a
hard failure via `unverified_in_hook_or_ending`). Full suite: **1091 passed, 16 deselected**
(up from 1090).

**Not yet live-verified**: no run has followed this fix yet.

---

## ERR-076 — Long-form video: `check_grounding_policy`'s "UNVERIFIED never in the hook/ending" rule is still unenforced (confirmed in ERR-075, not yet fixed for this format)

**Date:** 2026-09-16 · **Severity:** major (same real gap as ERR-075, on the format that
actually ships as the primary video, not the derived shorts) · **Status:** OPEN, not fixed ·
**Component:** `orchestration/pipeline.py`

**Where:** `verification/hard/grounding.py::check_grounding_policy(narration, claims,
hook_scene_ids=None, ending_scene_ids=None)` correctly implements "an UNVERIFIED claim must
never be narrated in the hook or the ending, even one that would otherwise be legitimately
narratable with a hedge" -- real, working, unit-tested logic
(`tests/verification/hard/test_grounding.py`). ERR-075 fixed this for shorts (an unambiguous
one-line change, since a short's segments are always exactly `hook`/`setup`/`mechanism`/
`payoff`) but found the identical gap at BOTH of `orchestration/pipeline.py`'s own call sites
for long-form:
- `_run_review_block()`'s own `grounding_violations = check_grounding_policy(narration,
  claims) + check_numeric_fidelity(narration, claims)`
- the post-REVISE branch's own `grounding_violations = check_grounding_policy(narration,
  claims)` (used to build the `RevisionPlan` via A3)

Neither passes `hook_scene_ids`/`ending_scene_ids`, so an UNVERIFIED-but-hedged claim can
legitimately land in a long-form video's own hook or ending today, with nothing catching it --
the exact placement plan §9's Factual gate exists to forbid.

**Why not fixed alongside ERR-075:** unlike a short's fixed four segment ids, long-form's
scene ids are dynamic per video. This module already has the right building block, though:
`_hook_context()` (same file, `orchestration/pipeline.py`) computes `hook_scene_ids` exactly
this way -- `{s.scene_id for s in plan.scene_plan if s.beat_id == plan.beats[0].beat_id}` --
on the reasoning that "the first-positioned beat IS the opening by construction" (matches
`verification/diagnostics/pacing.py`'s own first-beat fallback). The symmetric case for
`ending_scene_ids` is plausibly `plan.beats[-1].beat_id` (the last-positioned beat is the
ending by the same construction argument) -- but this hasn't been verified against a real
`StoryPlan`/`ScenePlan` (e.g. whether a CTA-only trailing beat should count as "the ending" for
this rule's purposes, or whether the actual payoff beat sits one before it), so it's proposed
here as the likely shape of the fix, not implemented.

**Fix (not yet applied):** thread real `hook_scene_ids`/`ending_scene_ids` (likely via a small
shared helper next to `_hook_context()`) into both call sites above, mirroring ERR-075's shorts
fix exactly once the ending-beat identification is confirmed correct against real long-form
plans.

**Tests:** none yet -- no code changed for long-form in this entry, logged for tracking only,
per explicit request to keep this as its own reviewed, live-verified pass rather than bundled
into a shorts-focused session.

---

## ERR-077 — Grounding-policy hard failures never reached the shorts targeted-rewrite mechanism at all (found live, v10 verification run)

**Date:** 2026-09-16 · **Severity:** major (a FAILed short with a real, nameable defect had
zero chance of being fixed by the one mechanism that exists to fix it) · **Status:** fixed ·
**Component:** `orchestration/shorts_pipeline.py`

**Where:** the v10 live verification run (`--resume` against the v01 checkpoint, after
ERR-072 through ERR-076). Short #1 FAILed with 4 `ungrounded_factual_sentence` hard failures
(2 in `hook`, 1 each in `setup`/`mechanism`) but `revisions_used: 0` -- the bounded
targeted-rewrite cycle (Phase 20) never even attempted a fix. Root cause: `_run_review()`
computed `check_grounding_policy`/`check_numeric_fidelity`'s `GroundingViolation`s (a plain
dataclass: `scene_id`, `sentence_index`, `code`, `detail` -- no `severity`, no `scene_ids`
list) and returned them as a THIRD, separate value alongside `critique_issues`, formatted
directly into `hard_failures` by `_format_hard_failures`. But `run_short()`'s rewrite trigger
(`critical_issues = [i for i in critique_issues if i.severity == "critical"]`) only ever
looks at `critique_issues` -- `GroundingViolation`s, never being `CritiqueIssue`s, could never
appear there, no matter how many piled up. This exact gap was already named in this module's
own docstring history (ERR-069, ERR-075): *"Deliberately NOT yet fed into the Phase 20
targeted-rewrite mechanism... extend that once a live run actually shows one of these firing
on a real short, not ahead of that evidence."* v10 is that evidence.

**Fix:** added `_grounding_violation_to_issue()`, converting each `GroundingViolation` into a
real `CritiqueIssue` (`severity="critical"`, `scene_ids=[v.scene_id]`, a per-code
`recommended_intent` -- `ungrounded_factual_sentence`/`grounding_ref_unknown_claim`/
`unverified_in_hook_or_ending`/`numeric_drift` each get their own specific actionable
instruction; `grounding_policy_violation` reuses its own already-specific `detail` text rather
than a second static sentence, matching ERR-074's own "give the rewrite something concrete"
principle). `_run_review()` now folds these into the single `critique_issues` list it returns
(matching its own type hint, `tuple[list[SceneNarration], list[CritiqueIssue]]`, for the first
time -- it previously returned a 3-tuple despite the 2-tuple hint). `_format_hard_failures()`
no longer takes a separate `grounding_violations` parameter, since these defects now reach
`hard_failures` via the existing critical-severity `critique_issues` path instead of a
redundant, now-removed direct-formatting line.

**Tests:** `tests/orchestration/test_shorts_pipeline.py` -- the 4 existing grounding-hard-failure
tests (`test_grounding_scope_violation_is_a_hard_failure`,
`test_an_ungrounded_factual_sentence_is_a_hard_failure`,
`test_a_drifted_number_against_the_cited_claim_is_a_hard_failure`,
`test_an_unverified_claim_in_the_hook_is_a_hard_failure_even_with_a_hedge`) now correctly
trigger a real rewrite cycle (previously impossible) -- updated with a no-op rewrite response
and doubled CM entries for the resulting re-review, plus one new assertion
(`result.revisions_used == 1`) directly proving the fix. `make_agents()`'s own defaults for
C2b/C1s/C4s-escalation were also doubled (matching the existing `ColdHookVerdict` x2
precedent) since any grounding violation now triggers a real second `_run_review()` pass, even
in tests that never touch grounding directly. Full suite: **1092 passed, 16 deselected**
(same count as before -- fixes to existing tests, no new test functions needed since the new
assertion was added to an existing test).

**Not yet live-verified**: no run has followed this fix yet.

---

## ERR-078 — A call that exceeded the budget hard cap vanished from usage.jsonl entirely (found live, Phase 17 interrupt-and-resume verification)

**Date:** 2026-09-16 · **Severity:** major (the single most expensive call in a crashed run was
silently missing from its own cost audit trail -- directly undermines the accuracy Phase 17's
own resume feature and Phase 18's own budget hardening both depend on) · **Status:** fixed ·
**Component:** `llm/client.py`

**Where:** live-verifying Phase 17.1 (deliberately interrupting a real run via a tight
`--loop-budget-usd`, then `--resume`-ing it). The first interrupt (`--loop-budget-usd 0.15`)
correctly raised `BudgetExceeded` with a real gpt-5.6-sol A2 call reported at $0.266102 -- but
`usage.jsonl` showed only the 3 calls before it, totaling $0.1656. Root cause:
`call_structured_paid()` called `budget.record_spend(result.billed_microusd)` (which raises
`BudgetExceeded` past the hard cap) BEFORE constructing and appending the `UsageRecord` to the
ledger -- so the exact call that crashed the run never reached `self.ledger.append(record)` at
all. The cost was real (billed by the provider) and briefly visible in the exception's own
message text, but nowhere else -- not in `usage.jsonl`, not in `PipelineState.loop_spent_microusd`
(which also never got the chance to persist it, since the crash is an uncaught exception, not a
graceful checkpoint-then-exit).

**Fix:** reordered `call_structured_paid()` to build and append the `UsageRecord` immediately
after the real API result is known, unconditionally, before `budget.record_spend()` gets a
chance to raise and lose it. A call that pushes spend over the cap still really happened and
really cost money; the ledger's job is to be the accurate record of that, not just of calls
that stayed under budget.

**Tests:** `tests/llm/test_client.py` (1 new -- a call configured to exceed a deliberately tiny
hard cap still appears in `ledger.read_all()` with its real `billed_microusd`, even though the
call itself raises `BudgetExceeded`). Full suite: **1093 passed, 16 deselected** (up from 1092).

**Live-verified the same day**: a second real interrupt (`--loop-budget-usd 2.0`, this time
crashing inside a C2b call at $2.050487 cumulative) confirmed the fix directly -- `usage.jsonl`'s
own total ($2.0505) now exactly matches the exception's own reported cumulative spend, unlike
the first crash where they diverged by the missing call's cost.

**Not fixed as part of this entry, deliberately out of scope**: `PipelineState.loop_spent_microusd`
still isn't updated on an uncaught mid-loop crash (only `usage.jsonl` is now accurate) -- a
resumed run's own budget bookkeeping still starts the loop's `BudgetCounter` at whatever the
last successful checkpoint recorded (0, if the crash happened before any stage-boundary
checkpoint), not the true amount spent on the failed attempt's own partial loop work. This is
the same gap Phase 17.2 (STORY_IMPROVEMENT_PLAN.md) already covers under "cycle-level
checkpoint inside the story+narration loop" -- the live-verify that surfaced this bug is also
the evidence informing that phase's own build-or-defer decision, not a reason to patch it here
ahead of that decision.

---

## ERR-079 — C2a claim verification never had a real evidence source; native Gemini web search wired in, one real "empty content" bug found in the smoke test itself

**Date:** 2026-09-16 · **Severity:** major (an entire verification tier -- the local/web
evidence broker -- has been non-functional on every real run in this project's history) ·
**Status:** fixed · **Component:** `llm/backends/litellm_backend.py`, `llm/client.py`,
`agents/base.py`, `facts/verify.py`

**Where:** while investigating why claim C040 ("self-attention without positional information
is permutation equivariant" -- `provenance_status=SOURCE_EXPLICIT`, `evidence=[]`) stayed
UNVERIFIED despite being a well-documented mathematical fact (STORY_IMPROVEMENT_PLAN.md
Phase 23's own open question). Traced the real cause: `facts/verify.py`'s evidence broker
tries `references_dir` first (confirmed empty -- `src/config/references/` has zero real
files) then an optional `web_backend` that `run_pipeline.py`'s CLI never actually passes
(`None` on every real invocation, confirmed by direct read). Checked whether either LLM
backend could do this natively instead: `llm/backends/claude_cli.py` passes a bare `--tools`
flag but also `--max-turns 1`, leaving no room for a real search round-trip -- not functional
as invoked. `llm/backends/litellm_backend.py` passed no `tools=` at all. But
`litellm.supports_web_search()` (confirmed by direct call) returns `True` for both Gemini
models this pipeline already uses (`gemini-3.1-pro-preview`, `gemini-3.6-flash`) -- the exact
model C2a's own `review_lead_strong` already runs on -- via a real, provider-hosted, single-
call tool (no multi-turn orchestration needed), schema confirmed by reading litellm's own
Gemini tool-transformation source: `tools=[{"googleSearch": {}}]`.

**Fix:** `LiteLLMBackend.call()` gained `enable_web_search: bool = False`, passing
`tools=[{"googleSearch": {}}]` when set; threaded up through `LLMClient.call_structured_paid()`
and `Agent.run()` (which raises `ValueError` if set on a subscription-lane agent, matching the
existing `images` guard, since Claude CLI's `--max-turns 1` makes it genuinely non-functional
there). `facts/verify.py`'s own first-pass C2a verdict call now sets it, with `TASK_PROMPT`
updated to tell the model it has a real search tool and should use it rather than guessing
from internal recall.

**Real bug found BY the live smoke test itself, before this ever reached the real pipeline:**
the first smoke-test run (`max_tokens=200`, an ad-hoc guess) came back with completely EMPTY
content -- 382 of 386 output tokens went to hidden reasoning. The exact same "reasoning eats
the whole token budget" failure mode already documented elsewhere in this project (ERR-021's
gpt-5.6-sol A2 bug) recurring here on Gemini's strong tier once search is added on top of
reasoning. Re-ran with the REAL production config (`max_tokens` left at the backend's actual
default of 4096, `reasoning_effort="low"` -- the exact value `gemini_review_strong` sets in
`config/models.yaml`) and it worked correctly: `2026-09-16.` came back for "what's today's
exact date" -- a question the model cannot answer from training data alone, real proof the
search actually happened, not a plausible-sounding guess. Cost: $0.0188 for that one call
(278 in / 357 out, 333 of which were reasoning) -- confirms the real, separate per-search
billing is small but real, as the plan anticipated.

**Tests:** `tests/llm/test_litellm_backend.py` (2 new mocked -- default sends no `tools` key,
`enable_web_search=True` sends the exact right schema; 1 new `@pytest.mark.integration` live
smoke test, not run by default), `tests/agents/test_base.py` (3 new -- forwards to the paid
backend only, defaults to `False`, a subscription-lane agent raises on `enable_web_search=True`
the same way it does for `images`), `tests/llm/test_client.py` (2 new -- reaches the paid
backend, defaults to `False`), `tests/facts/test_verify.py` (1 new -- the initial C2a verdict
call sets it). Full suite: **1122 passed, 17 deselected** (up from 1114).

**Not yet live-verified against the full pipeline**: the smoke test confirms the mechanism
works in isolation; a real C2a run against the actual source (checking whether C040 or an
equivalent claim actually moves from UNVERIFIED to VERIFIED with real evidence attached) is
still pending.

---

## ERR-080 — Shorts repeat the exact same template transition phrase ("the real fix is/works") across DIFFERENT shorts, in DIFFERENT runs

**Date:** 2026-09-16 · **Severity:** minor (a repetition tell, not a factual or structural
defect) · **Status:** fixed · **Component:** `narration/short_generator.py`

**Where:** while planning STORY_IMPROVEMENT_PLAN.md Phase 23's shorts-quality continuation,
read 6 real shorts across two separate runs (v08, v10). 4 of them -- all `problem_fix`
micro-arc -- use "the real fix is..." / "the real fix works..." as the transition into the
actual mechanism, verbatim or near-verbatim, across shorts about completely unrelated topics
(encoder-decoder attention, positional encoding, causal masking). This is a more damaging
version of the causal-connector/repeated-device tell already fixed earlier in this same phase
(which caps repetition only *within* one script) -- this repeats *across* a channel's own
output, which a real viewer who watches more than one short is more likely to notice than a
single video's internal repetition, and nothing in the prompt named this specific phrase as
something to avoid.

**Fix:** `short_generator.py`'s `problem_fix` arc-specific guidance now names "the real fix
is/works" directly as a phrase the model has been observed defaulting to, and instructs it to
vary the transition into the mechanism every time (naming the mechanism directly, stating what
changes, or asking what the fix would need to do) -- the same "name the specific confirmed
pattern" style already used for this file's jargon-hook and empty-hook fixes.

**Tests:** `tests/narration/test_short_generator.py::test_prompt_warns_against_the_real_fix_template_phrase`.

**Live-verified 2026-09-16** (`video-01-attention-phase23-verify/runs/v03`): confirmed fixed --
checked all 5 shorts produced in that run's mechanism transitions, zero instances of "the real
fix is/works." The same run's bridge/goal selection also showed partial movement (see Phase 23
section E): `goal` stayed 100% DISCOVERY, but `bridge.mode` moved off 100% NONE to 100% SPOKEN,
a real change from the two prior 0%-variation runs.

---

## ERR-081 — Native web search (ERR-079's own fix) silently dropped 21/80 claims from C2a verification via response truncation

**Date:** 2026-09-16 · **Severity:** major (defeats the exact fix ERR-079 shipped -- claims
came back UNVERIFIED again, now for a NEW reason) · **Status:** fixed · **Component:**
`facts/verify.py`

**Where:** live-verifying Phase 23 (`video-01-attention-phase23-verify/runs/v03`). C2a batches
claims 40 at a time (`DEFAULT_BATCH_SIZE`) to `gemini_review_strong`. ERR-079 enabled native
web search on this call, which makes each claim's verdict far more verbose (a real search plus
reasoning per claim, not just a judgement). Both real batch calls in this run came back at
`output_tokens=4092` -- 4 tokens short of `LiteLLMBackend`'s hardcoded `max_tokens=4096`
default -- truncating the JSON response before the model finished writing verdicts for the
tail of each batch. Confirmed via the claim registry directly: batch 1 (claims C001-C040) lost
its last 4 (C037-C040); batch 2 (C041-C080) lost its LAST 17 (C064-C080). **21 of 80 claims
(26%) got zero real verification**, silently falling back to `Claim`'s own pristine defaults
(`verification_status="UNVERIFIED"`, `evidence=[]`) -- indistinguishable, with no error and no
log line, from a claim the model genuinely couldn't verify. This directly explains most of that
run's 12 hard failures and made the run's true technical-grounding score unmeasurable.

**Fix:** `verify_claims_with_llm`'s two `review_lead.run()` calls (the initial verdict pass and
the evidence re-verify pass) now pass an explicit `max_tokens=12000`, mirroring
`openai_story_strong_gpt56`'s own precedent (`config/models.yaml`) that for a reasoning model
`max_tokens` is a combined ceiling over hidden reasoning + visible output, not just the visible
JSON -- confirmed the override chain already existed end to end
(`Agent.run()` → `LLMClient.call_structured_paid()` → `LiteLLMBackend.call()`), this was a
config gap at one call site, not a missing capability. Also added
`find_claims_with_no_verdict(claims)`: every arithmetic-resolved AND every LLM-resolved claim
(including a legitimate UNVERIFIED verdict) always gets at least one `VerificationEvidence`
attached, so a claim reaching the final registry with BOTH fields still at their untouched
defaults can only mean no verdict was ever recorded for it -- for whatever reason, not just
this specific 4096 ceiling. Wired into `run_pipeline.py` right after `_build_claim_registry`,
logging any dropped claim ids by name instead of silently degrading (same "measure and
surface" precedent as ERR-078's ledger-logging fix).

**Tests:** `tests/facts/test_verify.py` -- 2 new confirming both calls pass the raised
`max_tokens`, 4 new for `find_claims_with_no_verdict` (a dropped claim is found; a legitimate
UNVERIFIED verdict is not flagged; a verified claim is not flagged; empty input). Full suite:
**1157 passed, 17 deselected** (up from 1149).

**Not yet live-verified against the full pipeline**: needs one more live run (resumed from
`v03`'s own checkpoint, per this project's "resume, don't restart" cost discipline) to confirm
`usage.jsonl` shows no more dropped-claim warnings and the true grounding hard-failure count.

---

## ERR-082 — B1's narration call timed out at 300s, twice in a row, on the session's own final live-verify run

**Date:** 2026-09-17 · **Severity:** major (blocked the final live-verify run entirely, twice)
· **Status:** fixed · **Component:** `narration/generator.py`

**Where:** the Phase 26/27/28 final live-verify run (`video-01-attention-phase23-verify`).
`generate_narration` (B1) makes exactly ONE `claude -p` subscription-CLI call for the WHOLE
script's narration, by design (the module's own docstring: "batch, don't loop"). Both a fresh
run (`v06`) and its resume (`v07`, same source/topic, skipping only the already-checkpointed
claims/source_brief stages) hit the identical failure at the identical call site
(`narration/generator.py:195`): `llm.backends.claude_cli.ClaudeCliInvocationError: claude -p
timed out after 300s`, each time only after `claude_cli.py`'s own 3-attempt tenacity retry was
fully exhausted (so not a single transient blip -- 3 real attempts per run, 2 runs, 6 total
timeouts at the same 300s ceiling). Confirmed by direct traceback inspection this was B1
specifically, not A2/A2b (which succeeded both times before B1 failed).

**Fix:** raised B1's own `timeout_s` override from 300 to 600 in `generate_narration`'s
`narration_lead.run(...)` call -- a full-script one-shot narration generation is exactly the
"potentially large call" the existing test for this line already names, and 300s had real,
repeated (not speculative) evidence of being too tight for it. Left `short_generator.py`'s own
180s (a much smaller single-short output, never implicated) and every other call site
unchanged -- scoped to the one call site with real evidence, not a blanket timeout increase.

**Tests:** `tests/narration/test_generator.py::test_uses_a_longer_timeout_for_this_potentially_large_call`
updated to assert 600. Full suite: **1240 passed, 17 deselected** (unchanged count, one
assertion updated).

**Update 2026-09-18, partially re-verified live:** the 600s fix worked -- the resumed run's
B1 call succeeded on the next attempt (`v08`), progressing well past it (into `run_short`
territory) before hitting a DIFFERENT, unrelated failure (`claude -p failed (exit 1)`, empty
stderr -- already a known, previously-documented-as-transient CLI failure signature per
`claude_cli.py`'s own 2026-09-11 comment, not a new bug; resolved by resuming again with no
code change). The NEXT resume (`v09`) then got further still (full story+narration loop,
H/HV, SC, 2 shorts all completed) before hitting a THIRD, structurally identical timeout: `B2s`
(`editing/short_targeted_rewrite.py:175`) timed out at its own 120s ceiling, again only after
all 3 retries exhausted. Same root cause as the original finding, different call site --
raised this call's `timeout_s` from 120 to 300 too, matching long-form's own analogous B2
rewrite call (`editing/targeted_rewrite.py`), which already sits at 300s for the identical
reason. Test: `tests/editing/test_short_targeted_rewrite.py::test_uses_a_300s_timeout_matching_long_forms_own_analogous_rewrite_call`.
Full suite: **1241 passed, 17 deselected**. Each failed attempt from `v06`'s checkpoint
re-spends the loop's own real cost (~$1.77 for the story+narration loop alone, confirmed from
`v09`'s own log) since only `claims`/`source_brief` are checkpointed -- the loop/H/HV/shorts
sequence is not resumable mid-way, so a persistent timeout at any call site inside it forces a
full, real-money replay of everything after it on every retry. Still not fully clean end to
end; the next resume is the real test of whether both fixes together get a run all the way to
promotion.

---

## ERR-083 — `claude -p` subprocess survived a SIGTERM to the whole pipeline, hung 11.5 hours as an orphan

**Date:** 2026-09-25 · **Severity:** critical (a run can hang indefinitely with no error, no
timeout, and outlive the parent process entirely) · **Status:** fixed · **Component:**
`llm/backends/claude_cli.py`

**Where:** live-verifying Phase 29 (Opus 5.5 story_lead, `video-01-attention-opus55-lead`).
A resumed run's A2b (`SCENE_EXPANSION`) calls showed a real, growing pattern of slow
individual calls (some 27-37 minutes) before the run went completely silent -- no new
`usage.jsonl` entries for 11.5 hours, `ps` still showed the top-level python process alive
but at 0% CPU (blocked, not computing). Killing the recorded process tree (`kill` on the
python + `caffeinate` pids) did **not** end the hang: a `ps aux | grep strict-mcp-config`
afterward found a real orphaned `claude -p` subprocess still running, its payload matching
this exact A2 call, alive since the point it should have either completed or timed out.
Root cause: `_call_once` used plain `subprocess.run(cmd, ..., timeout=effective_timeout)` --
Python's implementation only kills the *immediate* child on timeout. The real `claude` CLI
spawns its own subagents/background workers (its own JSON envelope carries a
`subagent_stats` field), and if a detached grandchild inherits the stdout pipe's write end,
the immediate child dying doesn't close that file descriptor -- `communicate()` can then
hang waiting for EOF that never arrives, past the configured timeout, past every retry, and
past the parent process's own death (a plain `kill` on the parent doesn't touch an already-
detached grandchild either).

**Fix:** `_call_once` now runs the subprocess with `start_new_session=True` (its own process
group) via `subprocess.Popen` + manual `communicate(timeout=...)`, and on
`TimeoutExpired`, kills the **whole process group** (`os.killpg(os.getpgid(proc.pid),
signal.SIGKILL)`, tolerating `ProcessLookupError` if it's already gone) instead of relying
on `subprocess.run`'s single-process kill. This is a real fix for any hang of this shape,
not specific to Opus 5.5 or this one call site -- every subscription-lane call goes through
`_call_once`.

**Tests:** `tests/llm/test_claude_cli_backend.py` -- all 10 existing mocks (previously
patching `subprocess.run`) migrated to a `FakePopen`/`_patch_popen` helper matching the new
`Popen`+`communicate()` shape (this alone caught that several had silently stopped being
mocked at all -- the full suite took 68s instead of its normal ~5s while they fell through
to real, unmocked subprocess calls), plus 1 new test confirming the timeout path calls
`os.killpg` on the child's own process group, not just `proc.kill()`.

**A real, separate lesson worth keeping:** a test suite runtime regression (68s vs. ~5s) was
itself the first hard confirmation that several mocks had gone stale after a refactor --
worth treating unexplained suite slowdowns as a signal, not just noise, the next time a
subprocess-invocation shape changes.

---

## ERR-084 — H's freeform `component_data` dict crashed the whole page render twice live, in two different ways; a 3-round audit found and fixed 3 more of the same bug class

**Date:** 2026-09-27 · **Severity:** critical (either crash loses the entire run's spend
mid-pipeline, after every earlier paid stage already succeeded) · **Status:** fixed ·
**Component:** `html_synth/synthesizer.py`, `html_synth/component_library.py`,
`html_synth/assembler.py`, `editing/html_repair.py`, `editing/targeted_rewrite.py`

**Where:** live-verifying Phase 32's own fixes (Opus 5.5 story_lead, resumed run). Two
crashes hit back to back on the same run:
1. `apply_repairs`'s `beat_visual_by_id[b.beat_id] for b in plan.beats` raised
   `KeyError: 'B1_hook'`. Root cause: `synthesize_beat_visual`'s payload never actually
   sends `beat.beat_id` to the model at all, yet `BeatVisual`'s schema requires the model
   to invent one from context -- this had silently worked on every prior run that never
   needed a repair pass (the repair path itself was accidentally safe, keyed by the
   caller's own known-good id, not the model's echoed one).
2. Once fixed and re-run past that point, `component_library.py::render_component`'s
   `solution_grid` branch raised `KeyError: 'name'` -- Phase 32's own P1 fix (the prompt
   nudge away from `diagram_card`'s monopoly) worked exactly as intended and got the model
   to use `solution_grid` for the first time in any live run, and one returned item simply
   omitted "name", which every *sibling* field on the same item (`body`) already degraded
   gracefully for via `.get()`.

**Fix (first pass):** forced `beat_id` from the input on the returned `BeatVisual` in both
`synthesizer.py::synthesize_beat_visual` and `editing/html_repair.py::repair_beat_visual`
(never trust the model's own echo of a value it was never even given); switched
`solution_grid`'s (and, by the same pattern, `suspect_board`'s and `step_list`'s) item
lookups from `item["key"]` to `item.get("key", "")`.

**Follow-up: 3 rounds of review, specifically hunting the SAME bug class** (a field
Pydantic validates as "a dict"/"a string" but not its keys/values, later code assumes has
a specific shape) before running anything else. 3 parallel audits (component rendering,
every LLM-filled freeform `dict` field codebase-wide, and unguarded lookups keyed by an
open `str` field) converged and found 3 more real instances, all fixed:
- `metric_table`'s `rows` iteration (`for cell in row`) crashed with `TypeError` on a
  scalar row, and silently rendered a dict row's KEYS instead of its values -- its item
  shape was documented only in a YAML comment, never sent to the model at all (unlike
  every sibling component). Now handles list/dict/scalar row shapes explicitly, and the
  prompt documents the expected flat-list shape.
- `assembler.py::_render_scene` called `render_component(scene.component_id, ...)` with no
  check that the model's freely-chosen `component_id` (`str | None`, not schema-restricted
  to the offered set) is actually a real component -- `render_component` itself
  intentionally raises `ValueError` for an unknown id (a useful loud failure for a
  programmer typo in code, kept as-is and still tested), but that same strictness would
  crash the whole page on a model-hallucinated id. Now falls back to no component (the
  scene's prose still renders) the same way a genuinely blank `component_id` already did.
- `editing/targeted_rewrite.py::_hook_last_scene_id` (added by Phase 32 itself) found the
  hook beat by `archetype_role == "hook"` -- a plain, model-filled string, not a `Literal`
  -- instead of the safer, already-established positional convention
  `verification/diagnostics/pacing.py` uses for the exact same question (the FIRST beat is
  the hook, by construction). A beat that IS the hook but whose label the model tagged
  differently would have silently disabled the whole CTA/hook guardrail with no signal.

**Tests:** 7 new (`tests/html_synth/test_synthesizer.py`, `test_html_repair.py`,
`test_component_library.py` x4, `test_assembler.py`, `test_targeted_rewrite.py`).

**A real, separate lesson worth keeping:** the SECOND crash only became reachable BECAUSE
the first fix (and Phase 32's own diagram_card nudge) worked -- fixing a bug can unlock a
code path that was never live-exercised before and was hiding its own separate bug. Worth
treating "the fix worked, and something new broke" as a reason to keep auditing the same
class of defect nearby, not just move on once the one crash in front of you is silenced.

---

## ERR-085 — Independent diff review (pre-commit) found 4 more real bugs across this session's own uncommitted changes

**Date:** 2026-09-27 · **Severity:** mixed (one real cost/resume regression, one silent
budget-guardrail weakening, two low-impact hygiene gaps) · **Status:** fixed ·
**Component:** `orchestration/run_pipeline.py`, `html_synth/synthesizer.py`,
`agents/base.py`, `llm/backends/claude_cli.py`

**Where:** before committing this session's accumulated changes, 3 parallel independent
code reviews (not looking for the ERR-084 crash class specifically -- a general
correctness pass over the whole diff) were run against `git diff` for every changed
area. Two came back clean; two found real, confirmed issues:

1. **`run_pipeline.py`'s no-verdict check raised BEFORE saving the checkpoint** (Phase
   30's own fix, ERR-081-adjacent): a claim registry with a confirmed, un-retryable
   verification hole correctly refuses to proceed, but the `raise` fired before
   `state.claim_registry`/`completed_stages`/`save_checkpoint` -- a run that hit this had
   NOTHING to `--resume` from, forcing a full re-pay of claim extraction + every
   verification retry from scratch. **Fix:** save the checkpoint first, then raise;
   the resume branch now re-runs the same no-verdict check against the loaded claims too
   (so persisting the checkpoint can't silently reintroduce the exact bug this check
   exists to prevent).
2. **`synthesizer.py::_screen_text_word_budget_by_beat`'s 20-word floor wasn't charged
   against the running total**: `allocations[bid] = max(words, 20)` but
   `allocated_so_far += words` (the UNCLAMPED value) -- whenever a non-last beat's
   proportional share rounded below the floor, the shortfall silently let the last
   beat's "absorb the remainder" share push the SUM past `_SCREEN_TEXT_TARGET_WORDS`,
   undermining the exact guardrail this function exists to provide (bounding H's total
   screen text, added after a real run overflowed `render.py`'s verified word ceiling).
   Verified by hand: a 4-beat plan (150/1/1/150 scenes) summed to 2622 before the fix,
   exactly 2600 after. **Fix:** `allocated_so_far` now accumulates the clamped value.
3. **`default_max_tokens` was dead on the subscription lane**: threaded through `Agent`
   construction from config, but `call_structured_subscription`/the Claude CLI backend
   never forwards it anywhere -- confirmed against `claude -p --help`, the CLI has no
   output-token-limiting flag at all (only `--autocompact` for context-window compaction
   and `--max-budget-usd` for cost). Currently harmless (no `subscription_lane` alias in
   `config/models.yaml` sets it), but silently doing nothing is worse than failing loudly
   the moment it's ever configured. **Fix:** `Agent.run()`'s subscription branch now
   raises `ValueError` for a non-`None` `max_tokens` (from either an explicit argument or
   `default_max_tokens`), matching the existing `images`/`enable_web_search`
   fail-loud-not-silently-drop precedent on the same lane.
4. **Minor FD leak on the subprocess timeout path** (`claude_cli.py`, the ERR-083 fix's
   own code): `os.killpg(...)` + `proc.wait()` on `TimeoutExpired` never closed
   `proc.stdout`/`proc.stderr` (the PIPE file objects) -- only `communicate()` completing
   normally, or an explicit close, does that. Each timeout leaked 2 open FDs; with
   retries across a full run's many calls, repeated timeouts could accumulate them.
   **Fix:** explicit `proc.stdout.close()`/`proc.stderr.close()` added to the except
   branch.

**Tests:** 6 new (`test_run_pipeline.py` x2, `test_synthesizer.py`, `test_base.py` x2,
`test_claude_cli_backend.py`, which also needed its `FakePopen` stand-in extended with
closeable `stdout`/`stderr` attributes to even exercise finding #4's fix).

**A real, separate lesson worth keeping:** none of these 4 were found by the earlier,
narrowly-scoped ERR-084 audit (which specifically hunted "unsafe access to LLM-generated
freeform data") -- a SEPARATE, general correctness review of the same diff, not looking
for that one bug class, caught a genuinely different set of issues. A narrow audit
answers the question it was scoped to ask; it doesn't substitute for a broader review
before committing a large accumulated diff.

---

## Open items (not yet bugs, flagged for future attention)

- **`check_grounding_policy`'s docstring names 5 protected locations, the function only
  ever implemented 2** (see ERR-075) -- "UNVERIFIED never in... central insight... an
  important numeric result" has no corresponding parameter or enforcement anywhere in the
  function, for either format. Needs a real design pass on how to identify "the central
  insight sentence(s)" or "an important numeric result" mechanically before this can be
  implemented, not a quick parameter addition.
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
- **Only CM/C2b's batch loops were parallelized (ERR-066), not the cold/continuing-viewer
  cascade (C4a-d)** — that cascade is Haiku-CLI-subprocess-based, not paid-API/HTTP, and this
  session's own earlier latency investigation found real subprocess contention when two full
  pipelines ran in parallel; parallelizing a local subprocess cascade carries more contention
  risk than parallelizing HTTP calls, so it was deliberately left sequential pending evidence
  CM/C2b's fix alone isn't enough. `MAX_STORY_REPLANS=2` (raised from 1, ERR-066) is still a
  finite bound, not a guarantee — a systematically bad A2 could in principle exhaust it again;
  no live evidence yet that 2 is insufficient.
