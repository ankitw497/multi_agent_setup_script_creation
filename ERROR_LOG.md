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
**Date:** 2026-09-10 · **Severity:** open finding, not a code bug (yet) · **Status:** open · **Component:** `planning/story_planner.py` (A2)

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

## Open items (not yet bugs, flagged for future attention)

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
- **C5/voice diagnostics are provisional** (see `verification/diagnostics/voice.py`) —
  real bands need a fitted corpus, deferred to V1D. C5 is gated on the provisional
  heuristic in the meantime, which is deliberately capped at AMBER (never RED) so an
  unfitted signal can't force a real revision cycle on its own.
- **`delete_or_compress` has no delete semantics in V1A** (see `editing/targeted_rewrite.py`'s
  own docstring) — it's always executed as a scoped compress-rewrite, never an actual
  removal from `plan.scene_plan`, to avoid leaving the plan's own word-budget target
  inconsistent with what was actually narrated.
