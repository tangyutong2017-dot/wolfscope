from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from wolfscope.agents.schemas import DecisionTask, SpeechDecision
from wolfscope.models.agentscope_gateway import AgentScopeModelGateway
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.gateway import ModelGatewayError

from tests.test_m2_runtime import speech_input


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


def valid_speech() -> StubResponse:
    return StubResponse(
        content={
            "action": "speak",
            "speech": "4号认为当前信息不足，先听后置位发言。",
            "intent": "保留判断并公开当前立场",
            "confidence": 0.55,
        },
        usage=StubUsage(input_tokens=240, output_tokens=48),
    )


class AgentScopeGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_renders_only_authorized_snapshot_and_tracks_usage(self) -> None:
        model = StubStructuredModel([valid_speech()])
        gateway = AgentScopeModelGateway(model)

        result = await gateway.structured_call(
            player=4,
            task=DecisionTask.SPEECH,
            decision_input=speech_input(),
            output_schema=SpeechDecision,
            config=model_config_for(ModelProfile.TEST),
        )

        prompt = model.calls[0][0][1].get_text_content()
        system_prompt = model.calls[0][0][0].get_text_content()
        self.assertIn("包括第一夜", system_prompt)
        self.assertIn("被毒不能开枪", system_prompt)
        self.assertIn("1号公开发言", prompt)
        self.assertIn('"player_context"', prompt)
        self.assertIn('"task_context"', prompt)
        self.assertNotIn('"player_view"', prompt)
        self.assertNotIn('"public_summary"', prompt)
        self.assertNotIn('"actor"', prompt)
        self.assertNotIn('"visible_events"', prompt)
        self.assertNotIn("隐藏身份信息", prompt)
        self.assertNotIn("god_fact", prompt)
        self.assertEqual(result.record.token_usage.input_tokens, 240)
        self.assertEqual(result.record.token_usage.output_tokens, 48)
        self.assertEqual(result.record.retry_count, 0)
        self.assertEqual(result.value.action, "speak")

    async def test_retries_once_with_schema_repair_instruction(self) -> None:
        model = StubStructuredModel(
            [RuntimeError("Failed to generate structured output for model."), valid_speech()],
        )
        gateway = AgentScopeModelGateway(model)

        result = await gateway.structured_call(
            player=4,
            task=DecisionTask.SPEECH,
            decision_input=speech_input(),
            output_schema=SpeechDecision,
            config=model_config_for(ModelProfile.TEST),
        )

        self.assertEqual(len(model.calls), 2)
        repair_prompt = model.calls[1][0][-1].get_text_content()
        self.assertIn("未通过结构化校验", repair_prompt)
        self.assertEqual(result.record.retry_count, 1)
        self.assertEqual(len(result.record.attempts), 2)
        self.assertEqual(
            result.record.attempts[0].failure_reason,
            "missing_structured_output",
        )
        self.assertEqual(result.record.attempts[1].stage, "schema_repair")
        self.assertTrue(result.record.attempts[1].success)

    async def test_exhausted_repair_is_auditable(self) -> None:
        model = StubStructuredModel(
            [RuntimeError("bad structure"), RuntimeError("still bad")],
        )
        gateway = AgentScopeModelGateway(model)

        with self.assertRaises(ModelGatewayError) as raised:
            await gateway.structured_call(
                player=4,
                task=DecisionTask.SPEECH,
                decision_input=speech_input(),
                output_schema=SpeechDecision,
                config=model_config_for(ModelProfile.TEST),
            )

        self.assertFalse(raised.exception.record.success)
        self.assertEqual(raised.exception.record.retry_count, 1)
        self.assertEqual(raised.exception.record.error_type, "structured_output")
        self.assertEqual(raised.exception.record.failure_stage, "schema_repair")
        self.assertEqual(
            raised.exception.record.failure_reason,
            "structured_output_runtime",
        )
        self.assertEqual(len(raised.exception.record.attempts), 2)

    async def test_request_failure_is_auditable_without_schema_retry(self) -> None:
        model = StubStructuredModel([OSError("network unavailable")])
        gateway = AgentScopeModelGateway(model)

        with self.assertRaises(ModelGatewayError) as raised:
            await gateway.structured_call(
                player=4,
                task=DecisionTask.SPEECH,
                decision_input=speech_input(),
                output_schema=SpeechDecision,
                config=model_config_for(ModelProfile.TEST),
            )

        self.assertEqual(len(model.calls), 1)
        self.assertEqual(raised.exception.record.error_type, "request_error")
        self.assertEqual(raised.exception.record.failure_stage, "generation")
        self.assertEqual(raised.exception.record.failure_reason, "request_exception")
        self.assertEqual(len(raised.exception.record.attempts), 1)
        self.assertFalse(raised.exception.record.success)

    async def test_task_must_match_observation(self) -> None:
        gateway = AgentScopeModelGateway(StubStructuredModel([]))
        with self.assertRaisesRegex(ValueError, "task must match"):
            await gateway.structured_call(
                player=4,
                task=DecisionTask.VOTE,
                decision_input=speech_input(),
                output_schema=SpeechDecision,
                config=model_config_for(ModelProfile.TEST),
            )

    def test_environment_factory_fails_before_network_without_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY"):
                AgentScopeModelGateway.from_environment(
                    model_config_for(ModelProfile.TEST),
                )


if __name__ == "__main__":
    unittest.main()
