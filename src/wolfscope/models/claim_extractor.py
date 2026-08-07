"""AgentScope adapter that only parses explicit claims from public text."""

from __future__ import annotations

import os
from time import perf_counter
from typing import Any

from agentscope.credential import DeepSeekCredential
from agentscope.message import SystemMsg, UserMsg
from agentscope.model import DeepSeekChatModel
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from wolfscope.cognition.claims import (
    SpeechClaimExtraction,
    SpeechExtractionBatch,
    SpeechExtractionItem,
)
from wolfscope.cognition.extraction import PublicClaimExtractorError
from wolfscope.models.agentscope_gateway import StructuredModel
from wolfscope.models.config import DeepSeekModelConfig
from wolfscope.models.gateway import ModelAttemptRecord, TokenUsage


EXTRACTOR_VERSION = "public-claims-v2-nonthinking"
EXTRACTION_MAX_TOKENS = 2000
EXTRACTION_TEMPERATURE = 0.0

EXTRACTION_SYSTEM_PROMPT = """你是狼人杀公开发言的文本解析器，不是玩家，也不是裁判。
你只能抽取原文明确表达的内容，不得判断真假、推断身份、补充隐含信息或提供策略。
speaker 已由系统给出，不得改变发言者归属。
只抽取直接身份声称、本人查验声称、明确阵营判断、站边态度、本人投票意图和对他人的投票建议。
他人转述不能变成当前 speaker 自己的查验。
supporting_text 必须逐字取自对应发言原文，不得改写。
投票意图或投票建议的 supporting_text 必须在同一段原文中同时明确写出投票/放逐动作和目标座位；
不得从前一句继承目标，也不得把“再比较发言、继续观察、听完再定”等普通条件讨论单独标成投票 Claim。
每段发言最多提取8条最明确、互不重复的 Claim；summary 不超过60字，supporting_text 不超过80字。
每个输入 item_id 必须在输出中出现且只出现一次。没有明确 Claim 时返回空 claims。
只提交指定的结构化输出，不评价游戏表现，不输出思维过程。"""


