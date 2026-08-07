"""Seat-isolated model runtime and call trace ownership."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, TypeVar

from pydantic import BaseModel

from wolfscope.agents.fallback import safe_fallback_decision
from wolfscope.models.config import DeepSeekModelConfig
from wolfscope.models.gateway import (
    ModelCallRecord,
    ModelGateway,
    ModelGatewayError,
)

from .schemas import (
    AgentDecisionInput,
    DecisionTask,
    VoteDecision,
    VoteTaskObservation,
)


TModel = TypeVar("TModel", bound=BaseModel)


@dataclass(slots=True)
class PlayerRuntime:
    seat: int
    model_config: DeepSeekModelConfig
    gateway: ModelGateway
    last_view_revision: int = 0
    call_records: list[ModelCallRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 1 <= self.seat <= 9:
            raise ValueError("runtime seat must be between 1 and 9")

    async def decide(
        self,
        *,
        task: DecisionTask,
        decision_input: AgentDecisionInput,
        output_schema: type[TModel],
        use_safe_fallback: bool = False,
    ) -> TModel:
        view = decision_input.player_view
        if view.viewer_seat != self.seat:
            raise ValueError("PlayerRuntime cannot process another seat's PlayerView")
        if view.view_revision < self.last_view_revision:
            raise ValueError("PlayerRuntime cannot process a stale PlayerView revision")
        try:
            result = await self.gateway.structured_call(
                player=self.seat,
                task=task,
                decision_input=decision_input,
                output_schema=output_schema,
                config=self.model_config,
            )
        except ModelGatewayError as error:
            record = error.record
            if use_safe_fallback:
                record = record.model_copy(update={"fallback_used": True})
                self.call_records.append(record)
                self.last_view_revision = view.view_revision
                return safe_fallback_decision(
                    task=task,
                    decision_input=decision_input,
                    output_schema=output_schema,
                )
            self.call_records.append(record)
            raise
        if not isinstance(result.value, output_schema):
            raise TypeError("ModelGateway returned a value outside the requested schema")
        if isinstance(result.value, VoteDecision):
            observation = decision_input.observation
            if not isinstance(observation, VoteTaskObservation):
                raise TypeError("VoteDecision requires VoteTaskObservation")
            if (
                result.value.target is not None
                and result.value.target not in observation.candidates
            ):
                self.call_records.append(
                    result.record.model_copy(
                        update={
                            "success": False,
                            "fallback_used": True,
                            "error_type": "illegal_target",
                            "invalid_target": result.value.target,
                        },
                    ),
                )
                self.last_view_revision = view.view_revision
                return output_schema.model_validate(
                    {
                        "action": "vote",
                        "target": None,
                        "confidence": 0.0,
                        "reason": "模型选择了非法候选人，本轮确定性改为弃票。",
                    },
                )
        self.call_records.append(result.record)
        self.last_view_revision = view.view_revision
        return result.value


class PlayerRuntimeRegistry:
    def __init__(self, runtimes: dict[int, PlayerRuntime]) -> None:
        if set(runtimes) != set(range(1, 10)):
            raise ValueError("runtime registry requires seats 1 through 9")
        self._runtimes = runtimes

    @classmethod
    def create(
        cls,
        model_config: DeepSeekModelConfig,
        gateway_factory: Callable[[int], ModelGateway],
    ) -> PlayerRuntimeRegistry:
        return cls(
            {
                seat: PlayerRuntime(
                    seat=seat,
                    model_config=model_config,
                    gateway=gateway_factory(seat),
                )
                for seat in range(1, 10)
            },
        )

    def get(self, seat: int) -> PlayerRuntime:
        return self._runtimes[seat]

    @property
    def seats(self) -> tuple[int, ...]:
        return tuple(self._runtimes)
