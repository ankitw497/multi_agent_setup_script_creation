# Build Plan — phase-wise task tracker

This is the "what's actually built" tracker. `IMPLEMENTATION_PLAN.md` is the
frozen design (v3.2) and does not track progress — this file does, and gets
its checkboxes updated as work lands. Section refs (`§N`) point into
`IMPLEMENTATION_PLAN.md` unless marked "guide §N" (`SYSTEM_DESIGN_GUIDE.md`).
Every real bug found while building this (not just design notes) is logged
in full in `ERROR_LOG.md` — this file only summarizes them inline.

Legend: `[x]` done · `[~]` partial/in progress · `[ ]` not started.

---

## Phase 0 — Infrastructure (plan §3–4; "precedes V1A")

- [x] Project scaffold — `pyproject.toml`, `requirements.txt`, `README.md`, `.env.example`, `.gitignore`
- [x] `llm/usage.py` — `UsageRecord`, `UsageLedger`, reconciliation invariant (13 tests)
- [x] `llm/budget.py` — `BudgetTier`, `BudgetCounter`, target/warning/hard-cap policy (9 tests)
- [x] `llm/backends/litellm_backend.py` — paid lane, public cost interface only, never `_hidden_params` (2 mocked tests + 1 gated integration test)
- [x] `llm/backends/claude_cli.py` — subscription lane, stripped-flag recipe, **key-leak test**, model-mismatch guard (8 mocked tests + 1 gated integration test)
- [x] `llm/structured.py` — validate → repair on Haiku ≤2 → fail loudly (8 tests)
- [x] `llm/client.py` — unified `call_structured_*()` wiring budget + backend + validation + ledger
- [x] `orchestration/cache.py` — central `cache_key()` policy (§4.2), `DiskCache` (9 tests)
- [x] `config/models.yaml`, `config/budget.yaml` — aliases + tiers, with verified/blocked status recorded per model
- [x] **API keys tested against real endpoints**: OpenAI **working** ($0.0000024 for a 12/1-token call); Gemini **blocked** — `403 API_KEY_SERVICE_BLOCKED` (action needed on your end: generate a key at aistudio.google.com/apikey, or enable the Generative Language API for the existing GCP project — not a code issue)
- [x] Live Haiku + live Sonnet smoke tests through the new backend, both passing end to end
- [ ] Direct unit test for `llm/client.py` (currently only exercised through its parts, not as a whole)
- [x] Re-run `test_live_gemini_smoke` once the Gemini key is fixed — **fixed, and two more real issues found in the process**

**Status: 54/54 unit tests passing** (`pytest`, 5 integration tests excluded by default; all 5 have now
been run and pass — OpenAI, Gemini flash, Gemini strong, Sonnet, Haiku, all live-verified end to end).

**Follow-up finding (same day, after the Gemini key was fixed on the Google Cloud side):** the key
started authenticating, but both pinned model ids from the original `models.yaml` (`gemini-1.5-flash`,
`gemini-1.5-pro`) turned out to be **fully retired** — Google's 404 responses named the exact
replacements each time (`gemini-3.6-flash`, `gemini-3.1-pro-preview`), found via one live
`ListModels` probe rather than guessing. A second issue surfaced immediately after: the new flash
model **reasons by default**, and a small `max_tokens` budget can be consumed almost entirely by
hidden reasoning tokens — one throwaway call spent 95 of 96 output tokens on reasoning and returned
empty `content` for $0.0003645. Fixed by adding `reasoning_effort` support to
`LiteLLMBackend.call()` (`"none"` for the cheap cascade tier, left unset for the strong tier where
reasoning is wanted) and by tracking `reasoning_tokens` separately on `CallResult` so this failure
mode is visible, not silent. Three regression tests added; `models.yaml` documents the ListModels
probe for next time a Gemini id 404s.

**A real bug was found and fixed while running the live tests** (exactly the kind of thing spending
real calls is for): a single `claude -p --model sonnet` call logs **two** entries in the envelope's
`modelUsage` — `claude-sonnet-5` (the actual answer) *and* an internal `claude-haiku-4-5-20251001`
entry (apparently a harness-internal sub-step, even in headless `-p` mode). The original parser took
`modelUsage`'s first dict key, which happened to be Haiku — so every Sonnet call would have silently
mis-attributed itself as a model-mismatch or, worse, as Haiku. Fixed: the resolved model is now
identified by matching token counts against the envelope's top-level `usage` block (§`_identify_resolved_model`
in `llm/backends/claude_cli.py`), which is unambiguous. Two regression tests lock this in
(`test_identifies_resolved_model_from_multi_model_envelope`,
`test_dict_key_order_alone_would_have_picked_the_wrong_model`). `config/models.yaml` now pins the
exact ids (`claude-sonnet-5`, `claude-haiku-4-5-20251001`) with a comment explaining why the exact
id — not the `sonnet`/`haiku` shorthand — must be what's actually passed to the CLI.