class ValidationIssue(BaseModel):
    """Sanitized field-level validation detail safe for replay diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    location: tuple[str | int, ...] = ()
    error_type: str
    message: str
    rejected_input: str | None = None


class ExtractionAttemptRecord(ModelAttemptRecord):
    validation_issues: tuple[ValidationIssue, ...] = ()


class ExtractionTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: int = Field(ge=1)
    model_name: str
    thinking_enabled: bool = False
    temperature: float = EXTRACTION_TEMPERATURE
    max_tokens: int = EXTRACTION_MAX_TOKENS
    item_count: int = Field(ge=1)
    success: bool
    latency_ms: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    failure_reason: str | None = None
    attempts: tuple[ExtractionAttemptRecord, ...] = ()


class AgentScopePublicClaimExtractor:
    def __init__(
        self,
        model: StructuredModel,
        config: DeepSeekModelConfig,
    ) -> None:
        self._model = model
        self.config = config
        self.thinking_enabled = False
        self.temperature = EXTRACTION_TEMPERATURE
        self.max_tokens = max(config.max_tokens, EXTRACTION_MAX_TOKENS)
        self.version = f"{EXTRACTOR_VERSION}:{config.model_name}"
        self.traces: list[ExtractionTrace] = []
        self.messages: list[tuple[Any, ...]] = []

    @classmethod
    def from_environment(
        cls,
        config: DeepSeekModelConfig,
        *,
        api_key_env: str = "DEEPSEEK_API_KEY",
    ) -> AgentScopePublicClaimExtractor:
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
                max_tokens=max(config.max_tokens, EXTRACTION_MAX_TOKENS),
                thinking_enable=False,
                temperature=EXTRACTION_TEMPERATURE,
            ),
            stream=False,
            max_retries=config.request_max_retries,
            client_kwargs={"timeout": config.request_timeout_seconds},
        )
        return cls(model, config)

    async def extract(
        self,
        items: tuple[SpeechExtractionItem, ...],
    ) -> tuple[SpeechClaimExtraction, ...]:
        if not items:
            return ()
        messages = [
            SystemMsg(name="claim_extractor", content=EXTRACTION_SYSTEM_PROMPT),
            UserMsg(
                name="public_speech_batch",
                content=(
                    "请只解析以下公开发言 JSON：\n"
                    + SpeechExtractionRequest(items=items).model_dump_json(indent=2)
                ),
            ),
        ]
        self.messages.append(tuple(messages))
        started = perf_counter()
        attempt_records: list[ExtractionAttemptRecord] = []
        attempts = self.config.schema_repair_attempts + 1
        for attempt in range(attempts):
            attempt_started = perf_counter()
            call_messages = list(messages)
            stage = "generation" if attempt == 0 else "schema_repair"
            if attempt:
                call_messages.append(
                    UserMsg(
                        name="extractor_validator",
                        content=(
                            "上一次结果未通过结构化校验。请只按 "
                            "SpeechExtractionBatch Schema 重新提交文本解析结果。"
                        ),
                    ),
                )
            try:
                response = await self._model.generate_structured_output(
                    call_messages,
                    SpeechExtractionBatch,
                )
                batch = SpeechExtractionBatch.model_validate(response.content)
            except (RuntimeError, ValueError) as error:
                attempt_records.append(
                    ExtractionAttemptRecord(
                        attempt_index=attempt + 1,
                        stage=stage,
                        success=False,
                        latency_ms=_elapsed_ms(attempt_started),
                        failure_reason=_failure_reason(error),
                        validation_issues=_validation_issues(error),
                    ),
                )
                continue
            except Exception as error:
                attempt_records.append(
                    ExtractionAttemptRecord(
                        attempt_index=attempt + 1,
                        stage=stage,
                        success=False,
                        latency_ms=_elapsed_ms(attempt_started),
                        failure_reason="request_exception",
                    ),
                )
                self.traces.append(
                    ExtractionTrace(
                        call_id=len(self.traces) + 1,
                        model_name=self.config.model_name,
                        thinking_enabled=self.thinking_enabled,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        item_count=len(items),
                        success=False,
                        latency_ms=_elapsed_ms(started),
                        retry_count=0,
                        failure_reason="request_exception",
                        attempts=tuple(attempt_records),
                    ),
                )
                raise PublicClaimExtractorError(
                    "public claim extractor request failed",
                ) from error
            usage = _usage(response)
            attempt_records.append(
                ExtractionAttemptRecord(
                    attempt_index=attempt + 1,
                    stage=stage,
                    success=True,
                    latency_ms=_elapsed_ms(attempt_started),
                    token_usage=usage,
                ),
            )
            self.traces.append(
                ExtractionTrace(
                    call_id=len(self.traces) + 1,
                    model_name=self.config.model_name,
                    thinking_enabled=self.thinking_enabled,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    item_count=len(items),
                    success=True,
                    latency_ms=_elapsed_ms(started),
                    retry_count=attempt,
                    token_usage=usage,
                    attempts=tuple(attempt_records),
                ),
            )
            return batch.items

        reason = attempt_records[-1].failure_reason
        self.traces.append(
            ExtractionTrace(
                call_id=len(self.traces) + 1,
                model_name=self.config.model_name,
                thinking_enabled=self.thinking_enabled,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                item_count=len(items),
                success=False,
                latency_ms=_elapsed_ms(started),
                retry_count=attempts - 1,
                failure_reason=reason,
                attempts=tuple(attempt_records),
            ),
        )
        raise PublicClaimExtractorError("public claim extraction failed")


class SpeechExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[SpeechExtractionItem, ...]


def _usage(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    return TokenUsage(
        input_tokens=getattr(usage, "input_tokens", 0),
        output_tokens=getattr(usage, "output_tokens", 0),
    )


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _failure_reason(error: Exception) -> str:
    text = str(error).lower()
    if "generate structured output" in text:
        return "missing_structured_output"
    if "completed response" in text or "empty" in text:
        return "empty_response"
    return "schema_validation"


def _validation_issues(error: Exception) -> tuple[ValidationIssue, ...]:
    """Extract bounded Pydantic diagnostics without retaining raw responses."""

    validation_error = _find_validation_error(error)
    if validation_error is None:
        return ()
    issues: list[ValidationIssue] = []
    for detail in validation_error.errors(include_url=False):
        issues.append(
            ValidationIssue(
                location=tuple(detail.get("loc", ())),
                error_type=str(detail.get("type", "validation_error")),
                message=_bounded_text(detail.get("msg", "validation failed"), 240),
                rejected_input=_safe_input_summary(detail.get("input")),
            ),
        )
    return tuple(issues[:12])


def _find_validation_error(error: Exception) -> ValidationError | None:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, ValidationError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _safe_input_summary(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return _bounded_text(value, 240)
    if isinstance(value, dict):
        safe = {
            str(key): _bounded_text(item, 80)
            for key, item in list(value.items())[:12]
            if str(key).lower() not in {"api_key", "authorization", "token"}
        }
        return _bounded_text(safe, 500)
    if isinstance(value, (list, tuple)):
        return _bounded_text(list(value)[:12], 500)
    return f"<{type(value).__name__}>"


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"
