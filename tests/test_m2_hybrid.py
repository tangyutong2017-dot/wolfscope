from __future__ import annotations

import unittest

from wolfscope.agents.hybrid import HybridProvider
from wolfscope.agents.runtime import PlayerRuntimeRegistry
from wolfscope.agents.support import DeterministicSupportProvider
from wolfscope.cognition.claims import SpeechClaimExtraction
from wolfscope.cognition.extraction import (
    EvidencePipeline,
    FakePublicClaimExtractor,
    PublicSpeechAnnotationCache,
)
from wolfscope.cognition.ledger import EvidenceLedgerRegistry
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.engine import GameEngine, GameRunStatus
from wolfscope.game.events import EventLog
from wolfscope.game.night import (
    SeerNightObservation,
    WitchNightObservation,
    WolfNightObservation,
)
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.fake import FakeModelGateway
from wolfscope.player_view import PlayerViewBuilder


def fixed_state() -> GameState:
    return GameState(
        seed=42,
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )


class DeterministicSupportTests(unittest.IsolatedAsyncioTestCase):
    async def test_support_returns_simple_legal_night_actions(self) -> None:
        support = DeterministicSupportProvider()

        wolf_target = await support.choose_wolf_target(
            WolfNightObservation(
                day=1,
                wolf_seats=(1, 2, 3),
                eligible_targets=tuple(range(1, 10)),
            ),
        )
        seer_target = await support.choose_seer_target(
            SeerNightObservation(
                day=1,
                seer_seat=7,
                checked_seats=(),
                eligible_targets=(1, 2, 3, 4, 5, 6, 8, 9),
            ),
        )
        witch_action = await support.choose_witch_action(
            WitchNightObservation(
                day=1,
                witch_seat=8,
                night_victim=4,
                antidote_available=True,
                poison_available=True,
                can_save=True,
                poison_targets=(1, 2, 3, 4, 5, 6, 7, 9),
            ),
        )

        self.assertEqual(wolf_target, 4)
        self.assertEqual(seer_target, 1)
        self.assertEqual(witch_action.action, "pass")


class HybridProviderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_agents_run_one_complete_day_without_script(self) -> None:
        state = fixed_state()
        events = EventLog()
        gateways: dict[int, FakeModelGateway] = {}

        def gateway_factory(seat: int) -> FakeModelGateway:
            vote_target = 8 if seat == 9 else 9
            gateway = FakeModelGateway(
                [
                    {
                        "action": "speak",
                        "speech": f"{seat}号通过 Fake Gateway 发言。",
                        "intent": "验证混合 Provider",
                        "confidence": 0.5,
                    },
                    {
                        "action": "vote",
                        "target": vote_target,
                        "confidence": 0.6,
                        "reason": "验证同时投票",
                    },
                ],
            )
            gateways[seat] = gateway
            return gateway

        runtimes = PlayerRuntimeRegistry.create(
            model_config_for(ModelProfile.TEST),
            gateway_factory,
        )
        support = DeterministicSupportProvider()
        claim_extractor = FakePublicClaimExtractor(
            [
                (SpeechClaimExtraction(item_id="speech-1"),)
                for _ in range(9)
            ],
        )
        annotation_cache = PublicSpeechAnnotationCache()
        view_builder = PlayerViewBuilder(state, events)
        provider = HybridProvider(
            view_builder=view_builder,
            runtimes=runtimes,
            support=support,
            evidence_pipeline=EvidencePipeline(
                ledgers=EvidenceLedgerRegistry(),
                cache=annotation_cache,
                extractor=claim_extractor,
                source_resolver=view_builder,
            ),
        )

        result = await GameEngine(
            state,
            provider,
            events,
            max_days=1,
            game_id="m2-hybrid-fake-day",
        ).run()

        self.assertIs(result.status, GameRunStatus.MAX_DAYS_REACHED)
        self.assertFalse(state.get_player(4).alive)
        self.assertFalse(state.get_player(9).alive)
        self.assertEqual(len(runtimes.get(4).call_records), 0)
        for seat in (1, 2, 3, 5, 6, 7, 8, 9):
            self.assertEqual(len(runtimes.get(seat).call_records), 2)
        self.assertNotIn(
            "support_day_turn",
            {call[0] for call in support.calls},
        )
        self.assertNotIn(
            "support_exile_vote",
            {call[0] for call in support.calls},
        )
        self.assertEqual(len(claim_extractor.calls), 9)
        self.assertEqual(len(annotation_cache), 9)
        for seat in (1, 2, 3, 5, 6, 7, 8, 9):
            vote_input = gateways[seat].inputs[1]
            self.assertIsNotNone(vote_input.evidence_context)
            self.assertEqual(vote_input.evidence_context.owner, seat)
            self.assertGreater(vote_input.evidence_context.ledger_revision, 0)
            self.assertIsNotNone(vote_input.decision_brief)
            self.assertEqual(vote_input.vote_context_mode, "full")
            self.assertEqual(vote_input.decision_brief.owner, seat)
            self.assertEqual(
                tuple(item.seat for item in vote_input.decision_brief.candidates),
                vote_input.observation.candidates,
            )
            self.assertNotIn(
                "exile_votes",
                {
                    event.event_type
                    for event in vote_input.player_view.visible_events
                },
            )


if __name__ == "__main__":
    unittest.main()
