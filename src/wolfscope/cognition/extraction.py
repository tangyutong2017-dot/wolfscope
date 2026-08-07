"""One-time public speech extraction, cache, validation and ledger delivery."""

from __future__ import annotations

import hashlib
import unicodedata
from enum import StrEnum
from typing import Protocol

from pydantic import Field

from wolfscope.contracts import GameEvent, PlayerView
from wolfscope.player_view import PlayerViewBuilder

from .claims import PublicClaim, SpeechClaimExtraction, SpeechExtractionItem
from .evidence import EvidenceModel, EvidenceRecord
from .ledger import EvidenceLedgerRegistry


class ExtractionStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class PublicSpeechAnnotation(EvidenceModel):
    source_event_id: int = Field(ge=1)
    speaker: int = Field(ge=1, le=9)
    speech_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    extractor_version: str = Field(min_length=1)
    status: ExtractionStatus
    claims: tuple[PublicClaim, ...] = ()
    rejected_claims: int = Field(default=0, ge=0)
    rejection_reasons: tuple[str, ...] = ()
    failure_reason: str | None = None


class PublicClaimExtractor(Protocol):
    version: str

    async def extract(
        self,
        items: tuple[SpeechExtractionItem, ...],
    ) -> tuple[SpeechClaimExtraction, ...]:
        ...


class PublicClaimExtractorError(RuntimeError):
    """Expected, sanitized failure from a public-claim extractor adapter."""


class PublicSpeechAnnotationCache:
    def __init__(self) -> None:
        self._annotations: dict[int, PublicSpeechAnnotation] = {}

    def get(self, source_event_id: int) -> PublicSpeechAnnotation | None:
        return self._annotations.get(source_event_id)

    def put(self, annotation: PublicSpeechAnnotation) -> None:
        existing = self._annotations.get(annotation.source_event_id)
        if existing is not None and existing != annotation:
            raise ValueError("public speech annotation cache is immutable")
        self._annotations[annotation.source_event_id] = annotation

    def __len__(self) -> int:
        return len(self._annotations)

    @property
    def values(self) -> tuple[PublicSpeechAnnotation, ...]:
        return tuple(self._annotations.values())


class EvidencePipeline:
    _SPEECH_CONTEXTS = {
        "sheriff_campaign_speech": "sheriff_campaign",
        "day_speech": "day_speech",
        "pk_speech": "pk_speech",
        "last_words": "last_words",
    }

    def __init__(
        self,
        *,
        ledgers: EvidenceLedgerRegistry,
        cache: PublicSpeechAnnotationCache,
        extractor: PublicClaimExtractor,
        source_resolver: PlayerViewBuilder,
    ) -> None:
        self.ledgers = ledgers
        self.cache = cache
        self.extractor = extractor
        self.source_resolver = source_resolver

    async def sync(self, view: PlayerView) -> tuple[EvidenceRecord, ...]:
        added = list(self.ledgers.sync(view))
        speech_events = [
            event
            for event in view.visible_events
            if event.event_type in self._SPEECH_CONTEXTS and event.actor is not None
        ]
        resolved = [
            (
                event,
                self.source_resolver.source_event_id(
                    view.viewer_seat,
                    event.event_id,
                    view_revision=view.view_revision,
                ),
            )
            for event in speech_events
        ]
        missing = [pair for pair in resolved if self.cache.get(pair[1]) is None]
        if missing:
            await self._extract_missing(missing)
        ledger = self.ledgers.get(view.viewer_seat)
        for event, source_event_id in resolved:
            annotation = self.cache.get(source_event_id)
            assert annotation is not None
            if annotation.speech_hash != _speech_hash(event.content):
                raise ValueError("cached public speech hash does not match source event")
            added.extend(
                ledger.ingest_public_claims(
                    event=event,
                    speaker=annotation.speaker,
                    claims=annotation.claims,
                    extractor_version=annotation.extractor_version,
                ),
            )
        return tuple(added)

    async def _extract_missing(
        self,
        missing: list[tuple[GameEvent, int]],
    ) -> None:
        items = tuple(
            SpeechExtractionItem(
                item_id=f"speech-{index}",
                day=event.day,
                speaker=event.actor,
                speech_context=self._SPEECH_CONTEXTS[event.event_type],
                text=event.content,
            )
            for index, (event, _) in enumerate(missing, start=1)
        )
        try:
            outputs = await self.extractor.extract(items)
        except PublicClaimExtractorError:
            outputs = ()
            extraction_failed = True
        else:
            extraction_failed = False
        by_item = {output.item_id: output for output in outputs}
        for item, (event, source_event_id) in zip(items, missing, strict=True):
            output = by_item.get(item.item_id)
            if extraction_failed or output is None:
                annotation = PublicSpeechAnnotation(
                    source_event_id=source_event_id,
                    speaker=item.speaker,
                    speech_hash=_speech_hash(item.text),
                    extractor_version=self.extractor.version,
                    status=ExtractionStatus.FAILED,
                    failure_reason="extractor_failure",
                )
            else:
                accepted, rejection_reasons = _validated_claims(item, output.claims)
                status = (
                    ExtractionStatus.PARTIAL
                    if rejection_reasons
                    else ExtractionStatus.SUCCESS
                )
                annotation = PublicSpeechAnnotation(
                    source_event_id=source_event_id,
                    speaker=item.speaker,
                    speech_hash=_speech_hash(item.text),
                    extractor_version=self.extractor.version,
                    status=status,
                    claims=accepted,
                    rejected_claims=len(rejection_reasons),
                    rejection_reasons=rejection_reasons,
                )
            self.cache.put(annotation)


def _validated_claims(
    item: SpeechExtractionItem,
    claims: tuple[PublicClaim, ...],
) -> tuple[tuple[PublicClaim, ...], tuple[str, ...]]:
    normalized_speech = _normalize_text(item.text)
    accepted: list[PublicClaim] = []
    fingerprints: set[str] = set()
    rejection_reasons: list[str] = []
    for claim in claims:
        if _normalize_text(claim.supporting_text) not in normalized_speech:
            rejection_reasons.append("unsupported_text")
            continue
        if getattr(claim, "night", 1) > item.day:
            rejection_reasons.append("invalid_time")
            continue
        fingerprint = claim.model_dump_json()
        if fingerprint in fingerprints:
            rejection_reasons.append("duplicate_claim")
            continue
        fingerprints.add(fingerprint)
        accepted.append(claim)
    return tuple(accepted), tuple(rejection_reasons)


def _normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _speech_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FakePublicClaimExtractor:
    def __init__(
        self,
        responses: list[tuple[SpeechClaimExtraction, ...] | Exception],
        *,
        version: str = "fake-claims-v1",
    ) -> None:
        self.version = version
        self.responses = list(responses)
        self.calls: list[tuple[SpeechExtractionItem, ...]] = []

    async def extract(
        self,
        items: tuple[SpeechExtractionItem, ...],
    ) -> tuple[SpeechClaimExtraction, ...]:
        self.calls.append(items)
        if not self.responses:
            raise RuntimeError("FakePublicClaimExtractor has no queued response")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise PublicClaimExtractorError("fake extractor failure") from response
        return response
