"""Coarse, deterministic role strategy hints for one public decision."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from wolfscope.contracts import PlayerView, Seat, StrictModel
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


class WolfPosture(StrEnum):
    CLAIMANT = "claimant"
    SUPPORT = "support"
    DISTANCE = "distance"
    HIDE = "hide"


class WolfAssignment(StrictModel):
    seat: Seat
    posture: WolfPosture


class SituationTag(StrEnum):
    """Small deterministic facts used to select strategies, never conclusions."""

    SINGLE_SEER_CLAIM = "single_seer_claim"
    MULTIPLE_SEER_CLAIMS = "multiple_seer_claims"
    SELF_UNDER_PRESSURE = "self_under_pressure"
    CLAIMED_WOLF_EXISTS = "claimed_wolf_exists"
    ROLE_CLAIM_CONFLICT = "role_claim_conflict"
    VOTE_BEHAVIOR_CONFLICT = "vote_behavior_conflict"
    EARLY_GAME = "early_game"
    MID_GAME = "mid_game"
    ENDGAME_PRESSURE = "endgame_pressure"
    SELF_RECEIVED_WOLF_CHECK = "self_received_wolf_check"
    SELF_RECEIVED_GOOD_CHECK = "self_received_good_check"
    TEAMMATE_UNDER_PRESSURE = "teammate_under_pressure"
    CLAIMANT_IS_TEAMMATE = "claimant_is_teammate"


WOLF_PRIVATE_SITUATION_TAGS = {
    SituationTag.TEAMMATE_UNDER_PRESSURE,
    SituationTag.CLAIMANT_IS_TEAMMATE,
}


class StrategySituationBuilder:
    """Derive compact observable tags without asking the model to judge truth."""

    def build(
        self,
        *,
        view: PlayerView,
        observation: Any,
        brief: DecisionBrief | None,
        wolf_team_plan: WolfTeamPlan | None,
    ) -> tuple[SituationTag, ...]:
        tags: set[SituationTag] = set()
        if view.day <= 1:
            tags.add(SituationTag.EARLY_GAME)
        elif view.day <= 3:
            tags.add(SituationTag.MID_GAME)
        alive = {player.seat for player in view.players if player.alive}
        if len(alive) <= 5:
            tags.add(SituationTag.ENDGAME_PRESSURE)
        if brief is not None:
            seer_claimants = {
                claim.speaker
                for claim in brief.role_claims
                if claim.subject == claim.speaker
                and claim.role is RoleType.SEER
                and claim.polarity.value == "assert"
            }
            if len(seer_claimants) == 1:
                tags.add(SituationTag.SINGLE_SEER_CLAIM)
            elif len(seer_claimants) > 1:
                tags.add(SituationTag.MULTIPLE_SEER_CLAIMS)
            wolf_checks = {
                check.target for check in brief.checks if check.result.value == "werewolf"
            }
            good_checks = {
                check.target for check in brief.checks if check.result.value == "good"
            }
            if wolf_checks:
                tags.add(SituationTag.CLAIMED_WOLF_EXISTS)
            if view.viewer_seat in wolf_checks:
                tags.add(SituationTag.SELF_RECEIVED_WOLF_CHECK)
                tags.add(SituationTag.SELF_UNDER_PRESSURE)
            if view.viewer_seat in good_checks:
                tags.add(SituationTag.SELF_RECEIVED_GOOD_CHECK)
            conflict_kinds = {conflict.kind for conflict in brief.conflicts}
            if conflict_kinds & {"unique_role_counterclaim", "self_role_claim_conflict"}:
                tags.add(SituationTag.ROLE_CLAIM_CONFLICT)
            if "vote_behavior_conflict" in conflict_kinds:
                tags.add(SituationTag.VOTE_BEHAVIOR_CONFLICT)
        pressure_seats = set(getattr(observation, "tied_seats", ()))
        if view.viewer_seat in pressure_seats:
            tags.add(SituationTag.SELF_UNDER_PRESSURE)
        if view.own_role is RoleType.WEREWOLF:
            teammates = set(view.own_role_state.teammate_seats)
            if teammates & pressure_seats:
                tags.add(SituationTag.TEAMMATE_UNDER_PRESSURE)
            if wolf_team_plan is not None and wolf_team_plan.primary_claimant in teammates:
                tags.add(SituationTag.CLAIMANT_IS_TEAMMATE)
        return tuple(tag for tag in SituationTag if tag in tags)


class WolfTeamPlan(StrictModel):
    """Small shared private plan; it coordinates wolves without a strategy tree."""

    day: int = Field(ge=1)
    objective: Literal["hide", "seer_counterclaim", "seer_pressure", "mixed"]
    primary_claimant: Seat | None = None
    claimed_role: Literal["seer", "villager", "witch", "hunter"] | None = None
    fake_check_target: Seat | None = None
    fake_check_alignment: Literal["good", "werewolf"] | None = None
    assignments: tuple[WolfAssignment, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def claim_and_assignments_are_coherent(self):
        seats = tuple(item.seat for item in self.assignments)
        if len(seats) != len(set(seats)):
            raise ValueError("wolf assignments cannot repeat a seat")
        claimants = tuple(
            item.seat
            for item in self.assignments
            if item.posture is WolfPosture.CLAIMANT
        )
        if self.primary_claimant is None:
            if any(
                value is not None
                for value in (
                    self.claimed_role,
                    self.fake_check_target,
                    self.fake_check_alignment,
                )
            ):
                raise ValueError("a no-claim plan cannot contain claim details")
            if claimants:
                raise ValueError("a no-claim plan cannot assign a claimant")
        else:
            if self.claimed_role is None:
                raise ValueError("primary claimant requires a claimed role")
            if claimants != (self.primary_claimant,):
                raise ValueError("exactly the primary claimant must use claimant posture")
            if self.claimed_role == "seer":
                if self.fake_check_target is None or self.fake_check_alignment is None:
                    raise ValueError("seer claimant requires a complete fake check")
            elif self.fake_check_target is not None or self.fake_check_alignment is not None:
                raise ValueError("only a seer claim can contain a fake check")
        return self


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
    situation_tags: tuple[SituationTag, ...] = ()
    wolf_team_plan: WolfTeamPlan | None = None

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
        if self.role is RoleType.WEREWOLF:
            pass
        elif self.wolf_team_plan is not None:
            raise ValueError("only werewolves can receive a wolf team plan")
        if self.role is not RoleType.WEREWOLF and set(self.situation_tags) & WOLF_PRIVATE_SITUATION_TAGS:
            raise ValueError("only werewolves can receive wolf-private situation tags")
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
        situation_tags: tuple[SituationTag, ...] = (),
        wolf_team_plan: WolfTeamPlan | None = None,
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
            situation_tags=situation_tags,
            wolf_team_plan=(
                wolf_team_plan if role is RoleType.WEREWOLF else None
            ),
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