**Cost actually spent verifying this phase (cumulative):**
| | amount | billed? |
|---|---:|---|
| OpenAI (paid lane, 2 test calls) | $0.0000064 | yes — real dollars |
| Gemini, first pass (blocked key, 2 attempts) | $0.00 | no — rejected before generation |
| Gemini, second pass (model-drift + reasoning discovery, 9 calls incl. 2 free ListModels probes) | $0.0026905 | yes — real dollars |
| Claude subscription (several debug + 4 final verified calls) | ≈ $0.006 notional | **no** — subscription quota only, never billed |
| **Total real API dollars spent, Phase 0** | **≈ $0.0027** | — |

**Plan's "done when":** *"one smoke call per lane logged; `ANTHROPIC_API_KEY` leak test fails loudly."*
→ **met.** Key-leak test passes; OpenAI verified live; Sonnet + Haiku verified live through this
codebase's backend (not just informally, as in earlier design-phase testing); Gemini blocked
pending your key fix, confirmed via a real request, not assumed.

---

## Phase 1 — Data contracts (plan §5) — ✅ DONE

All pydantic v2, with golden fixtures, before any prompt is written.

- [x] `facts/models.py` — `SourceUnit`; `Claim` (+ `provenance_status`, `verification_status`, `importance`, `derived_from_claim_ids`, `inference_kind`, `mode`, `stage`, `scope`); `VerificationEvidence`; `EvidenceRequest`; `NumericClaim` (`numeric_claim_id` distinct from `claim_id`, unit-aware `expression`/`variables`/`output_unit`); `AssumptionLedger` (open to source-declared constants via `extra="allow"`)
- [x] `planning/models.py` — `ArchetypeSpec` (core/optional roles + driver); `SourceBrief` (+ `novelty_statement`); `TitleContract`; `HookContract`; `CTAContract` (default intent `VALUE_LINKED`, `max_ctas<=2` enforced); `StoryBeat` (+ `learning_objective`, `forward_driver`, observable fields — no numeric energy score); `MiniPayoff`; `EndingContract`; `ScenePlan` (word budget 30-100 enforced); `SemanticObject`; `StoryPlan`; `SeriesLedger`
- [x] `planning/shorts_models.py` — `HookEvent` (0-3s enforced); `ShortsCandidate` (open multi-factor `scores` dict); `ShortPlan` (+ `micro_arc`, `short_goal`, `bridge.mode`) — confirmed to have **no** `archetype` field at all
- [x] `narration/models.py` — `SentenceNarration` (`grounding_required` decoupled from `sentence_type`, defaults `False` until the Claim Mapper sets it); `SceneNarration`; `EditMapEntry`/`EditMap`
- [x] `review/models.py` — `CritiqueIssue` (`repair_owner` restricted to agents that actually rewrite); `DiagnosticResult` (banded, always carries evidence); `ReviewBundle`
- [x] `editing/models.py` — `RewriteBeat`, `TechnicalFix`, `DeleteOrCompress`, `RevisionPlan`
- [x] `verification/models.py` — `RenderReport` (+ `reader_standalone_ok`/`page_parity_ok` for the §12.0 dual-audience contract); `ApprovalQuestion`; `QualityReport` (`final_status` restricted to the four §14 values)
- [x] `orchestration/state.py` — `PipelineState`, confirmed its own `model_dump_json()` round-trips (the property the checkpoint/resume design depends on)
- [x] `llm/usage.py` — `AgentCostSummary`, `CostReport` (+ `CostReport.from_ledger()`, the one deterministic path from records to a report)
- [x] Golden JSON fixtures under `tests/fixtures/<package>/` for every aggregate/substantial model (17 fixture files); simpler "leaf" models round-tripped from inline literals in their test file instead — see the strategy note in `tests/conftest.py`
- [x] One type-level design choice worth flagging: `Archetype`/`ArchetypeSpec.archetype` is a `Literal` of the six real archetypes with **no `"auto"` option** — so "archetype resolved to auto" (a §9 hard-gate failure) is unrepresentable by construction, not just checked at runtime. Confirmed by `test_archetype_literal_excludes_auto`.

**Status: 109/109 unit tests passing** (55 new this phase). **Done when (plan):** *"schemas round-trip; no prompts yet"* — met; zero prompts were written to build this phase.

---

## V1A — Script intelligence (plan §8, §17 — the core thesis)

### Cost-discipline fix: strong-tier Gemini reasoning was unbounded (2026-09-10)

Following a direct steer to keep GPT/Gemini calls cost-conscious: `gemini_review_strong`
(C1/C2a/C2b) had `reasoning_effort: null` -- "provider default," which is **unbounded**
reasoning depth, not a deliberately-sized one. The completed live e2e run spent $0.218 across
11 paid calls partly because of this.

Fixed: `reasoning_effort: "low"`. Verified with two minimal calls (not a full run) rather than
re-running the expensive pipeline:
- First attempt used `max_tokens=20` and was a **misleading test** — too small a budget for a
  fair comparison, since the model can burn its entire tiny allowance on reasoning regardless
  of effort level. Caught before drawing a conclusion from it.
