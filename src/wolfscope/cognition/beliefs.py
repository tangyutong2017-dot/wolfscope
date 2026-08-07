"""Deterministic, player-local belief baseline derived from EvidenceLedger."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Literal

from pydantic import Field, model_validator

from wolfscope.contracts import Probability, Seat, StrictModel
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.types import Camp, RoleType

from .claims import ClaimPolarity, RoleClaim
from .evidence import (
    OwnRoleFact,
    PublicClaimEvidence,
    SeerCheckFact,
    WolfTeammateFact,
)
from .ledger import EvidenceLedger


class RoleDistribution(StrictModel):
    werewolf: Probability
    villager: Probability
    seer: Probability
    witch: Probability
    hunter: Probability

    @model_validator(mode="after")
    def sums_to_one(self):
        if abs(sum(self.as_role_map().values()) - 1.0) > 1e-6:
            raise ValueError("role distribution must sum to one")
        return self

    def as_role_map(self) -> dict[RoleType, float]:
        return {
            role: float(getattr(self, role.value))
            for role in RoleType
        }

    @classmethod
    def one_hot(cls, role: RoleType) -> RoleDistribution:
        return cls(
            **{
                candidate.value: 1.0 if candidate is role else 0.0
                for candidate in RoleType
            },
        )

    @classmethod
    def from_weights(cls, weights: dict[RoleType, float]) -> RoleDistribution:
        total = sum(weights.values())
        if total <= 0:
            raise ValueError("role distribution weights must contain positive mass")
        return cls(
            **{
                role.value: weights.get(role, 0.0) / total
                for role in RoleType
            },
        )


class CampDistribution(StrictModel):
    good: Probability
    werewolf: Probability

    @model_validator(mode="after")
    def sums_to_one(self):
        if abs(float(self.good) + float(self.werewolf) - 1.0) > 1e-6:
            raise ValueError("camp distribution must sum to one")
        return self


class SeatBelief(StrictModel):
    seat: Seat
    roles: RoleDistribution
    camps: CampDistribution
    trust_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    supporting_evidence_ids: tuple[str, ...] = ()


class ClaimedRole(StrictModel):
    speaker: Seat
    subject: Seat
    role: RoleType
    polarity: ClaimPolarity
    evidence_id: str


class BeliefConflict(StrictModel):
    kind: Literal["unique_role_counterclaim"] = "unique_role_counterclaim"
    role: Literal["seer", "witch", "hunter"]
    seats: tuple[Seat, ...] = Field(min_length=2)
    evidence_ids: tuple[str, ...] = Field(min_length=2)


class BeliefState(StrictModel):
    owner: Seat
    revision: int = Field(ge=0)
    seat_beliefs: tuple[SeatBelief, ...] = Field(min_length=9, max_length=9)
    claimed_roles: tuple[ClaimedRole, ...] = ()
    conflicts: tuple[BeliefConflict, ...] = ()

    @model_validator(mode="after")
    def covers_all_seats_once(self):
        seats = [belief.seat for belief in self.seat_beliefs]
        if set(seats) != set(range(1, 10)) or len(seats) != len(set(seats)):
            raise ValueError("BeliefState must contain seats 1 through 9 exactly once")
        prefix = f"p{self.owner}-e"
        referenced = [
            evidence_id
            for belief in self.seat_beliefs
            for evidence_id in belief.supporting_evidence_ids
        ]
        referenced.extend(claim.evidence_id for claim in self.claimed_roles)
        referenced.extend(
            evidence_id
            for conflict in self.conflicts
            for evidence_id in conflict.evidence_ids
        )
        if any(not evidence_id.startswith(prefix) for evidence_id in referenced):
            raise ValueError("BeliefState cannot reference another player's evidence")
        return self


class BeliefStateBuilder:
    """Recompute an auditable baseline without asking an LLM for probabilities."""

    UNIQUE_ROLES = {RoleType.SEER, RoleType.WITCH, RoleType.HUNTER}

    def build(self, ledger: EvidenceLedger) -> BeliefState:
        remaining = Counter(STANDARD_9_RULES.roles)
        confirmed: dict[int, RoleType] = {}
        good_constraints: set[int] = set()
        hard_support: dict[int, list[str]] = defaultdict(list)
        claimed_roles: list[ClaimedRole] = []

        for record in ledger.records:
            content = record.content
            if isinstance(content, OwnRoleFact):
                confirmed[ledger.owner] = content.role
                hard_support[ledger.owner].append(record.evidence_id)
            elif isinstance(content, WolfTeammateFact):
                confirmed[content.teammate] = RoleType.WEREWOLF
                hard_support[content.teammate].append(record.evidence_id)
            elif isinstance(content, SeerCheckFact):
                hard_support[content.target].append(record.evidence_id)
                if content.result is Camp.WEREWOLF:
                    confirmed[content.target] = RoleType.WEREWOLF
                else:
                    good_constraints.add(content.target)
            elif (
                isinstance(content, PublicClaimEvidence)
                and isinstance(content.claim, RoleClaim)
            ):
                claimed_roles.append(
                    ClaimedRole(
                        speaker=content.speaker,
                        subject=content.claim.subject,
                        role=content.claim.role,
                        polarity=content.claim.polarity,
                        evidence_id=record.evidence_id,
                    ),
                )

        for role in confirmed.values():
            remaining[role] -= 1
            if remaining[role] < 0:
                raise ValueError("confirmed roles exceed ruleset role count")

        unconfirmed_count = 9 - len(confirmed)
        base_weights = {
            role: float(remaining[role]) / unconfirmed_count
            for role in RoleType
        } if unconfirmed_count else {}
        seat_beliefs: list[SeatBelief] = []
        for seat in range(1, 10):
            if seat in confirmed:
                roles = RoleDistribution.one_hot(confirmed[seat])
            else:
                weights = dict(base_weights)
                if seat in good_constraints:
                    weights[RoleType.WEREWOLF] = 0.0
                roles = RoleDistribution.from_weights(weights)
            role_map = roles.as_role_map()
            wolf_probability = role_map[RoleType.WEREWOLF]
            seat_beliefs.append(
                SeatBelief(
                    seat=seat,
                    roles=roles,
                    camps=CampDistribution(
                        good=1.0 - wolf_probability,
                        werewolf=wolf_probability,
                    ),
                    supporting_evidence_ids=tuple(hard_support[seat]),
                ),
            )

        conflicts = self._conflicts(claimed_roles)
        return BeliefState(
            owner=ledger.owner,
            revision=ledger.revision,
            seat_beliefs=tuple(seat_beliefs),
            claimed_roles=tuple(claimed_roles),
            conflicts=conflicts,
        )

    def _conflicts(
        self,
        claims: list[ClaimedRole],
    ) -> tuple[BeliefConflict, ...]:
        by_role: dict[RoleType, dict[int, str]] = defaultdict(dict)
        for claim in claims:
            if (
                claim.polarity is ClaimPolarity.ASSERT
                and claim.role in self.UNIQUE_ROLES
            ):
                by_role[claim.role].setdefault(claim.subject, claim.evidence_id)
        conflicts: list[BeliefConflict] = []
        for role in sorted(self.UNIQUE_ROLES, key=lambda value: value.value):
            claimants = by_role.get(role, {})
            if len(claimants) < 2:
                continue
            seats = tuple(sorted(claimants))
            conflicts.append(
                BeliefConflict(
                    role=role.value,
                    seats=seats,
                    evidence_ids=tuple(claimants[seat] for seat in seats),
                ),
            )
        return tuple(conflicts)
