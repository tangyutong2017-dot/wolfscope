from __future__ import annotations

import unittest

from wolfscope.agents.hybrid import HybridProvider
from wolfscope.agents.prompt import render_decision_prompt
from wolfscope.agents.runtime import PlayerRuntimeRegistry
from wolfscope.agents.schemas import DecisionTask
from wolfscope.agents.support import DeterministicSupportProvider
from wolfscope.game import DeathCause, GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.day import (
    PkSpeechObservation,
    SpeechDirection,
    SpeechDirectionObservation,
)
from wolfscope.game.events import EventLog
from wolfscope.game.resolution import DeathResolutionEngine
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.fake import FakeModelGateway
from wolfscope.player_view import PlayerViewBuilder


def state_and_provider(responses):
    state = GameState(
        seed=42,
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )
    events = EventLog()
    gateways = {}

    def factory(seat):
        gateway = FakeModelGateway(responses.get(seat, ()))
        gateways[seat] = gateway
        return gateway

    runtimes = PlayerRuntimeRegistry.create(
        model_config_for(ModelProfile.TEST),
        factory,
    )
    support = DeterministicSupportProvider()
    provider = HybridProvider(
        view_builder=PlayerViewBuilder(state, events),
        runtimes=runtimes,
        support=support,
    )
    return state, events, runtimes, support, provider


class PublicPhaseAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_sheriff_direction_and_pk_speech_use_agents(self) -> None:
        state, _events, _runtimes, support, provider = state_and_provider(
            {
                5: [{"action": "speech_direction", "direction": "counterclockwise", "confidence": 0.7, "reason": "让关键位置先发言"}],
                2: [{"action": "pk_speech", "speech": "2号回应PK焦点。", "intent": "争取出局另一候选", "confidence": 0.7}],
            },
        )
        state.sheriff.holder = 5

        direction = await provider.choose_speech_direction(
            SpeechDirectionObservation(day=1, sheriff=5, alive_seats=tuple(range(1, 10))),
        )
        speech = await provider.pk_speech(
            PkSpeechObservation(
                day=1,
                actor=2,
                tied_seats=(2, 6),
                day_speeches=((1, "公开发言"),),
                previous_pk_speeches=(),
            ),
        )

        self.assertIs(direction, SpeechDirection.COUNTERCLOCKWISE)
        self.assertEqual(speech, "2号回应PK焦点。")
        self.assertFalse(
            {"speech_direction", "pk_speech"} & {call[0] for call in support.calls},
        )


class TerminalActionAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_dead_hunter_sheriff_uses_words_shot_then_badge_agent_chain(self) -> None:
        state, events, runtimes, support, provider = state_and_provider(
            {
                9: [
                    {"action": "death_last_words", "speech": "9号留下死亡遗言。", "intent": "交代公开判断", "confidence": 0.8},
                    {"action": "hunter_target", "target": 4, "reason": "带走最可疑目标", "confidence": 0.8},
                    {"action": "badge_transfer", "target": 5, "reason": "5号适合组织信息", "confidence": 0.8},
                ],
            },
        )
        state.sheriff.holder = 9
        state.sheriff.election_completed = True
        state.mark_dead(9, DeathCause.EXILE)

        result = await DeathResolutionEngine(state, events).resolve(
            (9,),
            provider,
            last_words_seats=(9,),
        )

        self.assertEqual(result.last_words, ((9, "9号留下死亡遗言。"),))
        self.assertEqual(result.hunter_target, 4)
        self.assertEqual(result.badge_holder, 5)
        self.assertEqual(
            [record.task.value for record in runtimes.get(9).call_records],
            ["death_last_words", "hunter_target", "badge_transfer"],
        )
        death_input = runtimes.get(9).gateway.inputs[0]
        death_prompt = render_decision_prompt(
            death_input,
            DecisionTask.DEATH_LAST_WORDS,
        )
        self.assertIn("你已在当前死亡批次中死亡", death_prompt)
        self.assertIn("不得假设自己未来再次出局", death_prompt)
        self.assertIn("不得承诺开枪、不开枪或具体目标", death_prompt)
        hunter_input = runtimes.get(9).gateway.inputs[1]
        self.assertEqual(
            hunter_input.observation.last_words,
            "9号留下死亡遗言。",
        )
        hunter_prompt = render_decision_prompt(
            hunter_input,
            DecisionTask.HUNTER_TARGET,
        )
        self.assertIn("枪权以本任务为唯一正式决定", hunter_prompt)
        self.assertIn("不能笼统以误伤风险回避决定", hunter_prompt)
        badge_input = runtimes.get(9).gateway.inputs[2]
        self.assertEqual(badge_input.observation.hunter_target, 4)
        self.assertFalse(
            {"death_last_words", "hunter_target", "badge_transfer"}
            & {call[0] for call in support.calls},
        )


if __name__ == "__main__":
    unittest.main()