- Second attempt at `max_tokens=300` (representative of real calls) gave an honest, useful
  answer: `"low"` used **261 reasoning tokens vs 285 for default** — and, more importantly,
  **completed its answer** ("...because its only positive divisors are 1 and itself.") while
  default **ran out of budget mid-sentence** ("...is a prime number because it"). `"low"` isn't
  just cheaper here; it's more reliable, because a shorter reasoning phase leaves more room for
  the actual output within a fixed token cap.

### A second major finding: repair wiring was never actually connected (2026-09-10)

The first live end-to-end orchestrator run (against the real saved v02 plan) crashed with a
plain `JSONDecodeError` from C2b's response -- not a schema mismatch, malformed JSON outright,
plausible given the payload's real size (61 claims + a full narration draft). The architecture
has always specified that malformed output gets repaired on Haiku, free, before ever reaching a
later stage (plan §3.4) -- but the e2e script had constructed `LLMClient` by hand, without
passing a `repair_fn`, so that safety net was never actually wired in. This is precisely the
class of gap that only running the *whole* pipeline surfaces: every individual stage's unit
tests use a FakeAgent that never produces malformed output, so this path was never exercised
until a real model call actually failed to parse.

Fixed properly, not patched around: `llm/repair.py::make_haiku_repair_fn` builds the real
Haiku-backed repair function, and `llm/client.py::make_llm_client` is now **the one correct way**
to construct an `LLMClient` for a real run — it always wires the repair function in, so this
specific mistake can't be made by a future caller. Live-verified: the corrected e2e run
(`runs/v04`, below) went through the same C2b payload without crashing.

### Major finding: real A2 output caught by real hard checks (2026-09-10)

Two live A2 runs against the real source produced structurally deficient plans, and both were
independently found via careful inspection AND caught by the structural hard check built in
direct response:

1. **Archetype instability across runs.** Three live runs of A2 on the same source returned
   three different archetypes (`foundation`, `foundation` again, `derivation`) — a live
   demonstration of exactly the run-to-run variance the plan's own evaluation section (§18) and
   the guide (§24a) warn about. This is now the single most important open question for C1 to
   answer: `tests/review/test_story_critic.py` locks in a regression test replaying the specific
   "foundation vs. build" scenario the source's own structure (explicit problem→fix framing:
   *"Score creates a new problem," "New limitations"*) plausibly supports better than either
   archetype the model actually chose.
2. **A real class of defect a prompt alone can't fix.** Both runs produced a scene plan whose
   total word budget (320, then 460 words) was wildly short of the 1,670-word target for a
   600-second video — even after the prompt was explicitly given the exact arithmetic
   (`target_duration_seconds / 60 * 167`) and told the expected scene count. **This is not a
   prompt-wording problem** — LLMs are reliably poor at satisfying an aggregate constraint
   (a sum across many generated items) through instruction alone, no matter how precisely
   stated. The correct fix, applied: a deterministic check (`verification/hard/structure.py`),
   never another round of prompt tuning.
3. **A genuine prompt gap, fixed.** Every beat came back with `source_unit_ids: []` — not
   because the model ignored an instruction, but because the prompt never asked for that field
   to be populated at all. Fixed; locked in with `test_prompt_instructs_populating_source_unit_ids`.

**The structural hard check was then run against both real saved plans on disk** (not just
synthetic test fixtures) and correctly flagged every one of these defects with precise, accurate
detail — word-budget ratios (0.19, 0.28), the exact beats missing `source_unit_ids`, and every
uncovered source unit. This is the architecture doing exactly what it is for: A2 does not have
to be right on the first try; the pipeline's job is to catch it when it isn't. Both real plans
are preserved on disk (`project/attention_series/video-01-attention-coherent-story/runs/v01/`,
`v02/`) as permanent, real evidence for this finding, and as fixtures for testing C1/A3 routing
next.

### Root cause found and fixed: A2/C1 never saw the source's real content (2026-09-10)

Direct user steer: give the LLM that decides the story archetype (A2) — and its reviewer (C1) —
the actual source content, not just A1's compressed `SourceBrief`. This traced back to the
archetype-instability finding above: three live A2 runs gave three different archetypes for a
source the user's own separate, existing render pipeline had *already* independently classified
as `build`. That was the real signal something upstream was starving A2 of evidence, not that A2
was simply unreliable.

Two compounding gaps, both fixed:

1. **Extraction was silently deleting the strongest evidence in the document.** The source's
   `<footer class="page-footer">` holds an author-written "Production notes · target pacing"
   section — a timestamped `.pipeline-step` plan (`Problem → Mini payoff → Why attention
   existed → ... → New limitations → ... → Payoff and Part 2 bridge`) that is, in effect, the
   author's own account of the story's `build` shape. `.page-footer` is chrome-stripped
   wholesale (`extraction/html_parser.py::_strip_chrome`) because on this same source it's
   *mostly* nav-adjacent captions — but that one blanket rule discarded the production notes
   right along with the chrome, before A1 or A2 ever got to see it. Fixed with
   `_extract_production_notes()`, which runs on the *unstripped* soup, pulls any
   `.pipeline-step` content out as its own `production_notes` `SourceUnit` (using a new shared
   `extract_pipeline_steps()` helper in `extraction/profiles/base.py`), and only then lets
   `_strip_chrome()` remove the rest of the footer. Locked in with three regression tests
   (`tests/extraction/test_html_parser.py`), including one against the real source file
   asserting the exact real section headings survive.
