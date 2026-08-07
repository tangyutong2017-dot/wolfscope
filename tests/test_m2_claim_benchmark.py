from __future__ import annotations

import unittest

from wolfscope.cognition.claims import (
    ClaimPolarity,
    RoleClaim,
    SpeechClaimExtraction,
)
from wolfscope.cognition.extraction import FakePublicClaimExtractor
from wolfscope.evaluation.claim_benchmark import run_benchmark
from wolfscope.evaluation.claim_dataset import ClaimDatasetCase
from wolfscope.game.types import RoleType


def benchmark_case(
    case_id: str,
    *,
    reviewed: bool = True,
    expected: bool = True,
) -> ClaimDatasetCase:
    return ClaimDatasetCase.model_validate(
        {
            "case_id": case_id,
            "review_status": "reviewed" if reviewed else "draft",
            "source": {"source_type": "manual"},
            "speaker": 7,
            "day": 1,
            "speech_context": "day_speech",
            "text": "我是7号预言家。",
            "expected_claims": (
                [
                    {
                        "kind": "role_claim",
                        "subject": 7,
                        "role": "seer",
                        "polarity": "assert",
                        "supporting_text": "我是7号预言家",
                    },
                ]
                if expected
                else []
            ),
            "difficulty": "basic",
        },
    )


def role_claim() -> RoleClaim:
    return RoleClaim(
        subject=7,
        role=RoleType.SEER,
        polarity=ClaimPolarity.ASSERT,
        summary="7号声称预言家",
        supporting_text="我是7号预言家",
    )


class ClaimBenchmarkTests(unittest.IsolatedAsyncioTestCase):
    async def test_blind_benchmark_scores_predictions(self) -> None:
        case = benchmark_case("benchmark_match_001")
        extractor = FakePublicClaimExtractor(
            [
                (
                    SpeechClaimExtraction(
                        item_id=case.case_id,
                        claims=(role_claim(),),
                    ),
                ),
            ],
        )

        report = await run_benchmark((case,), extractor, model_name="fake")

        self.assertEqual(report["overall"]["f1"], 1.0)
        self.assertEqual(report["cases"], 1)
        sent_item = extractor.calls[0][0]
        self.assertEqual(sent_item.text, case.text)
        self.assertFalse(hasattr(sent_item, "expected_claims"))

    async def test_adapter_rejection_marks_partial_without_losing_valid_claim(self) -> None:
        case = benchmark_case("benchmark_partial_001")
        extractor = FakePublicClaimExtractor(
            [
                (
                    SpeechClaimExtraction(
                        item_id=case.case_id,
                        claims=(role_claim(),),
                        rejected_claims=1,
                        rejection_reasons=("value_error",),
                    ),
                ),
            ],
        )

        report = await run_benchmark((case,), extractor, model_name="fake")

        self.assertEqual(report["overall"]["recall"], 1.0)
        self.assertEqual(report["partial_cases"], 1)
        self.assertEqual(report["schema_rejections"], 1)

    async def test_draft_cases_are_not_sent_to_model(self) -> None:
        reviewed = benchmark_case("benchmark_reviewed_001", expected=False)
        draft = benchmark_case("benchmark_draft_001", reviewed=False, expected=False)
        extractor = FakePublicClaimExtractor(
            [(SpeechClaimExtraction(item_id=reviewed.case_id),)],
        )

        report = await run_benchmark(
            (reviewed, draft),
            extractor,
            model_name="fake",
        )

        self.assertEqual(report["cases"], 1)
        self.assertEqual(len(extractor.calls), 1)


if __name__ == "__main__":
    unittest.main()
