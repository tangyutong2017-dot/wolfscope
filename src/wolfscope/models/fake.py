"""Queued deterministic model outcomes for zero-cost M2 tests."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, TypeVar

from pydantic import BaseModel, ValidationError

from wolfscope.agents.schemas import AgentDecisionInput, DecisionTask

from .config import DeepSeekModelConfig
from .gateway import (
    ModelCallRecord,
    ModelCallResult,
    ModelGatewayError,
    TokenUsage,
)


@dataclass(frozen=True, slots=True)
class FakeResponse:
    payload: Any
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


TModel = TypeVar("TModel", bound=BaseModel)


class FakeModelGateway:
    def __init__(self, responses: Iterable[FakeResponse | Any]) -> None:
        self._responses = deque(
            response if isinstance(response, FakeResponse) else FakeResponse(response)
            for response in responses
        )
        self.records: list[ModelCallRecord] = []
        self.inputs: list[AgentDecisionInput] = []

    async def structured_call(
        self,
        *,
        player: int,
        task: DecisionTask,
        decision_input: AgentDecisionInput,
        output_schema: type[TModel],
        config: DeepSeekModelConfig,
    ) -> ModelCallResult:
        if not self._responses:
            raise RuntimeError("FakeModelGateway has no queued response")
        response = self._responses.popleft()
        self.inputs.append(decision_input.model_copy(deep=True))
        usage = TokenUsage(
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
        base = {
            "call_id": len(self.records) + 1,
            "player": player,
            "task": task,
            "model_name": config.model_name,
            "thinking_enabled": config.thinking_enabled,
            "latency_ms": response.latency_ms,
            "token_usage": usage,
        }
        try:
            value = output_schema.model_validate(response.payload)
        except ValidationError as error:
            record = ModelCallRecord(
                **base,
                success=False,
                error_type="schema_validation",
            )
            self.records.append(record)
            raise ModelGatewayError("fake structured output failed validation", record) from error
        record = ModelCallRecord(**base, success=True)
        self.records.append(record)
        return ModelCallResult(value=value, record=record)

    @property
    def remaining_responses(self) -> int:
        return len(self._responses)
