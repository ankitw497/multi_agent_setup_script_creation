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
- [ ] Re-run `test_live_gemini_smoke` once the Gemini key is fixed

**Status: 51/51 unit tests passing** (`pytest`, 3 integration tests excluded by default; all 3 have now
been run at least once — 2 pass, 1 blocked on the Gemini key, not on code).

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

**Cost actually spent verifying this phase:**
| | amount | billed? |
|---|---:|---|
| OpenAI (paid lane, 2 test calls) | $0.0000064 | yes — real dollars |
| Gemini (paid lane, blocked, 2 attempts) | $0.00 | no — rejected before generation |
| Claude subscription (several debug + 2 final verified calls) | ≈ $0.006 notional | **no** — subscription quota only, never billed |

**Plan's "done when":** *"one smoke call per lane logged; `ANTHROPIC_API_KEY` leak test fails loudly."*
→ **met.** Key-leak test passes; OpenAI verified live; Sonnet + Haiku verified live through this
codebase's backend (not just informally, as in earlier design-phase testing); Gemini blocked
pending your key fix, confirmed via a real request, not assumed.

---

## Phase 1 — Data contracts (plan §5)

All pydantic v2, with golden fixtures, before any prompt is written. **Not started.**

- [ ] `SourceUnit`; `Claim` (+ `provenance_status`, `verification_status`, `importance`, `derived_from_claim_ids`, `inference_kind`, `mode`, `stage`, `scope`); `NumericClaim` (`numeric_claim_id` distinct from `claim_id`, unit-aware `expression`/`variables`/`output_unit`); `AssumptionLedger`
- [ ] `SourceBrief` (+ `novelty_statement`); `TitleContract`; `HookContract`; `CTAContract`; `StoryBeat` (+ `knowledge_delta`, `forward_driver`, observable fields); `MiniPayoff`; `EndingContract`; `StoryPlan`; `OpenLoop`; `RetentionMap`
- [ ] `ScenePlan`; `SentenceNarration` (+ `grounding_required`/`grounding_refs`, decoupled from `sentence_type`); `SceneNarration`; `SceneHTML`
- [ ] `CritiqueIssue`; `ReviewBundle`; `RevisionPlan`; `RenderReport`; `QualityReport`; `SeriesLedger`
- [ ] `ShortsCandidate`; `HookEvent`; `ShortPlan` (§20.5)
- [ ] Golden JSON fixture per model; round-trip test (`model_validate_json` → `model_dump_json` → re-validate)

**Done when (plan):** *"schemas round-trip; no prompts yet."*

---

## V1A — Script intelligence (plan §8, §17 — the core thesis)

Pipeline order from §8. Nothing here is built yet; each line becomes its own
PR-sized unit with tests before the next.

- [ ] **S0** extraction — DOM + JS-literal AST (Acorn via a Node bridge; literals only, never `node:vm`) → `extraction/`
- [ ] **S2a** deterministic seeds — numbers, equations, JS constants → `AssumptionLedger`, formulas → `NumericClaim.expression`
- [ ] **S2b** claim extraction (Haiku, batched over all source units) → `facts/claim_extract.py`
- [ ] **S2c** normalize/dedupe/link numbers→claims → `facts/normalize.py`, `facts/ledger.py`
- [ ] **C2a** source verification (Python + local evidence broker + Gemini), cached by the §4.2/§6.5 key → `facts/verify.py`, `facts/evidence.py` — **blocked on the Gemini key fix**
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

## Cross-cutting (build alongside, not a separate phase)

- [ ] Mutation test suite (§18) — grows with each stage as it lands, not written all at once
- [ ] `reporting/cost_report.py`, `cost_cli.py` — scaffold once V1A produces its first real run to report on
- [ ] Repeated-run stability harness (§18, guide §24a) — once V1A is stable enough to run 20×
