"""Strict M2-1 inputs and structured public-action decisions."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from wolfscope.contracts import (
    OwnRoleState,
    PlayerView,
    Probability,
    Seat,
    StrictModel,
)
from wolfscope.cognition.context import EvidenceContext
from wolfscope.cognition.brief import DecisionBrief
from wolfscope.cognition.strategy import StrategyBrief, WolfTeamPlan
from wolfscope.game.day import (
    DayTurnObservation,
    ExileVoteObservation,
    ExileVoteRound,
    LastWordsObservation,
    PkSpeechObservation,
    SpeechDirectionObservation,
)
from wolfscope.game.sheriff import (
    CampaignSpeechObservation,
    SheriffSignupObservation,
    SheriffVoteObservation,
    SheriffWithdrawalObservation,
)
from wolfscope.game.night import (
    SeerNightObservation,
    WitchNightObservation,
    WolfNightObservation,
)
from wolfscope.game.resolution import (
    BadgeTransferObservation,
    DeathLastWordsObservation,
    HunterShotObservation,
)
from wolfscope.game.types import Phase, RoleType


class DecisionTask(StrEnum):
    SPEECH = "speech"
    VOTE = "vote"
    SHERIFF_SIGNUP = "sheriff_signup"
    SHERIFF_CAMPAIGN = "sheriff_campaign"
    SHERIFF_WITHDRAWAL = "sheriff_withdrawal"
    SHERIFF_VOTE = "sheriff_vote"
    WOLF_TARGET = "wolf_target"
    SEER_TARGET = "seer_target"
    WITCH_ACTION = "witch_action"
    SPEECH_DIRECTION = "speech_direction"
    PK_SPEECH = "pk_speech"
    LAST_WORDS = "last_words"
    DEATH_LAST_WORDS = "death_last_words"
    HUNTER_TARGET = "hunter_target"
    BADGE_TRANSFER = "badge_transfer"


class VoteContextMode(StrEnum):
    FULL = "full"
    BALANCED = "balanced"
    COMPACT = "compact"


class PublicGameSummary(StrictModel):
    alive_seats: tuple[Seat, ...]
    dead_seats: tuple[Seat, ...]
    sheriff: Seat | None

    @classmethod
    def from_view(cls, view: PlayerView) -> PublicGameSummary:
        return cls(
            alive_seats=tuple(player.seat for player in view.players if player.alive),
            dead_seats=tuple(player.seat for player in view.players if not player.alive),
            sheriff=next(
                (player.seat for player in view.players if player.is_sheriff),
                None,
            ),
        )


class PlayerContext(StrictModel):
    seat: Seat
    ruleset: str
    day: int = Field(ge=0)
    phase: Phase
    own_role: RoleType
    own_role_state: OwnRoleState
    alive_seats: tuple[Seat, ...]
    dead_seats: tuple[Seat, ...]
    sheriff: Seat | None

    @classmethod
    def from_view(cls, view: PlayerView) -> PlayerContext:
        summary = PublicGameSummary.from_view(view)
        return cls(
            seat=view.viewer_seat,
            ruleset=view.ruleset,
            day=view.day,
            phase=view.phase,
            own_role=view.own_role,
            own_role_state=view.own_role_state,
            alive_seats=summary.alive_seats,
            dead_seats=summary.dead_seats,
            sheriff=summary.sheriff,
        )


class SpeechTaskObservation(StrictModel):
    task: Literal["speech"] = "speech"
    actor: Seat
    speaking_order: tuple[Seat, ...]
    previous_speeches: tuple[tuple[Seat, str], ...]
    can_explode: bool

    @classmethod
    def from_domain(cls, observation: DayTurnObservation) -> SpeechTaskObservation:
        return cls(
            actor=observation.actor,
            speaking_order=observation.speaking_order,
            previous_speeches=observation.previous_speeches,
            can_explode=observation.can_explode,
        )


class VoteTaskObservation(StrictModel):
    task: Literal["vote"] = "vote"
    voter: Seat
    vote_round: ExileVoteRound
    candidates: tuple[Seat, ...]
    speeches: tuple[tuple[Seat, str], ...]

    @classmethod
    def from_domain(cls, observation: ExileVoteObservation) -> VoteTaskObservation:
        return cls(
            voter=observation.voter,
            vote_round=observation.vote_round,
            candidates=observation.candidates,
            speeches=observation.speeches,
        )


class SheriffSignupTaskObservation(StrictModel):
    task: Literal["sheriff_signup"] = "sheriff_signup"
    actor: Seat
    eligible_seats: tuple[Seat, ...]

    @classmethod
    def from_domain(cls, observation: SheriffSignupObservation):
        return cls(actor=observation.actor, eligible_seats=observation.eligible_seats)


class SheriffCampaignTaskObservation(StrictModel):
    task: Literal["sheriff_campaign"] = "sheriff_campaign"
    actor: Seat
    candidates: tuple[Seat, ...]
    previous_speeches: tuple[tuple[Seat, str], ...]

    @classmethod
    def from_domain(cls, observation: CampaignSpeechObservation):
        return cls(
            actor=observation.actor,
            candidates=observation.candidates,
            previous_speeches=observation.previous_speeches,
        )


class SheriffWithdrawalTaskObservation(StrictModel):
    task: Literal["sheriff_withdrawal"] = "sheriff_withdrawal"
    actor: Seat
    candidates: tuple[Seat, ...]
    campaign_speeches: tuple[tuple[Seat, str], ...]

    @classmethod
    def from_domain(cls, observation: SheriffWithdrawalObservation):
        return cls(
            actor=observation.actor,
            candidates=observation.candidates,
            campaign_speeches=observation.campaign_speeches,
        )


class SheriffVoteTaskObservation(StrictModel):
    task: Literal["sheriff_vote"] = "sheriff_vote"
    voter: Seat
    candidates: tuple[Seat, ...]
    campaign_speeches: tuple[tuple[Seat, str], ...]
    withdrawn: tuple[Seat, ...]

    @classmethod
    def from_domain(cls, observation: SheriffVoteObservation):
        return cls(
            voter=observation.voter,
            candidates=observation.candidates,
            campaign_speeches=observation.campaign_speeches,
            withdrawn=observation.withdrawn,
        )


class WolfTargetTaskObservation(StrictModel):
    task: Literal["wolf_target"] = "wolf_target"
    actor: Seat
    wolf_seats: tuple[Seat, ...]
    eligible_targets: tuple[Seat, ...]

    @classmethod
    def from_domain(cls, observation: WolfNightObservation):
        return cls(
            actor=min(observation.wolf_seats),
            wolf_seats=observation.wolf_seats,
            eligible_targets=observation.eligible_targets,
        )


class SeerTargetTaskObservation(StrictModel):
    task: Literal["seer_target"] = "seer_target"
    actor: Seat
    checked_seats: tuple[Seat, ...]
    eligible_targets: tuple[Seat, ...]

    @classmethod
    def from_domain(cls, observation: SeerNightObservation):
        return cls(
            actor=observation.seer_seat,
            checked_seats=observation.checked_seats,
            eligible_targets=observation.eligible_targets,
        )


class WitchActionTaskObservation(StrictModel):
    task: Literal["witch_action"] = "witch_action"
    actor: Seat
    night_victim: Seat | None
    antidote_available: bool
    poison_available: bool
    can_save: bool
    poison_targets: tuple[Seat, ...]

    @classmethod
    def from_domain(cls, observation: WitchNightObservation):
        return cls(
            actor=observation.witch_seat,
            night_victim=observation.night_victim,
            antidote_available=observation.antidote_available,
            poison_available=observation.poison_available,
            can_save=observation.can_save,
            poison_targets=observation.poison_targets,
        )


class SpeechDirectionTaskObservation(StrictModel):
    task: Literal["speech_direction"] = "speech_direction"
    actor: Seat
    alive_seats: tuple[Seat, ...]

    @classmethod
    def from_domain(cls, observation: SpeechDirectionObservation):
        return cls(actor=observation.sheriff, alive_seats=observation.alive_seats)


class PkSpeechTaskObservation(StrictModel):
    task: Literal["pk_speech"] = "pk_speech"
    actor: Seat
    tied_seats: tuple[Seat, ...]
    day_speeches: tuple[tuple[Seat, str], ...]
    previous_pk_speeches: tuple[tuple[Seat, str], ...]

    @classmethod
    def from_domain(cls, observation: PkSpeechObservation):
        return cls(
            actor=observation.actor,
            tied_seats=observation.tied_seats,
            day_speeches=observation.day_speeches,
            previous_pk_speeches=observation.previous_pk_speeches,
        )


class LastWordsTaskObservation(StrictModel):
    task: Literal["last_words"] = "last_words"
    actor: Seat
    day_speeches: tuple[tuple[Seat, str], ...]
    votes: tuple[tuple[Seat, Seat | None], ...]
    revotes: tuple[tuple[Seat, Seat | None], ...]

    @classmethod
    def from_domain(cls, observation: LastWordsObservation):
        return cls(
            actor=observation.actor,
            day_speeches=observation.day_speeches,
            votes=observation.votes,
            revotes=observation.revotes,
        )


class DeathLastWordsTaskObservation(StrictModel):
    task: Literal["death_last_words"] = "death_last_words"
    actor: Seat
    deaths: tuple[Seat, ...]

    @classmethod
    def from_domain(cls, observation: DeathLastWordsObservation):
        return cls(actor=observation.actor, deaths=observation.deaths)


class HunterTargetTaskObservation(StrictModel):
    task: Literal["hunter_target"] = "hunter_target"
    actor: Seat
    death_cause: str
    eligible_targets: tuple[Seat, ...]
    last_words: str | None = None

    @classmethod
    def from_domain(cls, observation: HunterShotObservation):
        return cls(
            actor=observation.hunter,
            death_cause=observation.death_cause.value,
            eligible_targets=observation.eligible_targets,
            last_words=observation.last_words,
        )


class BadgeTransferTaskObservation(StrictModel):
    task: Literal["badge_transfer"] = "badge_transfer"
    actor: Seat
    eligible_targets: tuple[Seat, ...]
    hunter_target: Seat | None = None

    @classmethod
    def from_domain(cls, observation: BadgeTransferObservation):
        return cls(
            actor=observation.former_sheriff,
            eligible_targets=observation.eligible_targets,
            hunter_target=observation.hunter_target,
        )


TaskObservation = Annotated[
    SpeechTaskObservation
    | VoteTaskObservation
    | SheriffSignupTaskObservation
    | SheriffCampaignTaskObservation
    | SheriffWithdrawalTaskObservation
    | SheriffVoteTaskObservation
    | WolfTargetTaskObservation
    | SeerTargetTaskObservation
    | WitchActionTaskObservation
    | SpeechDirectionTaskObservation
    | PkSpeechTaskObservation
    | LastWordsTaskObservation
    | DeathLastWordsTaskObservation
    | HunterTargetTaskObservation
    | BadgeTransferTaskObservation,
    Field(discriminator="task"),
]


class AgentDecisionInput(StrictModel):
    player_view: PlayerView
    public_summary: PublicGameSummary
    observation: TaskObservation
    evidence_context: EvidenceContext | None = None
    decision_brief: DecisionBrief | None = None
    strategy_brief: StrategyBrief | None = None
    vote_context_mode: VoteContextMode = VoteContextMode.FULL

    @model_validator(mode="after")
    def actor_matches_viewer(self) -> AgentDecisionInput:
        actor = getattr(self.observation, "actor", None)
        if actor is None:
            actor = self.observation.voter
        if actor != self.player_view.viewer_seat:
            raise ValueError("decision observation actor must match PlayerView viewer")
        expected = PublicGameSummary.from_view(self.player_view)
        if self.public_summary != expected:
            raise ValueError("public_summary must be derived from PlayerView")
        if (
            self.evidence_context is not None
            and self.evidence_context.owner != self.player_view.viewer_seat
        ):
            raise ValueError("evidence_context owner must match PlayerView viewer")
        if self.decision_brief is not None:
            if not isinstance(self.observation, VoteTaskObservation):
                raise ValueError("decision_brief is only valid for vote tasks")
            if self.decision_brief.owner != self.player_view.viewer_seat:
                raise ValueError("decision_brief owner must match PlayerView viewer")
            if self.decision_brief.ledger_revision != self.decision_brief.belief_revision:
                raise ValueError("decision_brief revisions must match")
            if self.decision_brief.day != self.player_view.day:
                raise ValueError("decision_brief day must match PlayerView")
            brief_candidates = tuple(
                item.seat for item in self.decision_brief.candidates
            )
            if brief_candidates != self.observation.candidates:
                raise ValueError("decision_brief candidates must match vote observation")
            if (
                self.evidence_context is not None
                and self.decision_brief.ledger_revision
                != self.evidence_context.ledger_revision
            ):
                raise ValueError("decision_brief and evidence_context revisions must match")
        if not isinstance(self.observation, VoteTaskObservation) and (
            self.vote_context_mode is not VoteContextMode.FULL
        ):
            raise ValueError("non-full vote context mode is only valid for vote tasks")
        if self.strategy_brief is not None:
            if self.strategy_brief.owner != self.player_view.viewer_seat:
                raise ValueError("strategy_brief owner must match PlayerView viewer")
            if self.strategy_brief.day != self.player_view.day:
                raise ValueError("strategy_brief day must match PlayerView")
            if self.strategy_brief.task != self.observation.task:
                raise ValueError("strategy_brief task must match observation")
            if self.strategy_brief.role != self.player_view.own_role:
                raise ValueError("strategy_brief role must match PlayerView")
        return self

    @property
    def available_evidence_ids(self) -> tuple[str, ...]:
        if self.evidence_context is None:
            return ()
        if self.vote_context_mode is VoteContextMode.FULL:
            return self.evidence_context.evidence_ids
        hard_ids = tuple(
            item.evidence_id
            for item in (
                self.evidence_context.verified_facts
                + self.evidence_context.rule_derivations
            )
        )
        brief_ids = (
            self.decision_brief.evidence_ids
            if self.decision_brief is not None
            else ()
        )
        return tuple(dict.fromkeys(hard_ids + brief_ids))


class SpeechDecision(StrictModel):
    action: Literal["speak", "explode"]
    speech: str | None = None
    intent: str = Field(min_length=1)
    confidence: Probability
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def action_payload_is_coherent(self) -> SpeechDecision:
        if self.action == "speak" and (self.speech is None or not self.speech.strip()):
            raise ValueError("speak decision requires non-empty speech")
        if self.action == "explode" and self.speech is not None:
            raise ValueError("explode decision cannot contain speech")
        return self


class VoteDecision(StrictModel):
    action: Literal["vote"] = "vote"
    target: Seat | None
    confidence: Probability
    reason: str = Field(min_length=1)
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()


class SheriffSignupDecision(StrictModel):
    action: Literal["sheriff_signup"] = "sheriff_signup"
    signup: bool
    confidence: Probability
    reason: str = Field(min_length=1)
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()


class SheriffCampaignDecision(StrictModel):
    action: Literal["sheriff_campaign"] = "sheriff_campaign"
    speech: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    confidence: Probability
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()


class SheriffWithdrawalDecision(StrictModel):
    action: Literal["sheriff_withdrawal"] = "sheriff_withdrawal"
    withdraw: bool
    confidence: Probability
    reason: str = Field(min_length=1)
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()


class SheriffVoteDecision(StrictModel):
    action: Literal["sheriff_vote"] = "sheriff_vote"
    target: Seat | None
    confidence: Probability
    reason: str = Field(min_length=1)
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()


class WolfTargetDecision(StrictModel):
    action: Literal["wolf_target"] = "wolf_target"
    target: Seat
    confidence: Probability
    reason: str = Field(min_length=1)
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()
    team_plan: WolfTeamPlan = Field(
        description=(
            "当前存活狼队共享的私有战术计划；每夜可保持或更新。"
            "若安排悍跳预言家，必须指定唯一 primary_claimant 和完整假查验。"
        ),
    )


class SeerTargetDecision(StrictModel):
    action: Literal["seer_target"] = "seer_target"
    target: Seat
    confidence: Probability
    reason: str = Field(min_length=1)
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()


class WitchActionDecision(StrictModel):
    action: Literal["pass", "save", "poison"]
    target: Seat | None = None
    confidence: Probability
    reason: str = Field(min_length=1)
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def target_matches_action(self):
        if self.action == "pass" and self.target is not None:
            raise ValueError("pass action cannot contain a target")
        if self.action != "pass" and self.target is None:
            raise ValueError("save and poison require a target")
        return self


class SpeechDirectionDecision(StrictModel):
    action: Literal["speech_direction"] = "speech_direction"
    direction: Literal["clockwise", "counterclockwise"]
    confidence: Probability
    reason: str = Field(min_length=1)
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()


class PkSpeechDecision(StrictModel):
    action: Literal["pk_speech"] = "pk_speech"
    speech: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    confidence: Probability
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()


class LastWordsDecision(StrictModel):
    action: Literal["last_words", "death_last_words"]
    speech: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    confidence: Probability
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()


class HunterTargetDecision(StrictModel):
    action: Literal["hunter_target"] = "hunter_target"
    target: Seat | None
    confidence: Probability
    reason: str = Field(min_length=1)
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()


class BadgeTransferDecision(StrictModel):
    action: Literal["badge_transfer"] = "badge_transfer"
    target: Seat | None
    confidence: Probability
    reason: str = Field(min_length=1)
    event_ids: tuple[int, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()
