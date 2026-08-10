from __future__ import annotations

import unittest

from wolfscope.agents.hybrid import AgentGameProvider
from wolfscope.agents.runtime import PlayerRuntime
from wolfscope.agents.prompt import render_decision_prompt
from wolfscope.agents.schemas import (
    AgentDecisionInput,
    DecisionTask,
    ComplexityLevel,
    PublicGameSummary,
    SpeechDecision,
    SpeechTaskObservation,
)
from wolfscope.cognition.brief import CheckBrief, DecisionBrief, RoleClaimBrief
from wolfscope.cognition.claims import ClaimAlignment, ClaimPolarity
from wolfscope.cognition.strategy import (
    SituationTag,
    StrategyBrief,
    StrategyBuilder,
    StrategySituationBuilder,
)
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.types import Phase, RoleType
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.fake import FakeModelGateway
from wolfscope.player_view import PlayerViewBuilder


def view_for(seat: int):
    state = GameState(
        players=[
            PlayerState(seat=index, role=role)
            for index, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
        day=1,
        phase=Phase.DAY_SPEECH,
    )
    return PlayerViewBuilder(state, EventLog()).build(seat)


class StrategyBuilderTests(unittest.TestCase):
    def test_complexity_policy_uses_role_default_and_villager_escalation(self) -> None:
        self.assertEqual(
            AgentGameProvider._complexity_for(
                role=RoleType.WEREWOLF,
                task="speech",
                situation_tags=(),
            )[0],
            ComplexityLevel.FULL,
        )
        self.assertEqual(
            AgentGameProvider._complexity_for(
                role=RoleType.VILLAGER,
                task="speech",
                situation_tags=(),
            )[0],
            ComplexityLevel.COMPACT,
        )
        self.assertEqual(
            AgentGameProvider._complexity_for(
                role=RoleType.VILLAGER,
                task="speech",
                situation_tags=(SituationTag.SELF_RECEIVED_WOLF_CHECK,),
            )[0],
            ComplexityLevel.FULL,
        )
    def test_active_wolf_plan_requires_focus_target(self) -> None:
        from wolfscope.cognition.strategy import WolfAssignment, WolfPosture, WolfTeamPlan

        with self.assertRaisesRegex(ValueError, "focus target"):
            WolfTeamPlan(
                day=1,
                objective="seer_pressure",
                primary_claimant=None,
                claimed_role=None,
                fake_check_target=None,
                fake_check_alignment=None,
                focus_target=None,
                plan_reason="压制预言家",
                assignments=(WolfAssignment(seat=2, posture=WolfPosture.HIDE),),
            )

    def test_all_roles_receive_small_distinct_playbooks(self) -> None:
        builder = StrategyBuilder()
        playbooks = {
            role: builder.build(
                owner=seat,
                role=role,
                day=1,
                task="speech",
            )
            for seat, role in enumerate(RoleType, start=1)
        }

        self.assertEqual(len({brief.role_goal for brief in playbooks.values()}), 5)
        for role, brief in playbooks.items():
            self.assertEqual(brief.role, role)
            self.assertLessEqual(len(brief.priorities), 3)
            self.assertLessEqual(len(brief.methods), 5)
            self.assertLessEqual(len(brief.warnings), 3)
            self.assertEqual(len(brief.strategy_ids), len(set(brief.strategy_ids)))

    def test_private_information_roles_receive_leak_warning(self) -> None:
        builder = StrategyBuilder()

        warning_roles = {
            role
            for role in RoleType
            if "private_information_leak" in builder.build(
                owner=1,
                role=role,
                day=1,
                task="vote",
            ).strategy_ids
        }

        self.assertEqual(
            warning_roles,
            {RoleType.WEREWOLF, RoleType.SEER, RoleType.WITCH},
        )

    def test_situation_tags_are_deterministic_public_facts(self) -> None:
        view = view_for(4)
        brief = DecisionBrief(
            owner=4,
            day=1,
            ledger_revision=2,
            belief_revision=2,
            candidates=(),
            role_claims=(
                RoleClaimBrief(
                    speaker=7,
                    subject=7,
                    role=RoleType.SEER,
                    polarity=ClaimPolarity.ASSERT,
                    evidence_id="p4-e1",
                ),
            ),
            checks=(
                CheckBrief(
                    speaker=7,
                    target=4,
                    night=1,
                    result=ClaimAlignment.WEREWOLF,
                    evidence_id="p4-e2",
                ),
            ),
        )

        tags = StrategySituationBuilder().build(
            view=view,
            observation=SpeechTaskObservation(
                actor=4,
                speaking_order=tuple(range(1, 10)),
                previous_speeches=(),
                can_explode=False,
            ),
            brief=brief,
            wolf_team_plan=None,
        )

        self.assertIn(SituationTag.EARLY_GAME, tags)
        self.assertIn(SituationTag.SINGLE_SEER_CLAIM, tags)
        self.assertIn(SituationTag.CLAIMED_WOLF_EXISTS, tags)
        self.assertIn(SituationTag.SELF_RECEIVED_WOLF_CHECK, tags)
        self.assertIn(SituationTag.SELF_UNDER_PRESSURE, tags)

    def test_good_role_rejects_wolf_private_situation_tag(self) -> None:
        with self.assertRaisesRegex(ValueError, "wolf-private"):
            StrategyBrief(
                owner=4,
                day=1,
                task="speech",
                role=RoleType.VILLAGER,
                role_goal="找狼",
                priorities=(),
                methods=(),
                warnings=(),
                situation_tags=(SituationTag.TEAMMATE_UNDER_PRESSURE,),
            )

    def test_role_selects_one_highest_priority_situation_method(self) -> None:
        brief = StrategyBuilder().build(
            owner=4,
            role=RoleType.VILLAGER,
            day=1,
            task="speech",
            situation_tags=(
                SituationTag.MULTIPLE_SEER_CLAIMS,
                SituationTag.SELF_RECEIVED_WOLF_CHECK,
                SituationTag.VOTE_BEHAVIOR_CONFLICT,
            ),
        )

        self.assertIn("answer_wolf_check", brief.strategy_ids)
        self.assertNotIn("compare_seer_claimants", brief.strategy_ids)
        self.assertNotIn("use_vote_behavior", brief.strategy_ids)
        self.assertLessEqual(len(brief.methods), 3)

    def test_deities_receive_task_specific_methods_without_larger_prompt(self) -> None:
        cases = (
            (RoleType.SEER, "sheriff_signup", "seer_must_run_for_sheriff"),
            (RoleType.SEER, "seer_target", "check_influential_unknown"),
            (RoleType.WITCH, "witch_action", "evaluate_medicine_value"),
            (RoleType.HUNTER, "hunter_target", "shoot_only_with_auditable_basis"),
            (RoleType.HUNTER, "death_last_words", "separate_words_from_shot"),
        )
        for role, task, expected_id in cases:
            with self.subTest(role=role, task=task):
                brief = StrategyBuilder().build(
                    owner=7,
                    role=role,
                    day=1,
                    task=task,
                )
                self.assertIn(expected_id, brief.strategy_ids)
                self.assertLessEqual(len(brief.methods), 3)


class StrategyRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_audits_strategy_ids(self) -> None:
        view = view_for(4)
        strategy = StrategyBuilder().build(
            owner=4,
            role=view.own_role,
            day=1,
            task="speech",
        )
        valid_id = strategy.methods[0].method_id
        decision_input = AgentDecisionInput(
            player_view=view,
            public_summary=PublicGameSummary.from_view(view),
            observation=SpeechTaskObservation(
                actor=4,
                speaking_order=tuple(range(1, 10)),
                previous_speeches=(),
                can_explode=False,
            ),
            strategy_brief=strategy,
        )
        runtime = PlayerRuntime(
            4,
            model_config_for(ModelProfile.TEST),
            FakeModelGateway([
                SpeechDecision(
                    action="speak",
                    speech="按粗粒度策略发言",
                    intent="测试策略审计",
                    confidence=0.5,
                    strategy_ids=(valid_id, "invented_strategy"),
                ),
            ]),
        )

        rendered = render_decision_prompt(decision_input, DecisionTask.SPEECH)
        self.assertIn('"strategy_brief"', rendered)
        self.assertIn(valid_id, rendered)

        decision = await runtime.decide(
            task=DecisionTask.SPEECH,
            decision_input=decision_input,
            output_schema=SpeechDecision,
        )

        self.assertEqual(decision.strategy_ids, (valid_id,))
        self.assertEqual(runtime.call_records[0].accepted_strategy_ids, (valid_id,))
        self.assertEqual(
            runtime.call_records[0].invalid_strategy_ids,
            ("invented_strategy",),
        )


if __name__ == "__main__":
    unittest.main()
