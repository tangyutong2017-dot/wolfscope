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
    SheriffVoteDecision,
    SheriffVoteTaskObservation,
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
            call_config = (
                self.model_config.model_copy(
                    update={"max_tokens": self.model_config.vote_max_tokens},
                )
                if task is DecisionTask.VOTE
                else self.model_config
            )
            result = await self.gateway.structured_call(
                player=self.seat,
                task=task,
                decision_input=decision_input,
                output_schema=output_schema,
                config=call_config,
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
        decision = result.value
        visible_event_ids = {
            event.event_id for event in decision_input.player_view.visible_events
        }
        submitted_event_ids = tuple(getattr(decision, "event_ids", ()))
        invalid_event_ids = tuple(
            event_id
            for event_id in submitted_event_ids
            if event_id not in visible_event_ids
        )
        record = result.record
        if invalid_event_ids:
            decision = decision.model_copy(
                update={
                    "event_ids": tuple(
                        event_id
                        for event_id in submitted_event_ids
                        if event_id in visible_event_ids
                    ),
                },
            )
            record = record.model_copy(
                update={"invalid_event_ids": invalid_event_ids},
            )
        valid_evidence_ids = set(decision_input.available_evidence_ids)
        submitted_evidence_ids = tuple(getattr(decision, "evidence_ids", ()))
        invalid_evidence_ids = tuple(
            evidence_id
            for evidence_id in submitted_evidence_ids
            if evidence_id not in valid_evidence_ids
        )
        if invalid_evidence_ids:
            decision = decision.model_copy(
                update={
                    "evidence_ids": tuple(
                        evidence_id
                        for evidence_id in submitted_evidence_ids
                        if evidence_id in valid_evidence_ids
                    ),
                },
            )
            record = record.model_copy(
                update={"invalid_evidence_ids": invalid_evidence_ids},
            )
        accepted_evidence_ids = tuple(
            evidence_id
            for evidence_id in submitted_evidence_ids
            if evidence_id in valid_evidence_ids
        )
        brief = decision_input.decision_brief
        brief_evidence_ids = set(brief.evidence_ids if brief is not None else ())
        accepted_brief_evidence_ids = tuple(
            evidence_id
            for evidence_id in accepted_evidence_ids
            if evidence_id in brief_evidence_ids
        )
        accepted_context_only_evidence_ids = tuple(
            evidence_id
            for evidence_id in accepted_evidence_ids
            if evidence_id not in brief_evidence_ids
        )
        record = record.model_copy(
            update={
                "accepted_evidence_ids": accepted_evidence_ids,
                "accepted_brief_evidence_ids": accepted_brief_evidence_ids,
                "accepted_context_only_evidence_ids": (
                    accepted_context_only_evidence_ids
                ),
            },
        )
        strategy_brief = decision_input.strategy_brief
        valid_strategy_ids = set(
            strategy_brief.strategy_ids if strategy_brief is not None else (),
        )
        submitted_strategy_ids = tuple(getattr(decision, "strategy_ids", ()))
        invalid_strategy_ids = tuple(
            strategy_id
            for strategy_id in submitted_strategy_ids
            if strategy_id not in valid_strategy_ids
        )
        if invalid_strategy_ids:
            decision = decision.model_copy(
                update={
                    "strategy_ids": tuple(
                        strategy_id
                        for strategy_id in submitted_strategy_ids
                        if strategy_id in valid_strategy_ids
                    ),
                },
            )
        accepted_strategy_ids = tuple(
            strategy_id
            for strategy_id in submitted_strategy_ids
            if strategy_id in valid_strategy_ids
        )
        record = record.model_copy(
            update={
                "invalid_strategy_ids": invalid_strategy_ids,
                "accepted_strategy_ids": accepted_strategy_ids,
            },
        )
        if isinstance(decision, (VoteDecision, SheriffVoteDecision)):
            observation = decision_input.observation
            if not isinstance(
                observation,
                (VoteTaskObservation, SheriffVoteTaskObservation),
            ):
                raise TypeError("vote decision requires a vote observation")
            if (
                decision.target is not None
                and decision.target not in observation.candidates
            ):
                self.call_records.append(
                    record.model_copy(
                        update={
                            "success": False,
                            "fallback_used": True,
                            "error_type": "illegal_target",
                            "invalid_target": decision.target,
                        },
                    ),
                )
                self.last_view_revision = view.view_revision
                return safe_fallback_decision(
                    task=task,
                    decision_input=decision_input,
                    output_schema=output_schema,
                )
        self.call_records.append(record)
        self.last_view_revision = view.view_revision
        return decision


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
