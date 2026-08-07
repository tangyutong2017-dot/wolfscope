from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from wolfscope.evaluation.claim_dataset import ClaimDatasetCase, load_dataset


DATASET = Path("datasets/claim_extraction/gold_v1.jsonl")


class ClaimDatasetTests(unittest.TestCase):
    def test_first_reviewed_dataset_is_valid(self) -> None:
        cases = load_dataset(DATASET)

        self.assertEqual(len(cases), 10)
        self.assertTrue(all(case.review_status == "reviewed" for case in cases))
        self.assertEqual(len({case.case_id for case in cases}), 10)

    def test_supporting_text_must_come_from_speech(self) -> None:
        with self.assertRaisesRegex(ValidationError, "supporting_text is not in text"):
            ClaimDatasetCase.model_validate(
                {
                    "case_id": "invalid_quote_001",
                    "source": {"source_type": "manual"},
                    "speaker": 7,
                    "day": 1,
                    "speech_context": "day_speech",
                    "text": "我是7号预言家。",
                    "expected_claims": [
                        {
                            "kind": "role_claim",
                            "subject": 7,
                            "role": "seer",
                            "polarity": "assert",
                            "supporting_text": "我是7号女巫",
                        },
                    ],
                    "difficulty": "basic",
                },
            )

    def test_duplicate_case_ids_are_rejected(self) -> None:
        line = (
            '{"case_id":"duplicate_001","source":{"source_type":"manual"},'
            '"speaker":1,"day":1,"speech_context":"day_speech",'
            '"text":"没有信息。","difficulty":"basic"}'
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.jsonl"
            path.write_text(f"{line}\n{line}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate case_id"):
                load_dataset(path)

    def test_dataset_uses_good_not_villager_for_alignment(self) -> None:
        with self.assertRaises(ValidationError):
            ClaimDatasetCase.model_validate(
                {
                    "case_id": "invalid_alignment_001",
                    "source": {"source_type": "manual"},
                    "speaker": 8,
                    "day": 1,
                    "speech_context": "day_speech",
                    "text": "我是8号，一个好人身份。",
                    "expected_claims": [
                        {
                            "kind": "alignment_claim",
                            "target": 8,
                            "alignment": "villager",
                            "polarity": "assert",
                            "supporting_text": "我是8号，一个好人身份",
                        },
                    ],
                    "difficulty": "basic",
                },
            )


if __name__ == "__main__":
    unittest.main()
