"""Coarse, deterministic role strategy hints for one public decision."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from wolfscope.contracts import Seat, StrictModel
from wolfscope.game.types import RoleType

from .brief import DecisionBrief


class StrategyPriority(StrictModel):
    priority_id: str = Field(min_length=1)
    description: str = Field(min_length=1)


class StrategyMethod(StrictModel):
    method_id: str = Field(min_length=1)
    description: str = Field(min_length=1)


class StrategyWarning(StrictModel):
    warning_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()


class StrategyBrief(StrictModel):
    owner: Seat
    day: int = Field(ge=0)
    task: Literal[
        "speech",
        "vote",
        "sheriff_signup",
        "sheriff_campaign",
        "sheriff_withdrawal",
        "sheriff_vote",
        "wolf_target",
        "seer_target",
        "witch_action",
        "speech_direction",
        "pk_speech",
        "last_words",
        "death_last_words",
        "hunter_target",
        "badge_transfer",
    ]
    role: RoleType
    role_goal: str = Field(min_length=1)
    priorities: tuple[StrategyPriority, ...] = Field(max_length=3)
    methods: tuple[StrategyMethod, ...] = Field(max_length=5)
    warnings: tuple[StrategyWarning, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def ids_are_unique_and_evidence_is_local(self):
        strategy_ids = self.strategy_ids
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("StrategyBrief IDs must be unique")
        prefix = f"p{self.owner}-e"
        if any(
            not evidence_id.startswith(prefix)
            for warning in self.warnings
            for evidence_id in warning.evidence_ids
        ):
            raise ValueError("StrategyBrief cannot reference another player's evidence")
        return self

    @property
    def strategy_ids(self) -> tuple[str, ...]:
        return tuple(
            [item.priority_id for item in self.priorities]
            + [item.method_id for item in self.methods]
            + [item.warning_id for item in self.warnings]
        )


class StrategyBuilder:
    """Select a small role playbook plus observable risk flags."""

    ROLE_GOALS = {
        RoleType.WEREWOLF: "隐藏狼队身份并制造好人误判，推动屠神或屠民。",
        RoleType.VILLAGER: "利用公开信息和票型找出狼人，避免无依据分票。",
        RoleType.SEER: "准确传播真实查验，建立可信且可持续的信息中心。",
        RoleType.WITCH: "保护好人阵营并谨慎管理身份暴露与药物信息。",
        RoleType.HUNTER: "保留身份威慑，在关键时刻用公开身份或枪权帮助好人。",
    }

    ROLE_PRIORITIES = {
        RoleType.WEREWOLF: ("maintain_cover", "公开视角保持自洽，避免暴露狼队私密信息。"),
        RoleType.VILLAGER: ("compare_public_information", "比较查验声明、发言冲突与实际票型。"),
        RoleType.SEER: ("communicate_checks", "准确区分并表达自己的真实查验与公开推理。"),
        RoleType.WITCH: ("protect_witch_information", "避免无意泄露只有女巫知道的刀口或药物状态。"),
        RoleType.HUNTER: ("preserve_hunter_leverage", "通常保留身份威慑，被强推或关键轮次再考虑公开。"),
    }

    ROLE_METHODS = {
        RoleType.WEREWOLF: (
            ("choose_wolf_posture", "根据局势选择普通伪装、冲锋、倒钩或悍跳，不要机械固定打法。"),
            ("attack_information_credibility", "从信息来源、时间线和动机质疑对手，不要编造规则。"),
        ),
        RoleType.VILLAGER: (
            ("test_claim_consistency", "追问身份声明、查验逻辑和前后发言是否自洽。"),
            ("use_vote_behavior", "区分发言票向与实际票型，关注改票和集中票。"),
        ),
        RoleType.SEER: (
            ("explain_check_plan", "公布查验时说明已知结果和后续验人方向。"),
            ("handle_counterclaim", "出现对跳时比较双方查验、时间线和信息完整度。"),
        ),
        RoleType.WITCH: (
            ("hide_or_reveal_witch", "权衡生存价值和纠错收益后决定是否公开女巫身份。"),
            ("separate_witch_fact", "只在有意公开身份时使用刀口或救毒私密信息。"),
        ),
        RoleType.HUNTER: (
            ("hide_or_reveal_hunter", "权衡被推风险与身份威慑后决定是否跳猎人。"),
            ("prepare_shot_reasoning", "枪权判断优先参考查验、冲突和实际票型。"),
        ),
    }

    def build(
        self,
        *,
        owner: int,
        role: RoleType,
        day: int,
        task: Literal[
            "speech",
            "vote",
            "sheriff_signup",
            "sheriff_campaign",
            "sheriff_withdrawal",
            "sheriff_vote",
            "wolf_target",
            "seer_target",
            "witch_action",
            "speech_direction",
            "pk_speech",
            "last_words",
            "death_last_words",
            "hunter_target",
            "badge_transfer",
        ],
        situation: DecisionBrief | None = None,
    ) -> StrategyBrief:
        priority_id, priority_description = {
            "speech": ("state_useful_position", "给出有信息价值且不泄露私密来源的公开立场。"),
            "vote": ("make_auditable_vote", "在合法候选人中形成有依据的票向，信息足够时避免消极弃票。"),
            "sheriff_signup": ("assess_sheriff_value", "结合身份目标判断上警收益，不机械固定上警或警下。"),
            "sheriff_campaign": ("present_sheriff_case", "清楚说明竞选立场和后续组织信息的方法。"),
            "sheriff_withdrawal": ("reassess_candidacy", "听完全部竞选发言后重新评估继续竞选是否有利。"),
            "sheriff_vote": ("choose_sheriff_auditably", "依据竞选发言选择更适合组织白天信息的候选人。"),
            "wolf_target": ("advance_wolf_win_path", "结合屠神或屠民路线选择合法刀口，并允许战术性自刀。"),
            "seer_target": ("maximize_check_value", "优先查验能显著缩小身份空间或影响白天归票的玩家。"),
            "witch_action": ("manage_witch_resources", "结合刀口、存活结构和药物价值选择救、毒或保留。"),
            "speech_direction": ("choose_information_order", "选择更有利于比较发言和归票的信息顺序。"),
            "pk_speech": ("resolve_pk_pressure", "回应平票焦点并指出双方可核对的关键差异。"),
            "last_words": ("leave_auditable_legacy", "用遗言留下可核对的身份、信息和后续建议。"),
            "death_last_words": ("leave_auditable_legacy", "用遗言留下可核对的身份、信息和后续建议。"),
            "hunter_target": ("use_hunter_shot", "只在带人收益高于误伤风险时开枪，否则可以不开枪。"),
            "badge_transfer": ("preserve_information_leadership", "将警徽交给更可信且能组织信息的存活玩家，必要时撕毁。"),
        }[task]
        task_priority = StrategyPriority(
            priority_id=priority_id,
            description=priority_description,
        )
        role_priority = StrategyPriority(
            priority_id=self.ROLE_PRIORITIES[role][0],
            description=self.ROLE_PRIORITIES[role][1],
        )
        methods = [
            StrategyMethod(method_id=method_id, description=description)
            for method_id, description in self.ROLE_METHODS[role]
        ]
        methods.append(
            StrategyMethod(
                method_id="separate_claim_from_fact",
                description="公开声明只代表发言者观点，不把它直接当成已验证事实。",
            ),
        )
        warnings = self._warnings(role, situation)
        return StrategyBrief(
            owner=owner,
            day=day,
            task=task,
            role=role,
            role_goal=self.ROLE_GOALS[role],
            priorities=(task_priority, role_priority),
            methods=tuple(methods),
            warnings=tuple(warnings[:3]),
        )

    @staticmethod
    def _warnings(
        role: RoleType,
        situation: DecisionBrief | None,
    ) -> list[StrategyWarning]:
        warnings: list[StrategyWarning] = []
        if role in {RoleType.WEREWOLF, RoleType.SEER, RoleType.WITCH}:
            warnings.append(
                StrategyWarning(
                    warning_id="private_information_leak",
                    description="公开表达不得无意泄露仅自己或己方知道的夜间信息。",
                ),
            )
        if situation is None:
            return warnings
        if situation.checks:
            warnings.append(
                StrategyWarning(
                    warning_id="unverified_public_check",
                    description="他人公开查验仍是声明，不能当作Engine确认事实。",
                    evidence_ids=tuple(check.evidence_id for check in situation.checks[-2:]),
                ),
            )
        conflict_kinds = {conflict.kind for conflict in situation.conflicts}
        if "self_role_claim_conflict" in conflict_kinds:
            conflicts = [
                conflict
                for conflict in situation.conflicts
                if conflict.kind == "self_role_claim_conflict"
            ]
            warnings.append(
                StrategyWarning(
                    warning_id="self_claim_conflict",
                    description="存在玩家前后身份声明冲突，应要求解释而非直接判定阵营。",
                    evidence_ids=tuple(
                        evidence_id
                        for conflict in conflicts
                        for evidence_id in conflict.evidence_ids
                    )[-4:],
                ),
            )
        return warnings
