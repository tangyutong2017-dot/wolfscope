from __future__ import annotations

import unittest

from wolfscope.agents.hybrid import HybridProvider
from wolfscope.agents.runtime import PlayerRuntimeRegistry
from wolfscope.agents.support import DeterministicSupportProvider
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.sheriff import SheriffElectionEngine
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.fake import FakeModelGateway
from wolfscope.player_view import PlayerViewBuilder


class SheriffAgentIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_agents_own_all_four_sheriff_decisions(self) -> None:
        state = GameState(
            seed=42,
            players=[
                PlayerState(seat=seat, role=role)
                for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
            ],
        )
        events = EventLog()
        candidates = {2, 5, 8}
        gateways: dict[int, FakeModelGateway] = {}

        def gateway_factory(seat: int) -> FakeModelGateway:
            responses = [
                {
                    "action": "sheriff_signup",
                    "signup": seat in candidates,
                    "confidence": 0.7,
                    "reason": "按测试剧本决定是否上警",
                },
            ]
            if seat in candidates:
                responses.extend(
                    [
                        {
                            "action": "sheriff_campaign",
                            "speech": f"{seat}号竞选警长。",
                            "intent": "组织公开信息",
                            "confidence": 0.7,
                        },
                        {
                            "action": "sheriff_withdrawal",
                            "withdraw": seat == 8,
                            "confidence": 0.7,
                            "reason": "按竞选局势决定",
                        },
                    ],
                )
            else:
                responses.append(
                    {
                        "action": "sheriff_vote",
                        "target": 2,
                        "confidence": 0.8,
                        "reason": "2号竞选发言更适合组织信息",
                    },
                )
            gateway = FakeModelGateway(responses)
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

        result = await SheriffElectionEngine(state, events).run(provider)

        self.assertEqual(result.original_candidates, (2, 5, 8))
        self.assertEqual(result.withdrawn, (8,))
        self.assertEqual(result.sheriff, 2)
        self.assertEqual(state.sheriff.holder, 2)
        self.assertFalse(any("sheriff" in call[0] for call in support.calls))
        for seat in range(1, 10):
            self.assertEqual(gateways[seat].remaining_responses, 0)
            self.assertIsNotNone(gateways[seat].inputs[-1].strategy_brief)

        first_campaign_seat = result.speech_order[0]
        first_campaign_input = gateways[first_campaign_seat].inputs[1]
        self.assertEqual(first_campaign_input.observation.previous_speeches, ())
        final_campaign_seat = result.speech_order[-1]
        final_campaign_input = gateways[final_campaign_seat].inputs[1]
        self.assertEqual(
            len(final_campaign_input.observation.previous_speeches),
            len(candidates) - 1,
        )


if __name__ == "__main__":
    unittest.main()
