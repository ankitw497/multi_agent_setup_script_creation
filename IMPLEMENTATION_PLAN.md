# Multi-Agent Pipeline: Rough HTML → YouTube Video-Script HTML

**Version 3 — frozen.** v2 was rewritten after `docs/reviews/multi_agent_implementation_plan_review.md`;
v3 applies the second and third review rounds. Appendix A records deviations from the original
design doc; B, C and E record the responses to each review; **D holds the architecture decision
records**. **v3.1** adds the shorts/reels format (§20) as an additive *format profile*; **v3.2** applies
the final hygiene review (Appendix G) — contracts, cache keys, budget tiers, naming. **v3.3** relocates
the run root from a generic `runs/<id>/` to a `project/<playlist>/<video>/` layout (ADR D12) —
additive, no change to what a run contains. No further architecture changes before V1A runs — the next
information comes from experiments, not design.

**Goal:** take a content HTML — clean or rough — and produce a **video-script HTML**: one
story, technically verified, scene-structured, narrated in a voice that reads as human. It
feeds the existing 8-step render pipeline.

**Four viewer outcomes, in priority order:** the viewer **learns something new** · the viewer
**stays** · the viewer **subscribes** · there is **one story** first second to last.
**Two means to those ends:** technical correctness · human voice.

**Primary artifact:** `video_script.html`. **Co-produced:** `narration.json` (canonical),
`plan.json`, quality report — all from one plan and one verified number registry.

**Model lanes:** Sonnet + Haiku on the Claude Code subscription (`subscription_lane`: zero
marginal API cost, quota-limited); GPT + Gemini through LiteLLM (`paid_api_lane`: hard USD cap).

**The governing principle** (from the review, adopted whole): *use deterministic code for what
is genuinely deterministic — numbers, units, schema, traceability, scene identity, HTML
validity; use models for judgement — coherence, interest, novelty, naturalness, pedagogy;
use measured heuristics as evidence for those judgements, never as substitutes.* Everything
below is organized around that split: **§9 hard gates** are few and mechanical; **§10
diagnostics** are many and advisory.

---

## 0. Verified facts this plan rests on

| Fact | Evidence | Consequence |
|---|---|---|
| Subscription lane works headless | `claude` v2.1.224, `ANTHROPIC_API_KEY` unset | `env -u ANTHROPIC_API_KEY` asserted in code on every call |
| Default `claude -p` costs ~30k tokens of harness overhead per call | 10 + 22,698 cache-read + 7,459 cache-creation for a one-line prompt | Stripped-flag recipe (§3.1) is mandatory: **170 tokens** |
| Raw inputs are story-thin, not unstructured | `docs/corpus/raw_inputs/*.html`: 1,205–1,964 words, same design system, 4 sections, **0** archetype components; sample outputs: 1,992–3,211 words, **1–8** archetype components | Tier-A extractor path is primary; the delta is the Stage H spec (§12) |
| Raw inputs are causally thin | causal connectives/100w: raw **0.65**, sample outputs **1.09**, human narration **1.04** | The pipeline adds *reasoning*, not facts |
| Technical payload can live in JS, not DOM | `video-1.1`: 4 memory modes, all formulas, `HIDDEN=3584, LAYERS=28, PARAMS=7.61` in a `<script>` object literal | Literal-AST extraction (§6.2); constants seed the assumption ledger deterministically |
| Sample markup is archetype-aware | `video-1.32`: `suspect`×25, `solution-card`×16 (mystery); `video-1.1`: `step-item`, `mode-selector` (build) | Component choice is by story role (§7) |
| Voice corpus: 6 of 10 transcripts usable | 4 are unpunctuated auto-captions (`video_2, 6, 7, 10`) | Corpus gate + restoration pass (§11.5) |
| Spoken narration ≠ on-screen prose | concrete tokens/100w **0.13 vs 3.48**; "we" **1.92 vs 0.09**; short sentences **1.8% vs 16.3%** | Two fingerprints; never apply one to the other (§11.2) |
| Signposts are normal human speech | 8.8 signpost openers per 100 sentences; "so" 5.4%, "now" 3.8% of openers | The diagnostic is opener *diversity*, not avoidance |
| Human opener share ranges to 16.4% | per-video top-opener share 6.1–16.4%; distinct openers 14–26 | Any threshold inside that range would reject real humans → bands, not gates (§11.3) |
| Series structure | all samples "Act 1, Video N of 3", shared constants | Series ledger (§5.3) |
| Keys | `OPENAI_API_KEY` placeholder-shaped; `GEMINI_API_KEY` unset | Blocking for the paid lane |
| Toolchain | Python 3.12.6, Node 24.14, pydantic 2.12.5 | Node for the JS AST parser and Playwright |

---

## 1. Scope

```
content.html (clean or rough)
     │
     ▼
┌──────────────────── THIS PIPELINE ────────────────────┐
│ extract → claims → understand → ONE archetype → plan  │
│ → narration → independent review → targeted revision  │
│ → (humanize if needed) → HTML → render-verify         │
└───────────────────────────────────────────────────────┘
     │
     ├── video_script.html          primary
     ├── narration.json             canonical narration
     ├── plan.json · quality_report.md
     ▼
render pipeline:  INGEST → PLAN → SCRIPT → NARRATION → VOICEOVER → SCENES → STORYBOARD → RENDER
```

- **Scene order is ours.** We author the source HTML, upstream of the render pipeline's step-3
  freeze; the playbook's Level-3 reorder is available.
- **Renderer compatibility is a compatibility rule, not a quality rule.** The render pipeline's
  Gate 1 (≥3 sections, ≥1,500 words) is checked as `renderer_compat`, separate from content
  gates. Duration is format-driven (`format.type`, `duration.target_seconds`, `planning_wpm`).
- **Narration and visuals come from one plan**, so the playbook's Part VII failures become
  structurally preventable rather than review-caught.
- **Two formats, one pipeline.** `format.type: longform` (10–15 min, the default) and
  `format.type: short` (45–60 s, vertical). A short is normally *derived* from a long-form
  run's verified plan — inherits the facts, never the story shape; its own micro-arc, outcome
  table and gates (§20).

### 1.1 Your manual loop, automated

| What you do by hand | Pass |
|---|---|
| paste source into GPT, ask what it's about | A1 |
| ask GPT for a structure / angle | A2 |
| paste outline into Sonnet, get the script | B1 |
| read it, notice what's wrong | C1 · C2b · C5 · validators · R1 |
| decide what needs fixing | A3 *(only if needed)* |
| paste back with notes | B2 / B3 *(only if needed)* |
| fix wording that sounds like a model | B4 *(only if needed)* |
| build the HTML | H |
| open it, check it | HV · C3 |
| final read | C4 · policy gate · A4 |

Agents exchange **typed artifacts, never conversation** (design doc §49) — a critic that sees
the writer's reasoning defends it; three families exist to disagree; artifacts cache and diff.
It remains a loop: reviews route work back, bounded (§15).

### 1.2 The four outcomes and what serves them

| Outcome | Hard (mechanical) | Judged (model) | Diagnosed (heuristic, advisory) |
|---|---|---|---|
| **Story** | archetype resolved; title→hook→ending promise chain present; core archetype roles present (optional roles are diagnostics) | C1 story critic; C4 cold viewers | causal-bridge presence; archetype-stage tracking |
| **Retention** | — | C1; C4c mid-video cold viewer; A3 decides | forward-driver continuity; payoff gaps; state-change valleys (§10.2) |
| **Subscribe** | ≤2 CTAs; none in hook; none before first payoff | Narration Lead writes; C1 judges fit | CTA position 20–40%; intent; length |
| **Learn** | central insight exists; `viewer_can_now` taught by the body | C1: "too obvious for this audience?"; Haiku delta-triviality *lint* | novelty statement present |

Rule: every stage or check names the outcome it serves and which column it sits in.

For **shorts** the outcomes re-weight — acquisition and the bridge to the long-form lead;
"learn" is one insight, not a capability; see the shorts outcome table in §20.1.

---

## 2. Agents

Five identities. An identity = one base system prompt + model alias + lane. A pass = one
stateless invocation in a named mode with isolated context.

| # | Agent | Model | Lane | Modes |
|---|---|---|---|---|
| 1 | **Story Lead** | GPT strong / mini | paid | `SOURCE_ANALYST` A1 · `PLAN` A2 · `REVISION_PLANNER` A3 · `EDITORIAL_SUMMARY` A4 |
| 2 | **Narration Lead** | Sonnet | subscription | `FIRST_DRAFT` B1 · `TARGETED_REWRITE` B2 · `PRECISION_EDIT` B3 · `HUMANIZE` B4 |
| 3 | **Review Lead** | Gemini strong / flash | paid | `STORY_CRITIC` C1 · `VERIFY_SOURCE_CLAIMS` C2a · `CLAIM_MAPPER` CM · `GROUND_NARRATION` C2b · `VISUAL_AUDITOR` C3 · `COLD_VIEWER` C4b/C4c · `STYLE_CRITIC` C5 · `ENTAILMENT_CHECK` C6 |
| 4 | **HTML Author** | Sonnet | subscription | `SYNTHESIZE` H · `REPAIR` |
| 5 | **Worker** | Haiku | subscription | `CLAIM_EXTRACT` S2b · `DIGEST` S1 · `PUNCTUATE` · `COLD_VIEWER` C4a/C4c (first tier) · `DELTA_LINT` · `SCHEMA_REPAIR` · `EDITORIAL_SUMMARY` (clean runs) · `REPORT` |

**Haiku rule:** structural, mechanical and lint work only; never the deciding reviewer on
story, correctness, voice, or the final decision (same family as the writer).

