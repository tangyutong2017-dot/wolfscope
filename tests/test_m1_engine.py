from __future__ import annotations

import unittest

from wolfscope.game import Camp, GameState, PlayerState, RoleType, WinReason
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.day import DayTurnAction, SpeechDirection
from wolfscope.game.engine import GameEngine, GameRunStatus
from wolfscope.game.events import EventLog
from wolfscope.game.factory import GameFactory
from wolfscope.game.night import WitchAction, WitchActionType


def fixed_state(seed: int = 17) -> GameState:
    return GameState(
        seed=seed,
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )


class FullGameProvider:
    def __init__(self, *, save_first_victim: bool = False) -> None:
        self.save_first_victim = save_first_victim
        self.calls: list[tuple[str, int, int | None]] = []

    async def choose_wolf_target(self, observation):
        self.calls.append(("wolf", observation.day, None))
        if self.save_first_victim:
            return 4
        return 1 if observation.day == 1 else 3

    async def choose_seer_target(self, observation):
        self.calls.append(("seer", observation.day, observation.seer_seat))
        return observation.eligible_targets[0]

    async def choose_witch_action(self, observation):
        self.calls.append(("witch", observation.day, observation.witch_seat))
        if self.save_first_victim and observation.day == 1:
            return WitchAction(WitchActionType.SAVE, target=observation.night_victim)
        return WitchAction.pass_night()

    async def choose_signup(self, observation):
        self.calls.append(("signup", observation.day, observation.actor))
        return False

    async def campaign_speech(self, observation):
        raise AssertionError("no player signs up in this script")

    async def choose_withdrawal(self, observation):
        raise AssertionError("no player signs up in this script")

    async def choose_sheriff_vote(self, observation):
        raise AssertionError("no sheriff vote in this script")

    async def choose_speech_direction(self, observation):
        return SpeechDirection.CLOCKWISE

    async def take_day_turn(self, observation):
        self.calls.append(("day_turn", observation.day, observation.actor))
        return DayTurnAction.speak(f"{observation.actor}号发言")

    async def choose_exile_vote(self, observation):
        self.calls.append(("vote", observation.day, observation.voter))
        if self.save_first_victim:
            return None
        return 3 if observation.voter == 2 else 2

    async def pk_speech(self, observation):
        return f"{observation.actor}号PK发言"

    async def last_words(self, observation):
        return f"{observation.actor}号放逐遗言"

    async def death_last_words(self, observation):
        return f"{observation.actor}号首夜遗言"

    async def choose_hunter_target(self, observation):
        return None

    async def choose_badge_transfer(self, observation):
        return None


class GameFactoryTests(unittest.TestCase):
    def test_same_seed_produces_same_deal(self) -> None:
        first = GameFactory.create(42)
        second = GameFactory.create(42)

        self.assertEqual(
            [player.role for player in first.players],
            [player.role for player in second.players],
        )
        self.assertEqual(first.seed, 42)

    def test_factory_preserves_standard_role_counts(self) -> None:
        state = GameFactory.create(99)
        self.assertEqual(sum(p.role is RoleType.WEREWOLF for p in state.players), 3)
        self.assertEqual(sum(p.role is RoleType.VILLAGER for p in state.players), 3)


class GameEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_engine_runs_first_night_election_dawn_day_then_loops(self) -> None:
        provider = FullGameProvider()
        events = EventLog()

        result = await GameEngine(fixed_state(), provider, events).run()

        self.assertIs(result.status, GameRunStatus.FINISHED)
        self.assertIs(result.winner, Camp.GOOD)
        self.assertIs(result.win_reason, WinReason.ALL_WOLVES_DEAD)
        self.assertEqual(result.days, 2)
        event_types = [event.event_type for event in events]
        self.assertLess(event_types.index("sheriff_failed"), event_types.index("dawn_deaths"))
        self.assertLess(event_types.index("dawn_deaths"), event_types.index("day_speech"))
        self.assertEqual(event_types.count("game_finished"), 1)

    async def test_engine_stops_requesting_actions_after_terminal_dawn(self) -> None:
        provider = FullGameProvider()

        await GameEngine(fixed_state(), provider).run()

        day_two_turns = [
            call for call in provider.calls if call[0] == "day_turn" and call[1] == 2
        ]
        self.assertEqual(day_two_turns, [])

    async def test_max_days_is_infrastructure_stop_not_a_draw(self) -> None:
        provider = FullGameProvider(save_first_victim=True)

        result = await GameEngine(fixed_state(), provider, max_days=1).run()

        self.assertIs(result.status, GameRunStatus.MAX_DAYS_REACHED)
        self.assertIsNone(result.winner)
        self.assertIsNone(result.win_reason)
        self.assertEqual(result.days, 1)
        self.assertEqual(result.events[-1].event_type, "game_run_limit_reached")

    async def test_start_events_separate_public_wolf_and_god_information(self) -> None:
        result = await GameEngine(
            fixed_state(),
            FullGameProvider(),
        ).run()

        start_events = result.events[:3]
        self.assertEqual(
            [event.event_type for event in start_events],
            ["game_started", "wolf_teammates", "initial_roles"],
        )
        self.assertNotIn("roles", start_events[0].data)


if __name__ == "__main__":
    unittest.main()
