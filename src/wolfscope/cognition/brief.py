"""Deterministic task-focused summary derived from one player's evidence."""

from __future__ import annotations

from pydantic import Field, model_validator

from wolfscope.contracts import Probability, Seat, StrictModel
from wolfscope.game.types import RoleType

from .beliefs import BeliefConflict, BeliefStateBuilder
from .claims import (
    CheckClaim,
    ClaimAlignment,
    ClaimPolarity,
    RoleClaim,
    VoteIntentClaim,
    VoteIntentType,
)
from .evidence import PublicClaimEvidence
from .ledger import EvidenceLedger


class CandidateBrief(StrictModel):
    seat: Seat
    wolf_probability: Probability
    trust_score: float = Field(ge=-1.0, le=1.0)
    supporting_evidence_ids: tuple[str, ...] = ()


class RoleClaimBrief(StrictModel):
    speaker: Seat
    subject: Seat
    role: RoleType
    polarity: ClaimPolarity
    evidence_id: str


class CheckBrief(StrictModel):
    speaker: Seat
    target: Seat
    night: int = Field(ge=1)
    result: ClaimAlignment
    evidence_id: str


class VoteIntentBrief(StrictModel):
    speaker: Seat
    target: Seat
    intent: VoteIntentType
    conditional: bool
    evidence_id: str


class DecisionBrief(StrictModel):
    owner: Seat
    day: int = Field(ge=1)
    task: str = Field(default="vote", pattern="^vote$")
    ledger_revision: int = Field(ge=0)
    belief_revision: int = Field(ge=0)
    candidates: tuple[CandidateBrief, ...]
    role_claims: tuple[RoleClaimBrief, ...] = ()
    checks: tuple[CheckBrief, ...] = ()
    conflicts: tuple[BeliefConflict, ...] = ()
    latest_vote_intents: tuple[VoteIntentBrief, ...] = ()

    @model_validator(mode="after")
    def references_are_local_and_candidates_unique(self):
        seats = [candidate.seat for candidate in self.candidates]
        if len(seats) != len(set(seats)):
            raise ValueError("DecisionBrief candidates must be unique")
        prefix = f"p{self.owner}-e"
        evidence_ids = [
            evidence_id
            for candidate in self.candidates
            for evidence_id in candidate.supporting_evidence_ids
        ]
        evidence_ids.extend(claim.evidence_id for claim in self.role_claims)
        evidence_ids.extend(check.evidence_id for check in self.checks)
        evidence_ids.extend(intent.evidence_id for intent in self.latest_vote_intents)
        evidence_ids.extend(
            evidence_id
            for conflict in self.conflicts
            for evidence_id in conflict.evidence_ids
        )
        if any(not evidence_id.startswith(prefix) for evidence_id in evidence_ids):
            raise ValueError("DecisionBrief cannot reference another player's evidence")
        return self


class DecisionBriefBuilder:
    """Build a compact semantic index without making a voting recommendation."""

    def build(
        self,
        ledger: EvidenceLedger,
        *,
        day: int,
        candidates: tuple[int, ...],
    ) -> DecisionBrief:
        belief = BeliefStateBuilder().build(ledger)
        by_seat = {item.seat: item for item in belief.seat_beliefs}
        candidate_items = tuple(
            CandidateBrief(
                seat=seat,
                wolf_probability=by_seat[seat].camps.werewolf,
                trust_score=by_seat[seat].trust_score,
                supporting_evidence_ids=by_seat[seat].supporting_evidence_ids,
            )
            for seat in candidates
        )

        role_claims: list[RoleClaimBrief] = []
        checks: list[CheckBrief] = []
        latest_intents: dict[int, tuple[int, VoteIntentBrief]] = {}
        for record in ledger.records:
            content = record.content
            if not isinstance(content, PublicClaimEvidence):
                continue
            claim = content.claim
            if isinstance(claim, RoleClaim):
                role_claims.append(
                    RoleClaimBrief(
                        speaker=content.speaker,
                        subject=claim.subject,
                        role=claim.role,
                        polarity=claim.polarity,
                        evidence_id=record.evidence_id,
                    ),
                )
            elif isinstance(claim, CheckClaim):
                checks.append(
                    CheckBrief(
                        speaker=content.speaker,
                        target=claim.target,
                        night=claim.night,
                        result=claim.result,
                        evidence_id=record.evidence_id,
                    ),
                )
            elif (
                isinstance(claim, VoteIntentClaim)
                and record.occurred_at.day == day
            ):
                latest_intents[content.speaker] = (
                    record.known_order,
                    VoteIntentBrief(
                        speaker=content.speaker,
                        target=claim.target,
                        intent=claim.intent,
                        conditional=claim.conditional,
                        evidence_id=record.evidence_id,
                    ),
                )

        return DecisionBrief(
            owner=ledger.owner,
            day=day,
            ledger_revision=ledger.revision,
            belief_revision=belief.revision,
            candidates=candidate_items,
            role_claims=tuple(role_claims),
            checks=tuple(checks),
            conflicts=belief.conflicts,
            latest_vote_intents=tuple(
                item[1]
                for item in sorted(latest_intents.values(), key=lambda pair: pair[0])
            ),
        )