**Paid calls cascade rather than duplicate.** Always: A1, A2, CM (flash), C1, C2b (C2a is
cached per source, so it's paid once per source, not per run). Conditional: C5 only if Python voice bands
are AMBER/RED; C3 only if HV flags scenes; Gemini cold viewers (C4b/C4c) only if the Haiku
first tier flags confusion or reports low confidence; GPT A4 only on `PASS_WARN`, revision
exhaustion, or benchmark runs — otherwise Python + Haiku write the editorial summary.
**A typical clean run: 5–7 paid calls** (CM is cheap — narration in, a list out). A revision cycle adds A3, C6, and re-runs as routed.
**Nothing runs because it exists.**

**Cascade blind spot, measured not assumed:** the Haiku first tier shares Sonnet's priors and
may not be confused where a human would be. So the Gemini cold viewers also run on every
benchmark run and on a **20% random sample of clean runs**, and the sample's disagreement rate
with Haiku is tracked in `run_manifest.json`. If it climbs, the cascade threshold drops.

Model aliases live in `config/models.yaml`; IDs are never in story logic.

---

## 3. Two-lane LLM layer

```
        llm.call_structured(role, mode, payload, schema)
                     ┌──────────┴──────────┐
          ClaudeCliBackend            LiteLLMBackend
          claude -p subprocess        litellm.Router
          subscription_lane           paid_api_lane
          budget = quota window       budget = USD, enforced locally
                     └──────────┬──────────┘
            pydantic validate → repair (≤2, Haiku) → artifact
```

### 3.1 `backends/claude_cli.py` — verified recipe

```bash
env -u ANTHROPIC_API_KEY claude -p "<payload>" --model <exact-id-from-models.yaml> \
  --system-prompt "<base instruction>" --tools --setting-sources "" \
  --strict-mcp-config --exclude-dynamic-system-prompt-sections \
  --max-turns 1 --output-format json
```

170 tokens overhead vs 30,167 default. **Pin the exact model, not the alias:** `models.yaml`
maps `sonnet`/`haiku` to versioned ids; the CLI is called with the exact id; and the envelope's
`modelUsage` key (which reports the resolved model — `claude-haiku-4-5-20251001` in the smoke
test) is read back and **asserted equal** to the requested id, then written to the manifest.
Benchmark runs refuse to start on an unpinned alias. Scratch cwd with no `CLAUDE.md`; `env -u`
asserted in code; parse `result`, strip fences; log `usage`/`total_cost_usd` as *notional quota*;
semaphore 2; backoff; on quota exhaustion **checkpoint and stop** — never fail over to a paid
model (design doc §52). `claude_agent_sdk.py` is reserved for a real SDK backend later.

### 3.2 `backends/litellm_backend.py`

Router per alias; transport retries only; JSON-schema `response_format` where supported;
per-mode `max_tokens`; cost read from the **public** callback path (`response_cost` in the
success-callback kwargs / `litellm.completion_cost()`), never from `_hidden_params`.

**Budget policy is application code**, not a LiteLLM helper:

```python
if preflight_estimate > run_budget: abort()
spend += call_cost
if spend > run_budget: stop_and_checkpoint()
```

LiteLLM supplies routing, cost data and callbacks; the safety boundary is ours and is
integration-tested.

### 3.3 Credential topology — a choice, not an assumption

LiteLLM is a client interface, not a model provider: it translates one `completion()` call into
each provider's API and authenticates with **that provider's** credentials. Three valid
topologies; the pipeline code is identical in all of them — only `models.yaml` aliases change.

| Topology | App holds | Provider keys exist | Notes |
|---|---|---|---|
| **Direct** | OpenAI + Gemini keys | in `.env` | simplest; native per-provider cost data |
| **LiteLLM Proxy** (self-hosted gateway) | one virtual key | in the proxy's config | central budgets/logging; still needs both provider keys, just not in the app |
| **OpenRouter** (aggregator; a LiteLLM provider) | one OpenRouter key | none | genuinely one key and one bill for GPT + Gemini; pays a margin; a third party in the path; availability/latency follow OpenRouter |

**Decided: Direct.** One OpenAI key and one Gemini key, both read from a gitignored `.env`
and passed to LiteLLM; the budget policy (§3.2) gets native per-provider cost figures. Two
hygiene rules follow: the keys never live in the shell environment (the current shell holds a
placeholder-shaped `OPENAI_API_KEY`, which is exactly how a bad key leaks into subprocess
calls), and `.env` is loaded only by the LiteLLM backend — the Claude CLI backend runs with
`ANTHROPIC_API_KEY` explicitly unset (§3.1). OpenRouter remains a one-alias-change fallback.

### 3.4 Structured output

Schema in prompt on both lanes → `model_validate` → repair on Haiku ≤2 → fail loudly.

---

## 4. Cost and quota

**Paid lane.** Raw HTML never reaches a paid model; volume (drafting, rewrites, humanizing,
HTML, repairs, lint) is subscription-side; flash/mini tiers by default with escalation; scoped
review payloads; ≤8 screenshots per run; content-hash cache per stage (`detected_archetype`
never in a key); stable prompt prefixes; caps in `config/budget.yaml`
— three tiers per format, because one number cannot be both the expected spend and the airbag:

```yaml
longform: {target_usd: 0.40, warning_usd: 0.60, hard_cap_usd: 1.00}
short:    {target_usd: 0.08, warning_usd: 0.15, hard_cap_usd: 0.25}
daily:    {warning_usd: 5.00, hard_cap_usd: 10.00}
```

The **target** guides tiering and escalation; crossing the **warning** logs and forces at most
`PASS_WARN`; the **hard cap** aborts (pre-flight above it never starts; a run reaching it stops
and checkpoints). A run at $0.46 that needs one legitimate technical revision proceeds — it is
under the hard cap — rather than stopping to save cents. Clean run ≈ 60–75k paid
input tokens, 25–30k output. The cap, not the estimate, is the guarantee.

**Subscription lane.** Stripped-flag recipe; batch (one Sonnet call per draft, one Haiku call
per screening pass; HTML by act); concurrency 2; `usage.jsonl`; checkpoint per stage so a
rate-limited run resumes.

---

### 4.1 Cost attribution — per agent, per pass, per script

Caps stop overspend; they don't tell you *where* the money went. Every model call writes exactly
one `UsageRecord`, and every run ends with a `CostReport` that answers, for one script: **what
did each agent cost, what did each stage cost, what did the revision cycle cost, what did the
cache save, and how far under the cap did we land.**

**One record per call, both lanes, one schema:**

```
UsageRecord   run_id, source_id, timestamp
              agent (story_lead | narration_lead | review_lead | html_author | worker)
              pass_id (A1 … R*), mode, revision_cycle (0 = first pass)
              lane (paid_api | subscription), model_alias, model_resolved
              tokens: input, output, cache_read, cache_write
              billed_usd            # paid lane: from LiteLLM's public response_cost
              notional_usd          # subscription lane: the CLI envelope's total_cost_usd —
                                    #   what it WOULD have cost; never billed; labelled as such
              cache_hit (bool), saved_usd_estimate   # what a hit avoided, at the price table
              latency_ms, attempt, transport_retries, schema_repairs
```

Capture points: the LiteLLM success callback (public `response_cost`, never `_hidden_params`)
and the `claude -p` JSON envelope (`usage`, `modelUsage`, `total_cost_usd`). The `@stage`
decorator stamps `pass_id`, `agent`, and `revision_cycle`, so attribution needs no manual
bookkeeping in stage code. Cache hits emit a record too — with `billed_usd = 0` and the
estimated avoided cost — so savings are visible, not silent.

**Attribution dimensions** (all derivable from the records, all in the report):

| Dimension | Question it answers |
|---|---|
| per **agent** | which identity is expensive — the lever for role↔family A/B |
| per **pass / mode** | is A2 or C2b the cost centre? is C5 firing more than expected? |
| per **stage group** | facts vs planning vs drafting vs review vs revision vs HTML |
| per **revision cycle** | what did fixing the first draft cost versus writing it |
| per **lane** | billed dollars vs subscription quota consumed |
| per **model tier** | did escalation to the strong tier pay for itself |
| **cache** | hits, avoided cost, hit rate per stage |
| **estimate vs actual** | pre-flight estimate, actual, variance — calibrates the estimator |
| **budget position** | run spend vs target / warning / hard cap; day spend likewise |

**Deliverables per run:** `final/cost_report.json` (the full breakdown) and a cost section in
`review_summary.md` shaped like this (numbers illustrative — real figures come from the
configured price table):

```
COST — run 2026-09-10_attention_v03           billed $0.41 · target $0.40 · hard cap $1.00 · est. $0.38 (+8%)

by agent            billed    notional   calls   tokens in/out     cache saved
  story_lead        $0.19        —         3      31k /  9k         $0.11  (A1 hit)
  review_lead       $0.22        —         6      44k / 11k         $0.04  (C2a hit)
  narration_lead       —      $0.31        3      38k / 14k            —
  html_author          —      $0.27        2      29k / 22k            —
  worker               —      $0.06        7      41k /  6k            —
  ────────────────────────────────────────────────────────────────────────
  paid total        $0.41                 9                          $0.15
  subscription         —      $0.64      12   (quota consumed; not billed)

by stage            facts $0.03 · plan $0.16 · draft — · review $0.17 · revision $0.05 · html —
by cycle            first pass $0.36 · revision cycle 1 $0.05
escalations         C5 → fired (voice AMBER) $0.01 · A4 → GPT (PASS_WARN) $0.02
```

**Aggregate across runs:** every report also appends one line to `runs/cost_index.jsonl`
(run id, source, archetype, billed, notional, calls, revisions, status) so cost per script over
time, per source, and per archetype is one query. A small CLI — `costs --run <id>`,
`costs --since 7d --by agent` — reads the index and the records; no dashboard in V1.

**The invariant:** `sum(UsageRecord.billed_microusd) == run_manifest.cost.billed_microusd ==
the budget counter`, reconciled at run end. Money is stored as **integer microdollars**
(`$0.412734 → 412734`), never floats, so reconciliation is exact rather than approximately true. A mismatch fails the run loudly —
a call that spent money without a record is the one failure mode a cost system must not have.

### 4.2 Cache policy — defined once, applied to every model stage

A model stage is not a pure function; it is a typed function of its inputs *and* of everything
that shapes the model's answer. Every stage's cache key therefore includes, from one central
`cache_key()` in `orchestration/cache.py`:

```
input artifact hashes · prompt version · schema version · exact resolved model id
· relevant config (format profile, thresholds) · temperature/seed where applicable
· evidence snapshot where applicable · never a stage's own output
```

**C2a in particular** — the mistake would be "cached by registry hash." A changed model card in
`config/references/` leaves the registry identical while the verification result must change.
So:

```
C2a_key = hash(claim_registry, assumption_ledger, evidence_snapshot,
               verifier_model_id, verifier_prompt_version, verification_schema_version,
               verification_policy_version)
```

When web retrieval arrives (V1B), evidence entries carry URL, content hash, retrieval timestamp,
and a TTL for time-sensitive facts; an expired TTL invalidates the key.

## 5. Data contracts (Phase 1 — before any prompt)

pydantic v2. From design doc §§8, 12, 16–18, 28, 32, 47, plus the entries marked NEW.

```
SourceUnit          id, heading, level, text, equations, diagrams[], callouts[], code[],
                    numbers[], js_literals[], dom_path, structure_confidence
Claim               claim_id, source_unit, claim, type(9), numbers[], assumptions[],
                    mode, stage, scope,
                    importance: CORE | SUPPORTING | OPTIONAL                       ← §5.1 policy
                    provenance_status: SOURCE_EXPLICIT | SOURCE_INFERRED | DERIVED | EXTERNAL
                    verification_status: UNVERIFIED | VERIFIED | CONTEXT_DEPENDENT | REJECTED
                    evidence: VerificationEvidence[]                              ← §6.5
                    derived_from_claim_ids[], inference_kind: NONE | DETERMINISTIC | EXPLANATORY
                      # every derivation or approved inference is a real Claim — a provenance graph
VerificationEvidence kind: SOURCE | CALCULATION | EXTERNAL_REFERENCE, ref, excerpt, verdict
EvidenceRequest     claim_id, what_would_settle_it, suggested_sources[]          ← C2a emits
ArchetypeSpec       archetype, core_roles[], optional_roles[], driver              ← §9
NumericClaim        numeric_claim_id, claim_id (parent), scene_id, expression, variables{},
                    output_unit,                                                   ← unit-aware
                    display_value, display_unit, tolerance, rounding, depends_on[]
AssumptionLedger    typed scalars + memory_units + source-declared constants
SourceBrief         topic, core_question, viewer_problem, central_insight, prerequisites,
                    key_concepts, concept_dependencies, likely_confusions,
                    source_constraints, visual_opportunities, novelty_statement  ← planning field
TitleContract       candidates[], chosen, promise
HookContract        viewer_problem, tension, promise, open_loop, must_not_reveal_yet[]
CTAContract         max_ctas=2, primary_after_beat, intent, end_after_final_payoff   ← §5.2
StoryBeat           beat_id, purpose, archetype_role, archetype_stage, source_unit_ids,
                    viewer_question_before, answer_or_payoff, next_question,
                    learning_objective, forward_driver,                           ← NEW §10.2
                    beat_function, new_information, payoff, visual_mode_change,
                    question_progress, concept_density                            ← observable
MiniPayoff          after_beat, payoff, opens
EndingContract      resolve_hook, compressed_mental_model, capstone_payoff,
                    viewer_can_now, next_video_bridge
StoryPlan           archetype, selection_reason, source_evidence[], rejected_archetypes{},
                    story_promise, central_question, question_chain[], title, hook, cta,
                    beats[], mini_payoffs[], ending, scene_plan[]
ScenePlan           scene_id, beat_id, archetype_role, narrative_beat, engine, narrative_job,
                    visual_importance, visual_description, word_budget, components[],
                    semantic_objects[]                                            ← §12
SentenceNarration   text, sentence_type (writer metadata), claim_refs[],
                    grounding_required (set by the claim mapper, not the writer),
                    grounding_refs[]                                             ← §5.1
SceneNarration      scene_id, sentences[], est_seconds
CritiqueIssue       issue_id, severity, category, layer, scene_ids, problem,
                    why_it_matters, recommended_intent, repair_owner
EditMap             per changed sentence: before, after, change_type               ← B4 output
ReviewBundle · RevisionPlan · RenderReport · QualityReport · SeriesLedger · PipelineState
UsageRecord · CostReport                                                       ← §4.1
HookEvent · ShortsCandidate · ShortPlan (micro_arc, short_goal, bridge.mode)        ← §20.5
```

Typed enums earned by evidence: `Claim.mode` (inference/full-training/LoRA/QLoRA),
`Claim.stage` (prefill/decode/both), `Claim.scope` (universal/model/example/implementation),
`CritiqueIssue.layer` (source/story/narration/voice/visual/renderer/technical).

### 5.1 Grounding is decoupled from the writer's labels

```python
sentence_type: Literal["technical_assertion", "source_paraphrase", "explanatory_inference",
                       "analogy", "transition", "question", "payoff", "cta"]   # metadata only
```

The writer labels every sentence and attaches `claim_refs` where it can — useful metadata for
prioritising review. **It is not the security boundary.** A factual statement mislabelled as
`explanatory_inference` or `analogy` must not escape grounding because Sonnet said so.

So an independent **Claim Mapper** (CM — its own cross-family pass, run before the review
block so C1, C2b, C5 and C6 all see its output) reads *every*
narration sentence, marks each factual proposition `grounding_required = true` regardless of
its label, and maps it to registry claims (`grounding_refs`). C2b then verifies every
grounding-required sentence — **and independently checks whether CM missed any factual
proposition.** C2b receives the raw narration, CM's output, and the verified fact set; it does
not trust CM's coverage. *CM accelerates grounding; C2b owns grounding completeness.* CM is a
speed-up, never a single point of failure.

**One grounding policy, by claim importance** (the same rule in §6.5, §9 and §15):

| `importance` | May be narrated when `verification_status` is |
|---|---|
| `CORE` | `VERIFIED` or `CONTEXT_DEPENDENT` (hedge present) — only |
| `SUPPORTING` | `VERIFIED` or `CONTEXT_DEPENDENT` by default |
| `OPTIONAL` | additionally `UNVERIFIED`, **only** with an explicit hedge |

Always: `UNVERIFIED` never in the hook, the central insight, a central payoff, the ending, or
an important numeric result. `REJECTED` is never narrated. This is what makes the phrase
"technically verified video" defensible.

Transitions, questions and payoffs that carry no factual proposition need nothing — "That's the
strange part" passes because the mapper finds no proposition in it, not because it was labelled
a transition. This is what makes the no-fabrication rule (§6.4) enforceable.

### 5.2 CTA contract

From `feedback.md`: *the payoff earns the ask.*

**Hard:** never inside the hook; never before the first meaningful payoff; ≤2 spoken CTAs;
never interrupting a high-tension explanation (a beat whose `forward_driver` is unresolved and
`question_progress` is `none`).

**Default (soft):** primary CTA after a strong payoff at ~20–40%; short; the next beat resumes
immediately; end sequence `final payoff → viewer capability → CTA → bridge`.

**Intent:** `VALUE_LINKED` (default, per `feedback.md`: names the payoff just delivered and the
channel promise) · `SERIES_LINKED` · `CHANNEL_PROMISE` · `MINIMAL`. A2 chooses; the Narration
Lead writes it in the script's voice so it doesn't become an audible template. C1 judges fit.

### 5.3 Series ledger

`config/series/<id>.yaml`: shared assumptions, terms already taught, hooks/analogies used,
per-video `viewer_can_now`, and **which shorts point at which video** (§20.5). Cross-video
assumption consistency; "already defined in 1.1"
warnings; bridges that are consequences, not adverts.

---

## 6. Extraction and the factual inventory

### 6.1 Profiles + generic fallback

Pluggable profiles in `config/extraction_profiles/` (*video-script*, *guide*); generic
`h1–h3` fallback for anything else; every unit carries `structure_confidence`. Strip nav,
chrome, presentational wrappers.

### 6.2 JS literal extraction — parse, never execute

`node:vm` is not a security boundary. The JS data-model extractor uses **Acorn** to build an
AST, locates top-level `const`/`let` declarations, and evaluates only literal-safe nodes
(`ObjectExpression`, `ArrayExpression`, string/number/boolean literals, unary minus on numbers,
expression-free template literals). Calls, functions, constructors and member access are
rejected. Output is JSON; nothing runs.

Scalar constants (`HIDDEN`, `LAYERS`, `PARAMS`…) seed the `AssumptionLedger`. Formula strings
(`'7.61B × 2 bytes'`) are parsed into unit-aware `NumericClaim` records:

```json
{"expression": "params * bytes_per_param",
 "variables": {"params": 7.61e9, "bytes_per_param": 2}, "output_unit": "byte"}
```

Conversion to GB/GiB happens in formatting code with the ledger's `memory_units`, never inside
the expression.

### 6.3 Order: facts before interpretation

```
S0   deterministic extraction (DOM + JS literals + visual inventory)
S2a  deterministic seeds: numbers, equations, JS constants, formulas     [Python]
S2b  claim extraction over ALL source units, batched by unit group        [Haiku]
S2c  normalize, dedupe, link numbers → claims, build ledger               [Python]
S1   narrative digest (only if source > ~12k tokens)                      [Haiku]
A1   source understanding — receives digest + full claim registry +
     equations + number registry + ledger + verbatim spans                [GPT strong]
A2   plan                                                                 [GPT strong]
```

The registry is the **complete source-assertion inventory**; the **verified fact set** (§6.5) is
the factual authority for planning and narration; the digest is for comprehension. A detail can no longer
vanish because a summarizer dropped it before the claim pass ran.

### 6.4 Input tiers and the no-fabrication rule

Tier A clean/in-system (the raw inputs) · Tier B structured/other markup (the guides) ·
Tier C rough (generic fallback). Behaviour scales with `structure_confidence`.

> Every factual proposition in the narration must be traceable to one of: a **verified source
> assertion**, a **deterministic derivation** from verified values, **verified external
> evidence**, or an **explanatory inference C2b judges safe** (`SAFE_INFERENCE`, as in the design
> doc's §29) — which C2b then **materializes as a real Claim** (`inference_kind: EXPLANATORY`,
> `derived_from_claim_ids`), never leaving it as an informal verdict. Never to nothing. Word count grows through explanation, causal scaffolding, worked
> examples and restatement of those — never through an untraceable technical claim. If the
> source cannot support the target duration, fail with a coverage report; do not pad.

Enforced through §5.1: every mapper-identified factual proposition maps to one of those four
grounding sources.

---

### 6.5 Source registry ≠ verified fact set

The registry records **what the source says**. It is not the truth. The input HTML can be
wrong, outdated, or internally inconsistent, and S2b uses a model to infer claims from it. So
correctness is a second, separate dimension:

```
                 SOURCE CLAIMS  (S2a–S2c: what the HTML asserts)
                       │        provenance: SOURCE_EXPLICIT | SOURCE_INFERRED | DERIVED
                       ▼
        ┌──────────────┼──────────────┐
   Python math    evidence lookup    Gemini C2a
   (CALCULATION)  (SOURCE /          (reasoning over
                   EXTERNAL_REFERENCE) evidence)
        └──────────────┼──────────────┘
                       ▼
              VERIFIED FACT SET    verification: VERIFIED | CONTEXT_DEPENDENT |
                       │                         UNVERIFIED | REJECTED
                       ▼
         A1 understanding → A2 planning → B1 narration
                       │
                       ▼
        C2b  Claim Mapper → grounding verification of the narration
```

**C2a `VERIFY_SOURCE_CLAIMS`** runs *before* planning and is cached by the §4.2 key (registry +
ledger + evidence snapshot + model + prompt + schema + policy) — paid once per source *and*
evidence state. For each claim it returns a verification status and the evidence it relied on. For
stable arithmetic, Python is the evidence. For architecture details, framework behaviour,
library semantics, GPU specs, or version-specific implementation facts, C2a may emit an
`EvidenceRequest`; a small **Evidence Broker** in the orchestrator (`facts/evidence.py` — a
component, not an agent) fulfils it and re-presents the claim with evidence attached:

- **V1A:** `SOURCE` and `CALCULATION` evidence, plus `EXTERNAL_REFERENCE` from a curated local
  `config/references/` (model cards, spec sheets, docs you drop in).
- **V1B:** web retrieval for unfulfilled requests.
- **Unfulfilled requests leave the claim `UNVERIFIED`** — visible in the plan and the report.
  Narration may use an `UNVERIFIED` claim only if its `importance` is `OPTIONAL` and an explicit
  hedge is present, and never in the hook, central insight, central payoff, ending, or an
  important numeric result (the single policy in §5.1). `REJECTED` claims are never narrated;
  the planner is told why.

"Technically verified" therefore means exactly what the attached evidence supports — never
"Gemini agrees with the uploaded HTML."

## 7. Design system — explicit in V1

One channel component library, one theme, story-role → component mappings, **manual**
component additions. `config/design_system.yaml` holds tokens, the base template lifted from
the samples, and a component catalogue with markup skeletons and story roles. It is swappable
config; it is not induced automatically. Automatic fitting from arbitrary references is V1D.

| Story role | Components (from the current library) |
|---|---|
| hook / expectation | hero block, concrete-contrast row |
| contradiction / failure | danger callout, before/after row |
| suspects / investigation | suspect list, elimination grid |
| problem → fix chain | step list, warn callout |
| mechanism / reveal | solution card, hero diagram, math block |
| comparison | 2-up grid, metric table, tradeoff card |
| derivation step | math block, annotated formula |
| observations | card grid, definition box |
| payoff | payoff section, success callout |

---

## 8. Pipeline

Plain `async` Python with a `@stage` decorator (cache, artifact write, checkpoint, cost
accounting, skip-if-cached) — no LangGraph. The route is known in advance (design doc §§4, 84);
loops are bounded counters; state is one pydantic model whose JSON dump is the checkpoint;
parallel review is `asyncio.gather`. Every stage has **explicit typed inputs and controlled side
effects** (an LLM stage is not literally pure — §4.2 says what its cache key must therefore
contain), which is the migration insurance if model-decided routing is ever needed.

```
S0 → S2a → S2b → S2c → C2a verify source claims (cached per source; evidence requests
     fulfilled by the orchestrator) → S1 → A1 → A2 (assert archetype != auto) → B1

CM  Claim Mapper — marks every factual proposition grounding_required,
    attaches candidate refs; output visible to C1, C2b, C5, C6   [Gemini flash]

   ┌──── parallel, independent ────────────────────────────────┐
   C1 story critic                                [Gemini strong]
   C2b grounding verification over CM output      [Gemini strong]
   C5 style critic — only if voice bands AMBER/RED [Gemini flash]
   V* deterministic hard checks                   [Python]
   D* diagnostics: voice bands, R1 retention,
      learning lint, CTA position                 [Python + Haiku lint]
   C4c mid-video cold viewer — Haiku first; Gemini on flag / low
      confidence / benchmark / 20% sample            [Haiku → Gemini flash]
   └───────────────────────────────────────────────────────────┘
                     ▼
              review aggregator → ReviewBundle (hard failures · graded diagnostics)
                     ▼
   ROUTE (deterministic, §15):
     critical/major story or technical  → A3 revision plan → B2 targeted rewrite
     precision-only                     → B3
     voice diagnostics RED or C5 major  → B4 humanize → number diff → C6 entailment on
                                           every changed sentence the mapper marked
                                           grounding-required → voice diagnostics
     nothing                            → skip all of the above
   re-run only affected checks (§15)

H  HTML synthesis            [Sonnet]    ── HV static + render checks [Python/Playwright]
   └─ structural failure → H REPAIR (≤2)        C3 screenshot audit, flagged scenes [Gemini flash]

C4 cold viewer on the FINAL opening — Haiku first; Gemini on flag / benchmark / sample
POLICY GATE — deterministic final status from hard checks + unresolved criticals (§14)
A4 editorial summary — Python + Haiku on clean PASS; GPT mini on PASS_WARN, exhaustion or
   benchmark. May add warnings or downgrade; may not clear a failure.
R* emit final/, review_summary.md, retention_map.json, run_manifest.json
```

---

## 9. Hard gates — few, mechanical, non-negotiable

A hard gate fails the run (or forces a bounded revision). Nothing here is a judgement call.

| Gate | Fails on |
|---|---|
| **Factual** | a verified calculation is wrong; a critical technical contradiction stands; a factual proposition (found by CM *or* by C2b's completeness check) maps to no claim, to a `REJECTED` claim, or to an `UNVERIFIED` claim outside the §5.1 policy (non-`OPTIONAL`, unhedged, or in hook / central insight / payoff / ending / important number); an assumption/unit mismatch |
| **Structural story** | archetype unresolved (`auto`); title promise unrelated to the hook or the hook promise unpaid by the ending; a **core role** of the resolved archetype absent (optional roles are diagnostics — see below); a scene with `archetype_role` and no bridge |
| **Source coverage** | target duration requires content the registry cannot support |

**Core vs optional roles** (`ArchetypeSpec`). The design doc's fixed-archetype rule says stages
adapt to the source rather than fabricating content, so only the structural logic is hard:

| Archetype | Core (hard) | Optional (diagnostic) |
|---|---|---|
| mystery | expectation · contradiction · mechanism · resolution | suspects · investigation steps |
| build | desired capability · ≥1 problem→solution pair · assembled system | further limitation/fix rounds |
| experiment | decision question · baseline · ≥1 method+result · decision rule | second method · tradeoff table |
| derivation | real problem · ≥1 justified step · usable result | concrete example · simplification step |
| foundation | ≥1 prerequisite→capability link · capstone | intermediate concepts |
| framework | organizing principle · ≥1 useful distinction · compressed model | groupings |
| **Learning (structural part)** | no `central_insight`; a major beat with no `learning_objective`; `viewer_can_now` not reachable from the beats' objectives |
| **CTA (hard part)** | CTA in the hook, before the first payoff, >2, or inside an unresolved high-tension beat |
| **Render** | invalid HTML; a scene missing or out of order; narration mismatch; a `data-numeric-claim-id` whose value ≠ registry; clipping that hides required content; `renderer_compat` (Gate 1) |
| **Humanize safety** | number diff non-empty; `claim_refs` changed; C6 finds a changed technical sentence not entailed by its original |

Independence: **the final status is a deterministic policy over these gates and unresolved
critical findings.** A4 writes the editorial summary and can downgrade a pass; it cannot
clear a failure raised by C2a, C2b, V*, or C6.

---

## 10. Diagnostics — many, graded, advisory

Every diagnostic reports **GREEN / AMBER / RED** against a band, with evidence
(*"burstiness 0.31 vs band 0.47–0.63; 14 consecutive sentences within ±3 words, scenes 7–11"*).
They are inputs to A3, B3, B4 and to `review_summary.md` — not publication gates.

**Escalation, so "advisory" doesn't mean "ignored":** ≥3 RED diagnostics across dimensions, or
a RED that survives a revision round, routes to targeted revision (A3/B3/B4) instead of
`PASS_WITH_WARNINGS`. On loop exhaustion the best candidate ships with the report; soft
signals never hard-fail.

### 10.1 Story and pedagogy
causal-bridge quality on archetype-role scenes · concept-before-motivation · generic
transitions · cognitive-load (open concepts) · term classification vs `audience.assume` ·
"too obvious for this audience?" (C1) · knowledge-delta triviality (Haiku lint, escalates
only).

### 10.2 Retention — archetype-aware forward drivers

Replace "an open loop at every point" with a **forward driver** the archetype defines:

| Archetype | Driver | Tracked stages | Failure signature |
|---|---|---|---|
| mystery | unanswered cause | expectation → contradiction → evidence → suspects narrowed → mechanism → resolution | investigation makes no progress |
| build | unresolved capability / limitation | capability → problem → fix → new limitation → fix → assembled | a component appears without solving anything |
| experiment | unresolved decision | question → baseline → method → result → comparison → rule | long method with no result |
| derivation | unresolved mathematical goal | goal → simplify → step → meaning → next step → usable result | algebra without intuition or progress |
| foundation | dependency toward capstone | prerequisite → capability unlocked → … → capstone | concepts don't increase explanatory power |
| framework | remaining organizing dimension | principle → distinction → accumulated model | observations become a list |

Diagnostics: driver present in every beat · driver progresses at least every N beats ·
**payoff gap** > ~75–90 s with no state change · **valley** = consecutive beats with
`new_information = false`, `payoff = false`, `visual_mode_change = false`,
`question_progress = none` (observable fields, no numeric energy) · hook **promise** paid by
the end (partial payoffs earlier are allowed — no artificial withholding) · central **value**
previewed early, central **answer** placed where the archetype earns it (mystery: delay the
mechanism; derivation: delay the expression; build: capability first, system last) · tension
reached inside ~30 s · C4c mid-video cold viewer: "do you know why this is being discussed?".

### 10.3 Subscribe
CTA position vs 20–40% · intent fit · length · resumes into the next beat (C1 judges).

### 10.4 Voice — see §11.3.

### 10.5 Visual (from HV) — sparse scene · key visual small · layout repetition · density.
Warn; feed C3.

---

## 11. Human voice

### 11.1 Tells (evidence for C5, not laws)
uniform rhythm · opener monoculture · rhetorical-question chains · symmetry addiction ·
filler epistemics · even emphasis · no stance · no specificity · screen-reading.

### 11.2 Two fingerprints, fitted
`voice/narration.yaml` from transcripts (governs B1/B4) and `voice/onscreen.yaml` from approved
output HTML (governs H's screen copy). Measured: they differ 27× on concrete density and 20×
on "we"; applying one to the other is the error this exists to prevent. Fitted narration medians
(6 clean transcripts): mean sentence 22.0 · burstiness 0.52 · contractions 1.78/100w ·
"we" 1.92/100w · questions 1.6/100 sentences · causal connectives 1.04/100w · hedges ~0.
`tools/voice_fit.py` is the working fitter. The transcripts are other people's voices — a
reference band; the channel's own approved scripts, once there are enough, fit a fingerprint
that takes precedence.

### 11.3 Bands, not thresholds

```yaml
opener_max_share:   {green_max: 0.11, amber_max: 0.17, red: above}   # human range 6.1–16.4%
burstiness:         {green: [0.47, 0.63], amber: [0.40, 0.75], red: outside}
hedge_per_100w:     {green_max: 0.05, amber_max: 0.15}
similar_length_run: {green_max: 6, amber_max: 10}
```

Every band is fitted from the corpus by the fitter, so **no band can reject a document in the
corpus that defined it**. Burstiness, variance, short-sentence share, opener diversity,
contractions, address, question rate: all advisory (§10 escalation applies).

### 11.4 B4 humanize — conditional and guarded
Runs only if voice diagnostics are RED or C5 reports a major issue. Emits an `EditMap`.
Guards: number diff empty → `claim_refs` unchanged → **C6 entailment check (Gemini flash)** on
every changed sentence the claim mapper marked `grounding_required` — whatever the writer
labelled it: *does AFTER preserve the meaning of
BEFORE and its linked claims?* ("grows with tokens" → "grows quadratically with tokens" fails
here and nowhere else) → voice diagnostics re-run. Any guard failure rejects the pass.

### 11.5 C5 style critic + corpus hygiene
C5 (`STYLE_CRITIC`) sees narration only and returns `{scene_id, sentence, category, severity}`
with categories `uniform_rhythm · generic_transition · symmetry · filler_epistemic ·
screen_reading · overexplaining · rhetorical_question_chain · weak_specificity ·
machine_like_repetition`. It diagnoses style; it never claims authorship.
Corpus gate: sentences ≥20, mean <40 words, terminal punctuation ≥1/60 words; failures
quarantined; Haiku restoration inserts punctuation only, verified by word-sequence identity.

### 11.6 Human anchors
`manual.lock_hook`, `lock_scene_ids` (design doc §72): critiqued, never rewritten; the locked
hook is the in-context voice exemplar for B1/B4.

---

## 12. Stage H — HTML synthesis

### 12.0 One page, two audiences — the dual-audience contract

The output HTML is read by two consumers with different needs, and it must satisfy both
**without looking like it was made for the other**:

| | The reader (your website) | The renderer (the video pipeline) |
|---|---|---|
| sees | a complete, story-driven article in the channel's design system — hero → sections → callouts → payoff, exactly the shape of the sample pages | one `<section>` per scene, in order |
| reads | **screen prose** in the on-screen voice profile (`voice/onscreen.yaml`) — enough that the page stands alone | **narration** in the spoken profile, from the embedded JSON block |
| numbers | rendered normally | `data-numeric-claim-id` on each, verified against the registry |
| visuals | diagrams, cards, callouts as in the samples | the same, with `visual_importance` driving scene dominance |
| never sees | narration text, claim ids, scene metadata — all invisible in a browser | — |

The sample pages already work this way: `video-1.1` carries 1,992 words of *visible* prose and
was both a published page and a video source. Screen prose and narration are **different
text** (playbook §30: narration must not read the screen; §11.2: the two fingerprints differ
27× on concrete density) — the page explains in writing, the voice explains in speech, and
they complement rather than duplicate.

**Requirements this adds:**

- **Reader-standalone test (HV):** strip the narration block and every `data-*` attribute, and
  the page must still pass an article check — every scene has visible prose, not just a heading
  and a diagram; visible word count sits in the article band (the samples: ~2,000–3,200); the
  hero states the problem; the payoff section closes it.
- **Readable grouping:** a 10-minute video has ~30 scenes, and thirty `<h2>`s would read as
  choppy. Scenes group under **beat-level visible headings** (`<h2>` per beat, scenes as
  sub-blocks) — the renderer reads scene sections; the reader sees 6–10 headings, as in the
  samples.
- **Self-contained file:** inline CSS/JS, assets embedded or relative, so it drops into a
  static site folder next to the existing pages with no build step.
- **Two files from one build:** `video_script.html` (full render metadata) and
  **`page.html`** (identical visible content, narration block and `data-*` attributes stripped —
  for publishing, so spoken narration isn't sitting in your page source). A deterministic
  transform; HV asserts the two render pixel-identically at 1920 and 390 px.
- Reveal-on-scroll and declarative interactive components stay, as in the samples.

**Measured spec:** raw → output is +25–65% words (claim-backed), 30–43 → 41–83 component
classes, **0 → 1–8** archetype components, causal connectives 0.65 → 1.09/100w.

- Assembly from the loaded library by story role; new components are manual (V1).
- One `<section id="scene_NN_slug">` per scene.
- **Numbers only from the registry, annotated:** `<span data-numeric-claim-id="N004">15.2 GB</span>`.
  Interactive content is a declarative `<script type="application/json">` block, never logic.
- **Narration is not in attributes.** Sections carry `data-narration-id`; a single
  `<script id="narration-data" type="application/json">` block embeds the text; `narration.json`
  is canonical and the embed carries its hash.
- **Continuity is semantic:** `ScenePlan.semantic_objects` with
  `{semantic_object_id, continuity: continues_from_previous | new | transforms}`; the renderer
  implements persistence if it can. No assumption that matching element ids animate.
- Visual weight follows `narrative_beat` / `visual_importance`; deictic narration must resolve.
- Batched by act.

---

## 13. Stage HV — render verification

**Hard (static):** HTML parses; unique ids; every scene present in order; narration-data hash
matches `narration.json`; every `data-numeric-claim-id` exists and its value matches the registry;
required numeric claims are traceable to the DOM; JS data blocks re-validated; deictic refs
resolve; `renderer_compat` (Gate 1); **reader-standalone check** and **`page.html` visual
parity** (§12.0). **Safety net (warn):** a regex sweep for unit-bearing
numbers with no `data-numeric-claim-id` — reported, not gated, so an unannotated "15.2 GB" cannot
slip through silently while "Video 1 of 3" and "Qwen 2.5" cause no noise.

**Hard (rendered, Playwright 1920×1080 + 390 px):** clipping, overflow, invisible required
content, contrast below readability. **Warn:** sparse scene, key visual small, layout
repetition, density → feed C3.

**C3** (Gemini flash, ≤8 images): flagged scenes + 20% sample — does the screen show what the
narration says, at the right weight? Structural failures → H REPAIR (≤2), never a paid model.

---

## 14. Final status policy

```
Evaluated in order; the first match wins:
FAIL          any §9 hard gate; or a critical C2a/C2b/V* finding unresolved after budgets
REVISE        no hard failure; §10 escalation criteria met; budget remains
PASS_WARN     no hard failure, no pending escalation; ≥1 unresolved RED, or more than
              `pass_amber_allowance` AMBERs (default 3), or any AMBER in a
              high-impact dimension (factual hedging, story structure)
PASS          no hard failure; no unresolved RED; AMBERs within the allowance
A few AMBERs still count as PASS on purpose — otherwise nearly every human script is PASS_WARN.
```

A4 then writes the editorial summary and may downgrade `PASS → PASS_WARN` or `PASS_WARN →
REVISE` with reasons; it may not upgrade. The playbook's ten approval questions ship as a
checklist; 3, 4, 7, 9 map to hard gates.

---

## 15. Routing and budgets

| Finding | Route |
|---|---|
| technical / numeric | targeted correction → B2 |
| source claim `REJECTED` by C2a | A2 plans around it; narration never uses it; noted in the report |
| claim left `UNVERIFIED` (no evidence found) | narration hedges it or B2 removes it; never in hook/ending |
| mapper finds an ungrounded proposition | B2 grounds it to a claim or removes it — never invents one |
| verbose / repetitive only | B3 |
| voice RED or C5 major | B4 → guards |
| weak payoff / driver stalls / valley cluster | A3 → B2 (move a question, result or example earlier — never fake drama) |
| arc broken / archetype wrong / title unpaid | A2 re-plan (≤1) |
| CTA hard violation | A2 re-places; B2 rewrites the sentence |
| HTML structural / render | H REPAIR — never B2, never a paid model (playbook §39) |
| clean | skip every revision stage |

Re-verify only what changed (design doc §70): prose → C1 with a scoped payload + diagnostics; technical
sentence → C2b + numeric; beats → C1 + C2b + R1 + H + C3 + C4c; assumption → dependent numerics
+ C2a + C2b + HV; voice → guards + diagnostics; HTML → HV + C3.

`MAX_STORY_REPLANS=1 · MAX_MAJOR_REVISIONS=2 · MAX_PRECISION_EDITS=2 · MAX_HUMANIZE=2 ·
MAX_HTML_REPAIRS=2 · MAX_SCHEMA_REPAIRS=2`. On exhaustion: best candidate + report.

**When a capability fails, the response is classed in advance:**

| Class | Rule | Applies to |
|---|---|---|
| **Fail closed** | continuing could silently violate an invariant | numeric validator, C2a/C2b, CM, C6, HV static checks, traceability, the policy gate |
| **Retry** | transient | 429 / timeout / 5xx on either lane; schema repair ≤2 |
| **Degrade visibly** | capability is optional; absence is recorded in `run_manifest.json` and `review_summary.md` and forces at most `PASS_WARN` | C5 style critic, C3 visual audit (only while HV static checks pass), Gemini cold-viewer tier, A4 editorial summary (Haiku fallback), Evidence Broker web retrieval (claim stays `UNVERIFIED`) |

A degraded run must *look* degraded. A run that silently skipped its style critic and reported
`PASS` is a manifest that lies.

---

## 16. Artifacts and layout

**Run root, superseded by ADR D12:** the tree below is written under
`project/<playlist>/<video_slug>/runs/vNN/`, not a standalone `runs/<id>/` —
`vNN` plays the role `<id>` played here, and `<video_slug>/final/` is the
promoted copy of whichever run's `final/` last reached PASS/PASS_WARN
(`orchestration/paths.py`). The internal shape below is unchanged.

```
runs/<id>/  input/ extraction/ facts/{claims,numbers,assumptions}.json analysis/ planning/
            drafts/narration_v0N.json reviews/{story,technical,style,voice,retention,learning,
            cold_viewer_mid,cold_viewer}.json revisions/ html/{v0N.html,render_report.json,
            screenshots/} final/{video_script.html,page.html,narration.json,plan.json,script.md,
            shorts/<k>/{short.html,narration.json,short_plan.json,quality_report.json,
                        cost_report.json,screenshots/}}
            # long-form: video_script.html (render source) + page.html (publishable article,
            #   identical visible content, metadata stripped); each short: its own short.html
            quality_report.json,review_summary.md,retention_map.json,cost_report.json}
            usage.jsonl                             # one UsageRecord per call, both lanes
            run_manifest.json                       # models, prompt versions, archetype
                                                        # in/out, fingerprint id, analytics
                                                        # schema (null until connected)
src/
├── extraction/    html_parser.py unit_extractor.py js_literal_extractor.py (acorn bridge)
│                  visual_extractor.py profiles/
├── facts/         seeds.py claim_extract.py normalize.py ledger.py verify.py evidence.py
├── agents/        base.py story_lead.py narration_lead.py review_lead.py html_author.py worker.py
├── prompts/       <agent>/<mode>.md              # versioned
├── planning/      planner.py archetypes.py drivers.py hook.py title.py cta.py components.py
├── narration/     generator.py humanizer.py
├── voice/         corpus.py fingerprint.py metrics.py bands.py
├── html/          synthesizer.py component_library.py templates/
├── review/        story_critic.py source_verifier.py claim_mapper.py grounding_verifier.py
│                  style_critic.py entailment.py
│                  visual_auditor.py cold_viewer.py aggregator.py
├── verification/  hard/{numeric,units,schema,traceability,structure,coverage,render}.py
│                  diagnostics/{story,retention,learning,cta,voice,visual}.py
│                  playwright_runner.py
├── editing/       revision_planner.py precision_editor.py
├── orchestration/ pipeline.py routing.py state.py policy_gate.py cache.py
├── llm/           client.py structured.py budget.py usage.py   # usage.py = UsageRecord capture
│                  backends/{claude_cli.py, litellm_backend.py}
├── reporting/     quality_report.py review_summary.py cost_report.py cost_cli.py
└── config/        models.yaml budget.yaml channel_style.yaml forbidden_patterns.yaml
                   design_system.yaml archetypes.yaml voice/ series/ extraction_profiles/
                   references/        # curated evidence for EXTERNAL_REFERENCE (V1A)
```

---

## 17. Rollout — prove the story thesis before the platform

| Stage | Adds | Proves |
|---|---|---|
| **V1A Script intelligence** | S0–S2, **C2a with local references**, A1, A2, B1, C1, **C2b claim mapper + grounding**, cascaded C4/C5, V* hard checks, diagnostics, conditional A3/B2/B3/B4 + C6, policy gate, conditional A4, `final/narration.json` + `script.md` | a rough HTML becomes one coherent, verified, human-sounding script; every mutation test caught |
| **V1A-S Shorts slice** *(after V1A passes; depends on it, kept out of it)* | SC, A2s, short profile, C1s, cold-hook critic, short diagnostics, `narration.json` for a derived short (§20) | a short derived from a successful V1A output is grounded within the parent's fact set, has one central insight, and its hook event lands ≤3 s |
| **V1B HTML** | H, HV static checks, `data-numeric-claim-id` traceability, narration embed, **web retrieval for evidence requests**, **vertical shorts template, safe zones, HV at 1080×1920** | `video_script.html` passes structure + traceability + `renderer_compat` |
| **V1C Visual loop** | Playwright, screenshots, C3, H REPAIR, **TTS preview for shorts → measured-duration gate** | render failures caught and repaired on the subscription lane |
| **V1D Calibration** | voice-corpus restoration + refit, retention-band tuning, series ledger automation, design-system fitting, measured-audio WPM, analytics feedback | bands tighten against the channel's own data |

Phase 0 (both backends, budget policy, **usage ledger + reconciliation**, cache, leak test)
precedes V1A. V1A's "done" includes a `cost_report.json` whose totals reconcile to the manifest. Contracts (§5) precede
prompts.

---

## 18. Evaluation

**Benchmark:** the sample outputs as gold; compare archetype, beats, driver progression,
numeric accuracy, voice distance, human preference. **Voice held-out:** fit on 4 transcripts,
hold out 2; held-out humans must land GREEN/AMBER. **Mutation tests** (each names its catcher):
`15.2→12.2` in narration → numeric; in HTML → `data-numeric-claim-id` check; GB→GiB → units;
motivating scene deleted → C1; fake contradiction → C1; phantom visual → deictic/C3; CTA in hook
→ hard CTA; O(N)→O(N²) → C2a/C2b; prefill→decode → C2b (`stage`); **a wrong claim in the source HTML itself → C2a `REJECTED`, planner told**; **factual sentence labelled `analogy` → claim mapper still grounds it**; uniform 20-word rhythm → voice
band RED + C5; "grows quadratically" after B4 → **C6**; hero diagram at 15% → HV warn → C3;
`node:vm`-style dynamic JS in source → extractor rejects, run continues; a scene with a heading
and a diagram but no visible prose → reader-standalone check; `page.html` differing visually
from `video_script.html` → parity check; term redefined → series
ledger. **A/B:** rotate role↔family on the same rubric; never on vibes.

**Repeated-run stability** — quality includes variance. Benchmark mode runs one source
(Attention) × 20 with S0–C2a cached, and reports: archetype-selection stability (a flip between
`build` and `foundation` on identical input is a planner defect), critical-error rate, revision
frequency, story-score variance, cost variance, and human preference across runs. Budgeted
against the daily cap as a named benchmark run.

**Cost-accounting tests** — every call yields exactly one `UsageRecord` (both lanes, including
cache hits and failed attempts); `sum(billed_usd)` reconciles to the manifest and the budget
counter; a cache hit records `billed_usd = 0` with a non-zero `saved_usd_estimate`; a
subscription record never carries `billed_usd > 0`; per-agent totals sum to the run total.
Mutation: suppress one LiteLLM callback → reconciliation must fail loudly, never silently
under-report.

**Shorts mutations** (§20) — hook event after 3 s → RED `time_to_hook`; setup past 10 s →
RED; a second *central* insight → hard gate (an intermediate micro-payoff must pass); CTA
before value → hard; derived short with no parent reference → hard; a proposition outside
`allowed_fact_ids` → C2b fails; title semantically unrelated to the payoff → alignment gate;
duration estimate 70 s → hard; word count 180 with duration 58 s → advisory only, must *not*
fail; short inheriting the parent's `build` roles verbatim → C1s "compressed lecture".

---

## 19. Decisions and needs

**Decisions:** deliverable is `video_script.html` with canonical `narration.json` · five
identities, conditional passes · Sonnet/Haiku via `claude_cli.py`, never LiteLLM · budget policy
local · facts before interpretation · literal-AST JS extraction · explicit design library in V1
· hard gates mechanical, diagnostics graded with cluster escalation · A4 editorial only ·
archetype-aware forward drivers · CTA hard/soft split with `VALUE_LINKED` default · B4
conditional with C6 entailment guard · `data-numeric-claim-id` traceability with a warning-level sweep ·
V1A–D rollout.

**Inputs needed at implementation time (not now — this is a plan):** an OpenAI key and a Gemini key in `.env` (§3.3) · budget tiers (§4 defaults proposed) · first-run source
and target duration · whether `docs/corpus/raw_inputs/` and `docs/corpus/transcripts/` are gitignored (transcripts are
third-party) · optionally, reference docs for `config/references/` and a Tier-C rough sample.

**Risk, stated plainly:** the subscription lane's quota window is deliberately loaded; the
pipeline stops and resumes rather than failing over. A benchmark sweep may span more than one
window. That is the right trade.

---
## 20. Shorts and reels — derive the knowledge, not the storytelling

A short is a different product that shares the long-form's *verified infrastructure*. It
inherits the parent video's **facts** — never its **story shape**. The parent supplies truth,
context, assets and technical scope; the short planner independently decides what single
insight to teach, how to hook it, which micro-arc fits, how fast to reveal, and whether to
bridge. *Different product semantics do not require duplicated architecture.*

### 20.1 What a short is for

| Outcome | Long-form | Short |
|---|---|---|
| **Reach** | secondary | primary for `DISCOVERY` — new viewers who don't know the channel |
| **Bridge** | next-video bridge at the end | primary for `BRIDGE` — a payoff that naturally exposes the larger question the long-form answers |
| **Series** | series ledger | primary for `SERIES` — the viewer recognises one piece of a larger technical series |
| **Subscribe** | earned mid-video | optional, only after value, ≤8 words |
| **Learn** | a capability | **one central insight** |
| **Stay** | forward driver, no valleys | the interesting *event* happens immediately |
| **Story** | one archetype, full arc | a **short-native micro-arc**, chosen per short |

`short_goal` is chosen per short by the planner (`channel_style.shorts.default_goal` sets the
lean; `DISCOVERY` is a reasonable default for a growing channel). All three grow the channel;
they grow it differently. The series ledger records every short's goal and parent; the
analytics schema carries short metrics (views, swipe-away, click-through, attributed
subscriptions) — null until connected, and the only real source of swipe behaviour.

### 20.2 What inherits, what doesn't

| Inherits from the parent run | Chosen fresh by the short planner |
|---|---|
| verified fact set, claims, assumptions, terminology, technical scope | `short_goal` |
| visual assets and the design library | central insight |
| series identity; `parent_video_reference` (required for derived) | **micro-arc** |
| cost accounting (`format: short`, `parent_run_id`) | hook event, reveal speed |
| — | bridge mode |
| **not** the archetype, CTA logic, rhythm, ending structure, or pacing | ending (usually: the payoff, then stop) |

### 20.3 Micro-arcs (short-native story grammar)

```python
micro_arc: Literal["contradiction_resolution",  # expectation → contradiction → cause → fix
                   "problem_fix",               # naive approach → problem → fix
                   "before_after",              # state A → change → state B, and why
                   "question_answer",           # one sharp question → one mechanism
                   "prediction_explanation",    # "what happens if…" → result → why
                   "myth_correction",           # what people believe → why it's wrong → what's true
                   "mini_derivation"]           # goal → one step → usable result
```

Two shorts from the same `build` video can use different micro-arcs. The archetype-aware
forward drivers of §10.2 do not apply; a short has one driver — the central insight — and the
question is only how quickly the interesting event arrives.

### 20.4 Shape — and no reserved outro

```
0–3 s    HOOK EVENT — the interesting thing happens; a visual may create the tension
         before a word is spoken
3–10 s   minimum context: the concrete failure, number, or contrast that makes it real
10–40 s  one mechanism (one — not a tour); an intermediate micro-payoff is allowed
40–55 s  the CENTRAL PAYOFF
then     stop. A 1–2 s on-screen or platform cue if bridging. No takeaway paragraph,
         no recap, no reserved subscribe slot — shorts have no narrative oxygen for it.
```

Duration: target 45–60 s, **max 60 s (hard)**. Word count **120–165 is an advisory planning
band** at the measured 167 wpm — never a gate. *Staging, stated honestly:* audio is produced
downstream by the render pipeline's voiceover step, so in V1A-S the ≤60 s gate is applied to the
*estimate* and flagged as such; V1C adds a cheap TTS preview for shorts (they're a minute long)
and the gate moves to **measured** duration, which is the authoritative figure.

### 20.5 Contracts

```
HookEvent        narration: str | None, visual: str | None, starts_at_seconds, tension
ShortsCandidate  beat_ids[], insight, hook_material, micro_arc_suggestion, prerequisites[],
                 visual_object, bridge_question, scores{…}                     ← §20.6
ShortPlan
  parent:        run_id, final_plan_hash, source_beat_ids[], allowed_fact_ids[]
  goal:          DISCOVERY | BRIDGE | SERIES
  central_insight
  micro_arc
  hook:          HookEvent (target 0–3 s)
  setup:         minimum_context
  mechanism
  payoff:        central, micro_payoffs[]        # one central insight; small ones allowed
  bridge:        mode: PLATFORM_LINK | ONSCREEN | SPOKEN | NONE, parent_video_id
  visual:        dominant_object, states[], safe_zones
  narration:     target_duration_seconds 45–60, word_band 120–165 (advisory)
```

Parent linkage and spoken bridge are separate: `parent_video_reference` is **required** for a
derived short; `bridge.mode` may be `NONE`. Sometimes the strongest ending is the payoff.

### 20.6 Candidate finding and selection — judgement, not ranking

Runs **only after the parent's plan is final**, keyed to `final_plan_hash`; re-planning the
parent invalidates its candidates automatically. Configurable:
`shorts.candidate_generation: auto | requested | off` (default `auto`); `shorts.count: 3`
(a ceiling, not a quota — the planner returns fewer when the source supports fewer).

```
SC   Candidate Finder — cheap shortlist of 3–5 plausible candidates      [Haiku]
A2s  Short Story Planner — selects the top `shorts.count` candidates
     (default 3; fewer if fewer are genuinely self-contained — it must
     not pad to the count), then designs EACH as its own ShortPlan: goal,
     insight, micro-arc, hook event, mechanism, central payoff, visual
     object, bridge strategy, title. Each ShortPlan becomes its own
     short run (§20.7), so a long-form run yields 2–3 finished
     short scripts, each with its own gates and cost report            [GPT mini]
```

Haiku's part is mechanical (inside the Haiku rule); the *choice* is story judgement and sits
cross-family. Candidate quality is multi-factor — **knowledge gain is one input, not the
dominant one**: instant intelligibility · hookability · surprise or contrast · self-containedness
· prerequisite burden · visual singularity · payoff strength · relevance · bridge potential.
The best long-form insight is often a poor short; the best short is often a side observation.

### 20.7 The short run

```
FINAL VERIFIED LONG-FORM RUN
  → SC candidate finder [Haiku]  → A2s short story planner [GPT mini]
  → B1 narration, short rhythm profile [Sonnet]
  → CM claim mapper → C2b grounding, scoped to allowed_fact_ids [Gemini flash]
  → C1s micro-arc critic [Gemini flash] · C5 style (if bands flag) · short diagnostics
  → rewrite only if routed
  → H vertical HTML → `final/shorts/<k>/short.html` + `narration.json`
  → HV static + Playwright 1080×1920 (+ TTS preview duration, V1C)
  → C4s COLD_HOOK_CRITIC on title + first 3 s: clarity, immediate tension, curiosity,
    confusion, generic opening — a critic, not a swipe predictor  [Haiku → Gemini flash]
  → policy gate → final
```

Derived shorts are **constrained to the parent's verified fact set — plus deterministic
derivations and safe explanatory inferences over it**, each materialized as a Claim with
`derived_from_claim_ids` (parent facts `3,847` and `4,001` tokens legitimately yield "only 154
more tokens"). What a derived short may *not* do is introduce a new external technical fact
without independent re-verification. CM + C2b still verify the short's *actual narration*,
because a paraphrase can be wrong. Roughly 3–4 paid calls per short, flash/mini tier; budget tiers
`target $0.08 · warning $0.15 · hard cap $0.25` per short — a long-form run plus three shorts
lands around $0.65 at target. A standalone short (no parent) runs the full pipeline under the `short`
profile; no parent reference is required.

### 20.8 Voice

Same **voice identity** (the channel's fingerprint); a different **rhythm profile**. Until
enough approved shorts exist, the long-form fingerprint is a loose reference only —
`voice/narration_short.yaml` is fitted in V1D from approved shorts. The 22-word-sentence
long-form median is almost certainly wrong at 60 seconds, and the system must not enforce it.

### 20.9 Vertical-safe composition (H + HV)

One primary focal region · few simultaneous text elements · important content outside platform
overlay zones (`visual.safe_zones`) · captions never cover the teaching object · math legible
at phone size · visual state changes frequent enough to hold attention. **Hard-gate only**
clipping, unreadable required text, missing required content, and layout failure; the rest are
diagnostics that feed C3.

### 20.10 Gates and diagnostics for the `short` profile

**Hard:** every factual proposition grounded (derived: within `allowed_fact_ids` or materialized
derivations/inferences over them) · exactly one
**central insight** · title ≈ hook event ≈ central payoff, *semantically* aligned · duration
≤ 60 s (estimate in V1A-S, measured from V1C) · valid vertical render, no clipping, no
unreadable required text · derived short has a valid parent reference · any CTA after value.

**Diagnostics (banded):** time to hook event (GREEN ≤ 3 s) · 3-second hook strength (C4s) ·
setup length (≤ 10 s) · word count vs band · mechanism count · visual density and change rate ·
spoken-bridge length · sentence rhythm vs the short profile · on-screen text density ·
prerequisite burden · candidate self-containedness. Evidence for the critic and the rewrite —
not another dashboard.

Switched off for shorts: forward-driver continuity, payoff-gap valleys, the mid-video cold
viewer, the 20–40% CTA window, `renderer_compat`'s ≥1,500 words (the renderer receives a
`format` flag).

### 20.11 What this reuses and what it adds

Reused unchanged: contracts, both lanes, the ledger, C2a, CM, C2b, the voice identity, H, HV,
the policy gate, cost attribution. Added: `config/formats/short.yaml`, the micro-arc enum,
`HookEvent`/`ShortsCandidate`/`ShortPlan`, SC and A2s, C1s, the cold-hook critic prompt, the
vertical template and safe zones, the short mutation tests, and a V1A-S slice (§17). Nothing in
the long-form path changes.

---

## Appendix A — Review of the design doc itself

`multi_agent_youtube_script_pipeline_architecture.md` (3,742 lines) is the backbone of this
plan. This appendix records what was kept verbatim, what was changed and why, and where the doc
has gaps or internal tensions that the plan resolves. It exists so that a future reader can tell
a deliberate deviation from a mistake.

### A.1 Kept as specified

Three-family split and the reason for it (§2) · LiteLLM as provider abstraction, not
orchestrator (§§3–4) · one primary archetype, six shapes, `framework`/`foundation` as
last-resort defaults (§§5–7) · extended `plan.json` story contract (§8) · question chain as the
core object (§9) · planned mini-payoffs (§10) · per-archetype contracts (§11) · hook contract
(§12) · causal-bridge representation (§13) · blank `archetype_role` is valid (§14) · source
brief, claim registry, assumption ledger (§§16–18) · archetype auto-classification order (§19)
· critic diagnoses, never rewrites (§§27–28) · four separate verification questions (§30) ·
deterministic arithmetic (§§31–32) · review aggregator (§35) · revision planner decides *what*,
writer decides *how* (§36) · routing by failure type (§37) · "reduce words, not causality"
(§§24, 39) · final gate never rewrites (§43) · hard gates before weighted score (§64) · typed
state, context isolation, artifacts not transcripts (§§47–49) · structured-output repair ≤2
(§50) · three separate retry counters (§53) · revision budgets (§54) · versioned artifacts and
run manifest (§§55–56) · cache keys with `detected_archetype` excluded (§60) · channel-style
and forbidden-pattern files (§§61–62) · prompt architecture (§65) · re-verification rules and
dependency-aware numeric revalidation (§§70–71) · human override points (§72) · readable
`review_summary.md` (§73) · mutation tests (§75) · the V1 ten-stage list (§78) · the §84
"do not build" list, all of it.

### A.2 Changed, with reasons

| Doc says | Plan does | Why |
|---|---|---|
| Three agents (§1, §78) | Five identities, conditional passes (§2) | Haiku for free mechanical work; HTML Author because markup ≠ prose. Both bounded by the doc's own §84 caution |
| All providers through LiteLLM (§§3, 51) | Sonnet/Haiku via `claude_cli.py` subscription lane; GPT/Gemini via LiteLLM (§3) | The doc assumes API keys for everyone. Subscription economics make the free lane the whole cost story |
| Input is an "existing HTML video source" with narration, animations, durations (§§1, 16, 50) | Input is a content HTML — clean or rough — with none of those (§6) | The real inputs (`docs/corpus/raw_inputs/`, `visual_guide/`) have no narration or timing. The doc conflated two different pipelines; the user clarified which one this is |
| Output is `narration.json` + `script.md` (§§55, 80) | Output is `video_script.html` with narration embedded (§§1, 12) | The render pipeline ingests **source HTML**; the doc stopped one artifact short of what downstream needs |
| Scene order must match source order (§33) | Reordering allowed at Plan (§1) | We author the source, so we sit upstream of the render pipeline's step-3 freeze; the playbook's Level-3 reorder applies |
| Visual audit, cold viewer, retention map are V2 (§79) | All V1 — as graded diagnostics, not gates (§§8, 10) | They serve the stated outcomes — retention and learning — directly. Deferring them defers the goal |
| "Avoid Now / So / Next" as a rule (§§39–40) | Opener *diversity* as a banded diagnostic (§11.3) | Measured on 22k words of human narration: signposts open 8.8% of sentences. The tell is monoculture, not presence |
| Human-narration audit is qualitative (§40) | Fitted `VoiceFingerprint` per text type (§11) | The doc gives no reference to measure against; the transcripts do |
| Scorecard: voice 5, no retention/learning dimensions (§44) | No weighted scorecard; a deterministic policy over few hard gates plus graded diagnostics (§§9, 10, 14) | The user's stated goals. Also §64's own logic: things that must not fail belong in gates, not weights |
| Invisible fallback forbidden (§52) — but silent on outage mid-run | Checkpoint and stop; resume later (§3.1) | The doc bans the wrong fix without naming the right one |

### A.3 Gaps in the doc the plan had to fill

1. **No HTML synthesis and no render verification.** The doc ends at narration, but the
   downstream pipeline starts at HTML. §§12–13 are new.
2. **No title.** §41's cold viewer takes a "video title" as input, but nothing in the doc
   produces one, and nothing checks it against the hook or the ending. `TitleContract` and the
   promise-chain gate fill this (§§5, 9).
3. **No CTA / subscribe design at all.** Entirely from `feedback.md`, which the architecture
   doc never integrates (§5.2).
4. **Nothing tests that the viewer learns something *new*.** `central_insight` exists but is
   never checked against the audience's assumed knowledge. `novelty_claim`, per-beat knowledge
   delta, and the structural learning gate fill this (§9).
5. **Retention is an artifact, not a mechanic.** §45's retention map has no open-loop model.
   Archetype-aware forward drivers (§10.2) are the missing piece.
6. **Who writes the numeric `expression`?** §§31–32 assume claims arrive with executable
   specs; neither doc says which agent authors them. Assigned to S2, and — a real finding — the
   sample sources already carry formulas as data (§6.2), so it's largely deterministic.
7. **No series continuity.** Every sample is "Act 1, Video N of 3" sharing constants, yet the
   doc is single-video. Series ledger (§5.3).
8. **No structured-output path for a CLI-driven model.** §50 assumes an API. §3.3 covers the
   subprocess lane.
9. **No input-quality handling.** The doc assumes a well-formed source; §6.4's tiers and the
   no-new-claims expansion rule handle rough input without fabrication.
10. **JS-resident content.** The doc's extraction (§50) is DOM-only; the richest sample keeps
    its technical payload in a `<script>` object (§6.2 — parsed as literals, never executed).

### A.4 Internal tensions resolved

- **§33 "match source order" vs playbook §13 "Level 3 reorder"** — resolved by *where* the
  pipeline sits: upstream of the freeze, so reorder is allowed; downstream artifacts freeze.
- **§2 "three families to avoid self-confirmation" vs adding Haiku** — resolved by the §2
  rule: same-family models never decide on story, correctness, voice, or the gate.
- **§54 "don't sand off personality" vs §§39–40 aggressive editing lists** — resolved by making
  B4 a rhythm-and-register pass that runs *after* the edits and is diff-guarded, so the last
  thing to touch the prose adds voice back rather than removing more.
- **§78 V1 minimalism vs the user's outcome goals** — resolved in favour of outcomes; the
  V1 list grows by exactly the stages that serve retention and learning, nothing else.

---

## Appendix B — Response to `docs/reviews/multi_agent_implementation_plan_review.md`

**Overall verdict — agreed.** The review's central charge is correct: diagnostics had become
laws, and one (opener share ≤11%) contradicted the corpus it was fitted from. Version 2 is
organized around the review's split — deterministic code for the deterministic, models for
judgement, heuristics as evidence.

| # | Point | Verdict | Where |
|---|---|---|---|
| 1 | No `node:vm`; parse JS with an AST | **Agree** | §6.2 |
| 2 | Facts before interpretation | **Agree** | §6.3 |
| 3 | Voice gates contradict the human range → bands | **Agree** — a real inconsistency | §11.3 |
| 4 | Rename `AI_TELL_DETECTOR` | **Agree** → `STYLE_CRITIC` | §11.5 |
| 5 | Humanize needs semantic protection | **Agree** → `EditMap` + C6 entailment | §11.4, §9 |
| 6 | Not every sentence needs a claim id | **Agree** → sentence types | §5.1 |
| 7 | Forward driver, not permanent open loop | **Agree** | §10.2 |
| 8 | Hook *promise* paid, not hook *question* withheld | **Agree** | §10.2 |
| 9 | Insight placement archetype-aware | **Agree** | §10.2 |
| 10 | Drop numeric `energy` | **Agree** → observable beat fields | §5, §10.2 |
| 11 | CTA over-engineered | **Agree with one modification:** hard/soft split adopted; the *default* intent stays `VALUE_LINKED` because `feedback.md` states that preference explicitly. Template sameness is handled by the Narration Lead writing it in the script's voice, not by a rule | §5.2 |
| 12 | Design-system fitting → V2 | **Agree** | §7, §17 |
| 13 | V1A–D rollout | **Agree** | §17 |
| 14 | A3/B2/B3 conditional | **Agree** | §8, §15 |
| 15 | B4 conditional | **Agree** | §11.4 |
| 16 | A4 cannot erase independent findings | **Agree** → deterministic policy gate; A4 editorial, downgrade-only | §9, §14 |
| 17 | `data-numeric-claim-id` instead of sweeping DOM numbers | **Agree with one addition:** annotation is the contract; a warning-level sweep for un-annotated unit-bearing numbers remains as a safety net so an unannotated technical value can't pass silently | §12, §13 |
| 18 | Unit-aware expressions | **Agree** | §5, §6.2 |
| 19 | Narration not in attributes | **Agree** | §12 |
| 20 | Semantic continuity objects | **Agree** | §12 |
| 21 | Playwright aesthetics warn | **Agree** | §13 |
| 22 | ≥1,500 words is renderer compat, not quality | **Agree** → `renderer_compat`, format-driven duration | §1, §9 |
| 23 | Calibrate WPM from real audio | **Agree** (V1D); 167 stays the planning figure — it was itself measured from rendered output | §17 |
| 24 | `novelty_claim` is planning, not a truth test | **Agree** → `novelty_statement`; the structural learning gate keeps only what is checkable | §5, §9 |
| 25 | Knowledge-delta triviality is model lint | **Agree** — escalates, never fails | §10.1 |
| 26 | `subscription_lane` / `paid_api_lane` | **Agree** | throughout |
| 27 | Own the budget policy | **Agree** | §3.2 |
| 28 | `claude_cli.py` | **Agree** | §3.1, §16 |
| — | Gate philosophy: hard vs soft | **Agree, with one refinement:** soft signals escalate to revision when they *cluster* (≥3 RED, or a RED surviving a round), so "advisory" cannot decay into "ignored" | §10 |
| — | Archetype-aware retention tables | **Agree** — adopted as written | §10.2 |


---

## Appendix C — Response to the second review round

**Verdict accepted:** stop redesigning after this round; build V1A; let the Attention / OOM /
KV-cache sources produce the next information.

| # | Point | Verdict | Where |
|---|---|---|---|
| 1 | Grounding loophole — writer labels are not a security boundary | **Agree** → independent Claim Mapper marks `grounding_required` on every factual proposition; C2b verifies all of them | §5.1, §9 |
| 2 | Registry is source assertions, not truth | **Agree** → `provenance_status` + `verification_status` + evidence on every claim; verified fact set is a distinct layer | §5, §6.5 |
| 3 | C2 needs an external-evidence path | **Agree, staged:** `VerificationEvidence`/`EvidenceRequest` and orchestrator-fulfilled retrieval in V1A from curated local references; web retrieval V1B; unfulfilled → honestly `UNVERIFIED`, hedged, never in hook/ending | §6.5, §17 |
| 4 | Required-stage rule too rigid | **Agree** → `core_roles` hard, `optional_roles` diagnostic, per archetype | §9 |
| 5 | Status definitions overlap | **Agree** → ordered precedence; AMBER allowance so human-quality scripts can PASS | §14 |
| 6 | Cascade paid reviews | **Agree, with a measurement:** Haiku first, Gemini on flag / low confidence / benchmark — **plus a 20% random sample** of clean runs so the cascade's miss rate is known, not assumed. Clean run: 4–6 paid calls | §2, §8 |
| 7 | Public LiteLLM cost interface | **Agree** | §3.2 |
| 8 | Pin exact Claude model | **Agree** → exact id in the call; envelope `modelUsage` read back and asserted; benchmark runs refuse aliases | §3.1 |
| — | Source verification before planning; grounding after narration | **Agree** → C2a (cached per source) and C2b are separate passes | §6.5, §8 |
| — | Extend C6 to any mapper-identified factual sentence | **Agree** | §11.4 |


---

## Appendix D — Architecture decision records

Each record: context → alternatives → why → cost → **revisit when**. The last field is the
point: a decision is right under conditions, and the conditions should be written down.

### D1 · Plain Python orchestration
**Context:** routing is static; four bounded loops; parallelism is one `gather`.
**Alternatives:** LangGraph, CrewAI, AutoGen. **Why:** the docs rule out model-decided routing
(design doc §§4, 84); state is one pydantic model whose JSON dump is the checkpoint;
debuggability is a stated requirement. **Cost:** we build checkpointing and tracing ourselves
(~80 lines). **Revisit when:** routing becomes model-driven, agents spawn dynamically, or
long-running human approvals enter the graph.

### D2 · Two-lane LLM client (subscription CLI + LiteLLM)
**Context:** Sonnet/Haiku are covered by a subscription; GPT/Gemini are metered.
**Alternatives:** all providers through LiteLLM with API keys. **Why:** routing Claude through
LiteLLM would bill the API and defeat the subscription; the stripped-flag CLI recipe cuts
overhead 30,167 → 170 tokens. **Cost:** two budget systems; a subprocess backend; quota-window
wall-clock. **Revisit when:** the subscription's headless terms or quota change, or a Claude
SDK path offers subscription auth with lower overhead.

### D3 · Five identities, conditional passes
**Context:** design doc specified three agents. **Alternatives:** three agents; a per-task
swarm. **Why:** Haiku is free mechanical capacity; HTML Author has a different failure mode
from prose; humanize is a mode, not an identity, because a diff guard is stronger than a prompt
boundary. **Cost:** the same-family rule must be enforced (Haiku never decides). **Revisit
when:** a genuinely different base instruction appears, or a role↔family A/B shows a better
split.

### D4 · Source verification before planning; grounding after narration
**Context:** the input HTML can be wrong. **Alternatives:** one verifier after narration.
**Why:** a story must never be built on a rejected claim; C2a is cached per source so it's paid
once. **Cost:** one extra paid pass per new source. **Revisit when:** sources become
pre-verified upstream.

### D5 · Producer metadata is never the validation boundary
**Context:** the writer labels sentence types. **Alternatives:** trust labels; verify only
`technical_assertion`. **Why:** a mislabelled factual sentence must not escape; an independent
cross-family Claim Mapper decides what needs grounding. **Cost:** one cheap paid pass; C2b sees
the whole narration. **Revisit when:** never — this is a principle, not a trade-off.

### D6 · Hard gates mechanical; diagnostics banded and advisory with cluster escalation
**Context:** v1 over-gated and one gate rejected the corpus it came from. **Alternatives:**
weighted score; everything gated. **Why:** deterministic ≠ unacceptable; bands are fitted so no
band rejects its own corpus. **Cost:** a policy layer and an escalation rule. **Revisit when:**
a diagnostic is shown, on data, to predict an unacceptable outcome — then it may graduate.

### D7 · Cascaded paid reviews with a measured sample
**Context:** nine paid calls on a clean run. **Alternatives:** run everything; run Haiku only.
**Why:** cheap first, expensive on flag; a 20% Gemini sample measures the cheap tier's miss
rate. **Cost:** the sample; a slightly more complex router. **Revisit when:** the measured miss
rate exceeds tolerance — then lower the cascade threshold.

### D8 · Explicit design library in V1; fitting in V1D
**Context:** samples show the target look. **Alternatives:** induce libraries automatically
from any reference set. **Why:** the *seam* (swappable config) is what matters for V1; the
fitter is a subsystem unrelated to the story thesis. **Cost:** manual component additions.
**Revisit when:** a second channel or theme is needed.

### D9 · Direct provider keys via LiteLLM
**Context:** one OpenAI key, one Gemini key in `.env`. **Alternatives:** LiteLLM proxy;
OpenRouter. **Why:** native per-provider cost figures for the local budget policy; fewest
moving parts. **Cost:** two keys to manage. **Revisit when:** a single bill or central gateway
becomes worth OpenRouter's margin or the proxy's operations.

### D10 · Artifacts, never conversation, between agents
**Context:** design doc §49. **Alternatives:** shared thread / debate. **Why:** independence,
caching, diffability, cost; a critic that sees the writer's reasoning defends it. **Cost:** no
emergent negotiation between models. **Revisit when:** a controlled debate stage is shown, on
the benchmark, to beat artifact passing on a specific failure class.

### D12 · `project/<playlist>/<video>/` layout, not a generic `runs/<id>/` root
**Context:** the user organizes work as a project of playlists, each with an `input/` of rough
sources; a video's outputs should live next to its source, browsable and publishable directly,
not in an opaque run-id-keyed directory elsewhere. **Alternatives:** the plan's original generic
`runs/<id>/` at the repo root; a flat `output/` mirroring `input/`. **Why:** `<video_slug>/final/`
gives a stable, always-current path to publish from (`page.html` especially — plan §12.0)
without hunting for the latest run id; `<video_slug>/runs/vNN/` keeps the full plan §16 working
tree per attempt for audit, with nothing overwritten and gaps in numbering never reused
(`orchestration/paths.py::next_run_dir`). **Cost:** one more layer of indirection between a
run and its promoted output; `promote_to_final` must only ever be called after a PASS/PASS_WARN
policy-gate result (plan §14) — a REVISE/FAIL run's `runs/vNN/final/` is real output but must
never overwrite the last good `final/`, tested explicitly
(`test_a_failed_runs_own_final_never_touches_the_video_final`). **Revisit when:** multiple
playlists need to share one video (a crossover) -- then `video_slug` alone won't be a unique key
and will need to be namespaced by playlist explicitly in cross-references, not just by directory
nesting.

### D11 · Shorts derive the parent's knowledge, not its storytelling
**Context:** the channel makes shorts from its videos; they must grow the channel.
**Alternatives:** a separate shorts pipeline; a short as a long-form with `duration: 60`; a
short that inherits the parent's archetype. **Why:** outcomes differ (reach / bridge / series
vs retention / capability), so story grammar and gates differ — a short-native micro-arc chosen
per short. Facts are identical, so the short is constrained to the parent's verified set:
little redundant verification, little drift, 3–4 cheap calls. Story shape is *not* inherited —
an earlier draft did that and would have produced compressed lectures. **Cost:** a format
profile, micro-arc enum, candidate finder + short planner, vertical template, a few gates.
**Revisit when:** standalone shorts dominate (own planner prompt), analytics show a goal mix
that doesn't convert, or enough approved shorts exist to fit their own rhythm profile.

---

## Appendix E — Response to the third review round

**Verdict accepted:** synchronize, freeze, implement V1A, evaluate on Attention / KV-cache / OOM.

**One correction to the review's premise.** §§6, 17 and 28 state that the plan still lacks
provenance/verification status, the Claim Mapper, C2a/C2b, the cascade, and resolved model
ids. It does not — those were applied in v2's second revision, before this review was written
(`provenance_status` ×2, `Claim Mapper` ×3, `C2a` ×14, `C2b` ×15, `grounding_required` ×4,
`modelUsage` ×2, `4–6 paid` ×2, `9 paid` ×0). The review appears to have read an earlier copy.
The synchronization it asks for was already done; this round adds what is genuinely new.

| # | Point | Verdict | Where |
|---|---|---|---|
| 8 | Evidence Broker in V1A | **Agree, named as a component**; staging kept — local references V1A, web V1B; unfulfilled → `UNVERIFIED`, hedged | §6.5 |
| 9 | Claim Mapper as a discrete step | **Agree** → CM runs before the review block; C1, C2b, C5, C6 see it | §2, §8 |
| 14 | Expansion sources beyond literal claims | **Agree** → verified source / derivation / external / `SAFE_INFERENCE` | §6.4 |
| 15 | Core vs optional roles | Already in v2. The review's mystery example makes *investigation* core and *mechanism* optional; v2 has the reverse. That is precisely why it lives in `archetypes.yaml` — a config choice, settled on the benchmark | §9 |
| 17 | Sync the call count | Already synced; CM adds one cheap call → **5–7** on a clean run | §2 |
| 20 | "Deterministic ⇒ hard gate" was a teaching error | **Agree** — corrected in the guide (§10) and recorded in its mistakes table | guide |
| 21 | Voice: product requirement → quality objective + one hard invariant | **Agree** — guide §4 reclassified | guide |
| 23 | Repeated-run stability testing | **Agree** | §18, guide §24a |
| 24 | Classical concepts in the guide | **Agree** → guide Part VI-b maps each onto this pipeline | guide |
| 25 | Fail-closed / retry / degrade-visibly | **Agree** → every capability classed | §15, guide §17 |
| 26 | ADRs with *revisit when* | **Agree** → Appendix D | here |
| 19 | PRINCIPLE / HEURISTIC / PROJECT DECISION labels | **Agree** → every guide section tagged | guide |
| 11 | Teach "not *currently* necessary," not "unnecessary" | **Agree** — D1's *revisit when* is that sentence | D1 |


---

## Appendix F — Response to the shorts review

**Verdict accepted:** no architectural rewrite; *derive the knowledge, not the storytelling.*

| # | Point | Verdict | Where |
|---|---|---|---|
| 1 | Facts inherit; archetype does not → short-native `micro_arc` | **Agree — the important one.** An earlier draft inherited core roles; that is the compressed-lecture failure | §20.2, §20.3 |
| 2 | "Can never contradict the parent" was an overclaim | **Agree** → constrained to the verified set; CM + C2b still verify the narration | §20.7 |
| 3 | Not every short is a bridge → `short_goal` | **Agree** → DISCOVERY / BRIDGE / SERIES, chosen per short | §20.1 |
| 4 | Parent linkage ≠ spoken bridge | **Agree** → reference required; `bridge.mode` may be `NONE` | §20.5 |
| 5 | No reserved outro | **Agree** → payoff, then stop | §20.4 |
| 6 | Word count advisory; measured duration authoritative | **Agree, staged honestly:** audio is downstream; V1A-S gates the *estimate* and says so; V1C adds a TTS preview and the gate becomes measured | §20.4, §17 |
| 7 | One central insight, not one payoff | **Agree** → `payoff.central` + `micro_payoffs[]` | §20.5 |
| 8–9 | Selection is multi-factor judgement, not knowledge-gain ranking | **Agree** → Haiku shortlists, GPT mini chooses and designs | §20.6 |
| 10 | Candidates only after the parent is final | **Agree** → keyed to `final_plan_hash` | §20.6 |
| 11 | Same voice identity, separate rhythm profile | **Agree** → `narration_short.yaml` in V1D; long-form fingerprint loose until then | §20.8 |
| 12 | `HookEvent`, not a tension sentence | **Agree** | §20.4, §20.5 |
| 13 | Semantic title alignment | **Agree** | §20.10 |
| 14 | Vertical-safe composition | **Agree** | §20.9 |
| 15 | Cold-hook critic, not swipe predictor | **Agree** — same correction as the style critic rename | §20.7 |
| 16 | Configurable generation | **Agree** → `auto \| requested \| off` | §20.6 |
| 17 | Separate V1A-S slice | **Agree** | §17 |
| 23 | "Different product semantics do not require duplicated architecture" | **Agree** — adopted as §20's opening line and in the guide | §20, guide §20a |


---

## Appendix G — Response to the final hygiene review

**Verdict accepted:** no redesign; hygiene only; then freeze and implement V1A.

| # | Point | Verdict | Where |
|---|---|---|---|
| 1 | "Registry is the source of truth" survived in §6.3 | **Agree — my patching error** → inventory vs authority wording | §6.3 |
| 2 | `UNVERIFIED` policy inconsistent between §5.1 and §6.5/§9 | **Agree** → `importance: CORE / SUPPORTING / OPTIONAL`; one policy table, referenced from all three | §5, §5.1, §6.5, §9 |
| 3 | CM as a single point of failure | **Agree** → C2b gets raw narration + CM output + fact set and checks completeness. *CM accelerates; C2b owns completeness* | §5.1, §9 |
| 4 | Materialize derivations and safe inferences as Claims | **Agree** → `derived_from_claim_ids`, `inference_kind` — a provenance graph | §5, §6.4 |
| 5 | Shorts may derive/infer over parent facts | **Agree** — "only 154 more tokens" is the case | §20.7, §20.10 |
| 6 | C2a cache key too weak | **Agree — important** → registry + ledger + evidence snapshot + model + prompt + schema + policy; TTL for web evidence | §4.2, §6.5 |
| 7 | Central cache policy; "pure function" is not literally true | **Agree** → `cache_key()` in one place; "explicit typed inputs and controlled side effects" | §4.2, §8, guide §13 |
| 8 | Float equality for reconciliation | **Agree** → integer microdollars | §4.1 |
| 9 | Target vs warning vs hard cap | **Agree** → three tiers per format and per day | §4 |
| 10 | Stale "required archetype stages" | **Agree** → "core archetype roles" | §1.2 |
| 11 | `C1-lite` undefined | **Agree** → "C1 with a scoped payload" | §15 |
| 12 | Distinct `numeric_claim_id`; `data-numeric-claim-id` | **Agree** | §5, §12, §13 |
| 13 | Guide typo `usage.jsonl and usage.jsonl` | **Agree** — an artefact of a search-and-replace | guide §18, §24 |
| 14–16 | Keep everything else | **Agree** | — |
