from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from wolfscope.agents.schemas import (
    ComplexityLevel,
    DecisionTask,
    SpeechDecision,
    VoteDecision,
)
from wolfscope.models.agentscope_gateway import AgentScopeModelGateway
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.gateway import ModelGatewayError

from tests.test_m2_runtime import speech_input, vote_input


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


def valid_speech_repair() -> StubResponse:
    return StubResponse(
        content={
            "action": "speak",
            "speech": "4号认为当前信息不足，先听后置位发言。",
            "intent": "保留判断并公开当前立场",
            "strategy_ids": [],
        },
        usage=StubUsage(input_tokens=90, output_tokens=30),
    )


class AgentScopeGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_routine_vote_uses_nonthinking_model_on_first_attempt(self) -> None:
        model = StubStructuredModel([])
        nonthinking_model = StubStructuredModel(
            [
                StubResponse(
                    content={
                        "target": 1,
                        "confidence": 0.6,
                        "reason": "当前更怀疑1号",
                    },
                    usage=StubUsage(input_tokens=100, output_tokens=20),
                ),
            ],
        )
        gateway = AgentScopeModelGateway(model, nonthinking_model)

        result = await gateway.structured_call(
            player=4,
            task=DecisionTask.VOTE,
            decision_input=vote_input(),
            output_schema=VoteDecision,
            config=model_config_for(ModelProfile.TEST),
        )

        self.assertEqual(len(model.calls), 0)
        self.assertEqual(len(nonthinking_model.calls), 1)
        transport_schema = nonthinking_model.calls[0][1]
        self.assertIsInstance(transport_schema, dict)
        self.assertEqual(
            transport_schema["properties"]["target"]["enum"],
            [1, 7, None],
        )
        self.assertFalse(result.record.thinking_enabled)
        self.assertFalse(result.record.attempts[0].thinking_enabled)
        self.assertEqual(result.record.retry_count, 0)

    async def test_compact_speech_uses_nonthinking_model(self) -> None:
        model = StubStructuredModel([])
        nonthinking_model = StubStructuredModel([valid_speech()])
        gateway = AgentScopeModelGateway(model, nonthinking_model)
        decision_input = speech_input().model_copy(
            update={"complexity_level": ComplexityLevel.COMPACT},
        )

        result = await gateway.structured_call(
            player=4,
            task=DecisionTask.SPEECH,
            decision_input=decision_input,
            output_schema=SpeechDecision,
            config=model_config_for(ModelProfile.TEST),
        )

        self.assertEqual(len(model.calls), 0)
        self.assertEqual(len(nonthinking_model.calls), 1)
        self.assertFalse(result.record.thinking_enabled)

    async def test_illegal_transport_target_enters_short_repair(self) -> None:
        model = StubStructuredModel([])
        nonthinking_model = StubStructuredModel(
            [
                StubResponse(
                    content={
                        "target": 9,
                        "confidence": 0.6,
                        "reason": "错误目标",
                    },
                ),
                StubResponse(
                    content={
                        "target": 7,
                        "confidence": 0.5,
                        "reason": "改为合法目标",
                    },
                ),
            ],
        )
        gateway = AgentScopeModelGateway(model, nonthinking_model)

        result = await gateway.structured_call(
            player=4,
            task=DecisionTask.VOTE,
            decision_input=vote_input(),
            output_schema=VoteDecision,
            config=model_config_for(ModelProfile.TEST),
        )

        self.assertEqual(result.value.target, 7)
        self.assertEqual(result.record.retry_count, 1)
        self.assertEqual(
            result.record.attempts[0].failure_reason,
            "value_validation",
        )

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
            [RuntimeError("Failed to generate structured output for model.")],
        )
        repair_model = StubStructuredModel([valid_speech_repair()])
        gateway = AgentScopeModelGateway(model, repair_model)

        result = await gateway.structured_call(
            player=4,
            task=DecisionTask.SPEECH,
            decision_input=speech_input(),
            output_schema=SpeechDecision,
            config=model_config_for(ModelProfile.TEST),
        )

        self.assertEqual(len(model.calls), 1)
        self.assertEqual(len(repair_model.calls), 1)
        repair_prompt = repair_model.calls[0][0][-1].get_text_content()
        self.assertIn("最小授权信息", repair_prompt)
        self.assertEqual(result.record.retry_count, 1)
        self.assertEqual(len(result.record.attempts), 2)
        self.assertEqual(
            result.record.attempts[0].failure_reason,
            "missing_structured_output",
        )
        self.assertEqual(result.record.attempts[1].stage, "schema_repair")
        self.assertTrue(result.record.attempts[1].success)
        self.assertFalse(result.record.attempts[1].thinking_enabled)
        self.assertEqual(result.record.final_complexity_level, "l2_minimal_repair")

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

    async def test_request_failure_uses_nonthinking_repair_then_is_auditable(self) -> None:
        model = StubStructuredModel([OSError("network unavailable")])
        repair_model = StubStructuredModel([OSError("still unavailable")])
        gateway = AgentScopeModelGateway(model, repair_model)

        with self.assertRaises(ModelGatewayError) as raised:
            await gateway.structured_call(
                player=4,
                task=DecisionTask.SPEECH,
                decision_input=speech_input(),
                output_schema=SpeechDecision,
                config=model_config_for(ModelProfile.TEST),
            )

        self.assertEqual(len(model.calls), 1)
        self.assertEqual(len(repair_model.calls), 1)
        self.assertEqual(raised.exception.record.error_type, "request_error")
        self.assertEqual(raised.exception.record.failure_stage, "schema_repair")
        self.assertEqual(raised.exception.record.failure_reason, "request_exception")
        self.assertEqual(len(raised.exception.record.attempts), 2)
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
