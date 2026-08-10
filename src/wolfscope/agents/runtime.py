"""Seat-isolated model runtime and call trace ownership."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, TypeVar

from pydantic import BaseModel

from wolfscope.agents.fallback import (
    safe_fallback_decision,
    seer_badge_flow_target,
)
from wolfscope.cognition.strategy import SituationTag
from wolfscope.models.config import DeepSeekModelConfig
from wolfscope.models.gateway import (
    ModelCallRecord,
    ModelGateway,
    ModelGatewayError,
)

from .schemas import (
    AgentDecisionInput,
    BadgeTransferDecision,
    BadgeTransferTaskObservation,
    DecisionTask,
    ComplexityLevel,
    HunterTargetDecision,
    HunterTargetTaskObservation,
    SheriffVoteDecision,
    SheriffVoteTaskObservation,
    SeerTargetDecision,
    SeerTargetTaskObservation,
    VoteDecision,
    VoteTaskObservation,
    WitchActionDecision,
    WitchActionTaskObservation,
    WolfTargetDecision,
    WolfTargetTaskObservation,
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
                record = record.model_copy(
                    update={
                        "fallback_used": True,
                        "final_complexity_level": ComplexityLevel.DETERMINISTIC.value,
                    },
                )
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
        record = result.record.model_copy(
            update={
                "initial_complexity_level": decision_input.complexity_level.value,
                "final_complexity_level": (
                    ComplexityLevel.MINIMAL_REPAIR.value
                    if result.record.retry_count > 0
                    else decision_input.complexity_level.value
                ),
                "complexity_reason": decision_input.complexity_reason,
            },
        )
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
        legal_target = True
        if isinstance(decision, WolfTargetDecision):
            observation = decision_input.observation
            if not isinstance(observation, WolfTargetTaskObservation):
                raise TypeError("WolfTargetDecision requires wolf observation")
            legal_target = decision.target in observation.eligible_targets
            plan_seats = {item.seat for item in decision.team_plan.assignments}
            legal_target = legal_target and plan_seats == set(observation.wolf_seats)
            legal_target = (
                legal_target
                and decision.team_plan.day == decision_input.player_view.day
            )
            legal_target = legal_target and (
                decision.team_plan.primary_claimant is None
                or decision.team_plan.primary_claimant in observation.wolf_seats
            )
            legal_target = legal_target and (
                decision.team_plan.focus_target is None
                or decision.team_plan.focus_target in observation.eligible_targets
            )
            previous_plan = (
                decision_input.strategy_brief.wolf_team_plan
                if decision_input.strategy_brief is not None
                else None
            )
            if (
                previous_plan is not None
                and previous_plan.day < decision.team_plan.day
                and previous_plan.claimed_role == "seer"
                and decision.team_plan.claimed_role == "seer"
                and previous_plan.primary_claimant == decision.team_plan.primary_claimant
            ):
                legal_target = legal_target and (
                    decision.team_plan.fake_check_target
                    != previous_plan.fake_check_target
                )
        elif isinstance(decision, SeerTargetDecision):
            observation = decision_input.observation
            if not isinstance(observation, SeerTargetTaskObservation):
                raise TypeError("SeerTargetDecision requires seer observation")
            legal_target = decision.target in observation.eligible_targets
        elif isinstance(decision, WitchActionDecision):
            observation = decision_input.observation
            if not isinstance(observation, WitchActionTaskObservation):
                raise TypeError("WitchActionDecision requires witch observation")
            legal_target = (
                decision.action == "pass"
                or (
                    decision.action == "save"
                    and observation.antidote_available
                    and observation.can_save
                    and decision.target == observation.night_victim
                )
                or (
                    decision.action == "poison"
                    and observation.poison_available
                    and decision.target in observation.poison_targets
                )
            )
        elif isinstance(decision, HunterTargetDecision):
            observation = decision_input.observation
            if not isinstance(observation, HunterTargetTaskObservation):
                raise TypeError("HunterTargetDecision requires hunter observation")
            legal_target = (
                decision.target is None
                or decision.target in observation.eligible_targets
            )
        elif isinstance(decision, BadgeTransferDecision):
            observation = decision_input.observation
            if not isinstance(observation, BadgeTransferTaskObservation):
                raise TypeError("BadgeTransferDecision requires badge observation")
            legal_target = (
                decision.target is None
                or decision.target in observation.eligible_targets
            )
        if not legal_target:
            self.call_records.append(
                record.model_copy(
                    update={
                        "success": False,
                        "fallback_used": True,
                        "error_type": "illegal_target",
                        "invalid_target": decision.target,
                        "final_complexity_level": ComplexityLevel.DETERMINISTIC.value,
                    },
                ),
            )
            self.last_view_revision = view.view_revision
            return safe_fallback_decision(
                task=task,
                decision_input=decision_input,
                output_schema=output_schema,
            )
        if isinstance(decision, BadgeTransferDecision) and view.own_role.value == "seer":
            observation = decision_input.observation
            if not isinstance(observation, BadgeTransferTaskObservation):
                raise TypeError("BadgeTransferDecision requires badge observation")
            expected_target = seer_badge_flow_target(decision_input)
            if decision.target != expected_target:
                self.call_records.append(
                    record.model_copy(
                        update={
                            "success": False,
                            "fallback_used": True,
                            "error_type": "seer_badge_constraint",
                            "invalid_target": decision.target,
                            "final_complexity_level": ComplexityLevel.DETERMINISTIC.value,
                        },
                    ),
                )
                self.last_view_revision = view.view_revision
                return safe_fallback_decision(
                    task=task,
                    decision_input=decision_input,
                    output_schema=output_schema,
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
            strategy = decision_input.strategy_brief
            if (
                isinstance(decision, VoteDecision)
                and view.own_role.value != "werewolf"
                and strategy is not None
                and SituationTag.DAY_ONE_SINGLE_SEER_HIGH_TRUST
                in strategy.situation_tags
            ):
                brief = decision_input.decision_brief
                seer_claimants = {
                    claim.subject
                    for claim in brief.role_claims
                    if claim.speaker == claim.subject
                    and claim.role.value == "seer"
                    and claim.polarity.value == "assert"
                } if brief is not None else set()
                sole_seer = (
                    next(iter(seer_claimants))
                    if len(seer_claimants) == 1
                    else None
                )
                violates_working_consensus = (
                    decision.target is None or decision.target == sole_seer
                )
                if violates_working_consensus:
                    self.call_records.append(
                        record.model_copy(
                            update={
                                "success": False,
                                "fallback_used": True,
                                "error_type": "provisional_single_seer_vote_constraint",
                                "invalid_target": decision.target,
                                "final_complexity_level": ComplexityLevel.DETERMINISTIC.value,
                            },
                        ),
                    )
                    self.last_view_revision = view.view_revision
                    return safe_fallback_decision(
                        task=task,
                        decision_input=decision_input,
                        output_schema=output_schema,
                    )
            if isinstance(decision, VoteDecision) and view.own_role.value == "seer":
                confirmed_wolves = {
                    event.target
                    for event in view.visible_events
                    if event.event_type == "seer_result"
                    and event.actor == self.seat
                    and event.target in observation.candidates
                    and event.data.get("alignment") == "werewolf"
                }
                confirmed_goods = {
                    event.target
                    for event in view.visible_events
                    if event.event_type == "seer_result"
                    and event.actor == self.seat
                    and event.target in observation.candidates
                    and event.data.get("alignment") == "good"
                }
                violates_check = (
                    bool(confirmed_wolves)
                    and decision.target not in confirmed_wolves
                ) or decision.target in confirmed_goods
                if violates_check:
                    self.call_records.append(
                        record.model_copy(
                            update={
                                "success": False,
                                "fallback_used": True,
                                "error_type": "seer_check_constraint",
                                "invalid_target": decision.target,
                                "final_complexity_level": ComplexityLevel.DETERMINISTIC.value,
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
