"""Deterministic minimal decisions used only after an audited model failure."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from wolfscope.cognition.strategy import WolfPosture

from .schemas import (
    AgentDecisionInput,
    DecisionTask,
    BadgeTransferTaskObservation,
    HunterTargetTaskObservation,
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
            "team_plan": {
                "day": decision_input.player_view.day,
                "objective": "hide",
                "primary_claimant": None,
                "claimed_role": None,
                "fake_check_target": None,
                "fake_check_alignment": None,
                "assignments": [
                    {"seat": seat, "posture": WolfPosture.HIDE.value}
                    for seat in observation.wolf_seats
                ],
            },
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
    elif task is DecisionTask.SPEECH_DIRECTION:
        payload = {
            "action": "speech_direction",
            "direction": "clockwise",
            "reason": "模型调用失败，使用固定顺时针方向。",
            "confidence": 0.0,
        }
    elif task is DecisionTask.PK_SPEECH:
        payload = {
            "action": "pk_speech",
            "speech": f"{seat}号PK阶段暂时没有新增信息，请结合此前发言和票型判断。",
            "intent": "模型调用失败后的最小PK发言",
            "confidence": 0.0,
        }
    elif task in {DecisionTask.LAST_WORDS, DecisionTask.DEATH_LAST_WORDS}:
        payload = {
            "action": task.value,
            "speech": f"{seat}号没有更多遗言，请结合公开发言和票型继续判断。",
            "intent": "模型调用失败后的最小遗言",
            "confidence": 0.0,
        }
    elif task is DecisionTask.HUNTER_TARGET:
        if not isinstance(decision_input.observation, HunterTargetTaskObservation):
            raise TypeError("hunter fallback requires hunter observation")
        payload = {
            "action": "hunter_target",
            "target": None,
            "reason": "模型调用失败，为避免误伤选择不开枪。",
            "confidence": 0.0,
        }
    elif task is DecisionTask.BADGE_TRANSFER:
        if not isinstance(decision_input.observation, BadgeTransferTaskObservation):
            raise TypeError("badge fallback requires badge observation")
        payload = {
            "action": "badge_transfer",
            "target": None,
            "reason": "模型调用失败，确定性撕毁警徽。",
            "confidence": 0.0,
        }
    else:  # pragma: no cover - protects future enum extensions
        raise ValueError(f"no safe fallback for task: {task}")
    return output_schema.model_validate(payload)
