"""AgentScope DeepSeek adapter for strict, stateless player decisions."""

from __future__ import annotations

import os
from time import perf_counter
from typing import Any, Protocol, TypeVar

from agentscope.credential import DeepSeekCredential
from agentscope.message import Msg, SystemMsg, UserMsg
from agentscope.model import DeepSeekChatModel
from pydantic import BaseModel, ValidationError

from wolfscope.agents.prompt import SYSTEM_PROMPT, render_decision_prompt
from wolfscope.agents.schemas import AgentDecisionInput, DecisionTask

from .config import DeepSeekModelConfig
from .gateway import (
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

    def __init__(self, model: StructuredModel) -> None:
        self._model = model
        self.records: list[ModelCallRecord] = []
        self.messages: list[tuple[Msg, ...]] = []

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
        model = DeepSeekChatModel(
            credential=DeepSeekCredential(
                api_key=api_key,
                base_url=config.base_url,
            ),
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
        return cls(model)

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
        attempts = config.schema_repair_attempts + 1
        for attempt in range(attempts):
            call_messages = list(messages)
            if attempt:
                call_messages.append(
                    UserMsg(
                        name="engine",
                        content=(
                            "上一次输出未通过结构化校验。请重新提交完全符合 "
                            f"{output_schema.__name__} Schema 的结果，不要添加其他内容。"
                        ),
                    ),
                )
            try:
                response = await self._model.generate_structured_output(
                    call_messages,
                    output_schema,
                )
                value = output_schema.model_validate(response.content)
            except (ValidationError, RuntimeError, ValueError) as error:
                last_error = error
                continue
            except Exception as error:
                record = self._record(
                    player=player,
                    task=task,
                    config=config,
                    response=None,
                    started=started,
                    success=False,
                    retry_count=0,
                    error_type="request_error",
                )
                self.records.append(record)
                raise ModelGatewayError("AgentScope model request failed", record) from error

            record = self._record(
                player=player,
                task=task,
                config=config,
                response=response,
                started=started,
                success=True,
                retry_count=attempt,
            )
            self.records.append(record)
            return ModelCallResult(value=value, record=record)

        record = self._record(
            player=player,
            task=task,
            config=config,
            response=None,
            started=started,
            success=False,
            retry_count=attempts - 1,
            error_type="structured_output",
        )
        self.records.append(record)
        raise ModelGatewayError("AgentScope structured output failed", record) from last_error

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
        response: Any,
        started: float,
        success: bool,
        retry_count: int,
        error_type: str | None = None,
    ) -> ModelCallRecord:
        usage = getattr(response, "usage", None)
        return ModelCallRecord(
            call_id=len(self.records) + 1,
            player=player,
            task=task,
            model_name=config.model_name,
            thinking_enabled=config.thinking_enabled,
            success=success,
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            retry_count=retry_count,
            token_usage=TokenUsage(
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
            ),
            error_type=error_type,
        )
