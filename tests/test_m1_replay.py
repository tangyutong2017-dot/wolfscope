from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wolfscope.contracts import Visibility
from wolfscope.game import Camp, Faction, WinReason
from wolfscope.game.engine import GameEngine
from wolfscope.game.factory import GameFactory
from wolfscope.replay import ReplayWriter
from wolfscope.scenarios import (
    GOOD_WIN_SEED_42,
    HUNTER_TIE_BREAK_SEED_42,
    M1_SCENARIOS,
    WOLVES_ELIMINATE_CIVILIANS_SEED_42,
    WOLVES_ELIMINATE_DEITIES_SEED_42,
)
from wolfscope.scripted import ScriptedProvider


async def run_script(script):
    provider = ScriptedProvider(script)
    result = await GameEngine(
        GameFactory.create(script.seed),
        provider,
        max_days=script.max_days,
        game_id=script.game_id,
    ).run()
    provider.assert_all_consumed()
    return result


class ReplayWriterTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_and_read_preserves_complete_god_event_stream(self) -> None:
        result = await run_script(GOOD_WIN_SEED_42)
        with tempfile.TemporaryDirectory() as directory:
            path = ReplayWriter.write(result, Path(directory) / "replay.json")
            replay = ReplayWriter.read(path)

            self.assertEqual(replay.game_id, result.game_id)
            self.assertEqual(replay.events, result.events)
            self.assertEqual(
                {event.visibility for event in replay.events},
                {
                    Visibility.PUBLIC,
                    Visibility.WOLVES,
                    Visibility.PRIVATE,
                    Visibility.GOD,
                },
            )
            self.assertIn("测试遗言", path.read_text(encoding="utf-8"))

    async def test_same_result_writes_byte_identical_json(self) -> None:
        first_result = await run_script(GOOD_WIN_SEED_42)
        second_result = await run_script(GOOD_WIN_SEED_42)
        with tempfile.TemporaryDirectory() as directory:
            first = ReplayWriter.write(first_result, Path(directory) / "first.json")
            second = ReplayWriter.write(second_result, Path(directory) / "second.json")
            self.assertEqual(first.read_bytes(), second.read_bytes())

    async def test_writer_refuses_overwrite_by_default(self) -> None:
        result = await run_script(GOOD_WIN_SEED_42)
        with tempfile.TemporaryDirectory() as directory:
            path = ReplayWriter.write(result, Path(directory) / "replay.json")
            with self.assertRaises(FileExistsError):
                ReplayWriter.write(result, path)
            ReplayWriter.write(result, path, overwrite=True)


class M1ScenarioAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_four_scenarios_finish_and_consume_their_scripts(self) -> None:
        expected = {
            GOOD_WIN_SEED_42.game_id: (Camp.GOOD, WinReason.ALL_WOLVES_DEAD),
            WOLVES_ELIMINATE_DEITIES_SEED_42.game_id: (
                Camp.WEREWOLF,
                WinReason.ALL_DEITIES_DEAD,
            ),
            WOLVES_ELIMINATE_CIVILIANS_SEED_42.game_id: (
                Camp.WEREWOLF,
                WinReason.ALL_CIVILIANS_DEAD,
            ),
            HUNTER_TIE_BREAK_SEED_42.game_id: (
                Camp.GOOD,
                WinReason.ALL_WOLVES_DEAD,
            ),
        }
        for game_id, script in M1_SCENARIOS.items():
            with self.subTest(game_id=game_id):
                result = await run_script(script)
                self.assertEqual((result.winner, result.win_reason), expected[game_id])

    async def test_hunter_boundary_ends_with_both_wolves_and_deities_eliminated(self) -> None:
        result = await run_script(HUNTER_TIE_BREAK_SEED_42)
        roles = dict(result.roles)
        alive_factions = {roles[seat].faction for seat in result.final_alive}

        self.assertNotIn(Faction.WEREWOLF, alive_factions)
        self.assertNotIn(Faction.DEITY, alive_factions)
        self.assertIs(result.winner, Camp.GOOD)
        hunter_shot = next(e for e in result.events if e.event_type == "hunter_shot")
        game_finished = next(e for e in result.events if e.event_type == "game_finished")
        self.assertLess(hunter_shot.event_id, game_finished.event_id)


if __name__ == "__main__":
    unittest.main()
