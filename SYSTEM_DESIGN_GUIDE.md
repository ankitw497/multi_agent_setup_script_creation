# System Design, Learned Through One Project
## How the multi-agent script pipeline was designed — and what to consider before building any system

This document is a companion to `IMPLEMENTATION_PLAN.md`. The plan says *what* the system is.
This document explains *how it was arrived at* — the questions asked before anything was
designed, how the architecture was decomposed, how testing is structured for a system whose
core components are non-deterministic, how the phases were ordered, and the mistakes made along
the way (there were several, and they are the most instructive part).

Each section follows the same shape:

> **Principle** — the general rule · **Applied here** — what it meant for this project ·
> **What would have gone wrong** — the concrete failure the rule prevents

Every numbered section carries one or two labels, so that project-specific choices are not
mistaken for universal laws:

> 🧭 **PRINCIPLE** — broadly transferable to other systems ·
> 🧪 **HEURISTIC** — usually useful, context-dependent ·
> 🔧 **PROJECT DECISION** — right under *these* constraints; carries a *revisit-when* (Appendix D of the plan)

Read it linearly the first time. Afterwards, Part VII is a standalone checklist.

---

# Part 0 — What "system design" actually is

System design is not drawing boxes. It is **making decisions under constraints, in an order that
lets later decisions depend on earlier ones without having to be re-made**. The boxes come last.

A useful frame: every system is an answer to five questions, and the questions must be asked in
this order because each one constrains the next.

```
1. What outcome is this for?             → defines success
2. What exists already, and is it true?  → defines the starting point
3. Where are the boundaries?             → defines scope and interfaces
4. What are the constraints?             → defines the solution space
5. What is uncertain, and what's cheap    → defines what to verify BEFORE designing
   to verify?
```

Only after those five does architecture begin. Most weak designs skip to boxes at step 1.

---

# Part I — Before you build: the questions that come first

## 1. Outcome, not output  ·  🧭 PRINCIPLE

**Principle.** Define success as an *outcome in the world*, not as an artifact. An artifact is
what the system produces; an outcome is what the artifact is *for*. Systems designed around
outputs optimize the wrong thing beautifully.

**Applied here.** The request was "generate a YouTube script HTML." That is an output. The
outcomes, extracted by asking *what is the HTML for?*, were four:

```
the viewer learns something new · the viewer stays · the viewer subscribes · there is one story
```

Once those were named, the design changed materially. "Retention" had appeared in the plan
only as a report artifact; "learn" and "title" appeared **zero** times. A grep of the plan
against the four outcomes found this — a check anyone can run on any design: *grep the design
for the words in your success definition.* Every stage was then required to name which outcome
it serves; anything serving none became a candidate to cut.

**What would have gone wrong.** A pipeline that produced correct, coherent, well-formatted HTML
that no one watched to the end. Technically flawless, purpose-failed.

## 2. Inventory what exists — and verify it instead of trusting it  ·  🧭 PRINCIPLE

**Principle.** Before designing, list every input, constraint, downstream consumer, and prior
artifact. Then **verify each one empirically**. Documents describe what someone *believed*;
files show what *is*.

**Applied here.** The inventory was: four specification documents (6,300 lines), three sample
outputs, four raw inputs, ten transcripts, eleven visual guides, and a downstream render
pipeline. Reading them was necessary but not sufficient. Verification found:

- The design doc assumed the input HTML carried "existing narration, animations, scene
  durations." The real inputs carried **none of those**. The doc had conflated two different
  pipelines. Caught only by opening the files.
- The richest technical content in one sample — four memory modes, every formula, the
  constants `HIDDEN=3584, LAYERS=28, PARAMS=7.61` — lived **inside a JavaScript object**,
  invisible to any HTML parser. A DOM-only extractor would have missed the most verifiable
  content in the file.
- 4 of 10 transcripts had **no sentence punctuation** — one was a single 5,249-word "sentence."
  Every rhythm metric computed over them was garbage until they were quarantined.
- The `OPENAI_API_KEY` in the shell was placeholder-shaped.

**What would have gone wrong.** An extractor built to the document's description, missing half
the facts; a voice model fitted to corrupted data; a first run failing on auth.

**The habit:** for every claim in a spec, ask *"how do I know that's true of the actual
files?"* and spend ten minutes finding out. It is always cheaper than discovering it in phase 4.

## 3. Boundaries — what you own, what you consume, what you feed  ·  🧭 PRINCIPLE

**Principle.** Draw the system boundary explicitly: which existing components are replaced,
which are kept, and what contract sits at each edge. Everything inside the boundary is yours to
change; everything outside is a fixed interface you must honour.

**Applied here.** The render pipeline had eight steps. This project **replaces steps 2–4**
(plan, script, narration) and **feeds step 5**. That single sentence settled several arguments:

- *Can we reorder scenes?* Yes — the render pipeline freezes scene order at step 3, and we
  *produce* step 3, so we sit upstream of the freeze. The playbook's "Level 3 reorder" was
  available, though the design doc's §33 seemed to forbid it. Boundary placement resolved the
  apparent contradiction.
- *What must the output satisfy?* The render pipeline's Gate 1 (≥3 sections, ≥1,500 words) —
  recorded as `renderer_compat`, a compatibility rule, explicitly *not* a content-quality rule.
- *Is 167 words-per-minute a stylistic choice?* No — it's the downstream TTS's measured pace,
  and word timestamps drive the animation. It's a boundary constraint.

**What would have gone wrong.** Arguing about scene reordering as a matter of taste when it was
a matter of where the freeze sits; treating a renderer compatibility number as a quality law.

## 4. Constraints — the shape of the solution space  ·  🧭 PRINCIPLE

**Principle.** Enumerate constraints before designing, and classify them: **hard** (violating
it makes the system unacceptable), **soft** (a cost to trade off), and **self-imposed** (a
choice that could be revisited). Confusing the categories is the most common design error.

**Applied here.**

| Constraint | Class | Consequence |
|---|---|---|
| Sonnet/Haiku must use the subscription, not the API | hard (economic) | two-lane backend; `ANTHROPIC_API_KEY` explicitly unset |
| GPT/Gemini cost must be capped | hard | pre-flight estimate, local budget counter, abort |
| Numbers must be correct | hard | deterministic arithmetic; single number registry |
| Script must sound human | **product requirement** (stated by the owner) → a *quality objective* (bands, preference) + one *hard invariant* (humanizing must not alter verified facts) | a measured subsystem, not a lint rule — and not a gate on taste |
| Runs must be reproducible and explainable weeks later | hard (non-functional) | artifacts not conversation; versioned prompts; manifest |
| ~10-minute videos | soft | format-driven duration config |
| Three model families for review independence | self-imposed, from the design doc | kept, but with an explicit rule for where Haiku (same family as the writer) may and may not act |

