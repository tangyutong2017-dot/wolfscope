"""Installed command-line entrypoints for deterministic M1 scenarios."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Sequence

from .game.engine import GameEngine
from .game.factory import GameFactory
from .replay import ReplayWriter
from .scenarios import M1_SCENARIOS
from .scripted import ScriptedProvider


async def run_scenario(game_id: str, output_dir: Path, overwrite: bool) -> None:
    script = M1_SCENARIOS[game_id]
    provider = ScriptedProvider(script)
    result = await GameEngine(
        GameFactory.create(script.seed),
        provider,
        max_days=script.max_days,
        game_id=script.game_id,
    ).run()
    provider.assert_all_consumed()
    path = ReplayWriter.write(
        result,
        output_dir / f"{script.game_id}.json",
        overwrite=overwrite,
    )
    print(
        f"{script.game_id}: status={result.status.value} "
        f"winner={result.winner.value if result.winner else None} "
        f"reason={result.win_reason.value if result.win_reason else None} "
        f"days={result.days} events={len(result.events)} replay={path}",
    )


async def _run_selected(args: argparse.Namespace) -> None:
    game_ids = list(M1_SCENARIOS) if args.scenario == "all" else [args.scenario]
    for game_id in game_ids:
        await run_scenario(game_id, args.output_dir, args.overwrite)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行 WolfScope M1 确定性验收剧本")
    parser.add_argument(
        "scenario",
        nargs="?",
        default="all",
        choices=["all", *M1_SCENARIOS],
    )
    parser.add_argument("--output-dir", type=Path, default=Path("replays"))
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    asyncio.run(_run_selected(args))


if __name__ == "__main__":
    main()
