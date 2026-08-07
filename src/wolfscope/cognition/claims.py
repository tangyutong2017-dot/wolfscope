"""Strict semantic claims extracted once from public speech text."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from wolfscope.contracts import Seat, StrictModel
from wolfscope.game.types import Camp, RoleType


class ClaimModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClaimPolarity(StrEnum):
    ASSERT = "assert"
    DENY = "deny"


class StanceType(StrEnum):
    SUPPORT = "support"
    OPPOSE = "oppose"
    TRUST = "trust"
    DISTRUST = "distrust"
    SUSPECT = "suspect"
    NEUTRAL = "neutral"


class VoteIntentType(StrEnum):
    VOTE = "vote"
    AVOID = "avoid"


class ClaimBase(ClaimModel):
    summary: str = Field(min_length=1, max_length=60)
    supporting_text: str = Field(min_length=1, max_length=80)


class RoleClaim(ClaimBase):
    kind: Literal["role_claim"] = "role_claim"
    subject: Seat
    role: RoleType
    polarity: ClaimPolarity


class CheckClaim(ClaimBase):
    kind: Literal["check_claim"] = "check_claim"
    target: Seat
    night: int = Field(ge=1)
    result: Camp


class AlignmentClaim(ClaimBase):
    kind: Literal["alignment_claim"] = "alignment_claim"
    target: Seat
    alignment: Camp
    polarity: ClaimPolarity


class StanceClaim(ClaimBase):
    kind: Literal["stance_claim"] = "stance_claim"
    target: Seat
    stance: StanceType


class VoteClaimBase(ClaimBase):
    target: Seat
    conditional: bool = False
    condition: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def condition_is_coherent(self):
        if self.conditional and not (self.condition and self.condition.strip()):
            raise ValueError("conditional vote claim requires a condition")
        if not self.conditional and self.condition is not None:
            raise ValueError("unconditional vote claim cannot contain a condition")
        return self


class VoteIntentClaim(VoteClaimBase):
    kind: Literal["vote_intent"] = "vote_intent"
    intent: VoteIntentType


class VoteRecommendationClaim(VoteClaimBase):
    kind: Literal["vote_recommendation"] = "vote_recommendation"


PublicClaim = Annotated[
    RoleClaim
    | CheckClaim
    | AlignmentClaim
    | StanceClaim
    | VoteIntentClaim
    | VoteRecommendationClaim,
    Field(discriminator="kind"),
]


class SpeechExtractionItem(ClaimModel):
    item_id: str = Field(min_length=1)
    day: int = Field(ge=1)
    speaker: Seat
    speech_context: Literal[
        "sheriff_campaign",
        "day_speech",
        "pk_speech",
        "last_words",
    ]
    text: str = Field(min_length=1)


class SpeechClaimExtraction(ClaimModel):
    item_id: str = Field(min_length=1)
    claims: tuple[PublicClaim, ...] = Field(default=(), max_length=8)


class SpeechExtractionBatch(ClaimModel):
    items: tuple[SpeechClaimExtraction, ...]
