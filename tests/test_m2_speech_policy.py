from __future__ import annotations

import unittest

from wolfscope.agents.agent_game import AgentGameProvider
from wolfscope.agents.prompt import render_decision_prompt
from wolfscope.agents.runtime import PlayerRuntimeRegistry
from wolfscope.agents.schemas import (
    AgentDecisionInput,
    DecisionTask,
    PublicGameSummary,
    SpeechTaskObservation,
)
from wolfscope.agents.speech_policy import SpeechPolicy
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.day import DayTurnObservation
from wolfscope.game.events import EventLog
from wolfscope.game.types import Phase
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.fake import FakeModelGateway
from wolfscope.player_view import PlayerViewBuilder


def game_state() -> GameState:
    return GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
        phase=Phase.DAY_SPEECH,
    )


class SpeechPolicyTests(unittest.TestCase):
    def test_short_speech_is_unchanged(self) -> None:
        result = SpeechPolicy.enforce(DecisionTask.SPEECH, "简短但完整的发言。")

        self.assertEqual(result.text, "简短但完整的发言。")
        self.assertFalse(result.truncated)
        self.assertEqual(result.original_chars, result.final_chars)

    def test_long_speech_is_trimmed_at_a_sentence_boundary(self) -> None:
        text = "甲" * 170 + "。" + "乙" * 170 + "。"

        result = SpeechPolicy.enforce(DecisionTask.SHERIFF_CAMPAIGN, text)

        self.assertTrue(result.truncated)
        self.assertLessEqual(result.final_chars, 280)
        self.assertTrue(result.text.endswith("。"))
        self.assertEqual(result.original_chars, len(text))

    def test_prompt_adds_length_only_without_content_structure(self) -> None:
        state = game_state()
        view = PlayerViewBuilder(state, EventLog()).build(4)
        decision_input = AgentDecisionInput(
            player_view=view,
            public_summary=PublicGameSummary.from_view(view),
            observation=SpeechTaskObservation(
                actor=4,
                speaking_order=tuple(range(1, 10)),
                previous_speeches=(),
                can_explode=False,
            ),
        )

        prompt = render_decision_prompt(decision_input, DecisionTask.SPEECH)

        self.assertIn('"target_min_chars": 140', prompt)
        self.assertIn('"hard_max_chars": 300', prompt)
        self.assertNotIn("三段", prompt)
        self.assertNotIn("身份或立场", prompt)


class SpeechPolicyProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_records_deterministic_truncation(self) -> None:
        state = game_state()
        events = EventLog()
        gateway = FakeModelGateway(
            [
                {
                    "action": "speak",
                    "speech": "长" * 350,
                    "intent": "测试字数硬上限",
                    "confidence": 0.8,
                },
            ],
        )
        runtimes = PlayerRuntimeRegistry.create(
            model_config_for(ModelProfile.TEST),
            lambda seat: gateway if seat == 4 else FakeModelGateway(()),
        )
        provider = AgentGameProvider(
            view_builder=PlayerViewBuilder(state, events),
            runtimes=runtimes,
        )

        action = await provider.take_day_turn(
            DayTurnObservation(
                day=1,
                actor=4,
                speaking_order=tuple(range(1, 10)),
                previous_speeches=(),
                can_explode=False,
            ),
        )

        self.assertLessEqual(len(action.speech), 300)
        record = runtimes.get(4).call_records[-1]
        self.assertEqual(record.speech_original_chars, 350)
        self.assertEqual(record.speech_final_chars, len(action.speech))
        self.assertTrue(record.speech_truncated)


if __name__ == "__main__":
    unittest.main()
