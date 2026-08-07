from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from wolfscope.cognition.claims import SpeechExtractionBatch
from wolfscope.cognition.claims import SpeechExtractionItem
from wolfscope.cognition.extraction import PublicClaimExtractorError
from wolfscope.models.claim_extractor import AgentScopePublicClaimExtractor
from wolfscope.models.config import ModelProfile, model_config_for


@dataclass
class StubUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class StubResponse:
    content: dict[str, Any]
    usage: StubUsage | None = None


class StubStructuredModel:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[list[Any], type[Any] | dict]] = []

    async def generate_structured_output(
        self,
        messages: list[Any],
        structured_model: type[Any] | dict,
        **kwargs: Any,
    ) -> StubResponse:
        self.calls.append((messages, structured_model))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def public_item() -> tuple[SpeechExtractionItem, ...]:
    return (
        SpeechExtractionItem(
            item_id="speech-1",
            day=1,
            speaker=7,
            speech_context="day_speech",
            text="我是7号预言家，昨夜查验1号是狼人。",
        ),
    )


class AgentScopePublicClaimExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_public_text_is_rendered_and_traced(self) -> None:
        model = StubStructuredModel(
            [
                StubResponse(
                    content={
                        "items": [
                            {
                                "item_id": "speech-1",
                                "claims": [
                                    {
                                        "kind": "role_claim",
                                        "subject": 7,
                                        "role": "seer",
                                        "polarity": "assert",
                                        "summary": "7号声称预言家",
                                        "supporting_text": "我是7号预言家",
                                    }
                                ],
                            }
                        ],
                    },
                    usage=StubUsage(input_tokens=300, output_tokens=80),
                ),
            ],
        )
        extractor = AgentScopePublicClaimExtractor(
            model,
            model_config_for(ModelProfile.TEST),
        )

        result = await extractor.extract(public_item())

        rendered = model.calls[0][0][1].get_text_content() or ""
        system = model.calls[0][0][0].get_text_content() or ""
        self.assertIn("我是7号预言家", rendered)
        self.assertNotIn("own_role", rendered)
        self.assertNotIn("wolf_teammates", rendered)
        self.assertIn("不得判断真假", system)
        self.assertIn("最多提取8条", system)
        self.assertEqual(result[0].claims[0].kind, "role_claim")
        self.assertEqual(extractor.traces[0].token_usage.input_tokens, 300)
        self.assertTrue(extractor.traces[0].success)
        self.assertFalse(extractor.traces[0].thinking_enabled)
        self.assertEqual(extractor.traces[0].temperature, 0.0)
        self.assertEqual(extractor.traces[0].max_tokens, 2000)

    async def test_schema_failure_gets_one_repair_attempt(self) -> None:
        model = StubStructuredModel(
            [
                RuntimeError("Failed to generate structured output for model."),
                StubResponse(content={"items": [{"item_id": "speech-1"}]}),
            ],
        )
        extractor = AgentScopePublicClaimExtractor(
            model,
            model_config_for(ModelProfile.TEST),
        )

        result = await extractor.extract(public_item())

        self.assertEqual(result[0].claims, ())
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(extractor.traces[0].retry_count, 1)
        self.assertEqual(
            extractor.traces[0].attempts[0].failure_reason,
            "missing_structured_output",
        )

    async def test_exhausted_failure_is_sanitized(self) -> None:
        model = StubStructuredModel(
            [RuntimeError("bad output"), RuntimeError("still bad")],
        )
        extractor = AgentScopePublicClaimExtractor(
            model,
            model_config_for(ModelProfile.TEST),
        )

        with self.assertRaises(PublicClaimExtractorError):
            await extractor.extract(public_item())

        trace = extractor.traces[0]
        self.assertFalse(trace.success)
        self.assertEqual(trace.failure_reason, "schema_validation")
        self.assertEqual(len(trace.attempts), 2)

    async def test_schema_failure_records_sanitized_field_diagnostics(self) -> None:
        def invalid_claim_error() -> ValidationError:
            try:
                SpeechExtractionBatch.model_validate(
                    {
                        "items": [
                            {
                                "item_id": "speech-1",
                                "claims": [
                                    {
                                        "kind": "check_claim",
                                        "target": 1,
                                        "night": 0,
                                        "result": "wolf",
                                        "summary": "x" * 100,
                                        "supporting_text": "查验1号是狼人",
                                    },
                                ],
                            },
                        ],
                    },
                )
            except ValidationError as error:
                return error
            raise AssertionError("expected validation error")

        model = StubStructuredModel([invalid_claim_error(), invalid_claim_error()])
        extractor = AgentScopePublicClaimExtractor(
            model,
            model_config_for(ModelProfile.TEST),
        )

        with self.assertRaises(PublicClaimExtractorError):
            await extractor.extract(public_item())

        issues = extractor.traces[0].attempts[0].validation_issues
        self.assertGreaterEqual(len(issues), 2)
        self.assertTrue(any("night" in issue.location for issue in issues))
        self.assertTrue(any("summary" in issue.location for issue in issues))
        self.assertTrue(all(len(issue.rejected_input or "") <= 500 for issue in issues))

    async def test_request_failure_does_not_trigger_schema_repair(self) -> None:
        model = StubStructuredModel([OSError("network unavailable")])
        extractor = AgentScopePublicClaimExtractor(
            model,
            model_config_for(ModelProfile.TEST),
        )

        with self.assertRaises(PublicClaimExtractorError):
            await extractor.extract(public_item())

        self.assertEqual(len(model.calls), 1)
        self.assertEqual(extractor.traces[0].failure_reason, "request_exception")


if __name__ == "__main__":
    unittest.main()
