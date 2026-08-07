from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from wolfscope.game import (
    STANDARD_9_RULES,
    DeathCause,
    GameState,
    HunterState,
    PendingDeath,
    Phase,
    PlayerState,
    RoleType,
)


def standard_players() -> list[PlayerState]:
    return [
        PlayerState(seat=seat, role=role)
        for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
    ]


class M1StateTests(unittest.TestCase):
    def test_standard_game_state(self) -> None:
        state = GameState(players=standard_players())
        self.assertEqual(state.day, 1)
        self.assertIs(state.phase, Phase.SETUP)
        self.assertEqual(state.alive_seats(), list(range(1, 10)))
        self.assertEqual(len(state.alive_wolves()), 3)

    def test_pending_death_does_not_change_public_alive_state(self) -> None:
        state = GameState(players=standard_players())
        state.pending_deaths[9] = PendingDeath(
            seat=9,
            causes={DeathCause.WEREWOLF},
        )
        self.assertTrue(state.get_player(9).alive)
        self.assertIn(9, state.sheriff_election_eligible_seats())
        self.assertEqual(state.pending_death_seats(), [9])

    def test_poison_dominates_multiple_pending_causes(self) -> None:
        pending = PendingDeath(
            seat=9,
            causes={DeathCause.WEREWOLF, DeathCause.POISON},
        )
        self.assertIs(pending.effective_cause, DeathCause.POISON)

    def test_hunter_only_loses_shot_to_poison(self) -> None:
        hunter = HunterState()
        self.assertFalse(hunter.can_shoot(DeathCause.POISON))
        for cause in (
            DeathCause.WEREWOLF,
            DeathCause.EXILE,
            DeathCause.HUNTER_SHOT,
            DeathCause.WOLF_EXPLODE,
        ):
            self.assertTrue(hunter.can_shoot(cause), cause)
        hunter.gun_available = False
        self.assertFalse(hunter.can_shoot(DeathCause.WEREWOLF))

    def test_rule_config_is_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            STANDARD_9_RULES.sheriff_vote_units = 4  # type: ignore[misc]

    def test_invalid_role_distribution_is_rejected(self) -> None:
        players = standard_players()
        players[0] = PlayerState(seat=1, role=RoleType.VILLAGER)
        with self.assertRaises(ValueError):
            GameState(players=players)


if __name__ == "__main__":
    unittest.main()
