"""Render an authorized player snapshot into one stateless model request."""

from __future__ import annotations

import json

from wolfscope.agents.schemas import (
    AgentDecisionInput,
    DecisionTask,
    PlayerContext,
    SheriffCampaignTaskObservation,
    SheriffSignupTaskObservation,
    SheriffVoteTaskObservation,
    SheriffWithdrawalTaskObservation,
    SeerTargetTaskObservation,
    SpeechTaskObservation,
    VoteTaskObservation,
    VoteContextMode,
    WitchActionTaskObservation,
    WolfTargetTaskObservation,
)


STATIC_RULES = """本局采用标准九人屠边规则：3狼人、3平民、预言家、女巫、猎人。
好人消灭全部狼人获胜；狼人消灭全部神职或全部平民获胜。
预言家每晚（包括第一夜）查验一名玩家，第一天可以合法报告首夜结果。
女巫有一瓶解药和一瓶毒药；只能救当夜刀口，不能毒自己。猎人被刀或被放逐可以开枪，被毒不能开枪。
狼人知道队友、每夜必须选择一个合法刀口且可以自刀；白天可以撒谎、悍跳和伪造查验。
公开身份、查验、阵营和投票表达都只是发言者声明；只有当前玩家收到的私人事实才是确认信息。
第一天夜间技能后进行警长竞选，再公布死亡；后续按夜晚、公布死亡、白天发言、同时投票循环。警长拥有1.5票，平票会进入PK和一次重投。"""


SYSTEM_PROMPT = f"""你正在参加一局标准九人狼人杀。
{STATIC_RULES}
你只能依据本次输入中的玩家视角行动；不得假设或索取上帝信息。
游戏引擎负责规则与合法性判断，你只负责当前座位的一次决策。
请保持角色目标一致。精简投影未提供事件明细时，event_ids 必须为空；结构化依据优先使用 evidence_ids。
EvidenceContext 中 epistemic_status=verified 是当前玩家确认的事实，rule_derivations 是规则必然推导，epistemic_status=claimed 只表示有人公开声称、绝不等于真实。
SituationBrief 是从当前玩家证据确定性生成的局势索引，不是投票建议。
StrategyBrief 只提供粗颗粒度目标、方法和风险提醒，不是行动命令；实际采用的策略写入 strategy_ids。
若决策实际依赖 EvidenceContext，请在 evidence_ids 中引用本玩家的证据 ID；不要编造或引用其他玩家的证据 ID。
只提交指定的结构化结果，不输出隐藏思维链。"""


def render_decision_prompt(
    decision_input: AgentDecisionInput,
    task: DecisionTask,
) -> str:
    """Serialize the already-authorized input without reading GameState."""

    observation_task = DecisionTask(decision_input.observation.task)
    if observation_task is not task:
        raise ValueError("requested task must match decision observation")
    task_text = {
        DecisionTask.SPEECH: "完成当前白天发言；仅在允许且确有必要时选择自爆。",
        DecisionTask.VOTE: (
            "从 candidates 中选择放逐目标。有合理怀疑对象时应正常投票；"
            "只有信息严重不足时才提交 target=null 弃票。"
        ),
        DecisionTask.SHERIFF_SIGNUP: "决定是否参加第一天警长竞选。",
        DecisionTask.SHERIFF_CAMPAIGN: "完成警长竞选发言，说明竞选立场和组织信息的方法。",
        DecisionTask.SHERIFF_WITHDRAWAL: "听完全部竞选发言后决定是否退水。",
        DecisionTask.SHERIFF_VOTE: "从 candidates 中选择警长；判断不足时可以弃票。",
        DecisionTask.WOLF_TARGET: "代表当前存活狼队选择今晚唯一合法刀口；允许战术性自刀。",
        DecisionTask.SEER_TARGET: "选择今晚的合法查验目标，不能查验自己或重复查验。",
        DecisionTask.WITCH_ACTION: "根据今晚刀口和剩余药物选择过夜、救人或毒人。",
    }[task]
    payload = _model_payload(decision_input)
    rendered_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"""当前任务：{task_text}

以下 JSON 是从完整授权视图生成的去重决策投影。player_context 是当前玩家状态，task_context 是当前合法任务，evidence_context 是证据，situation_brief 是结构化局势：
{rendered_payload}

请根据指定 Schema 返回一次决策。`intent` 或 `reason` 只写简洁可审计依据，在 evidence_ids 和 strategy_ids 中列出实际使用的证据与策略；不要输出逐步思维过程。"""


