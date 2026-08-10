"""Render an authorized player snapshot into one stateless model request."""

from __future__ import annotations

import json

from wolfscope.agents.schemas import (
    AgentDecisionInput,
    BadgeTransferTaskObservation,
    DeathLastWordsTaskObservation,
    ComplexityLevel,
    DecisionTask,
    PlayerContext,
    HunterTargetTaskObservation,
    LastWordsTaskObservation,
    PkSpeechTaskObservation,
    SheriffCampaignTaskObservation,
    SheriffSignupTaskObservation,
    SheriffVoteTaskObservation,
    SheriffWithdrawalTaskObservation,
    SpeechDirectionTaskObservation,
    SeerTargetTaskObservation,
    SpeechTaskObservation,
    VoteTaskObservation,
    VoteContextMode,
    WitchActionTaskObservation,
    WolfTargetTaskObservation,
)
from wolfscope.agents.speech_policy import SpeechPolicy


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
狼人收到的 wolf_team_plan 是狼队私有协调结果，应按本人 assignment 执行悍跳、支援、倒钩或隐藏姿态；只有新事实使计划明显失效时才偏离，并在简洁依据中说明。
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
            "从 candidates 中选择放逐目标。听完本轮发言后，即使证据不充分也应比较相对怀疑并正常投票；"
            "不能仅以‘信息不足’为理由弃票。只有候选人完全无法区分且不存在任何相对依据时才提交 target=null。"
        ),
        DecisionTask.SHERIFF_SIGNUP: "决定是否参加第一天警长竞选。",
        DecisionTask.SHERIFF_CAMPAIGN: "完成警长竞选发言，说明竞选立场和组织信息的方法。",
        DecisionTask.SHERIFF_WITHDRAWAL: "听完全部竞选发言后决定是否退水。",
        DecisionTask.SHERIFF_VOTE: "从 candidates 中选择警长；判断不足时可以弃票。",
        DecisionTask.WOLF_TARGET: "代表当前存活狼队选择今晚唯一合法刀口，并制定或更新一份全体存活狼人共享的私有 team_plan。team_plan 应明确共同 focus_target、简短 plan_reason、是否安排悍跳、由谁承担，以及其他狼人的冲锋、倒钩或隐藏姿态；允许战术性自刀。",
        DecisionTask.SEER_TARGET: "选择今晚的合法查验目标，不能查验自己或重复查验。",
        DecisionTask.WITCH_ACTION: "根据今晚刀口和剩余药物选择过夜、救人或毒人。",
        DecisionTask.SPEECH_DIRECTION: "作为警长选择今天顺时针或逆时针发言，自己最后发言。",
        DecisionTask.PK_SPEECH: "完成平票PK发言，回应当前焦点并给出可核对信息。",
        DecisionTask.LAST_WORDS: "你即将因本轮放逐出局；完成最后遗言，不得描述自己未来仍会参与后续轮次。",
        DecisionTask.DEATH_LAST_WORDS: "你已在当前死亡批次中死亡；这是首夜死讯公布后、第一天白天发言前，不能等待或引用尚未发生的白天发言和票型。完成唯一一次死亡遗言，不得假设自己未来再次出局或继续行动。若你是可开枪猎人，本任务只发表遗言，不得承诺开枪、不开枪或具体目标；遗言结束后 Engine 会立即用独立任务询问枪权。",
        DecisionTask.HUNTER_TARGET: "你已经死亡且正在结算唯一一次猎人枪权；当前不能等待任何未来发言或票型，必须根据已有信息决定立即开枪或永久不开枪。残局或遗言已有明确最高怀疑目标时应优先开枪，不能笼统以误伤风险回避决定；如开枪只能选择 eligible_targets。",
        DecisionTask.BADGE_TRANSFER: "你已经死亡且正在结算警徽。若你是预言家，必须执行所有玩家都知道的标准警徽流：本夜查验为金水就传给本夜新金水；本夜查验为狼人就传给最近存活旧金水，没有存活旧金水则 target=null 撕徽。其他身份立即移交给 eligible_targets 中一人，或撕毁。",
    }[task]
    payload = _model_payload(decision_input)
    speech_limit = SpeechPolicy.limit_for(task)
    if speech_limit is not None:
        payload["speech_length"] = {
            "target_min_chars": speech_limit.target_min_chars,
            "target_max_chars": speech_limit.target_max_chars,
            "hard_max_chars": speech_limit.hard_max_chars,
            "instruction": "尽量落在建议区间内，不得超过硬上限；按中文字符计数。",
        }
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
            "previous_speeches": (
                observation.previous_speeches[-3:]
                if decision_input.complexity_level is ComplexityLevel.COMPACT
                else observation.previous_speeches
            ),
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
    elif isinstance(observation, SpeechDirectionTaskObservation):
        task_context = {
            "task": observation.task,
            "alive_seats": observation.alive_seats,
        }
    elif isinstance(observation, PkSpeechTaskObservation):
        task_context = {
            "task": observation.task,
            "tied_seats": observation.tied_seats,
            "day_speeches": observation.day_speeches,
            "previous_pk_speeches": observation.previous_pk_speeches,
        }
    elif isinstance(observation, LastWordsTaskObservation):
        task_context = {
            "task": observation.task,
            "day_speeches": observation.day_speeches,
            "votes": observation.votes,
            "revotes": observation.revotes,
        }
    elif isinstance(observation, DeathLastWordsTaskObservation):
        task_context = {
            "task": observation.task,
            "deaths": observation.deaths,
            "timing": "首夜死亡公布后、第一天白天发言前；不存在本日发言或票型。",
        }
    elif isinstance(observation, HunterTargetTaskObservation):
        task_context = {
            "task": observation.task,
            "death_cause": observation.death_cause,
            "eligible_targets": observation.eligible_targets,
            "your_last_words": observation.last_words,
            "decision_boundary": "枪权以本任务为唯一正式决定；your_last_words 只提供公开语境，不得把其中的非正式措辞当作已执行行动。",
            "information_limit": "现在立即结算，不能等待或假设尚未发生的白天发言和票型。",
        }
    elif isinstance(observation, BadgeTransferTaskObservation):
        task_context = {
            "task": observation.task,
            "eligible_targets": observation.eligible_targets,
            "hunter_target": observation.hunter_target,
        }
    else:  # pragma: no cover - discriminated union protects this boundary
        raise TypeError("unsupported task observation")

    evidence_context = None
    evidence_free_tasks = {
        "sheriff_signup",
        "sheriff_withdrawal",
        "sheriff_vote",
        "seer_target",
        "speech_direction",
    }
    if (
        decision_input.evidence_context is not None
        and observation.task not in evidence_free_tasks
    ):
        compact = decision_input.complexity_level is ComplexityLevel.COMPACT
        evidence_context = decision_input.evidence_context.model_dump(
            mode="json",
            exclude={
                "owner",
                "ledger_revision",
                *(
                    {"public_claims"}
                    if compact or decision_input.vote_context_mode
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
        "complexity_level": decision_input.complexity_level.value,
    }


def render_minimal_repair_prompt(
    decision_input: AgentDecisionInput,
    task: DecisionTask,
) -> str:
    """L2 prompt: retain legal task facts and one compact strategy only."""

    payload = _model_payload(
        decision_input.model_copy(
            update={"complexity_level": ComplexityLevel.COMPACT},
        ),
    )
    strategy = payload.get("strategy_brief") or {}
    methods = strategy.get("methods") or []
    strategy["methods"] = methods[:1]
    payload["strategy_brief"] = strategy
    payload["evidence_context"] = None
    payload["situation_brief"] = None
    payload["complexity_level"] = ComplexityLevel.MINIMAL_REPAIR.value
    return (
        "上一次完整决策没有形成合法结构。不要重新展开长篇推理。"
        "仅根据以下最小授权信息提交合法结果；不得补充未提供的事实。\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
