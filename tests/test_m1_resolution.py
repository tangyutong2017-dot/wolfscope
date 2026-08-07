from __future__ import annotations

import unittest

from wolfscope.contracts import Visibility
from wolfscope.game import (
    Camp,
    DeathCause,
    GameState,
    PendingDeath,
    PlayerState,
    WinReason,
)
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.resolution import (
    BadgeTransferObservation,
    DeathResolutionEngine,
    DeathLastWordsObservation,
    HunterShotObservation,
)
from wolfscope.game.sheriff import DawnAnnouncementEngine


def game_state() -> GameState:
    return GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )


class ScriptedResolutionProvider:
    def __init__(self, hunter_target=None, badge_target=None) -> None:
        self.hunter_target = hunter_target
        self.badge_target = badge_target
        self.last_words_observations: list[DeathLastWordsObservation] = []
        self.hunter_observations: list[HunterShotObservation] = []
        self.badge_observations: list[BadgeTransferObservation] = []

    async def death_last_words(self, observation: DeathLastWordsObservation) -> str:
        self.last_words_observations.append(observation)
        return f"{observation.actor}号夜间遗言"

    async def choose_hunter_target(self, observation: HunterShotObservation):
        self.hunter_observations.append(observation)
        return self.hunter_target

    async def choose_badge_transfer(self, observation: BadgeTransferObservation):
        self.badge_observations.append(observation)
        return self.badge_target


class DeathResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_night_deaths_speak_in_seat_order(self) -> None:
        state = game_state()
        state.pending_deaths = {
            9: PendingDeath(9, {DeathCause.POISON}),
            4: PendingDeath(4, {DeathCause.WEREWOLF}),
        }
        provider = ScriptedResolutionProvider()

        _, result = await DawnAnnouncementEngine(state, EventLog()).announce_and_resolve(provider)

        self.assertEqual(result.initial_deaths, (4, 9))
        self.assertEqual([item.actor for item in provider.last_words_observations], [4, 9])
        self.assertEqual(provider.hunter_observations, [])

    async def test_later_night_has_no_last_words_and_killed_hunter_may_shoot(self) -> None:
        state = game_state()
        state.day = 2
        state.pending_deaths = {9: PendingDeath(9, {DeathCause.WEREWOLF})}
        provider = ScriptedResolutionProvider(hunter_target=1)

        _, result = await DawnAnnouncementEngine(state, EventLog()).announce_and_resolve(provider)

        self.assertEqual(result.last_words, ())
        self.assertEqual(result.hunter_target, 1)
        self.assertFalse(state.get_player(1).alive)
        self.assertIs(state.get_player(1).death_cause, DeathCause.HUNTER_SHOT)
        self.assertFalse(state.hunter.gun_available)

    async def test_poisoned_hunter_cannot_shoot(self) -> None:
        state = game_state()
        state.mark_dead(9, DeathCause.POISON)
        provider = ScriptedResolutionProvider(hunter_target=1)

        result = await DeathResolutionEngine(state, EventLog()).resolve((9,), provider)

        self.assertIsNone(result.hunter_target)
        self.assertEqual(provider.hunter_observations, [])
        self.assertTrue(state.hunter.gun_available)

    async def test_hunter_shot_target_has_no_last_words(self) -> None:
        state = game_state()
        state.mark_dead(9, DeathCause.EXILE)
        provider = ScriptedResolutionProvider(hunter_target=4)

        result = await DeathResolutionEngine(state, EventLog()).resolve((9,), provider)

        self.assertEqual(result.all_deaths, (9, 4))
        self.assertEqual(provider.last_words_observations, [])

    async def test_hunter_shoots_sheriff_then_badge_is_resolved(self) -> None:
        state = game_state()
        state.sheriff.holder = 4
        state.sheriff.election_completed = True
        state.mark_dead(9, DeathCause.EXILE)
        provider = ScriptedResolutionProvider(hunter_target=4, badge_target=5)

        result = await DeathResolutionEngine(state, EventLog()).resolve((9,), provider)

        self.assertEqual(result.hunter_target, 4)
        self.assertEqual(result.badge_holder, 5)
        self.assertEqual(state.sheriff.transfer_pending_from, None)
        event_types = [event.event_type for event in result.events]
        self.assertLess(event_types.index("hunter_shot"), event_types.index("badge_transferred"))

    async def test_dead_sheriff_can_destroy_badge(self) -> None:
        state = game_state()
        state.sheriff.holder = 9
        state.sheriff.election_completed = True
        state.mark_dead(9, DeathCause.WEREWOLF)
        state.sheriff.transfer_pending_from = 9

        result = await DeathResolutionEngine(state, EventLog()).resolve(
            (9,), ScriptedResolutionProvider(),
        )

        self.assertTrue(result.badge_destroyed)
        self.assertIsNone(state.sheriff.holder)
        self.assertFalse(state.sheriff.badge_exists)

    async def test_invalid_decisions_fall_back_without_public_leak(self) -> None:
        state = game_state()
        state.sheriff.holder = 9
        state.mark_dead(9, DeathCause.EXILE)
        state.sheriff.transfer_pending_from = 9
        events = EventLog()

        result = await DeathResolutionEngine(state, events).resolve(
            (9,), ScriptedResolutionProvider(hunter_target=9, badge_target=9),
        )

        self.assertIsNone(result.hunter_target)
        self.assertTrue(result.badge_destroyed)
        fallbacks = [e for e in events if e.event_type == "invalid_decision_fallback"]
        self.assertEqual(len(fallbacks), 2)
        self.assertTrue(all(e.visibility is Visibility.GOD for e in fallbacks))

    async def test_all_wolves_dead_is_good_win(self) -> None:
        state = game_state()
        state.mark_dead(1, DeathCause.EXILE)
        state.mark_dead(2, DeathCause.EXILE)
        state.mark_dead(3, DeathCause.EXILE)

        result = await DeathResolutionEngine(state, EventLog()).resolve(
            (3,), ScriptedResolutionProvider(),
        )

        self.assertIs(result.winner, Camp.GOOD)
        self.assertIs(result.win_reason, WinReason.ALL_WOLVES_DEAD)

    async def test_all_deities_dead_is_wolf_win(self) -> None:
        state = game_state()
        state.mark_dead(7, DeathCause.EXILE)
        state.mark_dead(8, DeathCause.EXILE)
        state.mark_dead(9, DeathCause.POISON)

        result = await DeathResolutionEngine(state, EventLog()).resolve(
            (9,), ScriptedResolutionProvider(),
        )

        self.assertIs(result.winner, Camp.WEREWOLF)
        self.assertIs(result.win_reason, WinReason.ALL_DEITIES_DEAD)

    async def test_all_civilians_dead_is_wolf_win(self) -> None:
        state = game_state()
        state.mark_dead(4, DeathCause.EXILE)
        state.mark_dead(5, DeathCause.EXILE)
        state.mark_dead(6, DeathCause.EXILE)

        result = await DeathResolutionEngine(state, EventLog()).resolve(
            (6,), ScriptedResolutionProvider(),
        )

        self.assertIs(result.winner, Camp.WEREWOLF)
        self.assertIs(result.win_reason, WinReason.ALL_CIVILIANS_DEAD)

    async def test_hunter_chain_tie_prioritizes_good_win(self) -> None:
        state = game_state()
        for seat in (2, 3, 4, 5, 6, 7, 8):
            state.mark_dead(seat, DeathCause.EXILE)
        state.mark_dead(9, DeathCause.EXILE)

        result = await DeathResolutionEngine(state, EventLog()).resolve(
            (9,), ScriptedResolutionProvider(hunter_target=1),
        )

        self.assertIs(result.winner, Camp.GOOD)
        self.assertIs(result.win_reason, WinReason.ALL_WOLVES_DEAD)


if __name__ == "__main__":
    unittest.main()
