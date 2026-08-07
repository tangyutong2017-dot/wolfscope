"""Compact, player-local EvidenceLedger snapshot for one model decision."""

from __future__ import annotations

from pydantic import Field, model_validator

from wolfscope.contracts import Seat, StrictModel

from .evidence import (
    EpistemicStatus,
    EvidenceContent,
    EvidenceKind,
    EvidenceRecord,
    ExtractionMethod,
    PublicClaimEvidence,
    TemporalPoint,
)
from .ledger import EvidenceLedger


class DecisionEvidenceItem(StrictModel):
    evidence_id: str = Field(pattern=r"^p[1-9]-e[1-9][0-9]*$")
    epistemic_status: EpistemicStatus
    extraction_method: ExtractionMethod
    occurred_at: TemporalPoint
    content: EvidenceContent


class EvidenceContext(StrictModel):
    owner: Seat
    ledger_revision: int = Field(ge=0)
    verified_facts: tuple[DecisionEvidenceItem, ...] = ()
    rule_derivations: tuple[DecisionEvidenceItem, ...] = ()
    public_claims: tuple[DecisionEvidenceItem, ...] = ()

    @model_validator(mode="after")
    def ids_are_local_unique_and_claims_are_claimed(self):
        items = self.verified_facts + self.rule_derivations + self.public_claims
        ids = [item.evidence_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("EvidenceContext cannot contain duplicate evidence IDs")
        prefix = f"p{self.owner}-e"
        if any(not evidence_id.startswith(prefix) for evidence_id in ids):
            raise ValueError("EvidenceContext cannot contain another player's evidence")
        if any(
            item.epistemic_status is not EpistemicStatus.CLAIMED
            for item in self.public_claims
        ):
            raise ValueError("public_claims must have CLAIMED epistemic status")
        if any(
            item.extraction_method is not ExtractionMethod.RULE_DERIVATION
            for item in self.rule_derivations
        ):
            raise ValueError("rule_derivations must use RULE_DERIVATION extraction")
        if any(
            item.extraction_method is not ExtractionMethod.LLM
            for item in self.public_claims
        ):
            raise ValueError("public_claims must use LLM extraction")
        return self

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(
            item.evidence_id
            for item in (
                self.verified_facts + self.rule_derivations + self.public_claims
            )
        )


class EvidenceContextBuilder:
    """Select durable hard evidence and a bounded window of softer claims."""

    def __init__(self, *, soft_claim_limit: int = 30) -> None:
        if soft_claim_limit < 0:
            raise ValueError("soft_claim_limit must be non-negative")
        self.soft_claim_limit = soft_claim_limit

    def build(self, ledger: EvidenceLedger) -> EvidenceContext:
        facts: list[EvidenceRecord] = []
        derivations: list[EvidenceRecord] = []
        critical_claims: list[EvidenceRecord] = []
        soft_claims: list[EvidenceRecord] = []
        for record in ledger.records:
            if record.extraction_method is ExtractionMethod.RULE_DERIVATION:
                derivations.append(record)
            elif record.kind is EvidenceKind.FACT:
                facts.append(record)
            elif isinstance(record.content, PublicClaimEvidence):
                if record.content.claim.kind in {"role_claim", "check_claim"}:
                    critical_claims.append(record)
                else:
                    soft_claims.append(record)
        selected_soft = (
            soft_claims[-self.soft_claim_limit :]
            if self.soft_claim_limit
            else []
        )
        selected_claims = sorted(
            critical_claims + selected_soft,
            key=lambda record: record.known_order,
        )
        return EvidenceContext(
            owner=ledger.owner,
            ledger_revision=ledger.revision,
            verified_facts=tuple(_compact(record) for record in facts),
            rule_derivations=tuple(_compact(record) for record in derivations),
            public_claims=tuple(_compact(record) for record in selected_claims),
        )


def _compact(record: EvidenceRecord) -> DecisionEvidenceItem:
    return DecisionEvidenceItem(
        evidence_id=record.evidence_id,
        epistemic_status=record.epistemic_status,
        extraction_method=record.extraction_method,
        occurred_at=record.occurred_at,
        content=record.content,
    )
