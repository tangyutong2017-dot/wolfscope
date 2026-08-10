"""AgentScope DeepSeek adapter for strict, stateless player decisions."""

from __future__ import annotations

import os
from time import perf_counter
from typing import Any, Protocol, TypeVar, get_args

from agentscope.credential import DeepSeekCredential
from agentscope.message import Msg, SystemMsg, UserMsg
from agentscope.model import DeepSeekChatModel
from pydantic import BaseModel, ValidationError

from wolfscope.agents.prompt import (
    SYSTEM_PROMPT,
    render_decision_prompt,
    render_minimal_repair_prompt,
)
from wolfscope.agents.schemas import (
    AgentDecisionInput,
    ComplexityLevel,
    DecisionTask,
    SpeechDecision,
    SpeechRepairDecision,
)

from .config import DeepSeekModelConfig
from .gateway import (
    ModelAttemptRecord,
    ModelCallRecord,
    ModelCallResult,
    ModelGatewayError,
    TokenUsage,
)


TModel = TypeVar("TModel", bound=BaseModel)


class StructuredModel(Protocol):
    async def generate_structured_output(
        self,
        messages: list[Msg],
        structured_model: type[BaseModel] | dict,
        **kwargs: Any,
    ) -> Any:
        ...


class AgentScopeModelGateway:
    """Translate WolfScope contracts to AgentScope messages and responses."""

    def __init__(
        self,
        model: StructuredModel,
        repair_model: StructuredModel | None = None,
    ) -> None:
        self._model = model
        self._repair_model = repair_model or model
        self.records: list[ModelCallRecord] = []
        self.messages: list[tuple[Msg, ...]] = []

    _ALWAYS_NONTHINKING_TASKS = frozenset(
        {
            DecisionTask.VOTE,
            DecisionTask.SHERIFF_SIGNUP,
            DecisionTask.SHERIFF_WITHDRAWAL,
            DecisionTask.SHERIFF_VOTE,
            DecisionTask.SEER_TARGET,
            DecisionTask.WITCH_ACTION,
            DecisionTask.SPEECH_DIRECTION,
            DecisionTask.HUNTER_TARGET,
            DecisionTask.BADGE_TRANSFER,
        },
    )

    @classmethod
    def _use_thinking(
        cls,
        *,
        task: DecisionTask,
        decision_input: AgentDecisionInput,
        config: DeepSeekModelConfig,
    ) -> bool:
        """Reserve expensive reasoning for planning and consequential speech."""

        if not config.thinking_enabled or task in cls._ALWAYS_NONTHINKING_TASKS:
            return False
        if task is DecisionTask.SPEECH:
            return decision_input.complexity_level is ComplexityLevel.FULL
        return True

    @classmethod
    def from_environment(
        cls,
        config: DeepSeekModelConfig,
        *,
        api_key_env: str = "DEEPSEEK_API_KEY",
    ) -> AgentScopeModelGateway:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"missing required environment variable: {api_key_env}")
        credential = DeepSeekCredential(
            api_key=api_key,
            base_url=config.base_url,
        )
        model = DeepSeekChatModel(
            credential=credential,
            model=config.model_name,
            parameters=DeepSeekChatModel.Parameters(
                max_tokens=config.max_tokens,
                thinking_enable=config.thinking_enabled,
                temperature=config.temperature,
            ),
            stream=False,
            max_retries=config.request_max_retries,
            client_kwargs={"timeout": config.request_timeout_seconds},
        )
        repair_model = DeepSeekChatModel(
            credential=credential,
            model=config.model_name,
            parameters=DeepSeekChatModel.Parameters(
                max_tokens=config.max_tokens,
                thinking_enable=False,
                temperature=0.0,
            ),
            stream=False,
            max_retries=config.request_max_retries,
            client_kwargs={"timeout": config.request_timeout_seconds},
        )
        return cls(model, repair_model)

    async def structured_call(
        self,
        *,
        player: int,
        task: DecisionTask,
        decision_input: AgentDecisionInput,
        output_schema: type[TModel],
        config: DeepSeekModelConfig,
    ) -> ModelCallResult:
        messages = self._messages(decision_input, task)
        self.messages.append(tuple(messages))
        started = perf_counter()
        last_error: Exception | None = None
        attempt_records: list[ModelAttemptRecord] = []
        attempts = config.schema_repair_attempts + 1
        initial_thinking = self._use_thinking(
            task=task,
            decision_input=decision_input,
            config=config,
        )
        for attempt in range(attempts):
            attempt_started = perf_counter()
            stage = "generation" if attempt == 0 else "schema_repair"
            call_messages = list(messages)
            if attempt:
                call_messages = [
                    SystemMsg(
                        name="game_master",
                        content="你正在修复一次狼人杀决策。只提交指定结构，不输出思维过程。",
                    ),
                    UserMsg(
                        name="engine",
                        content=render_minimal_repair_prompt(decision_input, task),
                    ),
                ]
            try:
                active_model = (
                    self._model
                    if attempt == 0 and initial_thinking
                    else self._repair_model
                )
                active_schema = (
                    SpeechRepairDecision
                    if attempt and output_schema is SpeechDecision
                    else self._transport_schema(output_schema, decision_input)
                )
                response = await active_model.generate_structured_output(
                    call_messages,
                    active_schema,
                    max_tokens=config.max_tokens,
                )
                self._validate_transport_target(response.content, active_schema)
                if active_schema is SpeechRepairDecision:
                    repaired = SpeechRepairDecision.model_validate(response.content)
                    value = output_schema.model_validate(
                        {
                            **repaired.model_dump(),
                            "confidence": 0.5,
                            "event_ids": (),
                            "evidence_ids": (),
                        },
                    )
                else:
                    value = output_schema.model_validate(response.content)
            except (ValidationError, RuntimeError, ValueError) as error:
                last_error = error
                attempt_records.append(
                    ModelAttemptRecord(
                        attempt_index=attempt + 1,
                        stage=stage,
                        success=False,
                        latency_ms=self._elapsed_ms(attempt_started),
                        failure_reason=self._failure_reason(error),
                        thinking_enabled=initial_thinking if attempt == 0 else False,
                    ),
                )
                continue
            except Exception as error:
                failure_reason = "request_exception"
                attempt_records.append(
                    ModelAttemptRecord(
                        attempt_index=attempt + 1,
                        stage=stage,
                        success=False,
                        latency_ms=self._elapsed_ms(attempt_started),
                        failure_reason=failure_reason,
                        thinking_enabled=initial_thinking if attempt == 0 else False,
                    ),
                )
                last_error = error
                continue

            usage = self._usage(response)
            attempt_records.append(
                ModelAttemptRecord(
                    attempt_index=attempt + 1,
                    stage=stage,
                    success=True,
                    latency_ms=self._elapsed_ms(attempt_started),
                    token_usage=usage,
                    thinking_enabled=initial_thinking if attempt == 0 else False,
                ),
            )
            record = self._record(
                player=player,
                task=task,
                config=config,
                thinking_enabled=initial_thinking,
                response=response,
                started=started,
                success=True,
                retry_count=attempt,
                attempts=tuple(attempt_records),
                initial_complexity_level=decision_input.complexity_level,
                complexity_reason=decision_input.complexity_reason,
            )
            self.records.append(record)
            return ModelCallResult(value=value, record=record)

        last_attempt = attempt_records[-1]
        request_failure = last_attempt.failure_reason == "request_exception"
        record = self._record(
            player=player,
            task=task,
            config=config,
            thinking_enabled=initial_thinking,
            response=None,
            started=started,
            success=False,
            retry_count=attempts - 1,
            error_type="request_error" if request_failure else "structured_output",
            failure_stage=last_attempt.stage,
            failure_reason=last_attempt.failure_reason,
            attempts=tuple(attempt_records),
            initial_complexity_level=decision_input.complexity_level,
            complexity_reason=decision_input.complexity_reason,
        )
        self.records.append(record)
        message = (
            "AgentScope model request failed"
            if request_failure
            else "AgentScope structured output failed"
        )
        raise ModelGatewayError(message, record) from last_error

    @staticmethod
    def _transport_schema(
        output_schema: type[TModel],
        decision_input: AgentDecisionInput,
    ) -> type[TModel] | dict:
        """Narrow target fields to the legal choices in this exact turn."""

        observation = decision_input.observation
        choices = getattr(observation, "candidates", None)
        if choices is None:
            choices = getattr(observation, "eligible_targets", None)
        if choices is None or "target" not in output_schema.model_fields:
            return output_schema
        values = list(choices)
        if type(None) in get_args(output_schema.model_fields["target"].annotation):
            values.append(None)
        schema = output_schema.model_json_schema()
        target_schema = schema["properties"]["target"]
        schema["properties"]["target"] = {
            "title": target_schema.get("title", "Target"),
            "enum": values,
        }
        return schema

    @staticmethod
    def _validate_transport_target(content: Any, schema: type[TModel] | dict) -> None:
        """Keep fake/custom gateways subject to the same enum as AgentScope."""

        if not isinstance(schema, dict) or not isinstance(content, dict):
            return
        target_schema = schema.get("properties", {}).get("target", {})
        allowed = target_schema.get("enum")
        if allowed is not None and content.get("target") not in allowed:
            raise ValueError("target is outside the legal choices for this turn")

    @staticmethod
    def _messages(
        decision_input: AgentDecisionInput,
        task: DecisionTask,
    ) -> list[Msg]:
        return [
            SystemMsg(name="game_master", content=SYSTEM_PROMPT),
            UserMsg(
                name=f"player_{decision_input.player_view.viewer_seat}",
                content=render_decision_prompt(decision_input, task),
            ),
        ]

    def _record(
        self,
        *,
        player: int,
        task: DecisionTask,
        config: DeepSeekModelConfig,
        thinking_enabled: bool,
        response: Any,
        started: float,
        success: bool,
        retry_count: int,
        error_type: str | None = None,
        failure_stage: str | None = None,
        failure_reason: str | None = None,
        attempts: tuple[ModelAttemptRecord, ...] = (),
        initial_complexity_level: ComplexityLevel = ComplexityLevel.FULL,
        complexity_reason: str = "default_full",
    ) -> ModelCallRecord:
        usage = self._usage(response)
        return ModelCallRecord(
            call_id=len(self.records) + 1,
            player=player,
            task=task,
            model_name=config.model_name,
            thinking_enabled=thinking_enabled,
            success=success,
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            retry_count=retry_count,
            token_usage=usage,
            error_type=error_type,
            failure_stage=failure_stage,
            failure_reason=failure_reason,
            attempts=attempts,
            initial_complexity_level=initial_complexity_level.value,
            final_complexity_level=(
                ComplexityLevel.MINIMAL_REPAIR.value
                if retry_count > 0 and success
                else initial_complexity_level.value
            ),
            complexity_reason=complexity_reason,
        )

    @staticmethod
    def _usage(response: Any) -> TokenUsage:
        usage = getattr(response, "usage", None)
        return TokenUsage(
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, round((perf_counter() - started) * 1000))

    @staticmethod
    def _failure_reason(error: Exception) -> str:
        if isinstance(error, ValidationError):
            return "schema_validation"
        if isinstance(error, ValueError) and not isinstance(error, RuntimeError):
            return "value_validation"
        message = str(error).lower()
        if "failed to generate structured output" in message:
            return "missing_structured_output"
        if "completed response" in message or "empty" in message:
            return "empty_response"
        return "structured_output_runtime"
