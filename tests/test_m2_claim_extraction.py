from __future__ import annotations

import unittest

from pydantic import ValidationError

from wolfscope.cognition.claims import (
    AlignmentClaim,
    CheckClaim,
    ClaimAlignment,
    ClaimPolarity,
    RoleClaim,
    SpeechClaimExtraction,
    VoteIntentClaim,
    VoteRecommendationClaim,
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
    def test_good_alignment_is_distinct_from_villager_role(self) -> None:
        claim = AlignmentClaim(
            target=8,
            alignment=ClaimAlignment.GOOD,
            polarity=ClaimPolarity.ASSERT,
            summary="8号声称自己是好人",
            supporting_text="我是8号，一个好人身份",
        )

        self.assertIs(claim.alignment, ClaimAlignment.GOOD)
        with self.assertRaises(ValidationError):
            AlignmentClaim(
                target=8,
                alignment="villager",
                polarity=ClaimPolarity.ASSERT,
                summary="错误地把村民当作阵营",
                supporting_text="我是8号，一个好人身份",
            )

    def test_conditional_vote_requires_condition(self) -> None:
        with self.assertRaises(ValidationError):
            VoteIntentClaim(
                target=1,
                intent=VoteIntentType.VOTE,
                conditional=True,
                summary="条件投票",
                supporting_text="如果没人对跳就投1号",
            )

    def test_vote_claim_rejects_inherited_target_from_previous_sentence(self) -> None:
        with self.assertRaisesRegex(ValidationError, "target seat"):
            VoteRecommendationClaim(
                target=1,
                conditional=True,
                condition="后面有人对跳",
                summary="若有人对跳再比较发言",
                supporting_text="如果后面有人对跳，再比较双方发言",
            )

    def test_vote_claim_requires_explicit_voting_action(self) -> None:
        with self.assertRaisesRegex(ValidationError, "voting/exile action"):
            VoteRecommendationClaim(
                target=1,
                conditional=True,
                condition="后面有人对跳",
                summary="若有人对跳再看1号发言",
                supporting_text="如果后面有人对跳，再看1号发言",
            )

    def test_explicit_conditional_vote_remains_valid(self) -> None:
        claim = VoteRecommendationClaim(
            target=1,
            conditional=True,
            condition="后面无人对跳",
            summary="无人对跳则投1号",
            supporting_text="如果后面无人对跳，今天投1号",
        )

        self.assertEqual(claim.target, 1)


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

    async def test_adapter_rejections_mark_cached_annotation_partial(self) -> None:
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
                        ),
                        rejected_claims=1,
                        rejection_reasons=("value_error",),
                    ),
                ),
            ],
        )
        pipeline, builder, _ = pipeline_for(state, events, extractor)

        await pipeline.sync(builder.build(4))

        annotation = pipeline.cache.values[0]
        self.assertIs(annotation.status, ExtractionStatus.PARTIAL)
        self.assertEqual(annotation.rejected_claims, 1)
        self.assertEqual(annotation.rejection_reasons, ("value_error",))
        self.assertEqual(len(annotation.claims), 1)

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
