# script-pipeline

Multi-agent pipeline: rough content HTML → verified, human-sounding YouTube
video-script HTML (+ derived shorts). Design lives in
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (frozen v3.2) and
[`SYSTEM_DESIGN_GUIDE.md`](SYSTEM_DESIGN_GUIDE.md) (the method, taught).
Build tracking lives in [`BUILD_PLAN.md`](BUILD_PLAN.md).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# create .env with OPENAI_API_KEY=... and GEMINI_API_KEY=...
```

The subscription lane (Sonnet/Haiku) needs no key — it shells out to the
`claude` CLI you're already authenticated with, and explicitly unsets
`ANTHROPIC_API_KEY` so it can never bill the API by accident.

V1C's rendered HV checks (clipping/overflow/invisible-content/contrast)
need a real browser — only required to run those checks or their
`pytest -m integration` tests, not for the rest of the pipeline:

```bash
pip install -e ".[dev,render]"
python3 -m playwright install chromium
```

## Running tests

```bash
pytest              # unit tests only (fast, free) — this is the default
pytest -m integration   # + real API/CLI calls: costs a fraction of a cent
                         # (OpenAI) or subscription quota (Claude); nothing
                         # runs against a live provider unless you ask for it
```

## Layout

Source lives under `src/` as flat top-level packages (`llm/`, `orchestration/`,
`config/`, ...), matching `IMPLEMENTATION_PLAN.md` §16 literally rather than
nesting everything under one wrapper package. Packages not yet implemented
carry a docstring pointing at the plan section and phase that specifies them
— see `BUILD_PLAN.md` for what's built vs. planned.

## Cost discipline

Every model call — both lanes — produces one `UsageRecord` (`llm/usage.py`).
Paid-lane cost is billed dollars from LiteLLM's public cost interface;
subscription-lane cost is *notional* (what it would have cost — never
billed). A local `BudgetCounter` (`llm/budget.py`) enforces target/warning/
hard-cap tiers per run; nothing here trusts a provider or library to self-report
correctly — see `IMPLEMENTATION_PLAN.md` §3–4 and Appendix G.
