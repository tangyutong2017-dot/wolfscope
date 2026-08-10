"""Deterministic minimal decisions used only after an audited model failure."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from wolfscope.cognition.strategy import SituationTag, WolfPosture

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


def seer_badge_flow_target(decision_input: AgentDecisionInput) -> int | None:
    """Resolve the standard badge flow from the seer's ordered private checks.

    A latest good result receives the badge.  A latest wolf result is signalled
    by passing the badge to the most recent earlier living good; without one,
    the badge is destroyed.
    """

    observation = decision_input.observation
    if not isinstance(observation, BadgeTransferTaskObservation):
        raise TypeError("badge flow requires badge observation")
    eligible = set(observation.eligible_targets)
    checks = [
        event
        for event in decision_input.player_view.visible_events
        if event.event_type == "seer_result"
        and event.actor == decision_input.player_view.viewer_seat
    ]
    if not checks:
        return None
    latest = checks[-1]
    if latest.data.get("alignment") == "good":
        return latest.target if latest.target in eligible else None
    return next(
        (
            event.target
            for event in reversed(checks[:-1])
            if event.target in eligible and event.data.get("alignment") == "good"
        ),
        None,
    )


def safe_fallback_decision(
    *,
    task: DecisionTask,
    decision_input: AgentDecisionInput,
    output_schema: type[TModel],
) -> TModel:
    """Return a legal, deterministic no-strategy action for public M2 tasks."""

    seat = decision_input.player_view.viewer_seat
    if task is DecisionTask.SPEECH:
        tags = set(
            decision_input.strategy_brief.situation_tags
            if decision_input.strategy_brief is not None
            else ()
        )
        if SituationTag.SELF_RECEIVED_WOLF_CHECK in tags:
            speech = f"{seat}号不接受对我的公开查杀，请结合查验者的时间线、发言和实际票型判断。"
        elif SituationTag.MULTIPLE_SEER_CLAIMS in tags:
            speech = "当前存在预言家对跳和冲突查验，我暂不把任何一方的公开声明当作确定事实。"
        elif SituationTag.VOTE_BEHAVIOR_CONFLICT in tags:
            speech = "当前存在发言票向与实际投票不一致，相关玩家需要解释立场变化。"
        elif SituationTag.ENDGAME_PRESSURE in tags:
            speech = "当前已进入关键轮次，应减少无依据分票，并围绕可核对的查验、冲突和票型归票。"
        else:
            speech = f"{seat}号当前没有新增确定事实，会结合后续发言和实际票型判断。"
        payload = {
            "action": "speak",
            "speech": speech,
            "intent": "模型失败后的局面感知保底发言",
            "confidence": 0.0,
        }
    elif task is DecisionTask.VOTE:
        observation = decision_input.observation
        legal_candidates = set(getattr(observation, "candidates", ()))
        target = None
        strategy = decision_input.strategy_brief
        if (
            strategy is not None
            and strategy.wolf_team_plan is not None
            and strategy.wolf_team_plan.focus_target in legal_candidates
        ):
            target = strategy.wolf_team_plan.focus_target
        if target is None:
            target = next(
                (
                    event.target
                    for event in reversed(decision_input.player_view.visible_events)
                    if event.event_type == "seer_result"
                    and event.actor == seat
                    and event.target in legal_candidates
                    and event.data.get("alignment") == "werewolf"
                ),
                None,
            )
        payload = {
            "action": "vote",
            "target": target,
            "reason": (
                "模型失败后依据本人确认查验或狼队共同目标投票。"
                if target is not None
                else "模型失败且没有确定性合法依据，本轮弃票。"
            ),
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
                "focus_target": (non_wolves or list(observation.eligible_targets))[0],
                "plan_reason": "模型失败后隐藏身份并采用确定性刀口。",
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
        observation = decision_input.observation
        if not isinstance(observation, BadgeTransferTaskObservation):
            raise TypeError("badge fallback requires badge observation")
        target = None
        if decision_input.player_view.own_role.value == "seer":
            target = seer_badge_flow_target(decision_input)
        payload = {
            "action": "badge_transfer",
            "target": target,
            "reason": (
                "模型决策不符合警徽流，改为传给本夜金水或最近存活旧金水。"
                if target is not None
                else "模型决策不符合警徽流且没有合法接收者，确定性撕毁警徽。"
            ),
            "confidence": 0.0,
        }
    else:  # pragma: no cover - protects future enum extensions
        raise ValueError(f"no safe fallback for task: {task}")
    return output_schema.model_validate(payload)
