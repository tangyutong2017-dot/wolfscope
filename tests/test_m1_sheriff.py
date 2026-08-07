from __future__ import annotations

import unittest

from wolfscope.contracts import Visibility
from wolfscope.game import DeathCause, GameState, PendingDeath, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.sheriff import (
    CampaignSpeechObservation,
    DawnAnnouncementEngine,
    SheriffElectionEngine,
    SheriffSignupObservation,
    SheriffVoteObservation,
    SheriffWithdrawalObservation,
)
from wolfscope.message_router import GameMessageRouter


def game_state(seed: int = 7) -> GameState:
    return GameState(
        seed=seed,
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )


class ScriptedSheriffProvider:
    def __init__(
        self,
        *,
        signups: set[int],
        withdrawals: set[int] | None = None,
        votes: dict[int, int | None] | None = None,
    ) -> None:
        self.signups = signups
        self.withdrawals = withdrawals or set()
        self.votes = votes or {}
        self.signup_observations: list[SheriffSignupObservation] = []
        self.speech_observations: list[CampaignSpeechObservation] = []
        self.withdrawal_observations: list[SheriffWithdrawalObservation] = []
        self.vote_observations: list[SheriffVoteObservation] = []

    async def choose_signup(self, observation: SheriffSignupObservation) -> bool:
        self.signup_observations.append(observation)
        return observation.actor in self.signups

    async def campaign_speech(self, observation: CampaignSpeechObservation) -> str:
        self.speech_observations.append(observation)
        return f"{observation.actor}号竞选发言"

    async def choose_withdrawal(
        self,
        observation: SheriffWithdrawalObservation,
    ) -> bool:
        self.withdrawal_observations.append(observation)
        return observation.actor in self.withdrawals

    async def choose_sheriff_vote(self, observation: SheriffVoteObservation) -> int | None:
        self.vote_observations.append(observation)
        return self.votes.get(observation.voter)


class SheriffElectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_seed_fixes_random_campaign_start(self) -> None:
        provider_a = ScriptedSheriffProvider(signups={2, 5, 8}, withdrawals={5, 8})
        provider_b = ScriptedSheriffProvider(signups={2, 5, 8}, withdrawals={5, 8})

        result_a = await SheriffElectionEngine(game_state(42), EventLog()).run(provider_a)
        result_b = await SheriffElectionEngine(game_state(42), EventLog()).run(provider_b)

        self.assertEqual(result_a.speech_order, result_b.speech_order)
        self.assertEqual(set(result_a.speech_order), {2, 5, 8})

    async def test_signup_and_withdrawal_are_simultaneous_observations(self) -> None:
        provider = ScriptedSheriffProvider(signups={2, 5, 8}, withdrawals={5, 8})

        await SheriffElectionEngine(game_state(), EventLog()).run(provider)

        signup_eligible = {obs.eligible_seats for obs in provider.signup_observations}
        self.assertEqual(len(signup_eligible), 1)
        withdrawal_payloads = {
            (obs.candidates, obs.campaign_speeches)
            for obs in provider.withdrawal_observations
        }
        self.assertEqual(len(withdrawal_payloads), 1)

    async def test_withdrawn_candidate_does_not_regain_vote(self) -> None:
        provider = ScriptedSheriffProvider(
            signups={2, 5, 8},
            withdrawals={5},
            votes={1: 2, 3: 2, 4: 8, 6: 8, 7: 2, 9: 2},
        )

        result = await SheriffElectionEngine(game_state(), EventLog()).run(provider)

        voters = {observation.voter for observation in provider.vote_observations}
        self.assertEqual(voters, {1, 3, 4, 6, 7, 9})
        self.assertNotIn(5, voters)
        self.assertEqual(result.sheriff, 2)

    async def test_abstention_is_allowed_and_all_abstain_means_no_sheriff(self) -> None:
        provider = ScriptedSheriffProvider(signups={2, 8})

        result = await SheriffElectionEngine(game_state(), EventLog()).run(provider)

        self.assertIsNone(result.sheriff)
        self.assertEqual(result.reason, "no_valid_votes")
        self.assertFalse(game_state().sheriff.election_completed)  # unrelated state sanity

    async def test_tie_means_no_sheriff(self) -> None:
        provider = ScriptedSheriffProvider(
            signups={2, 8},
            votes={1: 2, 3: 8, 4: 2, 5: 8},
        )
        state = game_state()

        result = await SheriffElectionEngine(state, EventLog()).run(provider)

        self.assertIsNone(result.sheriff)
        self.assertEqual(result.reason, "tie")
        self.assertTrue(state.sheriff.election_completed)
        self.assertFalse(state.sheriff.badge_exists)

    async def test_pending_dead_player_can_run_and_win(self) -> None:
        state = game_state()
        state.pending_deaths[9] = PendingDeath(9, {DeathCause.WEREWOLF})
        provider = ScriptedSheriffProvider(signups={9})

        result = await SheriffElectionEngine(state, EventLog()).run(provider)

        self.assertEqual(result.sheriff, 9)
        self.assertTrue(state.get_player(9).alive)
        self.assertIn(9, provider.signup_observations[0].eligible_seats)


class DawnAnnouncementTests(unittest.TestCase):
    def test_dawn_reveals_seats_not_causes_and_clears_pending(self) -> None:
        state = game_state()
        state.pending_deaths = {
            4: PendingDeath(4, {DeathCause.WEREWOLF}),
            9: PendingDeath(9, {DeathCause.WEREWOLF, DeathCause.POISON}),
        }
        events = EventLog()

        result = DawnAnnouncementEngine(state, events).announce()

        self.assertEqual(result.deaths, (4, 9))
        self.assertFalse(state.get_player(4).alive)
        self.assertFalse(state.get_player(9).alive)
        self.assertIs(state.get_player(9).death_cause, DeathCause.POISON)
        self.assertEqual(state.pending_deaths, {})
        public = [event for event in events if event.visibility is Visibility.PUBLIC]
        self.assertEqual(public[0].data, {"deaths": [4, 9]})
        self.assertNotIn("poison", public[0].content)
        god = [event for event in events if event.visibility is Visibility.GOD]
        self.assertEqual(god[0].data["deaths"][1]["effective_cause"], "poison")

    def test_dead_sheriff_is_marked_for_later_badge_resolution(self) -> None:
        state = game_state()
        state.sheriff.holder = 9
        state.sheriff.election_completed = True
        state.pending_deaths[9] = PendingDeath(9, {DeathCause.WEREWOLF})

        DawnAnnouncementEngine(state, EventLog()).announce()

        self.assertEqual(state.sheriff.holder, 9)
        self.assertEqual(state.sheriff.transfer_pending_from, 9)

    def test_pending_death_is_invisible_before_dawn(self) -> None:
        state = game_state()
        state.pending_deaths[9] = PendingDeath(9, {DeathCause.POISON})
        events = EventLog()
        router = GameMessageRouter(wolf_seats={1, 2, 3})

        self.assertEqual(router.project(events.events, 4), ())
        DawnAnnouncementEngine(state, events).announce()
        spectator = router.project(events.events, 4)
        self.assertEqual([event.event_type for event in spectator], ["dawn_deaths"])
        self.assertNotIn("poison", spectator[0].content)


if __name__ == "__main__":
    unittest.main()
