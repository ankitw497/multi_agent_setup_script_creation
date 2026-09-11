"""The Agent shape shared by all 5 identities (plan §2).

An agent is one base system prompt + one model + one lane. A pass is one
stateless call in a named mode, with its own task prompt and its own
isolated context (plan §2.4) -- no conversation history between calls.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel

from llm.budget import BudgetCounter
from llm.client import LLMClient, StructuredCallResult
from llm.structured import schema_prompt

T = TypeVar("T", bound=BaseModel)

Lane = Literal["subscription", "paid_api"]


@dataclass
class Agent:
    name: str  # one of llm.usage.VALID_AGENTS
    lane: Lane
    client: LLMClient
    model_alias: str
    model_resolved: str
    base_system_prompt: str
    default_reasoning_effort: str | None = None  # from config/models.yaml; a per-call override wins
    default_max_tokens: int | None = None  # from config/models.yaml; a per-call override wins

    def run(
        self,
        *,
        pass_id: str,
        mode: str,
        task_prompt: str,
        payload: dict,
        schema: type[T],
        revision_cycle: int = 0,
        budget: BudgetCounter | None = None,
        estimated_usd: float = 0.0,
        reasoning_effort: str | None = None,
        timeout_s: int | None = None,
        max_tokens: int | None = None,
        images: list[str] | None = None,
    ) -> T:
        reasoning_effort = reasoning_effort if reasoning_effort is not None else self.default_reasoning_effort
        max_tokens = max_tokens if max_tokens is not None else self.default_max_tokens
        system_prompt = f"{self.base_system_prompt}\n\n{task_prompt}\n\n{schema_prompt(schema)}"
        user_payload = json.dumps(payload, default=str)

        if self.lane == "subscription":
            if images:
                raise ValueError(
                    f"{self.name}.{pass_id}: images given for a subscription-lane call -- "
                    "the Claude CLI backend has no multimodal support (V1C's C3 visual "
                    "critic is paid_api/Gemini-lane only)"
                )
            result: StructuredCallResult = self.client.call_structured_subscription(
                agent=self.name, pass_id=pass_id, mode=mode,
                model_alias=self.model_alias, model_resolved=self.model_resolved,
                system_prompt=system_prompt, user_payload=user_payload,
                schema=schema, revision_cycle=revision_cycle, timeout_s=timeout_s,
            )
        else:
            if budget is None:
                raise ValueError(f"{self.name}.{pass_id}: paid-lane calls require a BudgetCounter")
            result = self.client.call_structured_paid(
                agent=self.name, pass_id=pass_id, mode=mode,
                model_alias=self.model_alias, model=self.model_resolved,
                system_prompt=system_prompt, user_payload=user_payload,
                schema=schema, budget=budget, estimated_usd=estimated_usd,
                revision_cycle=revision_cycle, reasoning_effort=reasoning_effort,
                max_tokens=max_tokens, images=images,
            )
        return result.value  # type: ignore[return-value]
