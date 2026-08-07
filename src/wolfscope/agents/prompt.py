"""Render an authorized player snapshot into one stateless model request."""

from __future__ import annotations

import json

from wolfscope.agents.schemas import (
    AgentDecisionInput,
    DecisionTask,
    PlayerContext,
    SpeechTaskObservation,
    VoteTaskObservation,
    VoteContextMode,
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
    }[task]
    payload = _model_payload(decision_input)
    rendered_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"""当前任务：{task_text}

以下 JSON 是从完整授权视图生成的去重决策投影。player_context 是当前玩家状态，task_context 是当前合法任务，evidence_context 是证据，situation_brief 是结构化局势：
{rendered_payload}

请根据指定 Schema 返回一次决策。`intent` 或 `reason` 只写简洁可审计依据，并在 evidence_ids 中列出实际使用的结构化证据；不要输出逐步思维过程。"""


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

    return {
        "player_context": PlayerContext.from_view(
            decision_input.player_view,
        ).model_dump(mode="json"),
        "task_context": task_context,
        "evidence_context": evidence_context,
        "situation_brief": situation_brief,
        "vote_context_mode": decision_input.vote_context_mode.value,
    }
