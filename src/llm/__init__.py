"""llm — the two-lane model layer (plan §3).

One call_structured() interface; two backends underneath it:

  ClaudeCliBackend    subscription_lane   sonnet | haiku    quota-limited, $0 marginal
  LiteLLMBackend      paid_api_lane       gpt | gemini       metered, local budget policy

Neither backend knows about story logic. Money is tracked in integer
microdollars everywhere (Appendix G #8) so reconciliation is exact.
"""
