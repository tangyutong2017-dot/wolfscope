"""Render an authorized player snapshot into one stateless model request."""

from __future__ import annotations

from wolfscope.agents.schemas import AgentDecisionInput, DecisionTask


SYSTEM_PROMPT = """你正在参加一局标准九人狼人杀。
你只能依据本次输入中的玩家视角行动；不得假设或索取上帝信息。
游戏引擎负责规则与合法性判断，你只负责当前座位的一次决策。
请保持角色目标一致，引用证据时只能使用当前视图里的本地事件 ID。
EvidenceContext 中 epistemic_status=verified 是当前玩家确认的事实，rule_derivations 是规则必然推导，epistemic_status=claimed 只表示有人公开声称、绝不等于真实。
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
    payload = decision_input.model_dump_json(indent=2)
    return f"""当前任务：{task_text}

以下 JSON 是你获准看到的完整当前快照。事件 ID 仅在本玩家视图内有效：
{payload}

请根据指定 Schema 返回一次决策。`intent` 或 `reason` 只写简洁可审计依据，并在 evidence_ids 中列出实际使用的结构化证据；不要输出逐步思维过程。"""
