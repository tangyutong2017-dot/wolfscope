from __future__ import annotations

import unittest

from pydantic import ValidationError

from wolfscope.cognition.claims import (
    CheckClaim,
    ClaimPolarity,
    RoleClaim,
    SpeechClaimExtraction,
    VoteIntentClaim,
    VoteIntentType,
)
from wolfscope.cognition.evidence import PublicClaimEvidence, RawSpeech
from wolfscope.cognition.extraction import (
    EvidencePipeline,
    ExtractionStatus,
    FakePublicClaimExtractor,
    PublicSpeechAnnotationCache,
)
from wolfscope.cognition.ledger import EvidenceLedgerRegistry
from wolfscope.contracts import Visibility
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.types import Phase, RoleType
from wolfscope.player_view import PlayerViewBuilder


def state_and_events(*speeches: tuple[int, str]) -> tuple[GameState, EventLog]:
    state = GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
        phase=Phase.DAY_SPEECH,
    )
    events = EventLog()
    for speaker, text in speeches:
        events.emit(
            day=1,
            phase=Phase.DAY_SPEECH,
            event_type="day_speech",
            visibility=Visibility.PUBLIC,
            actor=speaker,
            content=text,
        )
    return state, events


def pipeline_for(
    state: GameState,
    events: EventLog,
    extractor: FakePublicClaimExtractor,
) -> tuple[EvidencePipeline, PlayerViewBuilder, EvidenceLedgerRegistry]:
    builder = PlayerViewBuilder(state, events)
    ledgers = EvidenceLedgerRegistry()
    return (
        EvidencePipeline(
            ledgers=ledgers,
            cache=PublicSpeechAnnotationCache(),
            extractor=extractor,
            source_resolver=builder,
        ),
        builder,
        ledgers,
    )


class PublicClaimSchemaTests(unittest.TestCase):
    def test_conditional_vote_requires_condition(self) -> None:
        with self.assertRaises(ValidationError):
            VoteIntentClaim(
                target=1,
                intent=VoteIntentType.VOTE,
                conditional=True,
                summary="条件投票",
                supporting_text="如果没人对跳就投1号",
            )


class EvidencePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_speech_is_extracted_once_and_delivered_locally(self) -> None:
        text = "我是7号预言家，昨夜查验1号是狼人，今天投1号。"
        state, events = state_and_events((7, text))
        extractor = FakePublicClaimExtractor(
            [
                (
                    SpeechClaimExtraction(
                        item_id="speech-1",
                        claims=(
                            RoleClaim(
                                subject=7,
                                role=RoleType.SEER,
                                polarity=ClaimPolarity.ASSERT,
                                summary="7号声称预言家",
                                supporting_text="我是7号预言家",
                            ),
                            CheckClaim(
                                target=1,
                                night=1,
                                result="werewolf",
                                summary="7号声称查验1号为狼人",
                                supporting_text="昨夜查验1号是狼人",
                            ),
                            VoteIntentClaim(
                                target=1,
                                intent=VoteIntentType.VOTE,
                                summary="7号准备投1号",
                                supporting_text="今天投1号",
                            ),
                        ),
                    ),
                ),
            ],
        )
        pipeline, builder, ledgers = pipeline_for(state, events, extractor)

        await pipeline.sync(builder.build(4))
        await pipeline.sync(builder.build(5))

        self.assertEqual(len(extractor.calls), 1)
        self.assertEqual(len(pipeline.cache), 1)
        for seat in (4, 5):
            claims = [
                record
                for record in ledgers.get(seat).records
                if isinstance(record.content, PublicClaimEvidence)
            ]
            self.assertEqual(len(claims), 3)
            self.assertTrue(
                all(record.evidence_id.startswith(f"p{seat}-e") for record in claims),
            )
            self.assertTrue(all(record.content.speaker == 7 for record in claims))

    async def test_invalid_claims_are_dropped_without_losing_raw_speech(self) -> None:
        text = "我是7号预言家。"
        state, events = state_and_events((7, text))
        extractor = FakePublicClaimExtractor(
            [
                (
                    SpeechClaimExtraction(
                        item_id="speech-1",
                        claims=(
                            RoleClaim(
                                subject=7,
                                role=RoleType.SEER,
                                polarity=ClaimPolarity.ASSERT,
                                summary="有效身份声称",
                                supporting_text="我是7号预言家",
                            ),
                            CheckClaim(
                                target=1,
                                night=2,
                                result="werewolf",
                                summary="不存在的未来查验",
                                supporting_text="昨夜查验1号",
                            ),
                        ),
                    ),
                ),
            ],
        )
        pipeline, builder, ledgers = pipeline_for(state, events, extractor)

        await pipeline.sync(builder.build(4))

        annotation = pipeline.cache.values[0]
        self.assertIs(annotation.status, ExtractionStatus.PARTIAL)
        self.assertEqual(annotation.rejected_claims, 1)
        self.assertEqual(annotation.rejection_reasons, ("unsupported_text",))
        self.assertEqual(len(annotation.claims), 1)
        self.assertTrue(
            any(isinstance(record.content, RawSpeech) for record in ledgers.get(4).records),
        )

    async def test_extractor_failure_is_cached_and_raw_speech_survives(self) -> None:
        state, events = state_and_events((7, "7号暂时没有额外信息。"))
        extractor = FakePublicClaimExtractor([RuntimeError("offline failure")])
        pipeline, builder, ledgers = pipeline_for(state, events, extractor)

        await pipeline.sync(builder.build(4))
        await pipeline.sync(builder.build(5))

        self.assertEqual(len(extractor.calls), 1)
        annotation = pipeline.cache.values[0]
        self.assertIs(annotation.status, ExtractionStatus.FAILED)
        self.assertEqual(annotation.failure_reason, "extractor_failure")
        self.assertTrue(
            any(isinstance(record.content, RawSpeech) for record in ledgers.get(5).records),
        )

    async def test_multiple_uncached_speeches_use_one_batch(self) -> None:
        state, events = state_and_events(
            (1, "1号暂时没有额外信息。"),
            (2, "2号暂时没有额外信息。"),
        )
        extractor = FakePublicClaimExtractor(
            [
                (
                    SpeechClaimExtraction(item_id="speech-1"),
                    SpeechClaimExtraction(item_id="speech-2"),
                ),
            ],
        )
        pipeline, builder, _ = pipeline_for(state, events, extractor)

        await pipeline.sync(builder.build(4))

        self.assertEqual(len(extractor.calls), 1)
        self.assertEqual(len(extractor.calls[0]), 2)
        self.assertEqual(len(pipeline.cache), 2)

    async def test_private_event_offsets_do_not_leak_through_shared_cache(self) -> None:
        state, events = state_and_events()
        events.emit(
            day=1,
            phase=Phase.NIGHT_WOLF,
            event_type="wolf_target",
            visibility=Visibility.WOLVES,
            target=4,
            content="狼队选择袭击4号",
            data={"target": 4},
        )
        events.emit(
            day=1,
            phase=Phase.DAY_SPEECH,
            event_type="day_speech",
            visibility=Visibility.PUBLIC,
            actor=7,
            content="我是7号预言家。",
        )
        extractor = FakePublicClaimExtractor(
            [
                (
                    SpeechClaimExtraction(
                        item_id="speech-1",
                        claims=(
                            RoleClaim(
                                subject=7,
                                role=RoleType.SEER,
                                polarity=ClaimPolarity.ASSERT,
                                summary="7号声称预言家",
                                supporting_text="我是7号预言家",
                            ),
                        ),
                    ),
                ),
            ],
        )
        pipeline, builder, ledgers = pipeline_for(state, events, extractor)

        await pipeline.sync(builder.build(1))
        await pipeline.sync(builder.build(4))

        self.assertEqual(len(extractor.calls), 1)
        wolf_claim = next(
            record
            for record in ledgers.get(1).records
            if isinstance(record.content, PublicClaimEvidence)
        )
        villager_claim = next(
            record
            for record in ledgers.get(4).records
            if isinstance(record.content, PublicClaimEvidence)
        )
        self.assertEqual(wolf_claim.source.view_event_id, 2)
        self.assertEqual(villager_claim.source.view_event_id, 1)
        self.assertNotEqual(wolf_claim.evidence_id, villager_claim.evidence_id)


if __name__ == "__main__":
    unittest.main()
