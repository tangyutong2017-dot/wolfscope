from __future__ import annotations

import unittest

from wolfscope.agents.hybrid import HybridProvider
from wolfscope.agents.runtime import PlayerRuntimeRegistry
from wolfscope.agents.support import DeterministicSupportProvider
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.night import NightEngine, WitchActionType
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.fake import FakeModelGateway
from wolfscope.player_view import PlayerViewBuilder


class NightAgentIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_role_agents_own_wolf_seer_and_witch_actions(self) -> None:
        state = GameState(
            seed=42,
            players=[
                PlayerState(seat=seat, role=role)
                for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
            ],
        )
        events = EventLog()
        responses = {
            1: [{"action": "wolf_target", "target": 4, "confidence": 0.8, "reason": "选择民牌刀口"}],
            7: [{"action": "seer_target", "target": 1, "confidence": 0.8, "reason": "查验高价值位置"}],
            8: [{"action": "save", "target": 4, "confidence": 0.8, "reason": "首夜救人"}],
        }
        gateways: dict[int, FakeModelGateway] = {}

        def gateway_factory(seat: int) -> FakeModelGateway:
            gateway = FakeModelGateway(responses.get(seat, ()))
            gateways[seat] = gateway
            return gateway

        runtimes = PlayerRuntimeRegistry.create(
            model_config_for(ModelProfile.TEST),
            gateway_factory,
        )
        support = DeterministicSupportProvider()
        provider = HybridProvider(
            view_builder=PlayerViewBuilder(state, events),
            runtimes=runtimes,
            support=support,
        )

        result = await NightEngine(state, events).run(provider)

        self.assertEqual(result.actions.wolf_target, 4)
        self.assertEqual(result.actions.seer_target, 1)
        self.assertIs(result.actions.witch_action.action, WitchActionType.SAVE)
        self.assertEqual(result.pending_deaths, ())
        self.assertFalse(state.witch.antidote_available)
        self.assertIn(1, state.seer.checked_seats)
        self.assertEqual(
            [record.task.value for record in runtimes.get(1).call_records],
            ["wolf_target"],
        )
        self.assertEqual(gateways[1].inputs[0].observation.wolf_seats, (1, 2, 3))
        self.assertEqual(gateways[8].inputs[0].observation.night_victim, 4)
        self.assertFalse(
            {"wolf_target", "seer_target", "witch_action"}
            & {call[0] for call in support.calls},
        )


if __name__ == "__main__":
    unittest.main()
