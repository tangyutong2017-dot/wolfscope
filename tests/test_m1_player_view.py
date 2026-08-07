from __future__ import annotations

import unittest

from wolfscope.contracts import (
    HunterPrivateState,
    SeerPrivateState,
    VillagerPrivateState,
    WerewolfPrivateState,
    WitchPrivateState,
    Visibility,
)
from wolfscope.game import DeathCause, GameState, PendingDeath, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.types import Phase
from wolfscope.player_view import DeadPlayerViewError, PlayerViewBuilder


def game_state() -> GameState:
    return GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )


def event_log() -> EventLog:
    events = EventLog()
    events.emit(
        day=1,
        phase=Phase.DAY_SPEECH,
        event_type="public_speech",
        visibility=Visibility.PUBLIC,
        actor=4,
        content="公开发言",
    )
    events.emit(
        day=1,
        phase=Phase.NIGHT_WOLF,
        event_type="wolf_target",
        visibility=Visibility.WOLVES,
        target=4,
        content="狼队刀4号",
    )
    events.emit(
        day=1,
        phase=Phase.NIGHT_SEER,
        event_type="seer_result",
        visibility=Visibility.PRIVATE,
        recipients=(7,),
        actor=7,
        target=1,
        content="1号是狼人",
    )
    events.emit(
        day=1,
        phase=Phase.NIGHT_RESOLUTION,
        event_type="night_resolution",
        visibility=Visibility.GOD,
        content="上帝结算",
    )
    events.emit(
        day=1,
        phase=Phase.NIGHT_WITCH,
        event_type="witch_night_victim",
        visibility=Visibility.PRIVATE,
        recipients=(8,),
        actor=8,
        target=4,
        content="今晚4号中刀",
    )
    events.emit(
        day=1,
        phase=Phase.DAWN_ANNOUNCEMENT,
        event_type="public_update",
        visibility=Visibility.PUBLIC,
        content="公开阶段更新",
    )
    return events


class PlayerViewBuilderTests(unittest.TestCase):
    def test_public_status_ruleset_sheriff_and_cursor(self) -> None:
        state = game_state()
        state.phase = Phase.DAY_SPEECH
        state.sheriff.holder = 5
        view = PlayerViewBuilder(state, event_log()).build(4)

        self.assertEqual(view.ruleset, "standard-9-v1")
        self.assertEqual(view.view_revision, 2)
        self.assertEqual(view.day, 1)
        self.assertIsInstance(view.own_role_state, VillagerPrivateState)
        self.assertTrue(view.players[4].is_sheriff)  # seat 5 occupies index 4

    def test_good_player_cannot_see_wolf_or_god_events(self) -> None:
        view = PlayerViewBuilder(game_state(), event_log()).build(4)
        self.assertEqual(
            [event.event_type for event in view.visible_events],
            ["public_speech", "public_update"],
        )
        self.assertEqual([event.event_id for event in view.visible_events], [1, 2])

    def test_wolf_sees_teammates_and_wolf_events(self) -> None:
        view = PlayerViewBuilder(game_state(), event_log()).build(1)
        self.assertIsInstance(view.own_role_state, WerewolfPrivateState)
        self.assertEqual(view.own_role_state.teammate_seats, (1, 2, 3))
        self.assertEqual(
            [event.event_type for event in view.visible_events],
            ["public_speech", "wolf_target", "public_update"],
        )

    def test_seer_sees_only_own_private_result_and_checked_state(self) -> None:
        state = game_state()
        state.seer.checked_seats.add(1)
        view = PlayerViewBuilder(state, event_log()).build(7)

        self.assertIsInstance(view.own_role_state, SeerPrivateState)
        self.assertEqual(view.own_role_state.checked_seats, (1,))
        self.assertEqual(
            [event.event_type for event in view.visible_events],
            ["public_speech", "seer_result", "public_update"],
        )

    def test_witch_and_hunter_resources_are_role_scoped(self) -> None:
        state = game_state()
        state.witch.antidote_available = False
        state.hunter.gun_available = False

        witch = PlayerViewBuilder(state, event_log()).build(8)
        hunter = PlayerViewBuilder(state, event_log()).build(9)

        self.assertEqual(
            witch.own_role_state,
            WitchPrivateState(antidote_available=False, poison_available=True),
        )
        self.assertEqual(
            [event.event_type for event in witch.visible_events],
            ["public_speech", "witch_night_victim", "public_update"],
        )
        self.assertEqual(
            hunter.own_role_state,
            HunterPrivateState(gun_available=False),
        )

    def test_pending_death_remains_publicly_alive(self) -> None:
        state = game_state()
        state.pending_deaths[4] = PendingDeath(4, {DeathCause.WEREWOLF})

        view = PlayerViewBuilder(state, event_log()).build(4)

        self.assertTrue(view.players[3].alive)  # seat 4 occupies index 3
        self.assertFalse(hasattr(view, "pending_deaths"))

    def test_dead_player_cannot_receive_a_current_view(self) -> None:
        state = game_state()
        state.mark_dead(4, DeathCause.EXILE)
        with self.assertRaises(DeadPlayerViewError):
            PlayerViewBuilder(state, event_log()).build(4)

    def test_dead_player_terminal_view_requires_explicit_engine_path(self) -> None:
        state = game_state()
        state.mark_dead(9, DeathCause.EXILE)
        state.phase = Phase.HUNTER_SHOT
        builder = PlayerViewBuilder(state, event_log())

        view = builder.build_terminal_action(9)

        self.assertEqual(view.viewer_seat, 9)
        self.assertFalse(view.players[8].alive)
        self.assertIsInstance(view.own_role_state, HunterPrivateState)

    def test_returned_events_are_deep_copied_from_god_log(self) -> None:
        events = event_log()
        view = PlayerViewBuilder(game_state(), events).build(4)

        view.visible_events[0].content = "被修改的副本"

        self.assertEqual(events.events[0].content, "公开发言")

    def test_local_event_reference_resolves_server_side_without_exposing_gaps(self) -> None:
        builder = PlayerViewBuilder(game_state(), event_log())
        view = builder.build(4)

        self.assertEqual([event.event_id for event in view.visible_events], [1, 2])
        self.assertEqual(
            builder.source_event_id(4, 2, view_revision=view.view_revision),
            6,
        )


if __name__ == "__main__":
    unittest.main()
