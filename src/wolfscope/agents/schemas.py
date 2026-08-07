"""Strict M2-1 inputs and structured public-action decisions."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from wolfscope.contracts import PlayerView, Probability, Seat, StrictModel
from wolfscope.game.day import (
    DayTurnObservation,
    ExileVoteObservation,
    ExileVoteRound,
)


class DecisionTask(StrEnum):
    SPEECH = "speech"
    VOTE = "vote"


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


TaskObservation = Annotated[
    SpeechTaskObservation | VoteTaskObservation,
    Field(discriminator="task"),
]


class AgentDecisionInput(StrictModel):
    player_view: PlayerView
    public_summary: PublicGameSummary
    observation: TaskObservation

    @model_validator(mode="after")
    def actor_matches_viewer(self) -> AgentDecisionInput:
        actor = (
            self.observation.actor
            if isinstance(self.observation, SpeechTaskObservation)
            else self.observation.voter
        )
        if actor != self.player_view.viewer_seat:
            raise ValueError("decision observation actor must match PlayerView viewer")
        expected = PublicGameSummary.from_view(self.player_view)
        if self.public_summary != expected:
            raise ValueError("public_summary must be derived from PlayerView")
        return self


class SpeechDecision(StrictModel):
    action: Literal["speak", "explode"]
    speech: str | None = None
    intent: str = Field(min_length=1)
    confidence: Probability
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
    public_reason: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    strategy_ids: tuple[str, ...] = ()
