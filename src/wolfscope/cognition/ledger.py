"""Append-only player-local ledger and deterministic Engine event projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from wolfscope.contracts import GameEvent, PlayerView
from wolfscope.game.types import Phase, RoleType

from .claims import PublicClaim
from .evidence import (
    ActualVoteFact,
    BadgeDestroyedFact,
    BadgeTransferredFact,
    DawnDeathFact,
    EpistemicStatus,
    EventEvidenceSource,
    EvidenceContent,
    EvidenceKind,
    EvidenceRecord,
    ExtractionMethod,
    HunterDidNotShootFact,
    HunterShotFact,
    NoExileFact,
    NoSheriffFact,
    OwnRoleFact,
    PeacefulNightFact,
    PlayerExiledFact,
    PublicAnnotationEvidenceSource,
    PublicClaimEvidence,
    RawSpeech,
    RoleStateEvidenceSource,
    SeerCheckFact,
    SheriffElectedFact,
    SheriffSignupFact,
    SheriffWithdrawalFact,
    TemporalPoint,
    WitchActionFact,
    WitchPoisonUsedDeducedFact,
    WitchSaveDeducedFact,
    WitchVictimFact,
    WolfExplosionFact,
    WolfTargetFact,
    WolfTeammateFact,
)


@dataclass(frozen=True, slots=True)
class ProjectedEvidence:
    suffix: str
    content: EvidenceContent
    kind: EvidenceKind = EvidenceKind.FACT
    epistemic_status: EpistemicStatus = EpistemicStatus.VERIFIED
    extraction_method: ExtractionMethod = ExtractionMethod.ENGINE
    occurred_phase: Phase | None = None


@dataclass(slots=True)
class EvidenceLedger:
    owner: int
    records: list[EvidenceRecord] = field(default_factory=list)
    last_processed_view_event_id: int = 0
    _dedupe_keys: set[tuple[object, ...]] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not 1 <= self.owner <= 9:
            raise ValueError("ledger owner must be between 1 and 9")

    @property
    def revision(self) -> int:
        return len(self.records)

    def sync(self, view: PlayerView) -> tuple[EvidenceRecord, ...]:
        if view.viewer_seat != self.owner:
            raise ValueError("EvidenceLedger cannot process another player's view")
        if view.view_revision < self.last_processed_view_event_id:
            raise ValueError("EvidenceLedger cannot process a stale PlayerView")
        added: list[EvidenceRecord] = []
        if not any(key[0] == "role_state" for key in self._dedupe_keys):
            added.extend(self._seed_role_state(view))
        for event in view.visible_events:
            if event.event_id <= self.last_processed_view_event_id:
                continue
            for projected in DeterministicEvidenceProjector.project(
                event,
                ruleset=view.ruleset,
            ):
                key = ("event", event.event_id, projected.suffix)
                record = self._append(
                    key=key,
                    source=EventEvidenceSource(view_event_id=event.event_id),
                    content=projected.content,
                    kind=projected.kind,
                    epistemic_status=projected.epistemic_status,
                    extraction_method=projected.extraction_method,
                    day=event.day,
                    occurred_phase=projected.occurred_phase or event.phase,
                    known_phase=event.phase,
                    local_order=event.event_id,
                )
                if record is not None:
                    added.append(record)
        self.last_processed_view_event_id = view.view_revision
        return tuple(added)

    def _seed_role_state(self, view: PlayerView) -> list[EvidenceRecord]:
        added: list[EvidenceRecord] = []
        own = self._append(
            key=("role_state", "own_role"),
            source=RoleStateEvidenceSource(field="own_role"),
            content=OwnRoleFact(role=view.own_role),
            kind=EvidenceKind.FACT,
            epistemic_status=EpistemicStatus.VERIFIED,
            extraction_method=ExtractionMethod.ENGINE,
            day=0,
            occurred_phase=Phase.SETUP,
            known_phase=Phase.SETUP,
            local_order=0,
        )
        if own is not None:
            added.append(own)
        if view.own_role is RoleType.WEREWOLF:
            teammates = getattr(view.own_role_state, "teammate_seats", ())
            for teammate in teammates:
                if teammate == self.owner:
                    continue
                record = self._append(
                    key=("role_state", "wolf_teammate", teammate),
                    source=RoleStateEvidenceSource(field="wolf_teammates"),
                    content=WolfTeammateFact(teammate=teammate),
                    kind=EvidenceKind.FACT,
                    epistemic_status=EpistemicStatus.VERIFIED,
                    extraction_method=ExtractionMethod.ENGINE,
                    day=0,
                    occurred_phase=Phase.SETUP,
                    known_phase=Phase.SETUP,
                    local_order=0,
                )
                if record is not None:
                    added.append(record)
        return added

    def ingest_public_claims(
        self,
        *,
        event: GameEvent,
        speaker: int,
        claims: tuple[PublicClaim, ...],
        extractor_version: str,
    ) -> tuple[EvidenceRecord, ...]:
        """Append cached public annotations using only player-local source IDs."""

        records: list[EvidenceRecord] = []
        for claim_index, claim in enumerate(claims, start=1):
            key = (
                "public_annotation",
                event.event_id,
                extractor_version,
                claim_index,
            )
            sequence = len(self.records) + 1
            point = TemporalPoint(
                day=event.day,
                phase=event.phase,
                local_order=event.event_id,
            )
            if key in self._dedupe_keys:
                continue
            record = EvidenceRecord(
                evidence_id=f"p{self.owner}-e{sequence}",
                owner=self.owner,
                source=PublicAnnotationEvidenceSource(
                    view_event_id=event.event_id,
                    claim_index=claim_index,
                ),
                kind=EvidenceKind.CLAIM,
                epistemic_status=EpistemicStatus.CLAIMED,
                occurred_at=point,
                known_at=point,
                known_order=sequence,
                content=PublicClaimEvidence(speaker=speaker, claim=claim),
                extraction_method=ExtractionMethod.LLM,
                extractor_version=extractor_version,
            )
            self._dedupe_keys.add(key)
            self.records.append(record)
            records.append(record)
        return tuple(records)

    def _append(
        self,
        *,
        key: tuple[object, ...],
        source,
        content: EvidenceContent,
        kind: EvidenceKind,
        epistemic_status: EpistemicStatus,
        extraction_method: ExtractionMethod,
        day: int,
        occurred_phase,
        known_phase,
        local_order: int,
    ) -> EvidenceRecord | None:
        if key in self._dedupe_keys:
            return None
        sequence = len(self.records) + 1
        occurred = TemporalPoint(
            day=day,
            phase=occurred_phase,
            local_order=local_order,
        )
        known = TemporalPoint(
            day=day,
            phase=known_phase,
            local_order=local_order,
        )
        record = EvidenceRecord(
            evidence_id=f"p{self.owner}-e{sequence}",
            owner=self.owner,
            source=source,
            kind=kind,
            epistemic_status=epistemic_status,
            occurred_at=occurred,
            known_at=known,
            known_order=sequence,
            content=content,
            extraction_method=extraction_method,
        )
        self._dedupe_keys.add(key)
        self.records.append(record)
        return record


class EvidenceLedgerRegistry:
    """Own exactly one isolated evidence ledger per player seat."""

    def __init__(self) -> None:
        self._ledgers = {
            seat: EvidenceLedger(owner=seat)
            for seat in range(1, 10)
        }

    def get(self, seat: int) -> EvidenceLedger:
        return self._ledgers[seat]

    def sync(self, view: PlayerView) -> tuple[EvidenceRecord, ...]:
        return self.get(view.viewer_seat).sync(view)

    @property
    def seats(self) -> tuple[int, ...]:
        return tuple(self._ledgers)


class DeterministicEvidenceProjector:
    _SPEECH_CONTEXTS = {
        "sheriff_campaign_speech": "sheriff_campaign",
        "day_speech": "day_speech",
        "pk_speech": "pk_speech",
        "last_words": "last_words",
    }

    @classmethod
    def project(
        cls,
        event: GameEvent,
        *,
        ruleset: str,
    ) -> tuple[ProjectedEvidence, ...]:
        items: list[ProjectedEvidence] = []
        event_type = event.event_type
        data = event.data
        if event_type == "wolf_target":
            items.append(ProjectedEvidence("wolf_target", WolfTargetFact(night=event.day, target=data["target"])))
        elif event_type == "seer_result":
            items.append(ProjectedEvidence("seer_result", SeerCheckFact(night=event.day, target=data["target"], result=data["alignment"])))
        elif event_type == "witch_night_victim":
            items.append(
                ProjectedEvidence(
                    "witch_victim",
                    WitchVictimFact(night=event.day, target=data["target"]),
                    occurred_phase=Phase.NIGHT_WOLF,
                ),
            )
        elif event_type == "witch_action":
            items.append(ProjectedEvidence("witch_action", WitchActionFact(night=event.day, action=data["action"], target=data.get("target"))))
        elif event_type == "sheriff_candidates":
            items.extend(ProjectedEvidence(f"signup:{seat}", SheriffSignupFact(seat=seat)) for seat in data["candidates"])
        elif event_type == "sheriff_withdrawals":
            items.extend(ProjectedEvidence(f"withdrawal:{seat}", SheriffWithdrawalFact(seat=seat)) for seat in data["withdrawn"])
        elif event_type in {"sheriff_votes", "exile_votes", "exile_revotes"}:
            vote_type = "sheriff" if event_type == "sheriff_votes" else "exile"
            vote_round = "revote" if event_type == "exile_revotes" else "first"
            items.extend(
                ProjectedEvidence(
                    f"vote:{index}",
                    ActualVoteFact(
                        vote_type=vote_type,
                        round=vote_round,
                        voter=vote["voter"],
                        target=vote.get("target"),
                        units=vote.get("units"),
                    ),
                )
                for index, vote in enumerate(data["votes"], start=1)
            )
        elif event_type == "sheriff_elected":
            items.append(ProjectedEvidence("sheriff", SheriffElectedFact(sheriff=data["sheriff"])))
        elif event_type == "sheriff_failed":
            items.append(ProjectedEvidence("no_sheriff", NoSheriffFact(reason=data["reason"])))
        elif event_type == "dawn_deaths":
            deaths = data["deaths"]
            items.extend(ProjectedEvidence(f"death:{seat}", DawnDeathFact(seat=seat)) for seat in deaths)
            if ruleset == "standard-9-v1" and len(deaths) == 2:
                items.append(ProjectedEvidence("poison_deduced", WitchPoisonUsedDeducedFact(night=event.day), extraction_method=ExtractionMethod.RULE_DERIVATION))
        elif event_type == "peaceful_night":
            items.append(
                ProjectedEvidence("peaceful", PeacefulNightFact(night=event.day)),
            )
            if ruleset == "standard-9-v1":
                items.append(
                    ProjectedEvidence(
                        "save_deduced",
                        WitchSaveDeducedFact(night=event.day),
                        extraction_method=ExtractionMethod.RULE_DERIVATION,
                    ),
                )
        elif event_type == "wolf_exploded":
            items.append(ProjectedEvidence("wolf_explosion", WolfExplosionFact(seat=data["seat"])))
        elif event_type == "player_exiled":
            items.append(ProjectedEvidence("exiled", PlayerExiledFact(seat=data["seat"])))
        elif event_type == "no_exile":
            items.append(ProjectedEvidence("no_exile", NoExileFact(day=event.day)))
        elif event_type == "hunter_shot":
            items.append(ProjectedEvidence("hunter_shot", HunterShotFact(hunter=data["hunter"], target=data["target"])))
        elif event_type == "hunter_did_not_shoot":
            items.append(ProjectedEvidence("hunter_no_shot", HunterDidNotShootFact(hunter=event.actor)))
        elif event_type == "badge_transferred":
            items.append(ProjectedEvidence("badge_transfer", BadgeTransferredFact(former_sheriff=data["from"], new_sheriff=data["to"])))
        elif event_type == "badge_destroyed":
            items.append(ProjectedEvidence("badge_destroyed", BadgeDestroyedFact(former_sheriff=event.actor)))
        elif event_type in cls._SPEECH_CONTEXTS and event.actor is not None:
            items.append(
                ProjectedEvidence(
                    "raw_speech",
                    RawSpeech(
                        speaker=event.actor,
                        speech_context=cls._SPEECH_CONTEXTS[event_type],
                        text=event.content,
                    ),
                    kind=EvidenceKind.RAW_SPEECH,
                    epistemic_status=EpistemicStatus.OBSERVED,
                ),
            )
        return tuple(items)
