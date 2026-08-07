"""Strict player-local evidence records for M2-2."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from wolfscope.contracts import Seat, StrictModel
from wolfscope.game.night import WitchActionType
from wolfscope.game.types import Camp, Phase, RoleType


class EvidenceModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EpistemicStatus(StrEnum):
    VERIFIED = "verified"
    OBSERVED = "observed"
    CLAIMED = "claimed"


class ExtractionMethod(StrEnum):
    ENGINE = "engine"
    RULE_DERIVATION = "rule_derivation"
    LLM = "llm"


class EvidenceKind(StrEnum):
    FACT = "fact"
    RAW_SPEECH = "raw_speech"
    CLAIM = "claim"


class TemporalPoint(EvidenceModel):
    day: int = Field(ge=0)
    phase: Phase
    local_order: int = Field(ge=0)


class EventEvidenceSource(EvidenceModel):
    source_type: Literal["event"] = "event"
    view_event_id: int = Field(ge=1)


class RoleStateEvidenceSource(EvidenceModel):
    source_type: Literal["role_state"] = "role_state"
    field: str = Field(min_length=1)


class PublicAnnotationEvidenceSource(EvidenceModel):
    source_type: Literal["public_annotation"] = "public_annotation"
    view_event_id: int = Field(ge=1)
    claim_index: int = Field(ge=1)


EvidenceSource = Annotated[
    EventEvidenceSource | RoleStateEvidenceSource | PublicAnnotationEvidenceSource,
    Field(discriminator="source_type"),
]


class OwnRoleFact(EvidenceModel):
    content_type: Literal["own_role_fact"] = "own_role_fact"
    role: RoleType


class WolfTeammateFact(EvidenceModel):
    content_type: Literal["wolf_teammate_fact"] = "wolf_teammate_fact"
    teammate: Seat


class WolfTargetFact(EvidenceModel):
    content_type: Literal["wolf_target_fact"] = "wolf_target_fact"
    night: int = Field(ge=1)
    target: Seat


class SeerCheckFact(EvidenceModel):
    content_type: Literal["seer_check_fact"] = "seer_check_fact"
    night: int = Field(ge=1)
    target: Seat
    result: Camp


class WitchVictimFact(EvidenceModel):
    content_type: Literal["witch_victim_fact"] = "witch_victim_fact"
    night: int = Field(ge=1)
    target: Seat


class WitchActionFact(EvidenceModel):
    content_type: Literal["witch_action_fact"] = "witch_action_fact"
    night: int = Field(ge=1)
    action: WitchActionType
    target: Seat | None = None


class SheriffSignupFact(EvidenceModel):
    content_type: Literal["sheriff_signup_fact"] = "sheriff_signup_fact"
    seat: Seat


class SheriffWithdrawalFact(EvidenceModel):
    content_type: Literal["sheriff_withdrawal_fact"] = "sheriff_withdrawal_fact"
    seat: Seat


class ActualVoteFact(EvidenceModel):
    content_type: Literal["actual_vote_fact"] = "actual_vote_fact"
    vote_type: Literal["sheriff", "exile"]
    round: Literal["first", "revote"] = "first"
    voter: Seat
    target: Seat | None
    units: int | None = Field(default=None, ge=1)


class SheriffElectedFact(EvidenceModel):
    content_type: Literal["sheriff_elected_fact"] = "sheriff_elected_fact"
    sheriff: Seat


class NoSheriffFact(EvidenceModel):
    content_type: Literal["no_sheriff_fact"] = "no_sheriff_fact"
    reason: str = Field(min_length=1)


class DawnDeathFact(EvidenceModel):
    content_type: Literal["dawn_death_fact"] = "dawn_death_fact"
    seat: Seat


class PeacefulNightFact(EvidenceModel):
    content_type: Literal["peaceful_night_fact"] = "peaceful_night_fact"
    night: int = Field(ge=1)


class WitchSaveDeducedFact(EvidenceModel):
    content_type: Literal["witch_save_deduced_fact"] = "witch_save_deduced_fact"
    night: int = Field(ge=1)


class WitchPoisonUsedDeducedFact(EvidenceModel):
    content_type: Literal["witch_poison_used_deduced_fact"] = (
        "witch_poison_used_deduced_fact"
    )
    night: int = Field(ge=1)


class WolfExplosionFact(EvidenceModel):
    content_type: Literal["wolf_explosion_fact"] = "wolf_explosion_fact"
    seat: Seat
    revealed_role: Literal["werewolf"] = "werewolf"


class PlayerExiledFact(EvidenceModel):
    content_type: Literal["player_exiled_fact"] = "player_exiled_fact"
    seat: Seat


class NoExileFact(EvidenceModel):
    content_type: Literal["no_exile_fact"] = "no_exile_fact"
    day: int = Field(ge=1)


class HunterShotFact(EvidenceModel):
    content_type: Literal["hunter_shot_fact"] = "hunter_shot_fact"
    hunter: Seat
    target: Seat


class HunterDidNotShootFact(EvidenceModel):
    content_type: Literal["hunter_did_not_shoot_fact"] = (
        "hunter_did_not_shoot_fact"
    )
    hunter: Seat


class BadgeTransferredFact(EvidenceModel):
    content_type: Literal["badge_transferred_fact"] = "badge_transferred_fact"
    former_sheriff: Seat
    new_sheriff: Seat


class BadgeDestroyedFact(EvidenceModel):
    content_type: Literal["badge_destroyed_fact"] = "badge_destroyed_fact"
    former_sheriff: Seat


class RawSpeech(EvidenceModel):
    content_type: Literal["raw_speech"] = "raw_speech"
    speaker: Seat
    speech_context: Literal[
        "sheriff_campaign",
        "day_speech",
        "pk_speech",
        "last_words",
    ]
    text: str = Field(min_length=1)


EvidenceContent = Annotated[
    OwnRoleFact
    | WolfTeammateFact
    | WolfTargetFact
    | SeerCheckFact
    | WitchVictimFact
    | WitchActionFact
    | SheriffSignupFact
    | SheriffWithdrawalFact
    | ActualVoteFact
    | SheriffElectedFact
    | NoSheriffFact
    | DawnDeathFact
    | PeacefulNightFact
    | WitchSaveDeducedFact
    | WitchPoisonUsedDeducedFact
    | WolfExplosionFact
    | PlayerExiledFact
    | NoExileFact
    | HunterShotFact
    | HunterDidNotShootFact
    | BadgeTransferredFact
    | BadgeDestroyedFact
    | RawSpeech,
    Field(discriminator="content_type"),
]


class EvidenceRecord(EvidenceModel):
    evidence_id: str = Field(pattern=r"^p[1-9]-e[1-9][0-9]*$")
    owner: Seat
    source: EvidenceSource
    kind: EvidenceKind
    epistemic_status: EpistemicStatus
    occurred_at: TemporalPoint
    known_at: TemporalPoint
    known_order: int = Field(ge=1)
    content: EvidenceContent
    extraction_method: ExtractionMethod
    extractor_version: str | None = None
    supersedes: tuple[str, ...] = ()
