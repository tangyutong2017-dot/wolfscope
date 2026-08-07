from __future__ import annotations

import unittest

from wolfscope.contracts import Visibility
from wolfscope.game import DeathCause, GameState, Phase, PlayerState, RoleType
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.night import (
    IllegalNightAction,
    NightEngine,
    SeerNightObservation,
    WitchAction,
    WitchActionType,
    WitchNightObservation,
    WolfNightObservation,
)
from wolfscope.message_router import GameMessageRouter


def game_state() -> GameState:
    return GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )


class ScriptedNightProvider:
    def __init__(
        self,
        *,
        wolf_target: int,
        seer_target: int,
        witch_action: WitchAction,
    ) -> None:
        self.wolf_target = wolf_target
        self.seer_target = seer_target
        self.witch_action = witch_action
        self.call_order: list[str] = []
        self.wolf_observation: WolfNightObservation | None = None
        self.seer_observation: SeerNightObservation | None = None
        self.witch_observation: WitchNightObservation | None = None

    async def choose_wolf_target(self, observation: WolfNightObservation) -> int:
        self.call_order.append("wolf")
        self.wolf_observation = observation
        return self.wolf_target

    async def choose_seer_target(self, observation: SeerNightObservation) -> int:
        self.call_order.append("seer")
        self.seer_observation = observation
        return self.seer_target

    async def choose_witch_action(self, observation: WitchNightObservation) -> WitchAction:
        self.call_order.append("witch")
        self.witch_observation = observation
        return self.witch_action


class NightEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_is_asked_in_order_and_deaths_remain_pending(self) -> None:
        state = game_state()
        events = EventLog()
        provider = ScriptedNightProvider(
            wolf_target=9,
            seer_target=1,
            witch_action=WitchAction.pass_night(),
        )

        resolution = await NightEngine(state, events).run(provider)

        self.assertEqual(provider.call_order, ["wolf", "seer", "witch"])
        self.assertEqual(state.pending_death_seats(), [9])
        self.assertTrue(state.get_player(9).alive)
        self.assertIs(state.phase, Phase.NIGHT_RESOLUTION)
        self.assertIs(resolution.pending_deaths[0].effective_cause, DeathCause.WEREWOLF)

    async def test_witch_sees_target_but_not_alignment(self) -> None:
        state = game_state()
        provider = ScriptedNightProvider(
            wolf_target=2,  # wolf-on-wolf target is legal
            seer_target=4,
            witch_action=WitchAction.pass_night(),
        )

        await NightEngine(state, EventLog()).run(provider)

        observation = provider.witch_observation
        assert observation is not None
        self.assertEqual(observation.night_victim, 2)
        self.assertFalse(hasattr(observation, "alignment"))

    async def test_save_consumes_antidote_and_removes_wolf_death(self) -> None:
        state = game_state()
        provider = ScriptedNightProvider(
            wolf_target=4,
            seer_target=1,
            witch_action=WitchAction(WitchActionType.SAVE, target=4),
        )

        await NightEngine(state, EventLog()).run(provider)

        self.assertFalse(state.witch.antidote_available)
        self.assertEqual(state.pending_death_seats(), [])

    async def test_witch_cannot_save_herself(self) -> None:
        state = game_state()
        witch = state.find_role(RoleType.WITCH)
        assert witch is not None
        original_phase = state.phase
        provider = ScriptedNightProvider(
            wolf_target=witch.seat,
            seer_target=1,
            witch_action=WitchAction(WitchActionType.SAVE, target=witch.seat),
        )

        with self.assertRaises(IllegalNightAction):
            await NightEngine(state, EventLog()).run(provider)

        self.assertTrue(state.witch.antidote_available)
        self.assertEqual(state.pending_deaths, {})
        self.assertIs(state.phase, original_phase)

    async def test_witch_cannot_poison_herself(self) -> None:
        state = game_state()
        witch = state.find_role(RoleType.WITCH)
        assert witch is not None
        provider = ScriptedNightProvider(
            wolf_target=4,
            seer_target=1,
            witch_action=WitchAction(WitchActionType.POISON, target=witch.seat),
        )

        with self.assertRaises(IllegalNightAction):
            await NightEngine(state, EventLog()).run(provider)
        self.assertTrue(state.witch.poison_available)

    async def test_poisoning_wolf_target_records_both_causes(self) -> None:
        state = game_state()
        provider = ScriptedNightProvider(
            wolf_target=9,
            seer_target=1,
            witch_action=WitchAction(WitchActionType.POISON, target=9),
        )

        await NightEngine(state, EventLog()).run(provider)

        pending = state.pending_deaths[9]
        self.assertEqual(pending.causes, {DeathCause.WEREWOLF, DeathCause.POISON})
        self.assertIs(pending.effective_cause, DeathCause.POISON)

    async def test_seer_cannot_check_self_or_repeat(self) -> None:
        state = game_state()
        seer = state.find_role(RoleType.SEER)
        assert seer is not None
        self_target_provider = ScriptedNightProvider(
            wolf_target=4,
            seer_target=seer.seat,
            witch_action=WitchAction.pass_night(),
        )
        with self.assertRaises(IllegalNightAction):
            await NightEngine(state, EventLog()).run(self_target_provider)

        state.seer.checked_seats.add(1)
        repeat_provider = ScriptedNightProvider(
            wolf_target=4,
            seer_target=1,
            witch_action=WitchAction.pass_night(),
        )
        with self.assertRaises(IllegalNightAction):
            await NightEngine(state, EventLog()).run(repeat_provider)

    async def test_seer_result_and_witch_victim_are_private(self) -> None:
        state = game_state()
        events = EventLog()
        provider = ScriptedNightProvider(
            wolf_target=9,
            seer_target=1,
            witch_action=WitchAction.pass_night(),
        )

        await NightEngine(state, events).run(provider)

        seer = state.find_role(RoleType.SEER)
        witch = state.find_role(RoleType.WITCH)
        assert seer is not None and witch is not None
        router = GameMessageRouter(wolf_seats={1, 2, 3})
        seer_events = router.project(events.events, seer.seat)
        witch_events = router.project(events.events, witch.seat)
        villager_events = router.project(events.events, 4)
        self.assertIn("seer_result", {event.event_type for event in seer_events})
        self.assertIn("witch_night_victim", {event.event_type for event in witch_events})
        self.assertNotIn("seer_result", {event.event_type for event in villager_events})
        self.assertNotIn("witch_night_victim", {event.event_type for event in villager_events})
        god_events = [event for event in events if event.visibility is Visibility.GOD]
        self.assertEqual([event.event_type for event in god_events], ["night_resolution"])

    async def test_used_antidote_hides_future_victim(self) -> None:
        state = game_state()
        state.witch.antidote_available = False
        provider = ScriptedNightProvider(
            wolf_target=4,
            seer_target=1,
            witch_action=WitchAction.pass_night(),
        )

        await NightEngine(state, EventLog()).run(provider)

        observation = provider.witch_observation
        assert observation is not None
        self.assertIsNone(observation.night_victim)
        self.assertFalse(observation.can_save)

    async def test_invalid_action_does_not_partially_mutate_state_or_events(self) -> None:
        state = game_state()
        events = EventLog()
        provider = ScriptedNightProvider(
            wolf_target=4,
            seer_target=99,
            witch_action=WitchAction.pass_night(),
        )

        with self.assertRaises(IllegalNightAction):
            await NightEngine(state, events).run(provider)

        self.assertEqual(state.pending_deaths, {})
        self.assertEqual(state.seer.checked_seats, set())
        self.assertTrue(state.witch.antidote_available)
        self.assertTrue(state.witch.poison_available)
        self.assertEqual(len(events), 0)
        self.assertIs(state.phase, Phase.SETUP)


if __name__ == "__main__":
    unittest.main()