2. **A2 and C1 only ever received compressed summaries, never raw source content.** Even with
   the footer bug fixed, `plan_story()` (A2) only took A1's `SourceBrief` (a lossy distillation)
   and `critique_story()` (C1) took no source content at all — only the plan's own
   self-description. Both now take a `source_units: list[SourceUnit]` parameter and receive the
   real content directly (`planning/story_planner.py`, `review/story_critic.py`), and
   `orchestration/pipeline.py` threads it through both the initial A2 call, the A2 replan call,
   and the C1 critique call. Both task prompts now explicitly instruct weighing an author's own
   production notes / storyboard plan as strong direct archetype evidence, not something to
   infer from the raw material.

**Live-verified with one minimal, targeted call** (not a full e2e re-run, per the standing
cost-discipline steer): re-ran A2 against the real source with the fixed extraction and the new
`source_units` payload (reusing the existing saved `source_brief.json`/`claims.json` from
`runs/v01` — free, no need to re-run A1). Result: `archetype: build` —
*"The source is structured around a problem-solution paradigm, accumulating understanding of
self-attention's mechanism piece by piece, solving issues such as context retrieval, variance
scaling, masking, and multi-head attention."* — correctly matching the user's own independent
pipeline's classification, and every rejected alternative given a real, specific reason. Cost:
**$0.0505** for the single call.

**V1A is now feature-complete** (2026-09-10): every remaining stage from the checklist below
was built in one continuous push — B2 targeted rewrite, S1 narrative digest, the remaining V*
hard checks (promise chain, CTA placement, numeric fidelity), D* diagnostics (retention, CTA
position, a provisional voice signal), C5 style critic, and R* final emission — each with real
unit tests and, where a new LLM call path was introduced, live validation against the actual
`video-01-attention-coherent-story.html` source, not synthetic fixtures alone. Full details,
including two more real bugs found live (a global 2048-token cap truncating A2's output, and an
open architectural finding about C1 disagreements), are in `ERROR_LOG.md` (ERR-016, ERR-021,
ERR-022). Not yet built: visual/learning diagnostics (need V1C screenshots / more corpus work
respectively), B3 precision editor and B4 humanize (no voice corpus to guard against drift yet),
C4/C4c cold-viewer cascades, and H/HV (HTML synthesis and render verification — V1B/V1C scope).

Pipeline order from §8. Nothing here is built yet; each line becomes its own
PR-sized unit with tests before the next.

