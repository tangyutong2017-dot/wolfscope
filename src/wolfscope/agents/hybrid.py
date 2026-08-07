"""Temporary provider routing public M2 tasks to isolated player runtimes."""

from __future__ import annotations

from wolfscope.agents.runtime import PlayerRuntimeRegistry
from wolfscope.agents.schemas import (
    AgentDecisionInput,
    DecisionTask,
    PublicGameSummary,
    SpeechDecision,
    SpeechTaskObservation,
    VoteDecision,
    VoteTaskObservation,
)
from wolfscope.game.day import DayTurnAction
from wolfscope.player_view import PlayerViewBuilder

from .support import DeterministicSupportProvider


class HybridProvider:
    """Route speech/votes to agents and all remaining actions to support."""

    def __init__(
        self,
        *,
        view_builder: PlayerViewBuilder,
        runtimes: PlayerRuntimeRegistry,
        support: DeterministicSupportProvider,
    ) -> None:
        self.view_builder = view_builder
        self.runtimes = runtimes
        self.support = support

    async def take_day_turn(self, observation) -> DayTurnAction:
        decision_input = self._input(
            observation.actor,
            SpeechTaskObservation.from_domain(observation),
        )
        runtime = self.runtimes.get(observation.actor)
        decision = await runtime.decide(
            task=DecisionTask.SPEECH,
            decision_input=decision_input,
            output_schema=SpeechDecision,
            use_safe_fallback=True,
        )
        if decision.action == "explode":
            if observation.can_explode:
                return DayTurnAction.explode()
            runtime.call_records[-1] = runtime.call_records[-1].model_copy(
                update={
                    "success": False,
                    "fallback_used": True,
                    "error_type": "illegal_explosion",
                },
            )
            return DayTurnAction.speak(
                f"{observation.actor}号本轮暂时没有新增信息。",
            )
        assert decision.speech is not None
        return DayTurnAction.speak(decision.speech)

    async def choose_exile_vote(self, observation) -> int | None:
        decision_input = self._input(
            observation.voter,
            VoteTaskObservation.from_domain(observation),
        )
        decision = await self.runtimes.get(observation.voter).decide(
            task=DecisionTask.VOTE,
            decision_input=decision_input,
            output_schema=VoteDecision,
            use_safe_fallback=True,
        )
        return decision.target

    def _input(self, seat: int, observation) -> AgentDecisionInput:
        view = self.view_builder.build(seat)
        return AgentDecisionInput(
            player_view=view,
            public_summary=PublicGameSummary.from_view(view),
            observation=observation,
        )

    async def choose_wolf_target(self, observation):
        return await self.support.choose_wolf_target(observation)

    async def choose_seer_target(self, observation):
        return await self.support.choose_seer_target(observation)

    async def choose_witch_action(self, observation):
        return await self.support.choose_witch_action(observation)

    async def choose_signup(self, observation):
        return await self.support.choose_signup(observation)

    async def campaign_speech(self, observation):
        return await self.support.campaign_speech(observation)

    async def choose_withdrawal(self, observation):
        return await self.support.choose_withdrawal(observation)

    async def choose_sheriff_vote(self, observation):
        return await self.support.choose_sheriff_vote(observation)

    async def choose_speech_direction(self, observation):
        return await self.support.choose_speech_direction(observation)

    async def pk_speech(self, observation):
        return await self.support.pk_speech(observation)

    async def last_words(self, observation):
        return await self.support.last_words(observation)

    async def death_last_words(self, observation):
        return await self.support.death_last_words(observation)

    async def choose_hunter_target(self, observation):
        return await self.support.choose_hunter_target(observation)

    async def choose_badge_transfer(self, observation):
        return await self.support.choose_badge_transfer(observation)
