# Build Plan — phase-wise task tracker

This is the "what's actually built" tracker. `IMPLEMENTATION_PLAN.md` is the
frozen design (v3.2) and does not track progress — this file does, and gets
its checkboxes updated as work lands. Section refs (`§N`) point into
`IMPLEMENTATION_PLAN.md` unless marked "guide §N" (`SYSTEM_DESIGN_GUIDE.md`).

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

Pipeline order from §8. Nothing here is built yet; each line becomes its own
PR-sized unit with tests before the next.

- [x] **S0** extraction — DOM + JS-literal AST (Acorn via a Node bridge; literals only, never `node:vm`) → `extraction/` — **done, validated against real content**
- [x] **S2a** deterministic seeds — numbers, equations, JS constants → `AssumptionLedger`, formulas → `NumericClaim.expression` — **done, cross-validated against real corpus values**
- [x] **S2b** claim extraction (Haiku, batched over all source units) → `facts/claim_extract.py` — **done, validated**
- [x] **S2c** normalize/dedupe/link numbers→claims → `facts/normalize.py` — **done, validated**
- [x] **C2a** source verification (Python + local evidence broker + Gemini), cached by the §4.2/§6.5 key → `facts/verify.py`, `facts/evidence.py` — **done, live-validated (adversarial test passed)**
- [ ] **S1** narrative digest (Haiku; only above ~12k source tokens)
- [ ] **A1** source understanding (GPT) → `agents/story_lead.py`
- [ ] **A2** archetype + story plan (title, hook, CTA, question chain, beats, ending, `open_loop_ledger`) → `planning/`
- [ ] **B1** narration first draft (Sonnet) → `narration/generator.py`
- [ ] **CM** claim mapper — independent of the writer's `sentence_type` → `review/claim_mapper.py`
- [ ] **C1** story critic, **C2b** grounding + CM-completeness check, **C5** style critic (conditional on voice bands) → `review/`
- [ ] **V\*** hard checks — numeric, units, schema, traceability, structure, coverage → `verification/hard/`
- [ ] **D\*** diagnostics — story, retention, learning, CTA, voice, visual, banded GREEN/AMBER/RED → `verification/diagnostics/`
- [ ] Routing table from §15 (targeted correction / B3 / B4→C6 / re-plan / skip) → `editing/`, `orchestration/routing.py`
- [ ] Policy gate — deterministic; A4 is editorial-only and downgrade-only → `orchestration/policy_gate.py`
- [ ] **R\*** emit `narration.json`, `script.md`, `cost_report.json`, `review_summary.md`
- [ ] `orchestration/pipeline.py`, `state.py` — the `@stage` decorator (cache + checkpoint + usage), wiring the run end to end

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

- [ ] `SC` candidate finder, `A2s` short planner, `micro_arc` enum
- [ ] `C1s` critic, cold-hook critic
- [ ] Short-profile gates/diagnostics (§20.10)

**Done when (plan):** *"a short derived from a successful V1A output is grounded within the parent's fact set, has one central insight, and its hook event lands ≤3s."*

---

## V1B — HTML (plan §12, §17)

- [ ] `html_synth/synthesizer.py`, `component_library.py` — dual-audience contract: `video_script.html` + `page.html` (§12.0)
- [ ] HV static checks; `data-numeric-claim-id` traceability
- [ ] Web retrieval for evidence requests (extends V1A's local-reference-only evidence broker)
- [ ] Vertical shorts template, safe zones, HV at 1080×1920

**Done when (plan):** *"`video_script.html` passes structure + traceability + `renderer_compat`."*

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
- [ ] `reporting/cost_report.py`, `cost_cli.py` — scaffold once V1A produces its first real run to report on
- [ ] Repeated-run stability harness (§18, guide §24a) — once V1A is stable enough to run 20×
