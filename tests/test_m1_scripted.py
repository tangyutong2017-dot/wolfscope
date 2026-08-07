from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from wolfscope.game import Camp, WinReason
from wolfscope.game.day import DayTurnAction, ExileVoteRound
from wolfscope.game.engine import GameEngine, GameRunStatus
from wolfscope.game.factory import GameFactory
from wolfscope.scenarios import GOOD_WIN_SEED_42
from wolfscope.scripted import (
    DayScript,
    MissingScriptedAction,
    ScriptedProvider,
    UnusedScriptedAction,
)


class ScriptedProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_good_win_scenario_runs_and_consumes_every_explicit_action(self) -> None:
        script = GOOD_WIN_SEED_42
        provider = ScriptedProvider(script)

        result = await GameEngine(
            GameFactory.create(script.seed),
            provider,
            max_days=script.max_days,
            game_id=script.game_id,
        ).run()
        provider.assert_all_consumed()

        self.assertIs(result.status, GameRunStatus.FINISHED)
        self.assertIs(result.winner, Camp.GOOD)
        self.assertIs(result.win_reason, WinReason.ALL_WOLVES_DEAD)
        self.assertEqual(result.days, 2)
        self.assertEqual(result.game_id, "good-win-seed-42")

    async def test_missing_vote_is_different_from_explicit_abstention(self) -> None:
        provider = ScriptedProvider(GOOD_WIN_SEED_42)
        observation = SimpleNamespace(
            day=1,
            voter=2,
            vote_round=ExileVoteRound.FIRST,
        )
        with self.assertRaisesRegex(MissingScriptedAction, "action=vote"):
            await provider.choose_exile_vote(observation)

        day = replace(GOOD_WIN_SEED_42.days[1], votes={2: None})
        script = replace(GOOD_WIN_SEED_42, days={1: day})
        provider = ScriptedProvider(script)
        self.assertIsNone(await provider.choose_exile_vote(observation))

    async def test_unrequested_explicit_action_is_reported(self) -> None:
        script = replace(
            GOOD_WIN_SEED_42,
            days={
                **GOOD_WIN_SEED_42.days,
                2: DayScript(turns={1: DayTurnAction.speak("不会被请求的发言")}),
            },
        )
        provider = ScriptedProvider(script)

        result = await GameEngine(
            GameFactory.create(script.seed),
            provider,
            max_days=script.max_days,
        ).run()
        self.assertIs(result.winner, Camp.GOOD)
        with self.assertRaises(UnusedScriptedAction):
            provider.assert_all_consumed()


if __name__ == "__main__":
    unittest.main()
