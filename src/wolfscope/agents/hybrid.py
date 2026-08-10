"""Complete Agent-owned game provider plus a legacy M2 compatibility name."""

from __future__ import annotations

from typing import TYPE_CHECKING

from wolfscope.agents.runtime import PlayerRuntimeRegistry
from wolfscope.agents.schemas import (
    AgentDecisionInput,
    BadgeTransferDecision,
    BadgeTransferTaskObservation,
    ComplexityLevel,
    DeathLastWordsTaskObservation,
    DecisionTask,
    HunterTargetDecision,
    HunterTargetTaskObservation,
    LastWordsDecision,
    LastWordsTaskObservation,
    PkSpeechDecision,
    PkSpeechTaskObservation,
    PublicGameSummary,
    SheriffCampaignDecision,
    SheriffCampaignTaskObservation,
    SheriffSignupDecision,
    SheriffSignupTaskObservation,
    SheriffVoteDecision,
    SheriffVoteTaskObservation,
    SheriffWithdrawalDecision,
    SheriffWithdrawalTaskObservation,
    SeerTargetDecision,
    SeerTargetTaskObservation,
    SpeechDecision,
    SpeechDirectionDecision,
    SpeechDirectionTaskObservation,
    SpeechTaskObservation,
    VoteDecision,
    VoteContextMode,
    VoteTaskObservation,
    WitchActionDecision,
    WitchActionTaskObservation,
    WolfTargetDecision,
    WolfTargetTaskObservation,
)
from wolfscope.game.day import DayTurnAction, SpeechDirection
from wolfscope.game.night import WitchAction, WitchActionType
from wolfscope.player_view import PlayerViewBuilder
from wolfscope.cognition.context import EvidenceContextBuilder
from wolfscope.cognition.brief import DecisionBriefBuilder
from wolfscope.cognition.strategy import (
    SituationTag,
    StrategyBuilder,
    StrategySituationBuilder,
    WolfTeamPlan,
)
from wolfscope.agents.speech_policy import SpeechPolicy
from wolfscope.agents.profile import PlayerTendencyRegistry

if TYPE_CHECKING:
    from wolfscope.cognition.extraction import EvidencePipeline
    from .support import DeterministicSupportProvider