**What would have gone wrong.** Treating "human voice" as a soft polish step (it was the
owner's stated non-negotiable), or treating "167 wpm" as hard (it's a planning figure to be
calibrated from real audio later).

## 5. De-risk the unknowns before designing around them  ·  🧭 PRINCIPLE

**Principle.** Identify the assumptions the design most depends on, rank them by *cost if
wrong × cheapness to test*, and test the top ones **before** committing the architecture. An
hour of experiment can save a month of building on a false premise.

**Applied here.** Three experiments, each under an hour, each of which changed the design:

1. **Is the subscription lane viable headless?** A one-line prompt through `claude -p` cost
   **30,167 tokens** of overhead — Claude Code's own system prompt and tools. That would have
   made the "free" lane useless at volume. With stripped flags: **170 tokens**. The whole cost
   story of the plan depends on this recipe; it was found by trying, not by reading docs.
2. **Can voice be measured?** Fitting sentence-length, opener, and connective metrics on the
   transcripts *worked* — and overturned two assumptions: spoken narration and on-screen prose
   differ 27× on concrete-token density (so they need separate fingerprints), and human
   narrators signpost 8.8 sentences per 100 (so "avoid Now/So/Next" was wrong as a rule).
3. **What does "better" mean, numerically?** Comparing raw inputs to sample outputs: +25–65%
   words, 0 → 1–8 archetype components, and causal connectives **0.65 → 1.09** per 100 words.
   That last figure became the thesis: the raw inputs aren't missing facts, they're missing
   *because* and *so*. Stage H's spec came from measurement, not intuition.

**What would have gone wrong.** Designing a voice system on the assumption that fragments like
"Same model. Same GPU. Same code." were the narration target (they're screen text — 16.3% of
sample-HTML sentences are under six words vs 1.8% in real narration). Building a cost model on a
lane that burned 30k tokens per call.

## 6. Failure modes are requirements in disguise  ·  🧪 HEURISTIC

**Principle.** The most valuable specification is a catalogue of *how this kind of system has
failed before*. Each recurring failure is a requirement; each requirement is a check.

**Applied here.** The playbook listed ~49 recurring script failures from previous manual
reviews. Each became a typed check somewhere:

| Past failure | Became |
|---|---|
| "scenes correct individually but not one story" | one archetype + question chain + causal bridges; story critic |
| "concept before its need" | concept-before-motivation diagnostic |
| "GB and GiB mixed" | `memory_units` in the assumption ledger; unit-aware expressions |
| "prefill and decode conflated" | `Claim.stage` as a typed enum |
| "numbers trusted to the LLM" | deterministic numeric validator |
| "editing for brevity removed the reasoning" | "reduce words, not causality"; C6 entailment check |
| "critic and editor roles mixed" | critic emits intents, never prose |
| "full regeneration destroyed good parts" | PRESERVE / REWRITE / DELETE / CORRECT revision plans |
| "too many revision loops sanded off personality" | bounded loops; conditional B4 |

**What would have gone wrong.** Rediscovering each failure in production, one video at a time.

## 7. Non-functional requirements — the ones nobody asks for  ·  🧭 PRINCIPLE

**Principle.** Functional requirements say what the system does. Non-functional ones — cost,
latency, reproducibility, debuggability, auditability, safety — determine whether it survives
contact with reality. They are rarely stated and must be elicited.

