"""Deterministic minimal decisions used only after an audited model failure."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from .schemas import AgentDecisionInput, DecisionTask


TModel = TypeVar("TModel", bound=BaseModel)


def safe_fallback_decision(
    *,
    task: DecisionTask,
    decision_input: AgentDecisionInput,
    output_schema: type[TModel],
) -> TModel:
    """Return a legal, deterministic no-strategy action for public M2 tasks."""

    seat = decision_input.player_view.viewer_seat
    if task is DecisionTask.SPEECH:
        payload = {
            "action": "speak",
            "speech": f"{seat}号本轮暂时没有新增信息，继续听取其他玩家发言。",
            "intent": "模型调用失败后的最小公开发言",
            "confidence": 0.0,
        }
    elif task is DecisionTask.VOTE:
        payload = {
            "action": "vote",
            "target": None,
            "public_reason": "模型调用失败，本轮弃票。",
            "confidence": 0.0,
        }
    else:  # pragma: no cover - protects future enum extensions
        raise ValueError(f"no safe fallback for task: {task}")
    return output_schema.model_validate(payload)
