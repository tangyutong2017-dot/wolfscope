from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from wolfscope.agents.schemas import VoteContextMode
from wolfscope.evaluation.game_benchmark import (
    aggregate_directory,
    aggregate_games,
    parse_seeds,
    render_report,
    run_evaluation,
)
from wolfscope.models.config import ModelProfile


def game_result(seed: int, winner: str = "good") -> dict:
    return {
        "seed": seed,
        "status": "finished",
        "winner": winner,
        "win_reason": "all_wolves_dead" if winner == "good" else "all_civilians_dead",
        "days": 3,
        "event_count": 60,
        "replay_output": f"replays/seed-{seed}.json",
        "trace_summary": {
            "calls": 10,
            "successful": 9,
            "fallbacks": 1,
            "thinking_calls": 4,
            "nonthinking_calls": 6,
            "input_tokens": 1000,
            "output_tokens": 200,
            "latency_ms": 5000,
            "by_task": {
                "vote": {
                    "calls": 4,
                    "successful": 4,
                    "fallbacks": 0,
                },
            },
            "by_initial_complexity": {
                "l0_full": {
                    "recovered_at_l2": 2,
                    "fell_to_l3": 1,
                },
            },
        },
        "extraction_summary": {
            "calls": 3,
            "input_tokens": 300,
            "output_tokens": 50,
            "latency_ms": 700,
        },
    }


class GameBenchmarkAggregationTests(unittest.TestCase):
    def test_parse_seeds_rejects_duplicates(self) -> None:
        self.assertEqual(parse_seeds("1, 3,5"), (1, 3, 5))
        with self.assertRaises(Exception):
            parse_seeds("1,1")

    def test_aggregates_winners_fallbacks_tasks_and_averages(self) -> None:
        summary = aggregate_games(
            (game_result(1, "good"), game_result(2, "werewolf")),
            requested_seeds=(1, 2, 3),
            failures=({"seed": 3, "error_type": "TimeoutError", "message": "x"},),
        )

        self.assertEqual(summary["completed_games"], 2)
        self.assertEqual(summary["failed_games"], 1)
        self.assertEqual(summary["winner_rates"], {"good": 0.5, "werewolf": 0.5})
        self.assertEqual(summary["totals"]["decisions"], 20)
        self.assertEqual(summary["totals"]["l2_repairs"], 4)
        self.assertEqual(summary["totals"]["l3_fallbacks"], 2)
        self.assertEqual(summary["by_task"]["vote"]["success_rate"], 1.0)
        self.assertEqual(summary["averages"]["model_latency_ms"], 5000)

    def test_report_is_portfolio_readable_and_discloses_limits(self) -> None:
        summary = aggregate_games((game_result(1),), requested_seeds=(1,))
        report = render_report(
            summary,
            {"model_profile": "production", "vote_context_mode": "balanced"},
        )

        self.assertIn("# WolfScope 自动对局评测报告", report)
        self.assertIn("| Seed |", report)
        self.assertIn("少量固定 seed", report)


class GameBenchmarkRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_incremental_outputs_and_resume_skips_completed_seed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            fake = AsyncMock(side_effect=[game_result(1), game_result(2, "werewolf")])
            with patch(
                "wolfscope.evaluation.game_benchmark.run_full_game",
                fake,
            ):
                summary = await run_evaluation(
                    seeds=(1, 2),
                    output_dir=output_dir,
                    max_days=8,
                    vote_context_mode=VoteContextMode.BALANCED,
                    model_profile=ModelProfile.PRODUCTION,
                    resume=False,
                    fail_fast=False,
                )

            self.assertEqual(summary["completed_games"], 2)
            self.assertTrue((output_dir / "summary.json").exists())
            self.assertTrue((output_dir / "report.md").exists())
            self.assertEqual(fake.await_count, 2)

            with patch(
                "wolfscope.evaluation.game_benchmark.run_full_game",
                AsyncMock(),
            ) as resumed:
                second = await run_evaluation(
                    seeds=(1, 2),
                    output_dir=output_dir,
                    max_days=8,
                    vote_context_mode=VoteContextMode.BALANCED,
                    model_profile=ModelProfile.PRODUCTION,
                    resume=True,
                    fail_fast=False,
                )
            self.assertEqual(second["completed_games"], 2)
            resumed.assert_not_awaited()

    async def test_failure_is_persisted_and_offline_reaggregated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with patch(
                "wolfscope.evaluation.game_benchmark.run_full_game",
                AsyncMock(side_effect=RuntimeError("api unavailable")),
            ):
                summary = await run_evaluation(
                    seeds=(9,),
                    output_dir=output_dir,
                    max_days=8,
                    vote_context_mode=VoteContextMode.BALANCED,
                    model_profile=ModelProfile.PRODUCTION,
                    resume=False,
                    fail_fast=False,
                )

            self.assertEqual(summary["failed_games"], 1)
            failure = json.loads(
                (output_dir / "failures" / "seed-9.json").read_text(),
            )
            self.assertEqual(failure["error_type"], "RuntimeError")
            rebuilt = aggregate_directory(output_dir)
            self.assertEqual(rebuilt["failed_games"], 1)


if __name__ == "__main__":
    unittest.main()
