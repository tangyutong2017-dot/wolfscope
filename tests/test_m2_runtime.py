from __future__ import annotations

import unittest

from pydantic import ValidationError

from wolfscope.agents.runtime import PlayerRuntime, PlayerRuntimeRegistry
from wolfscope.agents.schemas import (
    AgentDecisionInput,
    BadgeTransferDecision,
    BadgeTransferTaskObservation,
    ComplexityLevel,
    DecisionTask,
    PublicGameSummary,
    SpeechDecision,
    SpeechTaskObservation,
    VoteDecision,
    VoteTaskObservation,
)
from wolfscope.contracts import Visibility
from wolfscope.game import DeathCause, GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.factory import GameFactory
from wolfscope.game.day import ExileVoteRound
from wolfscope.game.events import EventLog
from wolfscope.game.types import Phase
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.fake import FakeModelGateway, FakeResponse
from wolfscope.models.gateway import ModelGatewayError
from wolfscope.player_view import PlayerViewBuilder


def game_state() -> GameState:
    return GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
        phase=Phase.DAY_SPEECH,
    )


def view_for(seat: int = 4):
    events = EventLog()
    events.emit(
        day=1,
        phase=Phase.DAY_SPEECH,
        event_type="public_speech",
        visibility=Visibility.PUBLIC,
        actor=1,
        content="1号公开发言",
    )
    events.emit(
        day=1,
        phase=Phase.NIGHT_RESOLUTION,
        event_type="god_fact",
        visibility=Visibility.GOD,
        content="隐藏身份信息",
    )
    return PlayerViewBuilder(game_state(), events).build(seat)


def speech_input(seat: int = 4) -> AgentDecisionInput:
    view = view_for(seat)
    return AgentDecisionInput(
        player_view=view,
        public_summary=PublicGameSummary.from_view(view),
        observation=SpeechTaskObservation(
            actor=seat,
            speaking_order=tuple(range(1, 10)),
            previous_speeches=((1, "1号公开发言"),),
            can_explode=False,
        ),
    )


def vote_input(seat: int = 4) -> AgentDecisionInput:
    view = view_for(seat)
    return AgentDecisionInput(
        player_view=view,
        public_summary=PublicGameSummary.from_view(view),
        observation=VoteTaskObservation(
            voter=seat,
            vote_round=ExileVoteRound.FIRST,
            candidates=(1, 7),
            speeches=((1, "查杀7号"), (7, "查杀1号")),
        ),
    )


def seer_vote_input(*, alignment: str, target: int) -> AgentDecisionInput:
    events = EventLog()
    events.emit(
        day=1,
        phase=Phase.NIGHT_SEER,
        event_type="seer_result",
        visibility=Visibility.PRIVATE,
        recipients=(7,),
        actor=7,
        target=target,
        content=f"查验{target}号结果为{alignment}",
        data={"target": target, "alignment": alignment},
    )
    view = PlayerViewBuilder(game_state(), events).build(7)
    return AgentDecisionInput(
        player_view=view,
        public_summary=PublicGameSummary.from_view(view),
        observation=VoteTaskObservation(
            voter=7,
            vote_round=ExileVoteRound.FIRST,
            candidates=(1, 4),
            speeches=(),
        ),
    )


