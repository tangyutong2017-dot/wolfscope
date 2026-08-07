from __future__ import annotations

import unittest
from pathlib import Path

from wolfscope.game import Camp, DeathCause, GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.night import IllegalNightAction, NightEngine
from wolfscope.game.resolution import DeathResolutionEngine
from wolfscope.game.sheriff import SheriffElectionEngine


def game_state() -> GameState:
    return GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )


class AllCandidatesProvider:
    async def choose_signup(self, observation) -> bool:
        return True

    async def campaign_speech(self, observation) -> str:
        return f"{observation.actor}号上警"

    async def choose_withdrawal(self, observation) -> bool:
        return False

    async def choose_sheriff_vote(self, observation):
        raise AssertionError("all players signed up, so no sheriff voter may be asked")


class MissingWolfTargetProvider:
    async def choose_wolf_target(self, observation):
        return None

    async def choose_seer_target(self, observation):
        raise AssertionError("night must reject the missing wolf target first")

    async def choose_witch_action(self, observation):
        raise AssertionError("night must reject the missing wolf target first")


class V1FailureRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_players_running_for_sheriff_produces_no_sheriff(self) -> None:
        state = game_state()
        result = await SheriffElectionEngine(state, EventLog()).run(
            AllCandidatesProvider(),
        )

        self.assertIsNone(result.sheriff)
        self.assertEqual(result.reason, "no_valid_votes")
        self.assertFalse(state.sheriff.badge_exists)

    async def test_wolves_cannot_submit_a_missing_kill_target(self) -> None:
        state = game_state()
        events = EventLog()

        with self.assertRaises(IllegalNightAction):
            await NightEngine(state, events).run(MissingWolfTargetProvider())

        self.assertEqual(state.pending_deaths, {})
        self.assertEqual(events.events, ())

    async def test_winner_resolution_is_idempotent(self) -> None:
        state = game_state()
        for seat in (1, 2, 3):
            state.mark_dead(seat, DeathCause.EXILE)
        events = EventLog()
        resolver = DeathResolutionEngine(state, events)

        self.assertIs(resolver.check_winner(), Camp.GOOD)
        self.assertIs(resolver.check_winner(), Camp.GOOD)
        self.assertEqual(
            [event.event_type for event in events].count("game_finished"),
            1,
        )

    async def test_game_domain_does_not_import_agentscope(self) -> None:
        game_dir = Path(__file__).parents[2] / "src" / "wolfscope" / "game"
        offenders = [
            path.name
            for path in game_dir.glob("*.py")
            if "agentscope" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