class AgentGameProvider:
    """Route every player-owned game action to an isolated seat runtime."""

    def __init__(
        self,
        *,
        view_builder: PlayerViewBuilder,
        runtimes: PlayerRuntimeRegistry,
        evidence_pipeline: EvidencePipeline | None = None,
        evidence_context_builder: EvidenceContextBuilder | None = None,
        decision_brief_builder: DecisionBriefBuilder | None = None,
        vote_context_mode: VoteContextMode = VoteContextMode.FULL,
        strategy_builder: StrategyBuilder | None = None,
        strategy_situation_builder: StrategySituationBuilder | None = None,
        tendency_registry: PlayerTendencyRegistry | None = None,
    ) -> None:
        self.view_builder = view_builder
        self.runtimes = runtimes
        self.evidence_pipeline = evidence_pipeline
        self.evidence_context_builder = (
            evidence_context_builder or EvidenceContextBuilder()
        )
        self.decision_brief_builder = decision_brief_builder or DecisionBriefBuilder()
        self.vote_context_mode = vote_context_mode
        self.strategy_builder = strategy_builder or StrategyBuilder()
        self.strategy_situation_builder = (
            strategy_situation_builder or StrategySituationBuilder()
        )
        self.tendency_registry = tendency_registry or PlayerTendencyRegistry.from_seed(
            view_builder.state.seed,
        )
        self.wolf_team_plan: WolfTeamPlan | None = None
        self.wolf_team_plan_history: list[WolfTeamPlan] = []

    async def take_day_turn(self, observation) -> DayTurnAction:
        decision_input = await self._input(
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
        return DayTurnAction.speak(
            self._bounded_speech(
                runtime,
                DecisionTask.SPEECH,
                decision.speech,
            ),
        )

    async def choose_exile_vote(self, observation) -> int | None:
        decision_input = await self._input(
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

    async def _input(
        self,
        seat: int,
        observation,
        *,
        terminal_action: bool = False,
    ) -> AgentDecisionInput:
        view = (
            self.view_builder.build_terminal_action(seat)
            if terminal_action
            else self.view_builder.build(seat)
        )
        if self.evidence_pipeline is not None:
            await self.evidence_pipeline.sync(view)
            ledger = self.evidence_pipeline.ledgers.get(seat)
            evidence_context = self.evidence_context_builder.build(
                ledger,
            )
            strategy_situation = self.decision_brief_builder.build(
                ledger,
                day=view.day,
                candidates=tuple(
                    player.seat
                    for player in view.players
                    if player.alive and player.seat != seat
                ),
            )
            decision_brief = (
                strategy_situation if isinstance(observation, VoteTaskObservation) else None
            )
        else:
            evidence_context = None
            decision_brief = None
            strategy_situation = None
        situation_tags = self.strategy_situation_builder.build(
            view=view,
            observation=observation,
            brief=strategy_situation,
            wolf_team_plan=self.wolf_team_plan,
        )
        strategy_brief = self.strategy_builder.build(
            owner=seat,
            role=view.own_role,
            day=view.day,
            task=observation.task,
            situation=strategy_situation,
            situation_tags=situation_tags,
            wolf_team_plan=self.wolf_team_plan,
            sheriff_initiative=self.tendency_registry.get(seat).sheriff_initiative,
        )
        complexity_level, complexity_reason = self._complexity_for(
            role=view.own_role,
            task=observation.task,
            situation_tags=situation_tags,
        )
        return AgentDecisionInput(
            player_view=view,
            public_summary=PublicGameSummary.from_view(view),
            observation=observation,
            evidence_context=evidence_context,
            decision_brief=decision_brief,
            strategy_brief=strategy_brief,
            vote_context_mode=(
                self.vote_context_mode
                if isinstance(observation, VoteTaskObservation)
                else VoteContextMode.FULL
            ),
            complexity_level=complexity_level,
            complexity_reason=complexity_reason,
        )

    @staticmethod
    def _complexity_for(*, role, task, situation_tags):
        if role.value != "villager":
            return ComplexityLevel.FULL, "private_role_default"
        critical_tags = {
            SituationTag.SELF_UNDER_PRESSURE,
            SituationTag.SELF_RECEIVED_WOLF_CHECK,
            SituationTag.ENDGAME_PRESSURE,
        }
        if set(situation_tags) & critical_tags:
            return ComplexityLevel.FULL, "villager_critical_situation"
        if task in {"pk_speech", "last_words", "death_last_words"}:
            return ComplexityLevel.FULL, "villager_terminal_or_pk"
        return ComplexityLevel.COMPACT, "villager_default"

    @staticmethod
    def _bounded_speech(runtime, task: DecisionTask, speech: str) -> str:
        result = SpeechPolicy.enforce(task, speech)
        runtime.call_records[-1] = runtime.call_records[-1].model_copy(
            update={
                "speech_original_chars": result.original_chars,
                "speech_final_chars": result.final_chars,
                "speech_truncated": result.truncated,
            },
        )
        return result.text

    async def choose_wolf_target(self, observation):
        task_observation = WolfTargetTaskObservation.from_domain(observation)
        decision_input = await self._input(
            task_observation.actor,
            task_observation,
        )
        decision = await self.runtimes.get(task_observation.actor).decide(
            task=DecisionTask.WOLF_TARGET,
            decision_input=decision_input,
            output_schema=WolfTargetDecision,
            use_safe_fallback=True,
        )
        self.wolf_team_plan = decision.team_plan
        self.wolf_team_plan_history.append(decision.team_plan)
        return decision.target

    async def choose_seer_target(self, observation):
        task_observation = SeerTargetTaskObservation.from_domain(observation)
        decision_input = await self._input(
            task_observation.actor,
            task_observation,
        )
        decision = await self.runtimes.get(task_observation.actor).decide(
            task=DecisionTask.SEER_TARGET,
            decision_input=decision_input,
            output_schema=SeerTargetDecision,
            use_safe_fallback=True,
        )
        return decision.target

    async def choose_witch_action(self, observation):
        task_observation = WitchActionTaskObservation.from_domain(observation)
        decision_input = await self._input(
            task_observation.actor,
            task_observation,
        )
        decision = await self.runtimes.get(task_observation.actor).decide(
            task=DecisionTask.WITCH_ACTION,
            decision_input=decision_input,
            output_schema=WitchActionDecision,
            use_safe_fallback=True,
        )
        return WitchAction(
            action=WitchActionType(decision.action),
            target=decision.target,
        )

    async def choose_signup(self, observation):
        decision_input = await self._input(
            observation.actor,
            SheriffSignupTaskObservation.from_domain(observation),
        )
        decision = await self.runtimes.get(observation.actor).decide(
            task=DecisionTask.SHERIFF_SIGNUP,
            decision_input=decision_input,
            output_schema=SheriffSignupDecision,
            use_safe_fallback=True,
        )
        return decision.signup

    async def campaign_speech(self, observation):
        decision_input = await self._input(
            observation.actor,
            SheriffCampaignTaskObservation.from_domain(observation),
        )
        decision = await self.runtimes.get(observation.actor).decide(
            task=DecisionTask.SHERIFF_CAMPAIGN,
            decision_input=decision_input,
            output_schema=SheriffCampaignDecision,
            use_safe_fallback=True,
        )
        return self._bounded_speech(
            self.runtimes.get(observation.actor),
            DecisionTask.SHERIFF_CAMPAIGN,
            decision.speech,
        )

    async def choose_withdrawal(self, observation):
        decision_input = await self._input(
            observation.actor,
            SheriffWithdrawalTaskObservation.from_domain(observation),
        )
        decision = await self.runtimes.get(observation.actor).decide(
            task=DecisionTask.SHERIFF_WITHDRAWAL,
            decision_input=decision_input,
            output_schema=SheriffWithdrawalDecision,
            use_safe_fallback=True,
        )
        return decision.withdraw

    async def choose_sheriff_vote(self, observation):
        decision_input = await self._input(
            observation.voter,
            SheriffVoteTaskObservation.from_domain(observation),
        )
        decision = await self.runtimes.get(observation.voter).decide(
            task=DecisionTask.SHERIFF_VOTE,
            decision_input=decision_input,
            output_schema=SheriffVoteDecision,
            use_safe_fallback=True,
        )
        return decision.target

    async def choose_speech_direction(self, observation):
        task_observation = SpeechDirectionTaskObservation.from_domain(observation)
        decision_input = await self._input(task_observation.actor, task_observation)
        decision = await self.runtimes.get(task_observation.actor).decide(
            task=DecisionTask.SPEECH_DIRECTION,
            decision_input=decision_input,
            output_schema=SpeechDirectionDecision,
            use_safe_fallback=True,
        )
        return SpeechDirection(decision.direction)

    async def pk_speech(self, observation):
        task_observation = PkSpeechTaskObservation.from_domain(observation)
        decision_input = await self._input(task_observation.actor, task_observation)
        decision = await self.runtimes.get(task_observation.actor).decide(
            task=DecisionTask.PK_SPEECH,
            decision_input=decision_input,
            output_schema=PkSpeechDecision,
            use_safe_fallback=True,
        )
        return self._bounded_speech(
            self.runtimes.get(observation.actor),
            DecisionTask.PK_SPEECH,
            decision.speech,
        )

    async def last_words(self, observation):
        task_observation = LastWordsTaskObservation.from_domain(observation)
        decision_input = await self._input(task_observation.actor, task_observation)
        decision = await self.runtimes.get(task_observation.actor).decide(
            task=DecisionTask.LAST_WORDS,
            decision_input=decision_input,
            output_schema=LastWordsDecision,
            use_safe_fallback=True,
        )
        return self._bounded_speech(
            self.runtimes.get(observation.actor),
            DecisionTask.LAST_WORDS,
            decision.speech,
        )

    async def death_last_words(self, observation):
        task_observation = DeathLastWordsTaskObservation.from_domain(observation)
        decision_input = await self._input(
            task_observation.actor,
            task_observation,
            terminal_action=True,
        )
        decision = await self.runtimes.get(task_observation.actor).decide(
            task=DecisionTask.DEATH_LAST_WORDS,
            decision_input=decision_input,
            output_schema=LastWordsDecision,
            use_safe_fallback=True,
        )
        return self._bounded_speech(
            self.runtimes.get(observation.actor),
            DecisionTask.DEATH_LAST_WORDS,
            decision.speech,
        )

    async def choose_hunter_target(self, observation):
        task_observation = HunterTargetTaskObservation.from_domain(observation)
        decision_input = await self._input(
            task_observation.actor,
            task_observation,
            terminal_action=True,
        )
        decision = await self.runtimes.get(task_observation.actor).decide(
            task=DecisionTask.HUNTER_TARGET,
            decision_input=decision_input,
            output_schema=HunterTargetDecision,
            use_safe_fallback=True,
        )
        return decision.target

    async def choose_badge_transfer(self, observation):
        task_observation = BadgeTransferTaskObservation.from_domain(observation)
        decision_input = await self._input(
            task_observation.actor,
            task_observation,
            terminal_action=True,
        )
        decision = await self.runtimes.get(task_observation.actor).decide(
            task=DecisionTask.BADGE_TRANSFER,
            decision_input=decision_input,
            output_schema=BadgeTransferDecision,
            use_safe_fallback=True,
        )
        return decision.target


class HybridProvider(AgentGameProvider):
    """Backward-compatible name for tests written during incremental M2 routing."""

    def __init__(
        self,
        *,
        support: DeterministicSupportProvider | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
