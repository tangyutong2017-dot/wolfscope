"""Framework-independent structured model call protocol and trace records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field

from wolfscope.agents.schemas import AgentDecisionInput, DecisionTask
from wolfscope.contracts import Seat, StrictModel

from .config import DeepSeekModelConfig


class TokenUsage(StrictModel):
    input_tokens: int = 0
    output_tokens: int = 0


class ModelAttemptRecord(StrictModel):
    attempt_index: int
    stage: str
    success: bool
    latency_ms: int
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    failure_reason: str | None = None
    thinking_enabled: bool | None = None


class ModelCallRecord(StrictModel):
    call_id: int
    player: Seat
    task: DecisionTask
    model_name: str
    thinking_enabled: bool
    success: bool
    latency_ms: int
    retry_count: int = 0
    fallback_used: bool = False
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    error_type: str | None = None
    invalid_target: Seat | None = None
    invalid_event_ids: tuple[int, ...] = ()
    invalid_evidence_ids: tuple[str, ...] = ()
    accepted_evidence_ids: tuple[str, ...] = ()
    accepted_brief_evidence_ids: tuple[str, ...] = ()
    accepted_context_only_evidence_ids: tuple[str, ...] = ()
    invalid_strategy_ids: tuple[str, ...] = ()
    accepted_strategy_ids: tuple[str, ...] = ()
    failure_stage: str | None = None
    failure_reason: str | None = None
    attempts: tuple[ModelAttemptRecord, ...] = ()
    speech_original_chars: int | None = Field(default=None, ge=0)
    speech_final_chars: int | None = Field(default=None, ge=0)
    speech_truncated: bool = False


TModel = TypeVar("TModel", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ModelCallResult:
    value: BaseModel
    record: ModelCallRecord


class ModelGatewayError(ValueError):
    def __init__(self, message: str, record: ModelCallRecord) -> None:
        super().__init__(message)
        self.record = record


class ModelGateway(Protocol):
    async def structured_call(
        self,
        *,
        player: int,
        task: DecisionTask,
        decision_input: AgentDecisionInput,
        output_schema: type[TModel],
        config: DeepSeekModelConfig,
    ) -> ModelCallResult:
        ...