class ModelConfigTests(unittest.IsolatedAsyncioTestCase):
    def test_test_and_production_profiles_use_flash(self) -> None:
        self.assertEqual(
            model_config_for(ModelProfile.TEST).model_name,
            "deepseek-v4-flash",
        )
        self.assertEqual(
            model_config_for(ModelProfile.PRODUCTION).model_name,
            "deepseek-v4-flash",
        )
        self.assertEqual(model_config_for(ModelProfile.TEST).temperature, 0.3)
        self.assertEqual(model_config_for(ModelProfile.PRODUCTION).temperature, 0.5)

    def test_model_config_contains_no_api_key_and_is_immutable(self) -> None:
        config = model_config_for(ModelProfile.TEST)
        self.assertFalse(hasattr(config, "api_key"))
        with self.assertRaises(ValidationError):
            config.model_name = "changed"  # type: ignore[misc]

    async def test_speech_and_vote_use_two_thousand_output_budget(self) -> None:
        gateway = FakeModelGateway(
            [
                SpeechDecision(action="speak", speech="发言", intent="测试", confidence=0.5),
                VoteDecision(target=1, confidence=0.5, reason="测试"),
            ],
        )
        runtime = PlayerRuntime(4, model_config_for(ModelProfile.TEST), gateway)

        await runtime.decide(
            task=DecisionTask.SPEECH,
            decision_input=speech_input(),
            output_schema=SpeechDecision,
        )
        await runtime.decide(
            task=DecisionTask.VOTE,
            decision_input=vote_input(),
            output_schema=VoteDecision,
        )

        self.assertEqual(gateway.configs[0].max_tokens, 2000)
        self.assertEqual(gateway.configs[1].max_tokens, 2000)


class DecisionSchemaTests(unittest.IsolatedAsyncioTestCase):
    def test_public_summary_is_derived_from_player_view(self) -> None:
        decision_input = speech_input()
        self.assertEqual(decision_input.public_summary.alive_seats, tuple(range(1, 10)))
        self.assertNotIn(
            "god_fact",
            {event.event_type for event in decision_input.player_view.visible_events},
        )

    def test_observation_actor_must_match_viewer(self) -> None:
        view = view_for(4)
        with self.assertRaises(ValidationError):
            AgentDecisionInput(
                player_view=view,
                public_summary=PublicGameSummary.from_view(view),
                observation=VoteTaskObservation(
                    voter=5,
                    vote_round=ExileVoteRound.FIRST,
                    candidates=(1, 2, 3),
                    speeches=(),
                ),
            )

    def test_speech_and_explosion_payloads_are_coherent(self) -> None:
        SpeechDecision(
            action="speak",
            speech="本轮发言",
            intent="分析票型",
            confidence=0.6,
        )
        SpeechDecision(
            action="explode",
            intent="结束白天",
            confidence=1.0,
        )
        with self.assertRaises(ValidationError):
            SpeechDecision(
                action="speak",
                speech=None,
                intent="空发言",
                confidence=0.5,
            )

    def test_vote_uses_private_audit_reason(self) -> None:
        decision = VoteDecision(
            target=7,
            confidence=0.7,
            reason="更相信1号的查验",
            event_ids=(1,),
        )
        self.assertEqual(decision.reason, "更相信1号的查验")

    async def test_invalid_local_event_references_are_removed_and_traced(self) -> None:
        gateway = FakeModelGateway(
            [
                {
                    "action": "speak",
                    "speech": "引用当前可见事件",
                    "intent": "测试引用",
                    "confidence": 0.5,
                    "event_ids": [1, 99],
                },
            ],
        )
        runtime = PlayerRuntime(4, model_config_for(ModelProfile.TEST), gateway)

        decision = await runtime.decide(
            task=DecisionTask.SPEECH,
            decision_input=speech_input(),
            output_schema=SpeechDecision,
        )

        self.assertEqual(decision.event_ids, (1,))
        self.assertEqual(runtime.call_records[0].invalid_event_ids, (99,))


class FakeGatewayAndRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_seer_badge_cannot_go_to_checked_wolf_and_prefers_gold(self) -> None:
        state = GameFactory.create(3)
        seer = next(player.seat for player in state.players if player.role.value == "seer")
        wolf = next(player.seat for player in state.players if player.role.value == "werewolf")
        good = next(
            player.seat
            for player in state.players
            if player.role.value == "villager"
        )
        events = EventLog()
        for target, alignment in ((wolf, "werewolf"), (good, "good")):
            events.emit(
                day=2,
                phase=Phase.NIGHT_SEER,
                event_type="seer_result",
                visibility=Visibility.PRIVATE,
                recipients=(seer,),
                actor=seer,
                target=target,
                content=f"查验{target}号为{alignment}",
                data={"target": target, "alignment": alignment},
            )
        state.mark_dead(seer, DeathCause.WEREWOLF)
        view = PlayerViewBuilder(state, events).build_terminal_action(seer)
        decision_input = AgentDecisionInput(
            player_view=view,
            public_summary=PublicGameSummary.from_view(view),
            observation=BadgeTransferTaskObservation(
                actor=seer,
                eligible_targets=tuple(
                    player.seat for player in state.players if player.alive
                ),
            ),
        )
        runtime = PlayerRuntime(
            seer,
            model_config_for(ModelProfile.TEST),
            FakeModelGateway(
                [
                    BadgeTransferDecision(
                        target=wolf,
                        confidence=0.8,
                        reason="错误交给本人查杀",
                    ),
                ],
            ),
        )

        decision = await runtime.decide(
            task=DecisionTask.BADGE_TRANSFER,
            decision_input=decision_input,
            output_schema=BadgeTransferDecision,
            use_safe_fallback=True,
        )

        self.assertEqual(decision.target, good)
        self.assertEqual(runtime.call_records[0].error_type, "seer_badge_constraint")
        self.assertEqual(runtime.call_records[0].invalid_target, wolf)
        self.assertTrue(runtime.call_records[0].fallback_used)

    async def test_seer_vote_is_constrained_by_own_confirmed_wolf(self) -> None:
        decision_input = seer_vote_input(alignment="werewolf", target=1)
        runtime = PlayerRuntime(
            7,
            model_config_for(ModelProfile.TEST),
            FakeModelGateway([
                VoteDecision(target=4, confidence=0.5, reason="错误忽略本人查杀"),
            ]),
        )

        decision = await runtime.decide(
            task=DecisionTask.VOTE,
            decision_input=decision_input,
            output_schema=VoteDecision,
        )

        self.assertEqual(decision.target, 1)
        self.assertEqual(runtime.call_records[0].error_type, "seer_check_constraint")

    async def test_seer_does_not_vote_own_confirmed_good(self) -> None:
        decision_input = seer_vote_input(alignment="good", target=4)
        runtime = PlayerRuntime(
            7,
            model_config_for(ModelProfile.TEST),
            FakeModelGateway([
                VoteDecision(target=4, confidence=0.5, reason="错误投本人金水"),
            ]),
        )

        decision = await runtime.decide(
            task=DecisionTask.VOTE,
            decision_input=decision_input,
            output_schema=VoteDecision,
        )

        self.assertIsNone(decision.target)
        self.assertEqual(runtime.call_records[0].error_type, "seer_check_constraint")

    async def test_fake_flash_call_returns_schema_and_trace(self) -> None:
        gateway = FakeModelGateway(
            [
                FakeResponse(
                    payload={
                        "action": "speak",
                        "speech": "4号测试发言",
                        "intent": "提供信息",
                        "confidence": 0.7,
                    },
                    input_tokens=120,
                    output_tokens=30,
                    latency_ms=15,
                ),
            ],
        )
        runtime = PlayerRuntime(4, model_config_for(ModelProfile.TEST), gateway)

        decision = await runtime.decide(
            task=DecisionTask.SPEECH,
            decision_input=speech_input(),
            output_schema=SpeechDecision,
        )

        self.assertEqual(decision.speech, "4号测试发言")
        record = runtime.call_records[0]
        self.assertEqual(record.model_name, "deepseek-v4-flash")
        self.assertEqual(record.token_usage.input_tokens, 120)
        self.assertTrue(record.success)

    async def test_invalid_fake_output_is_traced_as_failure(self) -> None:
        gateway = FakeModelGateway([{"action": "speak", "speech": "缺少字段"}])
        runtime = PlayerRuntime(4, model_config_for(ModelProfile.TEST), gateway)

        with self.assertRaises(ModelGatewayError):
            await runtime.decide(
                task=DecisionTask.SPEECH,
                decision_input=speech_input(),
                output_schema=SpeechDecision,
            )

        self.assertFalse(runtime.call_records[0].success)
        self.assertEqual(runtime.call_records[0].error_type, "schema_validation")
        self.assertEqual(
            runtime.call_records[0].attempts[0].failure_reason,
            "schema_validation",
        )

    async def test_explicit_safe_fallback_keeps_public_turn_running(self) -> None:
        gateway = FakeModelGateway([{"action": "speak", "speech": "缺少字段"}])
        runtime = PlayerRuntime(4, model_config_for(ModelProfile.TEST), gateway)

        decision = await runtime.decide(
            task=DecisionTask.SPEECH,
            decision_input=speech_input(),
            output_schema=SpeechDecision,
            use_safe_fallback=True,
        )

        self.assertEqual(decision.action, "speak")
        self.assertIn("4号", decision.speech or "")
        self.assertTrue(runtime.call_records[0].fallback_used)
        self.assertFalse(runtime.call_records[0].success)
        self.assertEqual(
            runtime.call_records[0].final_complexity_level,
            ComplexityLevel.DETERMINISTIC.value,
        )

    async def test_illegal_vote_target_becomes_audited_abstention(self) -> None:
        gateway = FakeModelGateway(
            [
                {
                    "action": "vote",
                    "target": 6,
                    "confidence": 0.8,
                    "reason": "错误地选择场外玩家",
                },
            ],
        )
        runtime = PlayerRuntime(4, model_config_for(ModelProfile.TEST), gateway)

        decision = await runtime.decide(
            task=DecisionTask.VOTE,
            decision_input=vote_input(),
            output_schema=VoteDecision,
        )

        self.assertIsNone(decision.target)
        record = runtime.call_records[0]
        self.assertFalse(record.success)
        self.assertTrue(record.fallback_used)
        self.assertEqual(record.error_type, "illegal_target")
        self.assertEqual(record.invalid_target, 6)

    async def test_legal_vote_target_is_preserved(self) -> None:
        gateway = FakeModelGateway(
            [
                {
                    "action": "vote",
                    "target": 7,
                    "confidence": 0.8,
                    "reason": "选择合法候选人",
                },
            ],
        )
        runtime = PlayerRuntime(4, model_config_for(ModelProfile.TEST), gateway)

        decision = await runtime.decide(
            task=DecisionTask.VOTE,
            decision_input=vote_input(),
            output_schema=VoteDecision,
        )

        self.assertEqual(decision.target, 7)
        self.assertTrue(runtime.call_records[0].success)
        self.assertFalse(runtime.call_records[0].fallback_used)

    async def test_runtime_registry_creates_nine_isolated_seats(self) -> None:
        gateways: dict[int, FakeModelGateway] = {}

        def factory(seat: int) -> FakeModelGateway:
            gateway = FakeModelGateway([])
            gateways[seat] = gateway
            return gateway

        registry = PlayerRuntimeRegistry.create(
            model_config_for(ModelProfile.TEST),
            factory,
        )

        self.assertEqual(registry.seats, tuple(range(1, 10)))
        self.assertIsNot(registry.get(1), registry.get(2))
        self.assertIsNot(gateways[1], gateways[2])
        registry.get(1).last_view_revision = 7
        self.assertEqual(registry.get(2).last_view_revision, 0)

    async def test_runtime_rejects_another_players_view(self) -> None:
        runtime = PlayerRuntime(
            5,
            model_config_for(ModelProfile.TEST),
            FakeModelGateway([]),
        )
        with self.assertRaisesRegex(ValueError, "another seat"):
            await runtime.decide(
                task=DecisionTask.SPEECH,
                decision_input=speech_input(4),
                output_schema=VoteDecision,
            )


if __name__ == "__main__":
    unittest.main()