**Applied here.** The one that shaped the most decisions was *"explain a bad script three weeks
later."* It implied: versioned prompts, exact model ids in the manifest (read back from the
provider's response and asserted, not assumed), typed artifacts on disk per stage, content-hash
caching, and no agent-to-agent conversation (a chat thread can't be diffed). Cost implied the
two-lane design and the cascade. Safety implied literal-AST JS parsing instead of `node:vm`.

**What would have gone wrong.** A system that worked but couldn't be debugged, and whose prompt
"regressions" were actually a model alias moving underneath it.

---

# Part II — Creating the architecture

## 8. Contracts first, components second  ·  🧭 PRINCIPLE

**Principle.** Define the *data* that flows between parts before defining the parts. A typed
contract is a promise both sides can test against; a component without a contract is a
guess. When contracts are right, components become interchangeable.

**Applied here.** Phase 1 of the plan is "every pydantic model, with golden fixtures, before a
single prompt is written." `Claim`, `NumericClaim`, `StoryPlan`, `SentenceNarration`,
`CritiqueIssue`, `RevisionPlan` — each is a contract between two stages. Several design
improvements were *only* expressible as contract changes:

- The playbook's repeated prefill/decode and inference/training confusions became typed enums
  on `Claim` (`stage`, `mode`, `scope`), not prose guidance in a prompt.
- The grounding loophole (§13 below) was closed by adding `grounding_required` — set by an
  independent mapper — to `SentenceNarration`, decoupling it from the writer's own label.
- "Source says X" versus "X is verified true" became two fields on the same claim:
  `provenance_status` and `verification_status`.

**What would have gone wrong.** Prompts full of instructions like "remember to distinguish
prefill from decode," which models follow inconsistently, instead of a field the validator can
check mechanically.

## 9. Decomposition — when is something a separate component?  ·  🧭 PRINCIPLE

**Principle.** Split by *distinct responsibility with a distinct failure mode*, not by
convenience or by model. Two things that fail differently and are validated differently are
two components. Two things that share a craft under different constraints are one component in
two modes.

**Applied here.** The design doc specified three agents. The final plan has five *identities*
(base prompt + model + lane) invoked in ~20 *modes*. Two decisions illustrate the rule:

- **HTML Author is separate from Narration Lead, even though both are Sonnet.** It emits markup
  under a component contract, not spoken prose; its failures (invalid HTML, unregistered
  numbers) and validators (Playwright, traceability) are entirely different. Sharing a model is
  not sharing an identity.
- **Humanize is a *mode* of Narration Lead, not a sixth agent.** Same craft, tighter
  constraints. Its safety comes from a mechanical diff guard plus an entailment check — a
  separate identity would add nothing a check doesn't already provide.

**What would have gone wrong.** The design doc's §84 warning: "six archetype agents," "all
three models writing full scripts" — a swarm with unclear ownership and no independent check.

## 10. The governing split: deterministic vs judgement  ·  🧭 PRINCIPLE

**Principle.** Two questions, in order:

```
Can code measure it?            → yes: measure it in code, always. Never ask a model to multiply.
Does violating it make the      → yes: hard gate.
output unacceptable?            → no:  diagnostic / warning / SLO — even though code measured it.
```

The second question is the one people skip. **Deterministic does not mean gate.** A CTA at 42%
instead of 35% is deterministically measurable and is a diagnostic; a wrong multiplication is a
hard failure. If code can't measure it, a model judges it, and measured heuristics are
*evidence* for that judgement — never a substitute. Mixing the layers produces systems that
fail both ways: models doing arithmetic badly, and code "deciding" whether prose is interesting.

*(An earlier draft of this section said "if code can decide it, it is a hard gate." That was
wrong, and it is exactly the confusion that produced the over-gated version 1 of the plan —
see §22.)*

**Applied here.** This became the organizing principle of the whole plan (v2 §9 vs §10):

```
Deterministic → hard gates          Judgement → models         Heuristics → evidence
numbers, units, schema,             coherence, interest,       burstiness, opener share,
traceability, scene identity,       novelty, naturalness,      payoff gaps, CTA position,
HTML validity, timing arithmetic    pedagogy, visual weight    layout repetition
```

The deterministic numeric validator exists because the playbook found real arithmetic errors
that models had confidently produced. The style critic exists because no regex can tell you a
paragraph sounds like a model — but a regex *can* tell you ten consecutive sentences are within
three words of each other, which is evidence the critic should see.

**What would have gone wrong.** Version 1 of the plan violated this split — see §22.

## 11. Independence — design so that no component can approve its own work  ·  🧭 PRINCIPLE

**Principle.** Wherever a component produces something and a check evaluates it, the check must
be independent: different information, different incentives, and ideally a different
implementation. A reviewer that shares the producer's context or priors converges to agreement.

**Applied here.** Four applications, each caught a specific hole:

- **Three model families** (from the design doc): the writer is never its own critic.
- **The Haiku rule:** Haiku shares a family with the writer, so it may pre-filter and lint but
  never be the *deciding* reviewer on story, correctness, voice, or the final status.
- **A4 cannot erase failures.** The Story Lead plans the arc and the revisions; letting it
  also declare PASS meant it could clear its own critical issues. The final status is now a
  deterministic policy over hard gates; A4 writes the editorial summary and may only downgrade.
- **The grounding boundary is not the writer's label.** Sonnet classifies each sentence
  (`technical_assertion`, `analogy`, …). If only sentences *it* labelled technical were
  fact-checked, a factual claim mislabelled `analogy` escapes. An independent Claim Mapper now
  marks every factual proposition regardless of label. *The producer's metadata is never the
  security boundary.*

**What would have gone wrong.** Self-confirmation dressed as review — the exact failure the
design doc's §2 was written to prevent, re-introduced through a side door.

## 12. Layering truth — "the source says" is not "it is true"  ·  🧭 PRINCIPLE

**Principle.** Data has *levels of trust*, and the architecture must keep them distinct. Raw
input, extracted assertions, verified facts, and generated content are four different things;
collapsing any two lets an error at one level masquerade as the level above.

**Applied here.** The second review's most valuable point: the claim registry had been called
"the source of truth." It isn't — it's *what the input HTML asserts*, and the input can be
wrong. The fix was a layer:

```
SOURCE CLAIMS (what the HTML says; provenance: explicit / inferred / derived)
      ↓  Python arithmetic · evidence lookup · Gemini reasoning over evidence
VERIFIED FACT SET (verified / context-dependent / unverified / rejected — with evidence attached)
      ↓
planning → narration
      ↓
claim mapper → grounding verification of what was actually written
```

Two consequences: source verification (C2a) runs *before* planning, cached per source, so no
story is ever built on a rejected claim; and "verified" means exactly what the attached evidence
supports — never "the model agreed with the upload."

**What would have gone wrong.** A pipeline that faithfully propagated a wrong number from a
draft HTML into a published video, with every check passing because every check compared
against the same wrong source.

## 13. Control flow — choose the simplest thing that expresses the real structure  ·  🧭 PRINCIPLE · 🔧 PROJECT DECISION

**Principle.** Match the orchestration mechanism to the *shape* of the control flow. A fixed
DAG with bounded loops is `if`, `while`, and counters. Dynamic, model-decided routing is a graph
framework. Using the heavier tool for the lighter shape adds indirection without capability.

**Applied here.** The question "LangGraph or plain Python?" was decided by the shape: the route
is known before the run starts; there are four bounded loops (replan ≤1, revision ≤2, humanize
≤2, HTML repair ≤2); parallelism is one `asyncio.gather`. Plain Python with an `@stage`
decorator (~80 lines: cache, artifact write, checkpoint, cost accounting) expresses all of it.
The migration insurance is not the framework — it's that *every stage has explicit typed inputs
and controlled side effects*, which makes any later move cheap. ("Pure function" is the
tempting phrase and it's not literally true of a model stage: the answer depends on the prompt
version, the model id, the evidence snapshot. That is exactly why every one of those belongs in
the stage's cache key — plan §4.2.)

Two more control-flow rules that came from review:

- **Nothing runs because it exists.** Revision, precision-edit, humanize, and several paid
  reviews are conditional on findings. A mandatory rewrite stage creates risk with no
  guaranteed gain.
- **Sequence by where findings route.** Version 1 placed the retention diagnostics *after* HTML
  synthesis while routing their failures to the revision planner — so a retention problem would
  have forced redoing the narration *and* the HTML. Rule: a stage runs before the earliest stage
  that must act on its output.

**What would have gone wrong.** A framework dependency wrapping the genuinely hard part (the
two-lane client) without helping build it; and a sequencing bug that doubled the cost of every
retention fix.

## 14. Interface design — one call, two worlds  ·  🧭 PRINCIPLE

**Principle.** When two implementations must be interchangeable, design the interface around
what the *caller* needs and push every difference below it. The test of a good abstraction is
that the caller cannot tell which implementation answered.

**Applied here.** `llm.call_structured(role, mode, payload, schema)` hides two backends that
differ in almost every way — a subprocess versus an HTTP client, quota versus dollars,
checkpoint-and-stop versus abort-on-budget. What the caller needs is identical: a validated
object matching a schema. Everything else — budget type, retry policy, the `env -u` assertion,
the stripped-flag recipe, reading back the resolved model id — lives below the line.

**What would have gone wrong.** Story logic that knew which provider it was talking to, and
therefore couldn't be A/B tested across role↔family assignments.

## 15. Data flow and context isolation  ·  🧭 PRINCIPLE

**Principle.** Each component receives *only* the information its job needs. Extra context is
not free: it costs tokens, and it contaminates judgement.

**Applied here.** Stages exchange typed artifacts — `plan.json`, `critique.json` — never
transcripts. No call ever sees "GPT thought… then Gemini disagreed." The cold viewer is
deliberately given *less* context (title + first 60 seconds) because that is what a real viewer
has. The style critic sees narration only — no plan, no rationale — so it can't defend choices
it didn't know were made.

**What would have gone wrong.** A critic that, shown *why* the writer chose a hook, evaluates
the justification instead of the hook.

## 16. Cost as a first-class design dimension  ·  🧭 PRINCIPLE · 🔧 PROJECT DECISION

**Principle.** Cost is not an afterthought to be optimized later; it is a constraint that shapes
architecture. Identify the levers early, and make the safety boundary local code you own.

**Applied here.** Eight levers, in order of impact: raw HTML never reaches a paid model
(compaction first); volume goes to the subscription lane; cheap tiers with escalation; scoped
review payloads; screenshot caps; content-hash caching per stage (with the rule that a stage's
*output* — like `detected_archetype` — must never enter its own cache key); stable prompt
prefixes for provider-side caching; and hard caps enforced by a local counter, not a library
helper. Then the second review added **cascading**: run the cheap check first, escalate only on
a flag. A clean run went from ~9 paid calls to 5–7 — with a 20% random sample still escalated so
the cascade's miss rate is *measured*, not assumed.

**What would have gone wrong.** A $3 run instead of a $0.30 one, and no way to know which stage
spent it.

## 17. Errors, retries, and the three counters  ·  🧭 PRINCIPLE

**Principle.** Different kinds of failure need different responses, and their retry budgets
must never share a counter. Conflating them means a transient network error consumes the budget
meant for creative revision, or vice versa.

**Applied here.** Three independent counters:

| Failure | Response | Budget |
|---|---|---|
| transport (429, timeout, 5xx) | retry with backoff, same model | near the client |
| schema (invalid JSON, missing field) | repair on Haiku, ≤2, then fail loudly | per call |
| creative (weak hook, wrong fact) | revision routing | per run, bounded |

Plus two resilience rules: **checkpoint after every stage** so a rate-limited run resumes rather
than re-paying; and **fail loudly** — malformed data never silently enters a later stage.

**Three responses to a failed capability — choose deliberately:**

| Response | When | Here |
|---|---|---|
| **Fail closed** | continuing could *silently* violate an invariant | wrong verified number; ungrounded factual proposition; narration↔HTML mapping corrupt |
| **Retry** | the failure is transient | 429, timeout, 5xx |
| **Degrade visibly** | the failed capability is optional and its absence is *recorded* | style critic unavailable → skip, flag in manifest; visual audit unavailable while deterministic render checks pass → ship with a warning |

The rule: *fail closed when continuing could silently break correctness; degrade visibly when
the missing capability is optional.* "Visibly" is the whole point — a degraded run that looks
like a normal run is a lie in the manifest.

**What would have gone wrong.** Silent fallback from a rate-limited Sonnet to a paid API,
"invisible cleverness" the design doc explicitly bans because it makes runs irreproducible.

## 18. Observability — design for the post-mortem  ·  🧭 PRINCIPLE

**Principle.** Assume something will go wrong and someone will need to explain it later. Every
run should leave enough evidence to reconstruct *what ran, with what inputs, under which
prompts and models, at what cost*.

**Applied here.** Per run: a versioned artifact per stage, `usage.jsonl` per
call, and `run_manifest.json` recording prompt versions, the *resolved* model ids (read back
from the provider's own response envelope and asserted equal to the request), archetype in/out,
revision counts, and the analytics schema (null until connected, so runs are comparable the day
it is). Reports come in two forms: JSON for machines, `review_summary.md` for people.

**What would have gone wrong.** "The script got worse last week" with no way to tell whether a
prompt changed, a model alias moved, or the source did.

## 18a. Cost attribution — you cannot optimize what you cannot attribute  ·  🧭 PRINCIPLE

**Principle.** A cap prevents disaster; attribution enables improvement. Every unit of spend
should be traceable to *the component, the reason, and the moment* it was incurred — so that
"this is too expensive" becomes "A2 is 40% of the run, and half of that is the strong tier
firing on inputs the mini tier handled fine." Attribution is what turns cost from a constraint
into a design input.

**Applied here.** Every model call, on both lanes, writes one `UsageRecord` stamped by the
`@stage` decorator with agent, pass, mode, revision cycle, lane, resolved model, tokens, and
cost. Three design choices matter more than the schema:

- **Two kinds of cost, never conflated.** The paid lane records *billed* dollars from the
  provider's public cost interface. The subscription lane records *notional* dollars — what the
  call would have cost — labelled as never-billed. Reporting them in one column would be a lie;
  reporting only billed would hide that Sonnet is doing 60% of the work.
- **Cache hits are records too.** A hit writes `billed = 0` plus the estimated avoided cost.
  Savings that aren't recorded aren't savings anyone can see, and an estimator that's never
  compared to reality never gets better.
- **Reconciliation is an invariant.** The sum of records must equal the manifest total must
  equal the budget counter. A mismatch fails the run. The one failure a cost system must never
  have is a call that spent money without leaving a record — and it's the easiest one to have,
  because a dropped callback is silent by default.

The report per script answers five questions in one screen: per agent, per stage, per revision
cycle, cache saved, headroom under the cap. Across runs, an index makes cost-per-script by
source and by archetype a one-line query. This is exactly what makes a role↔family A/B
meaningful: preference *and* cost, per agent, on the same rubric.

**What would have gone wrong.** A pipeline that stayed under its $0.50 cap and nobody could say
why one script cost $0.20 and the next $0.48 — so nobody could fix it.

## 19. Safety and hygiene  ·  🧭 PRINCIPLE

**Principle.** Untrusted input is never executed; credentials never leak across boundaries;
generation never fabricates. Each of these is a rule enforced in code, not a guideline.

**Applied here.** `node:vm` was replaced by literal-AST extraction (Acorn) — nothing in a source
file ever runs. `ANTHROPIC_API_KEY` is explicitly unset in the subscription backend so it cannot
silently bill the API. Expansion of a thin source is bounded by the rule *"every factual proposition must be
traceable to verified source evidence, a deterministic derivation, verified external evidence,
or an inference C2b judges safe"* — never to nothing. Restricting it to *literal* registered
claims (an earlier wording) would have forbidden a correct derived number.

**What would have gone wrong.** A downloaded HTML executing code on the build machine; a
subscription run quietly billed to an API key; a 900-word source padded to 1,700 with invented
facts.

## 20. Evolvability — put change where it's cheap  ·  🧭 PRINCIPLE

**Principle.** Things that will change often should live in configuration; things that change
rarely may live in code. Design the seams so that the expected changes require no code.

**Applied here.** Model ids → `models.yaml`. Extraction rules → pluggable profiles. Design
system → a swappable library file (automatic *fitting* of libraries deferred to V1D, because the
seam — not the automation — is what matters in V1). Archetype core/optional roles →
`archetypes.yaml`. Voice bands → fitted files. Prompts → versioned templates per agent and
mode. The story logic never contains a model id, a class name, or a threshold.

---

## 20a. A new use case: parameter, or product?  ·  🧭 PRINCIPLE · 🔧 PROJECT DECISION

**Principle.** When a new use case arrives, the first question is not "how do we support it"
but **"is this a parameter of the existing product, or a different product sharing the
machinery?"** The test is the outcome table: if the new case serves the *same* outcomes with
different values, it's a parameter. If it serves *different* outcomes, it's a product — it needs
its own success definition and its own gates, however much code it shares.

**Applied here.** Shorts arrived as "also make 45–60 second versions." Treated as a parameter
(`duration: 60`), the long-form pipeline would have produced compressed lectures: forward-driver
checks demanding momentum across a beat that lasts nine seconds, a CTA-window rule aimed at
minute three of a one-minute video, a `≥1,500 words` compatibility gate failing every one of
them. The outcome table said otherwise: a short exists to *acquire* viewers and *bridge* them to
the long-form; it teaches one insight, not a capability; its retention question is "survive the
swipe in 3 seconds," not "avoid a valley at minute six." Different outcomes → a **format
profile** with its own gates (plan §20).

The second decision was the valuable one, and it took a review to get it exactly right:
**derive the knowledge, not the storytelling.** A short built from the parent video's *verified*
plan inherits every fact — it is constrained to the parent's fact set, so redundant verification
and drift mostly disappear (grounding still runs on the short's actual words, because a
paraphrase can be wrong). But the *story shape* is not inherited: a short from a `build` video
may be a `contradiction_resolution` micro-arc, and forcing the parent's roles onto sixty
seconds produces a compressed lecture. Candidate finding is cheap and mechanical; the *choice*
of which candidate and which micro-arc is story judgement and sits with a planner. A separate
shorts pipeline would have re-verified the same facts and let the two drift apart.

The phrasing worth keeping: **different product semantics do not require duplicated
architecture.** Shorts have their own success criteria, story grammar, timing and visual
constraints, and share facts, verification, orchestration, grounding, backends and cost
accounting.

**What would have gone wrong.** Shorts that read as truncated lectures, failed gates designed
for a different product, and — worst — a short and its parent video disagreeing on a number.

# Part III — Gates, verification, and the Goodhart trap

## 21. Hard gates versus diagnostics  ·  🧭 PRINCIPLE

**Principle.** A *gate* blocks; a *diagnostic* informs. Something belongs behind a gate only if
(a) code can decide it and (b) violating it makes the output unacceptable regardless of anything
else. Everything else is a graded signal that feeds a judgement.

**Applied here (v2).** Hard gates are few and mechanical: a wrong verified calculation; a
factual proposition mapped to no claim or a rejected one; an unresolved archetype; a hook promise
the ending doesn't pay; invalid HTML; a displayed number that doesn't match its registered claim.
Diagnostics are many and graded GREEN / AMBER / RED with evidence: burstiness, opener share,
payoff gaps, CTA position, layout repetition, novelty judgement.

## 22. The Goodhart trap — the biggest lesson of this design  ·  🧭 PRINCIPLE

**Principle.** *When a measure becomes a target, it ceases to be a good measure.* Any threshold
you gate on, the system will learn to satisfy — at the expense of the thing the threshold was
meant to approximate.

**What happened here.** Version 1 of the plan, over two enthusiastic revisions, turned nearly
every useful observation into a law: opener share ≤11%, CTA at 20–35%, payoff gap ≤90 s,
central insight before 50%, an open loop at every moment, a 1–10 energy score per beat. The
external review named it exactly: *"the system will learn to satisfy the dashboard rather than
the viewer."*

One of those laws was self-contradictory. The opener-share gate was set at ≤11% using a corpus
whose human range ran to **16.4%** — the gate would have rejected real human transcripts from
the very corpus that defined it. The fix was structural, not a number change: every band is now
*fitted from the corpus by the fitter*, so **no band can reject a document in the corpus that
defined it**, and every band is advisory.

**The safeguard against the opposite failure.** If everything is a warning, nothing is. So soft
signals *escalate* when they cluster — three REDs across dimensions, or a RED that survives a
revision round, routes to targeted revision instead of "pass with warnings." Advisory does not
mean ignored.

**The transferable lesson.** Whenever you find yourself writing a numeric threshold into a gate,
ask: *did this number come from data, and would the best real examples pass it?* If either
answer is no, it is a diagnostic.

## 23. Archetype-aware rules — one rule rarely fits all shapes  ·  🧪 HEURISTIC

**Principle.** A rule that is right for one kind of content is often wrong for another. Before
making a rule universal, check it against every kind the system handles.

**Applied here.** "At every point at least one loop is open" is a *mystery* instinct — it
produces artificial withholding in a *derivation* and fake suspense in a *foundation*. The
replacement is a **forward driver** the archetype defines: an unanswered cause (mystery), an
unresolved limitation (build), an unresolved decision (experiment), a mathematical goal
(derivation), progress toward a capstone (foundation), a remaining organizing dimension
(framework). Likewise "central insight before 50%" became "central *value* previewed early;
central *answer* placed where the archetype earns it" — revealing a mystery's mechanism at 40%
kills the story.

---

# Part IV — Testing a system whose core is non-deterministic

## 24. The test pyramid, adapted  ·  🧭 PRINCIPLE

**Principle.** Classic testing assumes determinism: same input, same output. LLM components
break that. The adaptation is to *test the contracts and the checks, not the prose*, and to add
test types that don't exist in ordinary software.

```
                      ┌───────────────┐
                      │  A/B harness  │   role↔family rotation, same rubric
                     ┌┴───────────────┴┐
                     │  golden / bench │   sample outputs as gold; archetype, beats, numerics
                    ┌┴─────────────────┴┐
                    │  mutation tests   │   inject a defect → assert the right check fires
                   ┌┴───────────────────┴┐
                   │  held-out tests     │   voice bands must admit unseen human samples
                  ┌┴─────────────────────┴┐
                  │  integration / smoke  │   each backend end-to-end; key-leak test; budget abort
                 ┌┴───────────────────────┴┐
                 │  contract tests         │   every schema round-trips; render handoff shape
                ┌┴─────────────────────────┴┐
                │  unit tests               │   parsers, validators, arithmetic, band scoring
                └───────────────────────────┘
```

**Unit tests** cover everything deterministic: the JS literal extractor (including *rejecting*
dynamic code), unit conversion (GB vs GiB), expression evaluation against the ledger, sentence
segmentation, band scoring, the status-precedence policy. These are ordinary tests and should
be the majority.

**Contract tests** assert that every pydantic model round-trips through JSON with a golden
fixture, and that `final/` has the shape the render pipeline ingests. They run before any prompt
exists — Phase 1.

**Integration / smoke tests** exercise each lane once with a trivial prompt and assert the
side effects: a `UsageRecord` in `usage.jsonl`, the resolved model id in the manifest,
and — critically — a **key-leak test**: set `ANTHROPIC_API_KEY` in the environment and assert
the subscription backend still runs without it. A budget test sets a $0.001 cap and asserts the
pre-flight aborts.

**Mutation tests** are the LLM-pipeline equivalent of unit tests for the *review* stages.
You cannot assert what a critic will say about a good script; you *can* inject a known defect
and assert the right check catches it. The plan's suite includes: `15.2 GB → 12.2 GB` in
narration (numeric validator) and in the HTML only (`data-numeric-claim-id` check); GB → GiB (units);
the motivating scene deleted (story critic); a factual sentence labelled `analogy` (claim mapper
still grounds it); a wrong claim in the *source* (C2a rejects it); "grows with tokens" →
"grows quadratically" after humanize (entailment check); ten sentences forced to uniform length
(voice band RED); a hero diagram shrunk to 15% of frame (render warning → visual critic). Each
mutation names its catcher. If a mutation is caught by the wrong check or none, that is a design
bug.

**Held-out tests** guard the fitted bands: fit on four transcripts, hold out two, and require the
held-out humans to land GREEN/AMBER. A band that rejects unseen human writing is over-fitted.

**Golden / benchmark tests** run the known sources — Attention, OOM, KV-cache — and compare
against the human-approved sample outputs on archetype match, beat count, driver progression,
numeric accuracy, voice distance, and human preference. This is where the real question gets
answered: *does the system independently catch the story failures that took multiple manual
rounds to find?*

**A/B harness** rotates role↔family assignments on the same sources and rubric, tracking
preference, revision count, critical-error rate, cost, and latency. The design doc's rule:
never rotate roles on vibes.

## 24a. Repeated-run stability — quality includes variance  ·  🧭 PRINCIPLE

**Principle.** A non-deterministic system's quality is a *distribution*, not a number. A
pipeline that produces a great script 70% of the time and a broken one 30% of the time has a
different problem from one that is consistently mediocre — and the average hides which.

**Applied here.** The benchmark includes a stability run: the same source (Attention) × 20 runs,
measuring archetype-selection stability, critical-error rate, revision frequency, story-score
variance, cost variance, and human preference across runs. S0–C2a are cached, so twenty runs
cost roughly twenty B1-onward passes — budgeted as a benchmark mode against the daily cap.
An archetype that flips between `build` and `foundation` on identical input is a planner
prompt defect no single run would reveal.

## 25. Testing principles specific to model components  ·  🧪 HEURISTIC

- **Test the check, not the output.** You can't assert prose; you can assert that a validator
  fires, a schema validates, a gate holds.
- **Replay from cache.** Content-hash caching means a full pipeline run can be *replayed* with
  zero model calls — the regression suite for orchestration logic runs against cached artifacts.
- **Make the non-deterministic part small.** The more that is deterministic (extraction,
  arithmetic, traceability, policy), the more is ordinarily testable. This is a *reason* for the
  deterministic/judgement split, not just a consequence.
- **Measure what you cascade.** Any "cheap check first, expensive check on flag" design needs a
  sampled run of the expensive check to measure the cheap check's miss rate.
- **Guard edits mechanically.** A model pass that must not change facts (humanize) is verified
  by diff (numbers, claim refs) plus a cross-family entailment check on changed sentences — not
  by instructing the model to be careful.

## 26. Test data is part of the system  ·  🧭 PRINCIPLE

**Principle.** Corpora, fixtures, and golden files are code: versioned, validated, and
hygiene-checked.

**Applied here.** The transcript corpus needed a *quality gate* (sentences ≥20, mean length
<40 words, punctuation density) before it could be used, and a restoration pass for the four
unpunctuated files — verified by asserting the word sequence is unchanged apart from case and
terminal punctuation. Without that gate, the "human reference" would have been 40% garbage and
every band fitted from it wrong.

## 27. "Done" must be observable  ·  🧭 PRINCIPLE

**Principle.** A phase is complete when a stated, observable condition holds — not when the
code is written. Write the condition before starting the phase.

**Applied here.** Every phase in the plan has a "done when": *"every mutation test caught,"*
*"a rough HTML with no known markup still yields usable units,"* *"`video_script.html` passes
structure + traceability + renderer_compat."* Each is a test that either passes or doesn't.

---

# Part V — Phase planning

## 28. Principles for ordering work  ·  🧭 PRINCIPLE

1. **Prove the riskiest thesis first, with the least machinery.** The thesis here is *"story
   logic as structured data before narration makes scripts coherent."* V1A tests that with
   narration-only output — no HTML, no Playwright, no design system. If V1A fails, none of the
   rest matters; if it succeeds, the rest is engineering.
2. **Contracts before prompts; infrastructure before features.** Phase 0 builds both backends,
   the budget policy, the cache, and the leak test. Phase 1 builds every schema. Prompts come
   after, because prompts are the *least* stable artifact and should be written against fixed
   contracts.
3. **Vertical slices over horizontal layers.** V1A is a thin end-to-end path (extract → verify →
   plan → write → review → revise → emit), not "all extraction, then all planning." A thin slice
   produces real output early and exposes integration problems that layers hide.
4. **Defer what doesn't change the thesis.** Automatic design-system fitting, web retrieval for
   evidence, analytics feedback, model A/B rotation — all real, all V1D. Each was in V1 in an
   earlier draft; the review's point that "V1 resembled a full production platform" was correct.
5. **Every phase ends in an observable "done" and a runnable artifact.**

## 29. The phases and their dependency logic  ·  🔧 PROJECT DECISION

```
Phase 0  Infrastructure ─────► both backends, local budget policy, cache, key-leak test
   │                          (nothing above can be tested without these)
Phase 1  Contracts ──────────► every schema + golden fixtures
   │                          (prompts must target fixed shapes)
V1A      Script intelligence ─► extract → claims → verify source → understand → plan →
   │                           draft → independent review → conditional revision →
   │                           policy gate → narration.json + script.md
   │                          PROVES: the story thesis; every mutation test caught
V1B      HTML ───────────────► HTML author, static render checks, number traceability,
   │                           web retrieval for evidence requests
   │                          PROVES: the output the render pipeline needs
V1C      Visual loop ────────► Playwright, screenshots, multimodal audit, HTML repair loop
   │                          PROVES: render failures caught and repaired on the cheap lane
V1D      Calibration ────────► corpus restoration + refit, band tuning against the channel's
                               own data, series ledger automation, design-system fitting,
                               measured-audio WPM, analytics feedback
```

Each arrow is a dependency: nothing in a later phase can be tested until the earlier one's
"done" holds. That dependency graph *is* the phase plan; the phases are just its topological
order.

## 30. Budgeting and estimating  ·  🧪 HEURISTIC

**Principle.** Estimate by *uncertainty*, not by size. The parts you've verified are cheap to
estimate; the parts you haven't are where the time goes. Spend estimation effort there.

**Applied here.** The two-lane client is well understood (the recipe was verified). Extraction
is well understood (the files were inspected). The uncertain parts are prompt quality for A2
(story planning) and C2b (grounding) — which is exactly why V1A isolates them with everything
else held simple.

## 31. Change management — how the plan itself evolved  ·  🧭 PRINCIPLE

**Principle.** A design document is a living artifact. Review it externally, record every
deviation from the original spec with its reason, and version it. When patches accumulate,
re-read end-to-end — incremental edits drift.

**Applied here.** The plan went through: an initial version; five in-conversation revisions as
the goal was clarified (input type, output type, voice requirement, design-system generality,
viewer outcomes); a full consistency pass that found **41 stale references and two real bugs**
introduced by incremental patching (the sequencing error and a component that contradicted a
decision three sections earlier); an external review that found metric over-fitting and led to
a clean rewrite as version 2; and a second review that found the grounding loophole and the
source-vs-verified distinction. Three appendices record every deviation and every response.

**The transferable habit:** after N incremental edits, stop and re-read the whole thing. The
consistency pass took an hour and found two design bugs that no single edit had introduced.

**Record decisions, not just designs.** Every major choice in the plan now has an architecture
decision record (Appendix D): context, alternatives, benefits, costs, and — the most
educational field — *revisit when*. System design is not only why you chose something; it is
knowing the conditions under which that choice stops being right.

---

# Part VI — The mistakes, collected

These are the most useful part of the document. Each was made *during this design*, by someone
trying to be careful, and caught by a check that is now part of the method.

| # | Mistake | How it was caught | Rule it produced |
|---|---|---|---|
| 1 | Believed the spec's description of the input ("has narration, animations, durations") | Opening the actual files | Verify every spec claim against the artifacts (§2) |
| 2 | Would have used a DOM-only extractor | Noticing a `<script>` object held the formulas | Inventory *where* the data actually lives, not where it's supposed to (§2) |
| 3 | Would have used `node:vm` to read that data | External review | Never execute input; parse literals (§19) |
| 4 | Assumed `claude -p` was cheap | Running one call: 30,167 tokens | De-risk the assumption the cost model rests on (§5) |
| 5 | Held up screen-text fragments as the narration voice target | Measuring both corpora: 27× difference | Different text types need different references (§5) |
| 6 | Adopted "avoid Now/So/Next" from the docs | Measuring: humans signpost 8.8/100 | Measure before adopting a rule, even from a trusted source (§5) |
| 7 | Fitted voice metrics over the whole transcript corpus | One "sentence" of 5,249 words | Gate corpus quality before fitting anything (§26) |
| 8 | Turned diagnostics into hard gates; set a gate that rejected the corpus it came from | External review | Bands from data; advisory by default; escalate on clusters (§22) |
| 9 | Sequenced retention diagnostics after HTML synthesis while routing their failures to the planner | End-to-end consistency read | A stage runs before the earliest stage that acts on it (§13) |
| 10 | Kept a `voice_editor.py` agent in the layout after deciding humanize was a mode | Same consistency read | After N patches, re-read everything (§31) |
| 11 | Let the writer's own sentence labels decide which sentences get fact-checked | External review | The producer's metadata is never the security boundary (§11) |
| 12 | Called the claim registry "the source of truth" | External review | Layer trust levels; source assertions ≠ verified facts (§12) |
| 13 | Let the Story Lead declare its own script PASS | External review | No component approves its own work (§11) |
| 14 | Overlapping status definitions (AMBER qualified for both PASS and PASS_WARN) | External review | Ordered precedence; first match wins |
| 15 | Ran every paid review on every clean run | External review | Cascade cheap → expensive; sample the expensive to measure the cheap (§16) |
| 16 | Assumed LiteLLM removes the need for provider keys | Owner's question | An abstraction over APIs is not a provider of access (§14) |
| 17 | Taught "if code can decide it, it's a hard gate" in this very guide | External review | Deterministic ≠ unacceptable; two questions, not one (§10) |
| 18 | Classed "human voice" as a hard constraint | External review | Product requirement → quality objective + one hard invariant (§4) |
| 19 | Restricted expansion to *literal* registered claims | External review | Grounding sources include verified derivation, verified external evidence, and safe inference (§19) |
| 21 | Left "the registry is the source of truth" in one section after replacing it in another; defined `C1-lite` nowhere; wrote a cost invariant with float equality | Final hygiene review | After every review round, grep the whole document for the *old* phrasing, not just the section you edited (§31) |
| 20 | Made a short inherit its parent's archetype, made the spoken bridge mandatory, and hard-gated a word count — three sections after writing "deterministic ≠ gate" | External review | Derive knowledge, not storytelling; product semantics decide gates; re-read your own rules (§20a, §10) |

Notice the pattern in the "how caught" column: *opening files, running one call, measuring,
re-reading, and external review.* None of them is cleverness. All of them are habits.

---

# Part VI-b — Classical system-design concepts, as they appear in this pipeline

The vocabulary of large-scale system design applies to a batch pipeline too — the scale is
smaller, the concepts identical. Each one is present here; knowing where lets you recognise
it elsewhere.

| Concept | Where it lives in this pipeline |
|---|---|
| **Capacity planning** | the subscription lane's rolling quota window is the capacity; batching per act and the stripped-flag recipe are how it's spent |
| **Latency vs throughput** | `asyncio.gather` on independent reviews cuts wall-clock; concurrency cap of 2 protects quota — a deliberate throughput ceiling |
| **Backpressure** | the Claude semaphore plus checkpoint-and-stop on rate limit: the system slows and persists rather than dropping work or failing over |
| **Idempotency** | content-hash cache keys make every stage re-runnable with the same result; a resumed run never double-pays |
| **Durability** | one artifact on disk per stage; state is the JSON dump, not process memory |
| **Consistency** | one number registry feeds narration *and* DOM; `data-numeric-claim-id` is the foreign key that lets HV verify the join |
| **Caching** | per-stage keys with the rule that a stage's own output never enters its key; provider-side prompt caching via stable prefixes |
| **Failure domains** | the two lanes fail independently — a paid-API outage cannot take down drafting; a quota exhaustion cannot take down verification |
| **Horizontal scaling** | runs are independent; a benchmark sweep is N processes sharing only the cache and the quota window |
| **SLOs** | the fitted bands *are* SLOs on voice and retention — targets with tolerances, reported, not gated |
| **Graceful degradation** | §17: optional critics skip visibly; invariants fail closed |
| **Observability** | `usage.jsonl`, `run_manifest.json` with resolved model ids and prompt versions |
| **Cost attribution / FinOps** | one `UsageRecord` per call; per-agent, per-stage, per-cycle breakdown; billed vs notional; cache savings; reconciliation as an invariant (§18a) |
| **Architecture decision records** | `IMPLEMENTATION_PLAN.md` Appendix D — each major choice with its alternatives, costs, and *revisit-when* |

# Part VII — The checklist: what to consider before building any system

Use this on the next system. Each item links back to the section that explains it.

**Before designing**
- [ ] Success is defined as outcomes, not outputs; the design is grepped for the outcome words (§1)
- [ ] Every input, consumer, and prior artifact is inventoried — and *verified against reality* (§2)
- [ ] The boundary is explicit: what's replaced, what's kept, what contract sits at each edge (§3)
- [ ] Constraints are listed and classified hard / soft / self-imposed (§4)
- [ ] The top assumptions by cost-if-wrong × cheapness-to-test have been tested (§5)
- [ ] Known failure modes are catalogued and each maps to a check (§6)
- [ ] Non-functional requirements are elicited: cost, reproducibility, debuggability, safety (§7)

**Architecture**
- [ ] Data contracts are defined and fixtured before components (§8)
- [ ] Components are split by distinct failure mode, not by convenience or by model (§9)
- [ ] Every check is classified: code measures, model judges, or heuristic informs — and **deterministic ≠ gate**; only unacceptable-if-violated becomes a gate (§10, §21)
- [ ] No component can approve its own work; producer metadata is never a security boundary (§11)
- [ ] Trust levels are layered; "the input says" ≠ "it is true" (§12)
- [ ] Control flow matches the real shape; stages run before whatever acts on them; nothing runs because it exists (§13)
- [ ] Interchangeable implementations sit below one caller-shaped interface (§14)
- [ ] Each component receives only what its job needs (§15)
- [ ] Cost levers are identified; the budget boundary is local code; cascades are sampled (§16)
- [ ] Transport, schema, and creative failures have separate counters; state is checkpointed; failures are loud (§17)
- [ ] Every capability is classed fail-closed / retry / degrade-visibly (§17)
- [ ] Every run leaves enough to reconstruct what ran, with what, at what cost (§18)
- [ ] Every unit of spend is attributed to a component and a reason; billed and notional are separate; totals reconcile or the run fails (§18a)
- [ ] Input is never executed; credentials can't cross lanes; generation can't fabricate (§19)
- [ ] Frequently-changing things live in config; seams exist for expected changes (§20)
- [ ] Each new use case is classified parameter-or-product by its outcome table; products derive from shared verified layers rather than regenerating (§20a)

**Gates**
- [ ] Hard gates are few, mechanical, and non-negotiable (§21)
- [ ] Every numeric threshold came from data and admits the best real examples; otherwise it's a diagnostic (§22)
- [ ] Soft signals escalate when they cluster (§22)
- [ ] Rules were checked against every kind of content the system handles (§23)

**Testing**
- [ ] Unit tests cover everything deterministic (§24)
- [ ] Contract tests run before any prompt exists (§24)
- [ ] Smoke tests assert side effects — cost logs, resolved model ids, the key-leak test (§24)
- [ ] Every review stage has mutation tests that name their catcher (§24)
- [ ] Fitted thresholds have held-out tests (§24)
- [ ] Golden benchmarks answer the real question (§24)
- [ ] Repeated-run stability is measured — quality includes variance (§24a)
- [ ] Cached replays make orchestration regression-testable without model calls (§25)
- [ ] Test data is gated for quality and versioned (§26)
- [ ] Every phase's "done" is an observable condition written before the phase starts (§27)

**Phasing**
- [ ] The riskiest thesis is proved first with the least machinery (§28)
- [ ] Infrastructure and contracts precede features and prompts (§28)
- [ ] Phases are vertical slices; each ends in a runnable artifact (§28)
- [ ] Everything that doesn't change the thesis is deferred, explicitly (§28)
- [ ] Estimation effort goes to the uncertain parts (§30)
- [ ] The design is externally reviewed; deviations and responses are recorded; after N patches it is re-read whole (§31)
- [ ] Major decisions have ADRs with a *revisit-when* (§31)

---

# Appendix — Reading map

| To learn about | Read here | Then in `IMPLEMENTATION_PLAN.md` |
|---|---|---|
| defining the goal | Part I §1 | §1.2 |
| verifying inputs | Part I §2, §5 | §0 |
| the two-lane backend | Part II §14, §16 | §3, §4 |
| cost attribution | Part II §18a | §4.1 |
| shorts / a second format | Part II §20a | §20 |
| data contracts | Part II §8 | §5 |
| trust layering | Part II §12 | §6.5 |
| independence | Part II §11 | §2, §5.1, §9, §14 |
| orchestration | Part II §13 | §8 |
| hard vs soft | Part III | §9, §10, §14 |
| voice system as a worked example of measurement | Part I §5, Part III §22 | §11 |
| testing | Part IV | §18 |
| phases | Part V | §17 |
| what the reviews changed | Part VI | Appendices A–C |
