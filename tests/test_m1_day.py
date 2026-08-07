from __future__ import annotations

import unittest

from wolfscope.game import GameState, PlayerState, RoleType
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.day import (
    DayEngine,
    DayTurnAction,
    DayTurnObservation,
    ExileVoteObservation,
    ExileVoteRound,
    IllegalDayAction,
    LastWordsObservation,
    PkSpeechObservation,
    SpeechDirection,
    SpeechDirectionObservation,
)
from wolfscope.game.events import EventLog


def game_state(seed: int = 11) -> GameState:
    return GameState(
        seed=seed,
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )


class ScriptedDayProvider:
    def __init__(
        self,
        *,
        direction: SpeechDirection = SpeechDirection.CLOCKWISE,
        explode_seat: int | None = None,
        votes: dict[int, int | None] | None = None,
        revotes: dict[int, int | None] | None = None,
    ) -> None:
        self.direction = direction
        self.explode_seat = explode_seat
        self.votes = votes or {}
        self.revotes = revotes or {}
        self.turn_observations: list[DayTurnObservation] = []
        self.vote_observations: list[ExileVoteObservation] = []
        self.pk_observations: list[PkSpeechObservation] = []
        self.last_words_observations: list[LastWordsObservation] = []

    async def choose_speech_direction(
        self,
        observation: SpeechDirectionObservation,
    ) -> SpeechDirection:
        return self.direction

    async def take_day_turn(self, observation: DayTurnObservation) -> DayTurnAction:
        self.turn_observations.append(observation)
        if observation.actor == self.explode_seat:
            return DayTurnAction.explode()
        return DayTurnAction.speak(f"{observation.actor}号白天发言")

    async def choose_exile_vote(self, observation: ExileVoteObservation) -> int | None:
        self.vote_observations.append(observation)
        source = self.revotes if observation.vote_round is ExileVoteRound.REVOTE else self.votes
        return source.get(observation.voter)

    async def pk_speech(self, observation: PkSpeechObservation) -> str:
        self.pk_observations.append(observation)
        return f"{observation.actor}号PK发言"

    async def last_words(self, observation: LastWordsObservation) -> str:
        self.last_words_observations.append(observation)
        return f"{observation.actor}号遗言"


class DayEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_sheriff_chooses_direction_and_speaks_last(self) -> None:
        state = game_state()
        state.sheriff.holder = 5
        state.sheriff.election_completed = True
        provider = ScriptedDayProvider(direction=SpeechDirection.COUNTERCLOCKWISE)

        outcome = await DayEngine(state, EventLog()).run(provider)

        self.assertEqual(outcome.speaking_order, (4, 3, 2, 1, 9, 8, 7, 6, 5))
        self.assertEqual(provider.turn_observations[-1].actor, 5)

    async def test_no_sheriff_seed_fixes_start(self) -> None:
        first = await DayEngine(game_state(42), EventLog()).run(ScriptedDayProvider())
        second = await DayEngine(game_state(42), EventLog()).run(ScriptedDayProvider())
        self.assertEqual(first.speaking_order, second.speaking_order)

    async def test_later_speaker_sees_previous_public_speeches(self) -> None:
        provider = ScriptedDayProvider()
        await DayEngine(game_state(), EventLog()).run(provider)
        for index, observation in enumerate(provider.turn_observations):
            self.assertEqual(len(observation.previous_speeches), index)

    async def test_wolf_explosion_stops_speech_and_vote_and_reveals_role(self) -> None:
        state = game_state()
        provider = ScriptedDayProvider(explode_seat=2)
        events = EventLog()

        outcome = await DayEngine(state, events).run(provider)

        self.assertEqual(outcome.exploded, 2)
        self.assertEqual(outcome.votes, ())
        self.assertFalse(state.get_player(2).alive)
        explosion = next(event for event in events if event.event_type == "wolf_exploded")
        self.assertEqual(explosion.data["revealed_role"], RoleType.WEREWOLF.value)
        actors = [observation.actor for observation in provider.turn_observations]
        self.assertEqual(actors[-1], 2)
        self.assertEqual(provider.vote_observations, [])

    async def test_non_wolf_cannot_explode(self) -> None:
        state = game_state(seed=1)
        provider = ScriptedDayProvider(explode_seat=4)
        with self.assertRaises(IllegalDayAction):
            await DayEngine(state, EventLog()).run(provider)
        self.assertTrue(state.get_player(4).alive)

    async def test_votes_are_simultaneous_and_abstention_is_allowed(self) -> None:
        provider = ScriptedDayProvider(votes={1: 4, 2: None, 3: 4})
        await DayEngine(game_state(), EventLog()).run(provider)
        speech_payloads = {observation.speeches for observation in provider.vote_observations[:9]}
        self.assertEqual(len(speech_payloads), 1)
        self.assertNotIn("votes", provider.vote_observations[0].__dataclass_fields__)

    async def test_sheriff_vote_has_one_and_a_half_weight(self) -> None:
        state = game_state()
        state.sheriff.holder = 5
        state.sheriff.election_completed = True
        provider = ScriptedDayProvider(
            votes={1: 2, 5: 3},  # 2号=1票，3号=警长1.5票
        )

        outcome = await DayEngine(state, EventLog()).run(provider)

        self.assertEqual(outcome.exiled, 3)

    async def test_tied_players_pk_and_do_not_revote(self) -> None:
        provider = ScriptedDayProvider(
            votes={1: 2, 3: 4},
            revotes={1: 2, 3: 2, 5: 4},
        )

        outcome = await DayEngine(game_state(), EventLog()).run(provider)

        self.assertEqual(outcome.tied_seats, (2, 4))
        self.assertEqual({obs.actor for obs in provider.pk_observations}, {2, 4})
        revote_observations = [obs for obs in provider.vote_observations if obs.candidates == (2, 4)]
        self.assertNotIn(2, {obs.voter for obs in revote_observations})
        self.assertNotIn(4, {obs.voter for obs in revote_observations})
        self.assertEqual(outcome.exiled, 2)

    async def test_revote_tie_means_no_exile(self) -> None:
        provider = ScriptedDayProvider(
            votes={1: 2, 3: 4},
            revotes={1: 2, 3: 4},
        )

        outcome = await DayEngine(game_state(), EventLog()).run(provider)

        self.assertIsNone(outcome.exiled)
        self.assertIsNone(outcome.last_words)

    async def test_exiled_hunter_speaks_before_pending_shot(self) -> None:
        provider = ScriptedDayProvider(votes={seat: 9 for seat in range(1, 9)})
        state = game_state()

        outcome = await DayEngine(state, EventLog()).run(provider)

        self.assertEqual(outcome.exiled, 9)
        self.assertEqual(outcome.last_words, "9号遗言")
        self.assertTrue(outcome.hunter_resolution_required)
        self.assertFalse(state.get_player(9).alive)
        self.assertEqual(
            [event.event_type for event in outcome.events][-2:],
            ["player_exiled", "last_words"],
        )

    async def test_exiled_sheriff_marks_badge_pending(self) -> None:
        state = game_state()
        state.sheriff.holder = 5
        state.sheriff.election_completed = True
        provider = ScriptedDayProvider(votes={seat: 5 for seat in range(1, 10) if seat != 5})

        outcome = await DayEngine(state, EventLog()).run(provider)

        self.assertEqual(outcome.exiled, 5)
        self.assertTrue(outcome.badge_resolution_required)
        self.assertEqual(state.sheriff.transfer_pending_from, 5)

    async def test_self_vote_is_rejected(self) -> None:
        provider = ScriptedDayProvider(votes={1: 1})
        with self.assertRaises(IllegalDayAction):
            await DayEngine(game_state(), EventLog()).run(provider)


if __name__ == "__main__":
    unittest.main()
