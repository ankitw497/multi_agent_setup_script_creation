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
