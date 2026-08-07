"""M0 contracts shared by the deterministic engine and agent adapter.

These models deliberately contain no AgentScope types. The framework adapter
may translate them into AgentScope messages, but the game domain must remain
usable and testable without an LLM runtime.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .game.types import Phase, RoleType


Seat = Annotated[int, Field(ge=1, le=9)]
Probability = Annotated[float, Field(ge=0.0, le=1.0)]


class StrictModel(BaseModel):
    """Base model that rejects unexpected fields at every trust boundary."""

    model_config = ConfigDict(extra="forbid")


class Visibility(StrEnum):
    PUBLIC = "public"
    WOLVES = "wolves"
    PRIVATE = "private"
    GOD = "god"


class GameEvent(StrictModel):
    """Append-only fact emitted by the deterministic game engine."""

    event_id: int = Field(ge=1)
    day: int = Field(ge=0)
    phase: Phase
    event_type: str = Field(min_length=1)
    visibility: Visibility
    recipients: tuple[Seat, ...] = ()
    actor: Seat | None = None
    target: Seat | None = None
    content: str = ""
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def private_events_have_recipients(self) -> GameEvent:
        if self.visibility is Visibility.PRIVATE and not self.recipients:
            raise ValueError("private events must name at least one recipient")
        if self.visibility is not Visibility.PRIVATE and self.recipients:
            raise ValueError("recipients are only valid for private events")
        return self


class PublicPlayer(StrictModel):
    seat: Seat
    alive: bool
    is_sheriff: bool = False


class VillagerPrivateState(StrictModel):
    role: Literal["villager"] = "villager"


class WerewolfPrivateState(StrictModel):
    role: Literal["werewolf"] = "werewolf"
    teammate_seats: tuple[Seat, ...]


class SeerPrivateState(StrictModel):
    role: Literal["seer"] = "seer"
    checked_seats: tuple[Seat, ...]


class WitchPrivateState(StrictModel):
    role: Literal["witch"] = "witch"
    antidote_available: bool
    poison_available: bool


class HunterPrivateState(StrictModel):
    role: Literal["hunter"] = "hunter"
    gun_available: bool


OwnRoleState = Annotated[
    VillagerPrivateState
    | WerewolfPrivateState
    | SeerPrivateState
    | WitchPrivateState
    | HunterPrivateState,
    Field(discriminator="role"),
]


class PlayerView(StrictModel):
    """The complete and only game input a player-side tool may inspect."""

    viewer_seat: Seat
    view_revision: int = Field(ge=0)
    ruleset: str = Field(min_length=1)
    day: int = Field(ge=0)
    phase: Phase
    own_role: RoleType
    own_role_state: OwnRoleState
    players: tuple[PublicPlayer, ...]
    visible_events: tuple[GameEvent, ...] = ()

    @model_validator(mode="after")
    def contains_viewer(self) -> PlayerView:
        seats = [player.seat for player in self.players]
        if len(seats) != len(set(seats)):
            raise ValueError("players must not contain duplicate seats")
        if self.viewer_seat not in seats:
            raise ValueError("viewer_seat must exist in players")
        if self.own_role.value != self.own_role_state.role:
            raise ValueError("own_role must match own_role_state.role")
        return self


class EvidenceKind(StrEnum):
    HARD_FACT = "hard_fact"
    ROLE_CLAIM = "role_claim"
    ALIGNMENT = "alignment"
    VOTE_INTENT = "vote_intent"
    CONTRADICTION = "contradiction"


class Evidence(StrictModel):
    """A source-linked observation in one player's subjective ledger."""

    evidence_id: str = Field(min_length=1)
    source_event_id: int = Field(ge=1)
    observer: Seat
    kind: EvidenceKind
    speaker: Seat | None = None
    target: Seat | None = None
    summary: str = Field(min_length=1)
    confidence: Probability = 1.0
    retracted: bool = False


class RoleBelief(StrictModel):
    seat: Seat
    probabilities: dict[str, Probability]

    @model_validator(mode="after")
    def probabilities_sum_to_one(self) -> RoleBelief:
        if not self.probabilities:
            raise ValueError("probabilities must not be empty")
        if abs(sum(self.probabilities.values()) - 1.0) > 1e-6:
            raise ValueError("role probabilities must sum to 1")
        return self


class BeliefState(StrictModel):
    """One player's subjective, revisable model of the game."""

    owner: Seat
    revision: int = Field(ge=0, default=0)
    role_beliefs: tuple[RoleBelief, ...] = ()
    trust_scores: dict[Seat, Annotated[float, Field(ge=-1.0, le=1.0)]] = Field(
        default_factory=dict,
    )
    evidence_ids: tuple[str, ...] = ()
    hypotheses: tuple[str, ...] = ()


class EvidenceReference(StrictModel):
    evidence_id: str = Field(min_length=1)
    relevance: str = Field(min_length=1)


class Decision(StrictModel):
    """Auditable action proposal returned by a player agent."""

    actor: Seat
    action_type: Literal[
        "speak",
        "vote",
        "wolf_kill",
        "seer_check",
        "witch_action",
        "hunter_shot",
        "sheriff_action",
    ]
    target: Seat | None = None
    speech: str | None = None
    confidence: Probability
    evidence: tuple[EvidenceReference, ...] = ()
    strategy_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def action_payload_is_coherent(self) -> Decision:
        if self.action_type == "speak" and not self.speech:
            raise ValueError("speak decisions require speech")
        if self.action_type != "speak" and self.speech is not None:
            raise ValueError("only speak decisions may contain speech")
        return self
