"""Deterministic minimal decisions used only after an audited model failure."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from .schemas import (
    AgentDecisionInput,
    DecisionTask,
    SeerTargetTaskObservation,
    WitchActionTaskObservation,
    WolfTargetTaskObservation,
)


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
            "reason": "模型调用失败，本轮弃票。",
            "confidence": 0.0,
        }
    elif task is DecisionTask.SHERIFF_SIGNUP:
        payload = {
            "action": "sheriff_signup",
            "signup": False,
            "reason": "模型调用失败，本轮不上警。",
            "confidence": 0.0,
        }
    elif task is DecisionTask.SHERIFF_CAMPAIGN:
        payload = {
            "action": "sheriff_campaign",
            "speech": f"{seat}号竞选警长，希望通过发言和票型整理公开信息。",
            "intent": "模型调用失败后的最小竞选发言",
            "confidence": 0.0,
        }
    elif task is DecisionTask.SHERIFF_WITHDRAWAL:
        payload = {
            "action": "sheriff_withdrawal",
            "withdraw": False,
            "reason": "模型调用失败，维持原竞选选择。",
            "confidence": 0.0,
        }
    elif task is DecisionTask.SHERIFF_VOTE:
        payload = {
            "action": "sheriff_vote",
            "target": None,
            "reason": "模型调用失败，本轮弃票。",
            "confidence": 0.0,
        }
    elif task is DecisionTask.WOLF_TARGET:
        observation = decision_input.observation
        if not isinstance(observation, WolfTargetTaskObservation):
            raise TypeError("wolf fallback requires wolf target observation")
        non_wolves = [
            target
            for target in observation.eligible_targets
            if target not in observation.wolf_seats
        ]
        payload = {
            "action": "wolf_target",
            "target": (non_wolves or list(observation.eligible_targets))[0],
            "reason": "模型调用失败，使用确定性合法刀口。",
            "confidence": 0.0,
        }
    elif task is DecisionTask.SEER_TARGET:
        observation = decision_input.observation
        if not isinstance(observation, SeerTargetTaskObservation):
            raise TypeError("seer fallback requires seer target observation")
        payload = {
            "action": "seer_target",
            "target": observation.eligible_targets[0],
            "reason": "模型调用失败，使用确定性合法查验目标。",
            "confidence": 0.0,
        }
    elif task is DecisionTask.WITCH_ACTION:
        observation = decision_input.observation
        if not isinstance(observation, WitchActionTaskObservation):
            raise TypeError("witch fallback requires witch action observation")
        payload = {
            "action": "pass",
            "target": None,
            "reason": "模型调用失败，保留药物并安全过夜。",
            "confidence": 0.0,
        }
    else:  # pragma: no cover - protects future enum extensions
        raise ValueError(f"no safe fallback for task: {task}")
    return output_schema.model_validate(payload)
