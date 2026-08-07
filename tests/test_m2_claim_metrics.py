from __future__ import annotations

import unittest

from wolfscope.cognition.claims import (
    AlignmentClaim,
    CheckClaim,
    ClaimAlignment,
    ClaimPolarity,
    RoleClaim,
    VoteIntentClaim,
    VoteIntentType,
)
from wolfscope.evaluation.claim_dataset import ClaimDatasetCase
from wolfscope.evaluation.claim_metrics import aggregate_scores, score_case
from wolfscope.game.types import RoleType


def case_with(expected: list[dict], forbidden: list[dict] | None = None) -> ClaimDatasetCase:
    return ClaimDatasetCase.model_validate(
        {
            "case_id": "metric_case_001",
            "review_status": "reviewed",
            "source": {"source_type": "manual"},
            "speaker": 7,
            "day": 1,
            "speech_context": "day_speech",
            "text": "我是7号预言家，昨夜查验1号是狼人，今天投1号。",
            "expected_claims": expected,
            "forbidden_claims": forbidden or [],
            "difficulty": "basic",
        },
    )


class ClaimMetricTests(unittest.TestCase):
    def test_exact_semantic_match_ignores_summary_wording(self) -> None:
        case = case_with(
            [
                {
                    "kind": "check_claim",
                    "target": 1,
                    "night": 1,
                    "result": "werewolf",
                    "supporting_text": "昨夜查验1号是狼人",
                },
            ],
        )
        prediction = CheckClaim(
            target=1,
            night=1,
            result=ClaimAlignment.WEREWOLF,
            summary="措辞可以不同",
            supporting_text="昨夜查验1号是狼人",
        )

        result = score_case(case, (prediction,))

        self.assertEqual(result.score.true_positive, 1)
        self.assertEqual(result.score.precision, 1.0)
        self.assertEqual(result.score.recall, 1.0)

    def test_wrong_semantic_field_is_fp_and_fn(self) -> None:
        case = case_with(
            [
                {
                    "kind": "check_claim",
                    "target": 1,
                    "night": 1,
                    "result": "werewolf",
                    "supporting_text": "昨夜查验1号是狼人",
                },
            ],
        )
        prediction = CheckClaim(
            target=1,
            night=1,
            result=ClaimAlignment.GOOD,
            summary="错误结果",
            supporting_text="昨夜查验1号是狼人",
        )

        result = score_case(case, (prediction,))

        self.assertEqual(result.score.false_positive, 1)
        self.assertEqual(result.score.false_negative, 1)

    def test_duplicate_prediction_cannot_match_gold_twice(self) -> None:
        case = case_with(
            [
                {
                    "kind": "role_claim",
                    "subject": 7,
                    "role": "seer",
                    "polarity": "assert",
                    "supporting_text": "我是7号预言家",
                },
            ],
        )
        prediction = RoleClaim(
            subject=7,
            role=RoleType.SEER,
            polarity=ClaimPolarity.ASSERT,
            summary="7号跳预言家",
            supporting_text="我是7号预言家",
        )

        result = score_case(case, (prediction, prediction))

        self.assertEqual(result.score.true_positive, 1)
        self.assertEqual(result.score.false_positive, 1)

    def test_forbidden_partial_pattern_is_reported(self) -> None:
        case = case_with(
            [],
            [{"kind": "check_claim", "target": 1}],
        )
        prediction = CheckClaim(
            target=1,
            night=1,
            result=ClaimAlignment.WEREWOLF,
            summary="错误地把转述当查验",
            supporting_text="昨夜查验1号是狼人",
        )

        result = score_case(case, (prediction,))

        self.assertEqual(result.forbidden_hits, ((0, 0),))

    def test_aggregate_reports_each_claim_kind(self) -> None:
        case = case_with(
            [
                {
                    "kind": "alignment_claim",
                    "target": 7,
                    "alignment": "good",
                    "polarity": "assert",
                    "supporting_text": "我是7号预言家",
                },
            ],
        )
        prediction = AlignmentClaim(
            target=7,
            alignment=ClaimAlignment.GOOD,
            polarity=ClaimPolarity.ASSERT,
            summary="7号声称好人",
            supporting_text="我是7号预言家",
        )
        result = score_case(case, (prediction,))

        report = aggregate_scores(((case, (prediction,), result),))

        self.assertEqual(report["overall"]["f1"], 1.0)
        self.assertEqual(report["by_kind"]["alignment_claim"]["recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