- [x] **S0** extraction — DOM + JS-literal AST (Acorn via a Node bridge; literals only, never `node:vm`) → `extraction/` — **done, validated against real content**
- [x] **S2a** deterministic seeds — numbers, equations, JS constants → `AssumptionLedger`, formulas → `NumericClaim.expression` — **done, cross-validated against real corpus values**
- [x] **S2b** claim extraction (Haiku, batched over all source units) → `facts/claim_extract.py` — **done, validated**
- [x] **S2c** normalize/dedupe/link numbers→claims → `facts/normalize.py` — **done, validated**
- [x] **C2a** source verification (Python + local evidence broker + Gemini), cached by the §4.2/§6.5 key → `facts/verify.py`, `facts/evidence.py` — **done, live-validated (adversarial test passed)**
- [x] **S1** narrative digest (Haiku; only above ~12k source tokens) → `planning/narrative_digest.py` — built, unit-tested, live-validated (free, subscription lane) against the real source with the gate forced open; every real source tested so far is still under the threshold in normal operation, so the gate itself has never fired live, only the underlying call
- [x] **A1** source understanding (GPT) → `planning/source_understanding.py` — built, unit-tested, live-validated; now also accepts an optional `narrative_digest` from S1
- [x] **A2** archetype + story structure (title, hook, CTA, question chain, beats, ending) → `planning/story_planner.py`, `planning/archetypes.py`, `config/archetypes.yaml` (the six archetype specs, previously only prose in the plan) — built, unit-tested, live-validated against the real full source (correctly resolves `build`, matching the user's independent pipeline). Scene-level breakdown split out into **A2b** (`planning/scene_expander.py`) after ERR-010 kept recurring live — `planning/beat_word_budget.py` computes each beat's word target deterministically, one small call per beat fills it in; live-validated at a 900s target: 2573/2505 words (ratio 1.03), down from ratios as low as 0.19-0.31 before the split.
- [x] **B1** narration first draft (Sonnet) → `narration/generator.py` — built, unit-tested (context isolation confirmed: a scene only sees claims from its own beat's source units, not the whole registry), live-validated end to end
- [x] **B2** targeted rewrite (Narration Lead / Sonnet) → `editing/targeted_rewrite.py` — built, unit-tested, live-validated (free, subscription lane); wired into the orchestrator's `TARGETED_REWRITE` branch (previously a no-op, see ERROR_LOG ERR-016's sibling finding)
- [x] **CM** claim mapper — independent of the writer's `sentence_type` → `review/claim_mapper.py` — built, unit-tested
- [x] **C1** story critic → `review/story_critic.py` — built, unit-tested (includes a real regression test replaying the actual foundation-vs-build finding below); now also receives real `source_units`, not just the plan's self-description
- [x] **C2b** grounding + CM-completeness check → `review/grounding_verifier.py` — built, unit-tested, live-validated
- [x] **C5** style critic (conditional on voice bands AMBER/RED) → `review/style_critic.py` — built, unit-tested, live-validated ($0.0014, correctly caught hedging-padding tells); gated on the provisional voice diagnostic below since no fitted corpus exists yet
- [x] **V\* (structure)** — `verification/hard/structure.py`: word-budget-vs-target, beat/scene/CTA/mini-payoff referential integrity, core-role coverage, source-unit coverage, **promise-chain gate** (title↔hook↔ending, word-overlap heuristic), **CTA placement** (not in the hook, not before the first payoff) — validated against real production data, catches both real saved plans below and the real saved plans stay clean against the two new checks
- [x] **V\* (numeric fidelity)** — `verification/hard/grounding.py::check_numeric_fidelity`: a number that drifted between the verified claim registry and the final narration (e.g. "175 billion" cited but narrated as "175 million") — the plan §9 traceability primitive run in reverse to catch drift instead of confirm equivalence; unit-tested with a real-magnitude-mismatch case
- [x] **D\*** diagnostics (retention + CTA position, fully deterministic; voice, provisional pending a fitted corpus — V1D) → `verification/diagnostics/{retention,cta,voice}.py` — built, unit-tested, live-validated as part of the full e2e run below. Visual/learning diagnostics remain unbuilt (V1C/V1D dependencies: screenshots and a real corpus, respectively)
- [x] Routing table from §15 (targeted correction / re-plan / skip; B3/B4/C6 not yet wired — no revision candidates for them yet) → `editing/revision_planner.py` (A3), `orchestration/routing.py` — built, unit-tested. A3 can now also dismiss a critique issue A2's own `rejected_archetypes` already addressed (ERR-022/ERR-025/ERR-026), enforced in code not just the prompt — live-verified: a full run held its correctly-resolved archetype through two rounds of targeted rewrite with zero replans, the first of four live attempts where the archetype survived intact
- [x] Policy gate — deterministic; A4 hook present (`apply_editorial_downgrade`, cannot upgrade or clear a failure) → `orchestration/policy_gate.py` — built, unit-tested
- [x] **R\*** emit `narration.json`, `plan.json`, `script.md`, `cost_report.json`, `review_summary.md`, `quality_report.json` → `reporting/emit.py`, `reporting/cost_report.py`, `reporting/script_md.py` — built, unit-tested, **live-validated against the real source's full run** (see below): all six files written correctly, `cost_report.json`'s `billed_usd` reconciles exactly to the run's own `usage.jsonl`
- [x] `orchestration/pipeline.py` — the bounded revision loop (A2→B1→[CM,C1,C2b,C5,structural,diagnostics]→aggregate→policy gate→A3→route→replan-or-rewrite, bounded MAX_STORY_REPLANS=1/MAX_MAJOR_REVISIONS=2) — built, unit-tested, **and run live end-to-end against the real saved plan** (see below). The `@stage` caching decorator is deferred; the loop itself is proven first.

**Done when (plan):** *"a rough HTML becomes one coherent, verified, human-sounding script; every mutation test caught"* (mutation suite: §18).

---

### C2a status detail

Built: `facts/verify.py` — arithmetic-linked claims verified by Python alone (no LLM, no
judgement — a computed product either matches the claim's stated number or it doesn't);
everything else goes to the Review Lead (Gemini strong tier) with a two-pass evidence loop:
verdicts → evidence requests → Evidence Broker (`facts/evidence.py`, local `config/references/`
only for V1A, word-overlap matching, no embeddings) → re-verdict only on what was actually
found, so an empty references directory costs nothing extra.

**Live-validated with a genuinely adversarial test**, not just plausible-looking claims: three
claims sent together — a real mechanism claim, a real historical claim, and one deliberately
fabricated ("Attention has exactly 1 trillion parameters"). Result: the first two correctly
**VERIFIED** with sound technical reasoning; the fabricated one correctly **REJECTED**, with the
model explaining *why* (attention is an operation, not a parameterized model with a fixed
count) rather than just flagging it. Cost: **$0.018** for the batch (real dollars, Gemini strong
tier — this is a paid-lane stage, unlike S2a-S2c).

### S2b + S2c status detail

Built: `facts/claim_extract.py` (Worker/Haiku, ids assigned by Python — never trusted from the
model, batched by word count per plan §6.3), `facts/normalize.py` (`normalize_number()` — the
exact plan §9 traceability example, `"175B" == "175 billion" == "175,000,000,000"`; `dedupe_claims()`;
`link_numeric_claims()` connecting a `NumericClaim`'s computed product back to whichever `Claim`
mentions that value).

**Live-validated end to end against the real source** (`video-01-attention-coherent-story.html`,
all 11 units, one batched call): 74 claims extracted, correctly typed (mechanism 43, definition 10,
causal 7, complexity 5, implementation 5, historical 3, comparison 1), correctly weighted
(47 CORE / 27 SUPPORTING), **0 duplicates** — a first read of two units alone (before the full run)
already showed correct number tagging (`5`, `50`, `2014`) and correct historical/mechanism
classification. Notional cost for the whole file: **$0.063** (subscription quota, never billed).
This source has no JS data object (unlike `video-1.1`), so S2a's ledger/numeric-claim counts are
correctly empty here — confirmed as expected behavior, not a bug, by re-running against
`video-1.1` separately.

### S2a status detail

Built: `facts/seeds.py` — `parse_formula()` (a deterministic multiplication-chain parser for
source-authored formula captions like `"7.61B × 2 bytes"`), `seed_assumption_ledger()`
(top-level scalar JS literals only, passed through unchanged), `find_formula_claims()`
(recursively finds any `{"formula": "..."}` dict at any nesting depth and turns it into a
`NumericClaim`, regardless of a source's own JSON shape).

**Two deliberate non-decisions, stated explicitly rather than guessed:**
1. A JS scalar (`PARAMS=7.61`) is **never** renamed to a typed ledger field (`parameter_count`)
   or unit-scaled (×1e9) automatically — that's a semantic judgement about a source's naming
   convention, not a deterministic fact, and guessing it wrong would silently corrupt the
   ledger. It's kept as `ledger.params = 7.61`, verbatim, and typed-field population is left to
   an explicit later step.
2. A messy real formula (`"CUDA init + cuDNN workspace + allocator"`, `"40.4M × 8 bytes (m + v)"`)
   is **never partially evaluated** — it fails closed and is reported in `unparsed`, never
   silently dropped or guessed at.

**Validated against real corpus data** (`docs/corpus/sample_outputs/video-1.1-*.html`, via the
already-working S0 pipeline): 11 of 25 real formulas parsed cleanly, matching the source's own
claimed values exactly — `7.61B × 2 bytes` → 15.22 GB (source said 15.2 GB); the six-factor KV-
cache formula → 117,440,512 bytes = 0.117 GB (source said ~0.12 GB). The other 14 correctly
failed closed (additions, named non-numeric factors, parenthetical annotations) rather than
being guessed at.

**One real fix from that validation:** the parser initially rejected `"~40.4M × 2 bytes"` — a
leading `~` is a source author's own "approximately" marker, a genuine and common pattern here,
not noise. Fixed to parse the number normally while widening `NumericClaim.tolerance` to 0.05
and recording a note — parsed rate went from 9/25 to 11/25 on the real file after the fix.

### S0 status detail

Built: `extraction/html_parser.py` (orchestrator), `extraction/profiles/{base,guide,video_script,generic}.py`
(pluggable, confidence-scored), `extraction/js_literal_extractor.py` + `extraction/js_bridge/`
(a small Node+Acorn subproject — `extract_literals.js` parses literal-safe `const`/`let`
declarations only; calls, `require`, `new`, member access are rejected and never executed).

**Validated against real content, not just fixtures:**
- All 7 files in `docs/corpus/` (raw inputs + sample outputs) correctly classified as `video_script`
  at 0.90-1.00 confidence.
- `video-1.1` correctly recovered its JS constants (`HIDDEN`, `LAYERS`, `KV_HEADS`, `HEAD_DIM`,
  `PARAMS`) via the Acorn bridge — the exact literals that originally motivated the
  parse-don't-execute design decision, now proven end to end.
- `project/attention_series/input/video-01-attention-coherent-story.html` (a real, in-progress
  source, not part of the original corpus) correctly classified as `guide` at 1.00 confidence,
  11 sections, matching its true structure exactly (3 equations, 15 diagrams, 7 callouts, 15 code
  blocks — verified against the source's own markup counts).

**Two real bugs found and fixed by running against that real file, not assumed from the markup
census:**
1. **Chrome-stripping deleted real content.** `.diagram-caption` and `.math-block` both render as
   `<footer>` tags in this design system; a chrome-stripping selector list had a bare `"footer"`
   entry meant only for the page footer, and it silently deleted all of them. Fixed by scoping to
   `.page-footer`; locked in with a regression test
   (`test_guide_extraction_recovers_footer_tagged_diagrams_and_equations`).
2. **The number-sweep regex's unit vocabulary was too narrow.** Realistic domain phrasing
   ("128 dimensions") wasn't recognized because `dimensions`/`dims` weren't in the accepted-unit
   list. Added.

Committed test fixtures are small, tracked, hand-written HTML snippets under
`tests/fixtures/extraction/` — never the real corpus (`docs/corpus/`, `project/`), both of which
are gitignored working content and must not be a dependency of the committed test suite.

## V1A-S — Shorts slice (plan §20; depends on V1A, kept out of it)

- [x] `micro_arc` enum, `HookEvent`/`ShortsCandidate`/`ShortPlan` contracts → `planning/shorts_models.py` (Phase 1) — `title: str` field added (a real gap: the plan's own A2s design output and the title~hook~payoff hard gate both need it, but it was missing from the original contract)
- [x] `SC` candidate finder (Haiku, subscription, free) → `planning/candidate_finder.py` — built, unit-tested, live-validated against the real verified attention-series claims (5 real, concrete candidates from 5 different beats)
- [x] `A2s` short story planner (GPT mini) → `planning/short_planner.py` — built, unit-tested, live-validated (`parent`/`allowed_fact_ids` assembled deterministically in Python from the model's own `source_beat_ids`, never trusted as the model's job)
- [x] `B1` short rhythm profile (Sonnet, subscription, free) → `narration/short_generator.py` — built, unit-tested, live-validated (four fixed segments: hook/setup/mechanism/payoff, not a scene_plan)
- [x] `C1s` micro-arc critic (Gemini flash) → `review/short_critic.py` — built, unit-tested, live-validated (correctly caught a narration that didn't actually execute its own declared `problem_fix` micro-arc)
- [x] Cold-hook critic `C4s` (Haiku → Gemini flash cascade) → `review/cold_hook_critic.py` — built, unit-tested; a clean, confident Haiku pass never escalates (free), matching the plan's cascade cost philosophy
- [x] Short-profile hard gates (§20.10) → `verification/hard/shorts.py`: central insight present, title~hook~payoff alignment, duration ≤60s (+2s estimate slack), parent reference, grounding scoped to `allowed_fact_ids` — built, unit-tested, live-validated (correctly caught a real title/hook mismatch and a 71.9s narration over the cap)
- [x] Short-profile diagnostics (§20.10, the deterministically-computable subset) → `verification/diagnostics/shorts.py`: time-to-hook, setup length, word-count band — built, unit-tested. Visual density/on-screen text (need H/HV) and sentence rhythm (needs a fitted voice corpus) deferred to V1B/V1C/V1D, same dependencies long-form's equivalents have
- [x] Single-pass short orchestrator (deliberately no A3/B2 revision loop — see module docstring) → `orchestration/shorts_pipeline.py` — built, unit-tested, live-validated end to end twice ($0.0101 then $0.0192) against the real verified source; one real bug found and fixed live (ERROR_LOG ERR-028: CM/C2b saw the full claim registry instead of the short's scoped fact set)
- [x] `narration.json`/`short_plan.json` emission → `reporting/emit_short.py` — built, unit-tested, live-validated. `short.html` (H/HV) and cost/quality reports for shorts are out of this scope (V1B/V1C, and no multi-short orchestration script yet to wire a UsageLedger through)

**Done when (plan):** *"a short derived from a successful V1A output is grounded within the parent's fact set, has one central insight, and its hook event lands ≤3s."* — **met**: live-validated twice against the real, C2a-verified attention-series claims; the second run correctly PASSED the grounding-scope, central-insight, and hook-timing gates (it still FAILed overall on real content-quality findings — title/hook mismatch, duration, micro-arc fidelity — which is the policy gate doing its job, not a reason this bar isn't met).

---

## V1B — HTML (plan §12, §17)

- [x] `config/design_system.yaml` — tokens + component catalogue + story-role mapping (plan §7), lifted from the 17 classes verified present across ALL THREE `docs/corpus/sample_outputs/*.html` pages (never a single video's bespoke one-off styling); `math_block`/`diagram_card` adapted from the "guide" markup family since the sample corpus (a GPU/memory series) never needed an equation
- [x] `html_synth/component_library.py` — deterministic component renderer, every slot HTML-escaped regardless of what the model returns — built, unit-tested, live-validated; two real bugs found and fixed (ERROR_LOG ERR-029: grid item shape assumed, not specified, crashed twice on two different real shapes before being made shape-agnostic)
- [x] `html_synth/synthesizer.py` — H (Sonnet, subscription, free): per-beat calls (not one page-wide call — same ERR-010/ERR-024 lesson applied here) for screen prose (genuinely different text from spoken narration, plan §12.0) + component selection + numeric-claim annotation — built, unit-tested, live-validated
- [x] `html_synth/assembler.py` — deterministic assembly; `video_script.html`/`page.html` rendered by ONE shared function parameterized only by `include_metadata`, so dual-audience parity is guaranteed by construction, not by a fragile post-hoc strip transform — built, unit-tested, live-validated
- [x] HV static checks (`verification/hard/render.py`) — HTML parses, unique ids, scene presence/order, narration-hash match, numeric-claim-id traceability, page/video_script text parity — built, unit-tested, live-validated at **zero render_issues** against the real source. NOT yet built (need a calibration decision, not guessed at): reader-standalone word-count band, `renderer_compat`'s claim-backed-word threshold, deictic resolution — see ERROR_LOG's open items
- [x] `reporting/emit_html.py` — `video_script.html`/`page.html`/`render_report.json` — built, unit-tested, live-validated
- [x] `orchestration/html_pipeline.py` — ties H + HV static into one pass — built, unit-tested
- [ ] Web retrieval for evidence requests (extends V1A's local-reference-only evidence broker) — not started; a separate, independent feature from H/HV, deliberately not bundled into this push
- [ ] Vertical shorts template, safe zones, HV at 1080×1920 — not started; needs its own design pass on top of the long-form component library, not a copy of it

**Live-validated end to end** against the real, C2a-verified attention-series plan/narration
(free — H is Sonnet/subscription): a real 59.7KB `video_script.html` / 34.3KB `page.html`,
3218 visible words (inside the plan's own ~2,000-3,200 sample band), 24 cards / 14 defboxes
/ 8 grid-3s rendered from real beat content, 3 numbers correctly traced to real claim ids,
**zero HV static issues**.

**Done when (plan):** *"`video_script.html` passes structure + traceability + `renderer_compat`."* —
structure and traceability are met and live-verified; `renderer_compat` specifically (the
>=1,500-claim-backed-words / no-empty-sections gate) is not yet implemented as its own named
check (tracked in ERROR_LOG's open items) — the real output already clears the word-count
figure informally, but the gate itself needs deliberate calibration, not an assumed threshold.

---

## V1C — Visual loop (plan §13, §17)

- [ ] Playwright runner, screenshots, `C3` visual audit, `H` REPAIR loop (≤2)
- [ ] TTS preview for shorts → measured-duration gate (replaces the estimate-based gate from V1A-S)

**Done when (plan):** *"render failures caught and repaired on the subscription lane."*

---

## V1D — Calibration (plan §17)

- [ ] Voice-corpus restoration + refit (`docs/corpus/transcripts/` → `voice/fingerprint.py`; `tools/voice_fit.py` is the working prototype)
- [ ] Retention-band tuning, series-ledger automation, design-system fitting
- [ ] Measured-audio WPM calibration, analytics feedback loop

**Done when (plan):** *"bands tighten against the channel's own data."*

---

## Project folder layout — ✅ DONE

`orchestration/paths.py` — `project/<playlist>/input/` for sources you add;
`project/<playlist>/<video_slug>/final/` for stable, publishable deliverables;
`project/<playlist>/<video_slug>/runs/vNN/` for the full plan §16 working tree per attempt
(nothing overwritten, version numbers never reused even across gaps). `promote_to_final()`
copies a run's `final/` into the video's `final/` — will be called by the orchestrator
(not yet built) only after a PASS/PASS_WARN policy-gate result, never on REVISE/FAIL.
Documented as plan **Appendix D, ADR D12**. 13 tests.

## Cross-cutting (build alongside, not a separate phase)

- [ ] Mutation test suite (§18) — grows with each stage as it lands, not written all at once
- [x] `reporting/cost_report.py` — built during V1A (`CostReport.from_ledger()`, live-reconciled against a real `usage.jsonl`). `cost_cli.py` (a small CLI wrapper over it) — not started.
- [ ] Repeated-run stability harness (§18, guide §24a) — once V1A is stable enough to run 20×
- [ ] **End-to-end orchestrator / CLI entry point** (2026-09-11 — a real gap, not yet its own module anywhere). Every stage from S0 through H/HV is built, unit-tested, and individually live-verified, but only ever driven by one-off scratch scripts written per validation run, not a single committed, callable pipeline. Needs one real entry point that wires, in order:
  `extraction.html_parser.parse_html` → `facts.seeds`/`facts.claim_extract`/`facts.normalize` (S2a-c)
  → `facts.verify.verify_claims` (C2a, cached per plan §4.2's key)
  → `planning.source_understanding.understand_source` (A1, + `planning.narrative_digest` above the token threshold)
  → `orchestration.pipeline.run_story_and_narration_loop` (the bounded A2→B1→review→A3 loop)
  → `orchestration.html_pipeline.synthesize_video_html` (H + HV static)
  → `orchestration.policy_gate` for the final PASS/PASS_WARN/FAIL decision
  → `reporting.emit`/`reporting.emit_html` writing into `orchestration.paths.next_run_dir()`
  → `orchestration.paths.promote_to_final()` **only** on PASS/PASS_WARN, never on REVISE/FAIL.
  Should also drive the V1A-S shorts run (`orchestration.shorts_pipeline.run_short` + `reporting.emit_short`) off the same finished long-form run, per plan §20.6's "runs only after the parent's plan is final, keyed to `final_plan_hash`." Until this exists, "running the pipeline" means assembling and wiring these calls by hand each time, which is exactly the failure mode a real entry point removes.
