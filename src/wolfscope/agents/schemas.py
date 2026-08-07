"""Strict M2-1 inputs and structured public-action decisions."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from wolfscope.contracts import PlayerView, Probability, Seat, StrictModel
from wolfscope.cognition.context import EvidenceContext
from wolfscope.cognition.brief import DecisionBrief
from wolfscope.game.day import (
    DayTurnObservation,
    ExileVoteObservation,
    ExileVoteRound,
)


class DecisionTask(StrEnum):
    SPEECH = "speech"
    VOTE = "vote"


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
    evidence_context: EvidenceContext | None = None
    decision_brief: DecisionBrief | None = None
    vote_context_mode: VoteContextMode = VoteContextMode.FULL

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
        if (
            not isinstance(self.observation, VoteTaskObservation)
            and self.vote_context_mode is not VoteContextMode.FULL
        ):
            raise ValueError("non-full vote context mode is only valid for vote tasks")
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