def _model_payload(decision_input: AgentDecisionInput) -> dict:
    observation = decision_input.observation
    if isinstance(observation, SpeechTaskObservation):
        task_context = {
            "task": "speech",
            "speaking_order": observation.speaking_order,
            "previous_speeches": observation.previous_speeches,
            "can_explode": observation.can_explode,
        }
    elif isinstance(observation, VoteTaskObservation):
        task_context = {
            "task": "vote",
            "vote_round": observation.vote_round.value,
            "candidates": observation.candidates,
        }
        if decision_input.vote_context_mode is not VoteContextMode.COMPACT:
            task_context["speeches"] = observation.speeches
    elif isinstance(observation, SheriffSignupTaskObservation):
        task_context = {
            "task": observation.task,
            "eligible_seats": observation.eligible_seats,
        }
    elif isinstance(observation, SheriffCampaignTaskObservation):
        task_context = {
            "task": observation.task,
            "candidates": observation.candidates,
            "previous_speeches": observation.previous_speeches,
        }
    elif isinstance(observation, SheriffWithdrawalTaskObservation):
        task_context = {
            "task": observation.task,
            "candidates": observation.candidates,
            "campaign_speeches": observation.campaign_speeches,
        }
    elif isinstance(observation, SheriffVoteTaskObservation):
        task_context = {
            "task": observation.task,
            "candidates": observation.candidates,
            "campaign_speeches": observation.campaign_speeches,
            "withdrawn": observation.withdrawn,
        }
    elif isinstance(observation, WolfTargetTaskObservation):
        task_context = {
            "task": observation.task,
            "wolf_seats": observation.wolf_seats,
            "eligible_targets": observation.eligible_targets,
            "coordinator_rule": "当前 actor 是存活狼队中座位号最小者，代表狼队提交本夜唯一刀口。",
        }
    elif isinstance(observation, SeerTargetTaskObservation):
        task_context = {
            "task": observation.task,
            "checked_seats": observation.checked_seats,
            "eligible_targets": observation.eligible_targets,
        }
    elif isinstance(observation, WitchActionTaskObservation):
        task_context = {
            "task": observation.task,
            "night_victim": observation.night_victim,
            "antidote_available": observation.antidote_available,
            "poison_available": observation.poison_available,
            "can_save": observation.can_save,
            "poison_targets": observation.poison_targets,
        }
    else:  # pragma: no cover - discriminated union protects this boundary
        raise TypeError("unsupported task observation")

    evidence_context = None
    if decision_input.evidence_context is not None:
        evidence_context = decision_input.evidence_context.model_dump(
            mode="json",
            exclude={
                "owner",
                "ledger_revision",
                *(
                    {"public_claims"}
                    if decision_input.vote_context_mode
                    in {VoteContextMode.BALANCED, VoteContextMode.COMPACT}
                    else set()
                ),
            },
        )

    situation_brief = None
    if decision_input.decision_brief is not None:
        situation_brief = decision_input.decision_brief.model_dump(
            mode="json",
            exclude={"owner", "day", "task", "ledger_revision", "belief_revision"},
        )

    strategy_brief = None
    if decision_input.strategy_brief is not None:
        strategy_brief = decision_input.strategy_brief.model_dump(
            mode="json",
            exclude={"owner", "day", "task", "role"},
        )

    return {
        "player_context": PlayerContext.from_view(
            decision_input.player_view,
        ).model_dump(mode="json"),
        "task_context": task_context,
        "evidence_context": evidence_context,
        "situation_brief": situation_brief,
        "strategy_brief": strategy_brief,
        "vote_context_mode": decision_input.vote_context_mode.value,
    }
