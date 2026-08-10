"""Coarse, deterministic role strategy hints for one public decision."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from wolfscope.contracts import PlayerView, Seat, StrictModel
from wolfscope.game.types import RoleType
from wolfscope.agents.profile import SheriffInitiative

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
    DAY_ONE_SINGLE_SEER_HIGH_TRUST = "day_one_single_seer_high_trust"
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
    OWN_CONFIRMED_WOLF_CANDIDATE = "own_confirmed_wolf_candidate"
    OWN_CONFIRMED_GOOD_CANDIDATE = "own_confirmed_good_candidate"
    PEACEFUL_NIGHT_CONFIRMS_WITCH_SAVE = "peaceful_night_confirms_witch_save"


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
        if view.ruleset == "standard-9-v1" and any(
            event.event_type == "peaceful_night" and event.day == view.day
            for event in view.visible_events
        ):
            tags.add(SituationTag.PEACEFUL_NIGHT_CONFIRMS_WITCH_SAVE)
        candidates = set(getattr(observation, "candidates", ()))
        if view.own_role is RoleType.SEER and candidates:
            for event in view.visible_events:
                if event.event_type != "seer_result" or event.actor != view.viewer_seat:
                    continue
                if event.target not in candidates:
                    continue
                if event.data.get("alignment") == "werewolf":
                    tags.add(SituationTag.OWN_CONFIRMED_WOLF_CANDIDATE)
                elif event.data.get("alignment") == "good":
                    tags.add(SituationTag.OWN_CONFIRMED_GOOD_CANDIDATE)
        if brief is not None:
            conflict_kinds = {conflict.kind for conflict in brief.conflicts}
            seer_claimants = {
                claim.speaker
                for claim in brief.role_claims
                if claim.subject == claim.speaker
                and claim.role is RoleType.SEER
                and claim.polarity.value == "assert"
            }
            if len(seer_claimants) == 1:
                tags.add(SituationTag.SINGLE_SEER_CLAIM)
                if view.day == 1 and not conflict_kinds & {
                    "unique_role_counterclaim",
                    "self_role_claim_conflict",
                }:
                    tags.add(SituationTag.DAY_ONE_SINGLE_SEER_HIGH_TRUST)
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
    focus_target: Seat | None = None
    plan_reason: str = Field(min_length=1, max_length=120)
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
        if self.objective != "hide" and self.focus_target is None:
            raise ValueError("an active wolf plan requires a focus target")
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
    sheriff_initiative: SheriffInitiative = SheriffInitiative.MEDIUM
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
        ),
        RoleType.VILLAGER: (
            ("test_claim_consistency", "追问身份声明、查验逻辑和前后发言是否自洽。"),
        ),
        RoleType.SEER: (
            ("explain_check_plan", "公布查验时说明已知结果和后续验人方向。"),
        ),
        RoleType.WITCH: (
            ("hide_or_reveal_witch", "默认隐藏女巫底牌；仅在本人受压、需要纠正假女巫或公开真实药物信息能直接自救时才考虑跳明。"),
        ),
        RoleType.HUNTER: (
            ("hide_or_reveal_hunter", "权衡被推风险与身份威慑后决定是否跳猎人。"),
        ),
    }

    SITUATION_METHODS = {
        RoleType.WEREWOLF: (
            (SituationTag.SELF_RECEIVED_WOLF_CHECK, "answer_wolf_check", "自己被公开查杀时，从公开逻辑回应来源与动机，并保持狼队分工一致。"),
            (SituationTag.TEAMMATE_UNDER_PRESSURE, "manage_teammate_pressure", "队友受压时按既定姿态选择支援、切割或隐藏，不暴露私下关系。"),
            (SituationTag.MULTIPLE_SEER_CLAIMS, "exploit_seer_conflict", "利用预言家对跳比较公开信息，按狼队分工推动可信叙事。"),
            (SituationTag.VOTE_BEHAVIOR_CONFLICT, "exploit_vote_conflict", "利用发言与票型冲突施压，但不要把冲突直接说成身份定论。"),
            (SituationTag.ENDGAME_PRESSURE, "protect_wolf_win_path", "残局优先计算屠神或屠民路径，减少与胜负无关的公开动作。"),
        ),
        RoleType.VILLAGER: (
            (SituationTag.SELF_RECEIVED_WOLF_CHECK, "answer_wolf_check", "被查杀时集中回应查验者的逻辑、时间线和团队关系，避免只重复身份表态。"),
            (SituationTag.MULTIPLE_SEER_CLAIMS, "compare_seer_claimants", "比较双方查验、警徽流、时间线和后续承诺，不因声量直接站边。"),
            (SituationTag.DAY_ONE_SINGLE_SEER_HIGH_TRUST, "provisionally_follow_single_seer", "第一天只有一名预言家声明者且没有直接矛盾时，给予其较高暂定可信度，优先沿其查验形成工作判断；这仍不是Engine身份认证。"),
            (SituationTag.SINGLE_SEER_CLAIM, "verify_single_seer", "第一天之后继续用后续查验、票型和警徽流复核单边预言家，不把声明升级为Engine认证。"),
            (SituationTag.VOTE_BEHAVIOR_CONFLICT, "use_vote_behavior", "区分公开票向与实际票型，要求冲突玩家解释变化。"),
            (SituationTag.ENDGAME_PRESSURE, "converge_endgame_vote", "残局减少无依据分票，明确比较候选人与可验证依据。"),
        ),
        RoleType.SEER: (
            (SituationTag.OWN_CONFIRMED_WOLF_CANDIDATE, "vote_own_confirmed_wolf", "合法候选中存在本人真实查杀时，投票必须优先投该查杀。"),
            (SituationTag.OWN_CONFIRMED_GOOD_CANDIDATE, "protect_own_confirmed_good", "本人真实金水不是放逐目标，不得因公开压力把票投给自己的金水。"),
            (SituationTag.SELF_UNDER_PRESSURE, "preserve_seer_information", "受压时优先完整交代真实查验和后续验人方向，避免信息随死亡丢失。"),
            (SituationTag.MULTIPLE_SEER_CLAIMS, "handle_counterclaim", "出现对跳时比较双方查验、时间线、警徽流和信息完整度。"),
            (SituationTag.SINGLE_SEER_CLAIM, "build_seer_credibility", "无人对跳时持续给出可验证查验计划，不靠身份声称要求盲信。"),
            (SituationTag.ENDGAME_PRESSURE, "focus_decisive_check", "残局围绕能改变当轮归票的查验和已知结果组织信息。"),
        ),
        RoleType.WITCH: (
            (SituationTag.SELF_UNDER_PRESSURE, "reveal_witch_for_correction", "被强推时评估公开身份与真实药物信息能否纠错和自救。"),
            (SituationTag.MULTIPLE_SEER_CLAIMS, "observe_seer_conflict_privately", "对跳局结合公开信息判断，除非主动跳身份，不用刀口或药物私密信息证明站边。"),
            (SituationTag.DAY_ONE_SINGLE_SEER_HIGH_TRUST, "provisionally_follow_single_seer", "第一天单边且无直接矛盾的预言家具有较高暂定可信度，优先沿其查验分析，同时保持女巫私密信息隔离。"),
            (SituationTag.ENDGAME_PRESSURE, "spend_witch_resources", "残局重新评估药物的即时胜负价值，避免为保留而保留。"),
        ),
        RoleType.HUNTER: (
            (SituationTag.SELF_UNDER_PRESSURE, "reveal_hunter_under_pressure", "被查杀、进PK或面临放逐时，评估公开枪权以降低误推风险。"),
            (SituationTag.MULTIPLE_SEER_CLAIMS, "compare_seer_claimants", "对跳时比较双方查验、时间线和警徽流，不提前确认任何一方。"),
            (SituationTag.DAY_ONE_SINGLE_SEER_HIGH_TRUST, "protect_provisional_single_seer", "第一天不得仅以身份尚未验证为由推、票或枪击唯一且无直接矛盾的预言家；先按高可信工作假设使用其查验。"),
            (SituationTag.VOTE_BEHAVIOR_CONFLICT, "prepare_shot_reasoning", "枪权候选优先参考查验、声明冲突与实际票型，而非单句情绪。"),
            (SituationTag.ENDGAME_PRESSURE, "use_decisive_shot", "残局枪权可能直接改变胜负；除非所有合法目标完全不可区分，否则应向已有依据下最高怀疑目标开枪。"),
        ),
    }

    DEITY_TASK_METHODS = {
        (RoleType.SEER, "sheriff_signup"): (
            "seer_must_run_for_sheriff",
            "第一天具备报名资格时应当上警，准备公开真实首夜查验并争取警徽。",
        ),
        (RoleType.SEER, "seer_target"): (
            "check_influential_unknown",
            "优先查验能明显缩小身份空间、影响下一轮站边或归票的未验玩家。",
        ),
        (RoleType.SEER, "sheriff_campaign"): (
            "campaign_with_check_flow",
            "竞选时准确公布已有查验，并给出可验证的后续验人方向与警徽处理思路。",
        ),
        (RoleType.SEER, "last_words"): (
            "leave_complete_check_legacy",
            "遗言完整留下全部真实查验、对跳关系和仍可验证的后续建议。",
        ),
        (RoleType.SEER, "death_last_words"): (
            "leave_complete_check_legacy",
            "遗言完整留下全部真实查验、对跳关系和仍可验证的后续建议。",
        ),
        (RoleType.SEER, "badge_transfer"): (
            "follow_standard_badge_flow",
            "严格执行公共警徽流：本夜验出金水就把警徽交给该新金水；本夜验出狼人就交给最近查验且仍存活的旧金水，没有存活旧金水则撕徽。",
        ),
        (RoleType.WITCH, "witch_action"): (
            "evaluate_medicine_value",
            "分别比较救人、毒人和留药对当前轮次的确定收益；不因持有药物就机械使用。",
        ),
        (RoleType.WITCH, "sheriff_campaign"): (
            "campaign_without_witch_claim",
            "没有被查杀、对跳女巫或面临立即放逐时，不得在竞选发言中主动公开女巫底牌和药物状态；以普通好人视角说明组织方法。",
        ),
        (RoleType.WITCH, "last_words"): (
            "leave_truthful_medicine_record",
            "若选择公开女巫身份，只陈述真实刀口与用药记录，并区分事实和个人判断。",
        ),
        (RoleType.WITCH, "death_last_words"): (
            "leave_truthful_medicine_record",
            "若选择公开女巫身份，只陈述真实刀口与用药记录，并区分事实和个人判断。",
        ),
        (RoleType.HUNTER, "hunter_target"): (
            "use_shot_with_best_available_basis",
            "比较已有查验、声明冲突和实际票型；遗言已有合法最高怀疑目标时保持行动一致，残局除非目标完全不可区分否则优先开枪。",
        ),
        (RoleType.HUNTER, "last_words"): (
            "separate_words_from_shot",
            "遗言只留下公开判断，不承诺枪权动作；开枪由随后独立任务决定。",
        ),
        (RoleType.HUNTER, "death_last_words"): (
            "separate_words_from_shot",
            "遗言只留下公开判断，不承诺枪权动作；开枪由随后独立任务决定。",
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
        sheriff_initiative: SheriffInitiative = SheriffInitiative.MEDIUM,
    ) -> StrategyBrief:
        priority_id, priority_description = {
            "speech": ("state_useful_position", "给出有信息价值且不泄露私密来源的公开立场。"),
            "vote": ("make_auditable_vote", "完成发言后比较相对怀疑并形成明确票向；不能只因信息不充分消极弃票，只有候选完全不可区分时才可弃票。"),
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
            "hunter_target": ("use_hunter_shot", "依据当前全部公开信息执行唯一枪权；残局或已有明确最高怀疑目标时优先开枪。"),
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
        assignment_method = self._wolf_assignment_method(owner, task, wolf_team_plan)
        deity_task_method = self._deity_task_method(role, task)
        initiative_method = self._sheriff_initiative_method(
            role,
            task,
            sheriff_initiative,
        )
        methods = (
            [assignment_method]
            if assignment_method is not None
            else [deity_task_method]
            if deity_task_method is not None
            else [initiative_method]
            if initiative_method is not None
            else [
                StrategyMethod(method_id=method_id, description=description)
                for method_id, description in self.ROLE_METHODS[role]
            ]
        )
        situation_method = self._situation_method(role, situation_tags)
        if situation_method is not None:
            methods.append(situation_method)
        methods.append(
            StrategyMethod(
                method_id="separate_claim_from_fact",
                description="公开声明只代表发言者观点，不把它直接当成已验证事实。",
            ),
        )
        warnings = self._warnings(role, situation, situation_tags)
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
            sheriff_initiative=sheriff_initiative,
            wolf_team_plan=(
                wolf_team_plan if role is RoleType.WEREWOLF else None
            ),
        )

    def _situation_method(
        self,
        role: RoleType,
        tags: tuple[SituationTag, ...],
    ) -> StrategyMethod | None:
        tag_set = set(tags)
        for tag, method_id, description in self.SITUATION_METHODS[role]:
            if tag in tag_set:
                return StrategyMethod(method_id=method_id, description=description)
        return None

    def _deity_task_method(
        self,
        role: RoleType,
        task: str,
    ) -> StrategyMethod | None:
        item = self.DEITY_TASK_METHODS.get((role, task))
        if item is None:
            return None
        return StrategyMethod(method_id=item[0], description=item[1])

    @staticmethod
    def _wolf_assignment_method(
        owner: int,
        task: str,
        plan: WolfTeamPlan | None,
    ) -> StrategyMethod | None:
        if plan is None:
            return None
        assignment = next(
            (item for item in plan.assignments if item.seat == owner),
            None,
        )
        if assignment is None:
            return None
        if task == "sheriff_signup":
            if assignment.posture is WolfPosture.CLAIMANT:
                return StrategyMethod(
                    method_id="wolf_claimant_must_run",
                    description="团队主跳者必须报名上警，以执行既定身份和假查验。",
                )
            return StrategyMethod(
                method_id="wolf_nonclaimant_follow_plan",
                description="非主跳狼人按支援、倒钩或隐藏分工决定留在警下，不抢主跳位置。",
            )
        method_id, description = {
            WolfPosture.CLAIMANT: (
                "execute_claimant_posture",
                "按团队计划承担悍跳，保持声称身份、假查验和后续叙事一致。",
            ),
            WolfPosture.SUPPORT: (
                "execute_support_posture",
                "只从公开逻辑支援团队主张，不暴露已知队友关系。",
            ),
            WolfPosture.DISTANCE: (
                "execute_distance_posture",
                "可公开质疑或切割队友，但理由必须来自公开信息并服务团队生存。",
            ),
            WolfPosture.HIDE: (
                "execute_hide_posture",
                "保持普通好人视角并提供可核对判断，不主动成为身份对跳中心。",
            ),
        }[assignment.posture]
        return StrategyMethod(method_id=method_id, description=description)

    @staticmethod
    def _sheriff_initiative_method(
        role: RoleType,
        task: str,
        initiative: SheriffInitiative,
    ) -> StrategyMethod | None:
        if task != "sheriff_signup" or role is RoleType.SEER:
            return None
        method_id, description = {
            SheriffInitiative.HIGH: (
                "high_sheriff_initiative",
                "你有较高竞选意愿，可以主动上警并承担组织与归票责任。",
            ),
            SheriffInitiative.MEDIUM: (
                "conditional_sheriff_initiative",
                "只有能提出区别于通用套话的具体竞选价值时才上警，否则留在警下。",
            ),
            SheriffInitiative.LOW: (
                "low_sheriff_initiative",
                "你更倾向留在警下，用警长票观察和表达判断；没有特殊理由不报名。",
            ),
        }[initiative]
        return StrategyMethod(method_id=method_id, description=description)

    @staticmethod
    def _warnings(
        role: RoleType,
        situation: DecisionBrief | None,
        situation_tags: tuple[SituationTag, ...],
    ) -> list[StrategyWarning]:
        warnings: list[StrategyWarning] = []
        if role in {RoleType.WEREWOLF, RoleType.SEER, RoleType.WITCH}:
            warnings.append(
                StrategyWarning(
                    warning_id="private_information_leak",
                    description="公开表达不得无意泄露仅自己或己方知道的夜间信息。",
                ),
            )
        if SituationTag.PEACEFUL_NIGHT_CONFIRMS_WITCH_SAVE in situation_tags:
            warnings.append(
                StrategyWarning(
                    warning_id="no_empty_kill_peaceful_night",
                    description="本规则狼人每夜必须选择刀口、不能空刀；当日平安夜必然表示女巫使用解药救人，不得再说可能空刀。",
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
