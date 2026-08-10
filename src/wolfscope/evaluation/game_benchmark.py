"""Run and aggregate reproducible full-game Agent evaluations."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from wolfscope.agents.schemas import VoteContextMode
from wolfscope.live_smoke import run_full_game
from wolfscope.models.config import ModelProfile


REPORT_VERSION = "m3-game-eval-v1"

GAMEPLAY_COUNT_KEYS = (
    "votes",
    "abstentions",
    "exiles",
    "wolf_exiles",
    "good_exiles",
    "seer_checks",
    "seer_wolf_checks",
    "witch_saves",
    "witch_poisons",
    "witch_poison_wolf_hits",
    "witch_poison_good_hits",
    "hunter_opportunities",
    "hunter_shots",
    "hunter_wolf_hits",
    "hunter_good_hits",
    "seer_badge_transfers",
    "seer_badge_to_checked_good",
    "seer_badge_to_checked_wolf",
    "seer_badge_to_unknown",
)


def parse_seeds(value: str) -> tuple[int, ...]:
    try:
        seeds = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("seeds 必须是逗号分隔的整数") from error
    if not seeds:
        raise argparse.ArgumentTypeError("至少需要一个 seed")
    if len(seeds) != len(set(seeds)):
        raise argparse.ArgumentTypeError("seeds 不能重复")
    return seeds


def aggregate_games(
    results: Iterable[dict[str, Any]],
    *,
    requested_seeds: tuple[int, ...],
    failures: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    games = sorted(results, key=lambda item: item["seed"])
    failed = sorted(failures, key=lambda item: item["seed"])
    winners = {"good": 0, "werewolf": 0, "unfinished": 0}
    task_totals: dict[str, dict[str, int]] = {}
    gameplay_totals = {key: 0 for key in GAMEPLAY_COUNT_KEYS}
    totals = {
        "decisions": 0,
        "successful": 0,
        "first_attempt_successes": 0,
        "fallbacks": 0,
        "thinking_calls": 0,
        "nonthinking_calls": 0,
        "l2_repairs": 0,
        "l3_fallbacks": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "model_latency_ms": 0,
        "extraction_calls": 0,
        "extraction_input_tokens": 0,
        "extraction_output_tokens": 0,
        "extraction_latency_ms": 0,
    }
    rows: list[dict[str, Any]] = []
    for game in games:
        winner = game.get("winner")
        winners[winner if winner in {"good", "werewolf"} else "unfinished"] += 1
        trace = game.get("trace_summary", {})
        extraction = game.get("extraction_summary", {})
        l2 = sum(
            item.get("recovered_at_l2", 0)
            for item in trace.get("by_initial_complexity", {}).values()
        )
        l3 = sum(
            item.get("fell_to_l3", 0)
            for item in trace.get("by_initial_complexity", {}).values()
        )
        values = {
            "decisions": trace.get("calls", 0),
            "successful": trace.get("successful", 0),
            "first_attempt_successes": sum(
                item.get("success", False)
                and item.get("retry_count", 0) == 0
                and not item.get("fallback_used", False)
                for item in game.get("traces", [])
            ),
            "fallbacks": trace.get("fallbacks", 0),
            "thinking_calls": trace.get("thinking_calls", 0),
            "nonthinking_calls": trace.get("nonthinking_calls", 0),
            "l2_repairs": l2,
            "l3_fallbacks": l3,
            "input_tokens": trace.get("input_tokens", 0),
            "output_tokens": trace.get("output_tokens", 0),
            "model_latency_ms": trace.get("latency_ms", 0),
            "extraction_calls": extraction.get("calls", 0),
            "extraction_input_tokens": extraction.get("input_tokens", 0),
            "extraction_output_tokens": extraction.get("output_tokens", 0),
            "extraction_latency_ms": extraction.get("latency_ms", 0),
        }
        for key, value in values.items():
            totals[key] += value
        for task, stats in trace.get("by_task", {}).items():
            target = task_totals.setdefault(
                task,
                {
                    "calls": 0,
                    "successful": 0,
                    "fallbacks": 0,
                    "first_attempt_successes": 0,
                    "l2_repairs": 0,
                    "l3_fallbacks": 0,
                },
            )
            for key in ("calls", "successful", "fallbacks"):
                target[key] += stats.get(key, 0)
        for item in game.get("traces", []):
            task_stats = task_totals[item["task"]]
            if (
                item.get("success", False)
                and item.get("retry_count", 0) == 0
                and not item.get("fallback_used", False)
            ):
                task_stats["first_attempt_successes"] += 1
            if item.get("final_complexity_level") == "l2_minimal_repair":
                task_stats["l2_repairs"] += 1
            if item.get("final_complexity_level") == "l3_deterministic":
                task_stats["l3_fallbacks"] += 1
        rows.append(
            {
                "seed": game["seed"],
                "status": game.get("status"),
                "winner": winner,
                "win_reason": game.get("win_reason"),
                "days": game.get("days", 0),
                "events": game.get("event_count", 0),
                **values,
                "replay": game.get("replay_output"),
                "gameplay": game.get("gameplay_metrics"),
            },
        )
        for key in GAMEPLAY_COUNT_KEYS:
            gameplay_totals[key] += game.get("gameplay_metrics", {}).get(key, 0)

    completed = len(games)
    terminal = winners["good"] + winners["werewolf"]
    averages = {
        "days": _average(row["days"] for row in rows),
        "events": _average(row["events"] for row in rows),
        "decisions": _average(row["decisions"] for row in rows),
        "model_latency_ms": _average(row["model_latency_ms"] for row in rows),
        "input_tokens": _average(row["input_tokens"] for row in rows),
        "output_tokens": _average(row["output_tokens"] for row in rows),
    }
    return {
        "report_version": REPORT_VERSION,
        "requested_seeds": list(requested_seeds),
        "requested_games": len(requested_seeds),
        "completed_games": completed,
        "failed_games": len(failed),
        "winner_counts": winners,
        "winner_rates": {
            "good": round(winners["good"] / terminal, 4) if terminal else None,
            "werewolf": (
                round(winners["werewolf"] / terminal, 4) if terminal else None
            ),
        },
        "totals": totals,
        "averages": averages,
        "decision_rates": {
            "success": _rate(totals["successful"], totals["decisions"]),
            "first_attempt_success": _rate(
                totals["first_attempt_successes"],
                totals["decisions"],
            ),
            "fallback": _rate(totals["fallbacks"], totals["decisions"]),
            "l2_repair": _rate(totals["l2_repairs"], totals["decisions"]),
            "l3_fallback": _rate(totals["l3_fallbacks"], totals["decisions"]),
        },
        "by_task": {
            task: {
                **stats,
                "success_rate": _rate(stats["successful"], stats["calls"]),
                "first_attempt_success_rate": _rate(
                    stats["first_attempt_successes"],
                    stats["calls"],
                ),
                "fallback_rate": _rate(stats["fallbacks"], stats["calls"]),
            }
            for task, stats in sorted(task_totals.items())
        },
        "gameplay": {
            **gameplay_totals,
            "abstention_rate": _rate(
                gameplay_totals["abstentions"],
                gameplay_totals["votes"],
            ),
            "wolf_exile_rate": _rate(
                gameplay_totals["wolf_exiles"],
                gameplay_totals["exiles"],
            ),
            "hunter_shot_rate": _rate(
                gameplay_totals["hunter_shots"],
                gameplay_totals["hunter_opportunities"],
            ),
        },
        "games": rows,
        "failures": failed,
        "measurement_notes": [
            "model_latency_ms 为各模型调用累计延迟，不等于并发场景下的墙钟时间。",
            "结构化输出失败若上游未返回 usage，token 汇总可能低估失败尝试。",
            "少量固定 seed 只用于工程稳定性评测，不代表阵营平衡结论。",
        ],
    }


def render_report(summary: dict[str, Any], config: dict[str, Any]) -> str:
    totals = summary["totals"]
    rates = summary["decision_rates"]
    winners = summary["winner_counts"]
    gameplay = summary["gameplay"]
    lines = [
        "# WolfScope 自动对局评测报告",
        "",
        f"- 报告版本：`{summary['report_version']}`",
        f"- 模型档位：`{config['model_profile']}`",
        f"- 投票上下文：`{config['vote_context_mode']}`",
        f"- Seeds：`{', '.join(map(str, summary['requested_seeds']))}`",
        f"- 完成/失败：{summary['completed_games']} / {summary['failed_games']}",
        "",
        "## 核心结果",
        "",
        f"- 好人胜利：{winners['good']} 局；狼人胜利：{winners['werewolf']} 局；未终局：{winners['unfinished']} 局。",
        f"- 玩家决策：{totals['decisions']} 次，最终成功率 {_percent(rates['success'])}，首次成功率 {_percent(rates['first_attempt_success'])}。",
        f"- L2 修复：{totals['l2_repairs']} 次（{_percent(rates['l2_repair'])}）；L3 兜底：{totals['l3_fallbacks']} 次（{_percent(rates['l3_fallback'])}）。",
        f"- Thinking / Non-thinking：{totals['thinking_calls']} / {totals['nonthinking_calls']}。",
        f"- 累计模型延迟：{totals['model_latency_ms'] / 1000:.1f} 秒；输出 tokens：{totals['output_tokens']}。",
        f"- 放逐投票弃票：{gameplay['abstentions']} / {gameplay['votes']}（{_percent(gameplay['abstention_rate'])}）。",
        f"- 放逐狼人/好人：{gameplay['wolf_exiles']} / {gameplay['good_exiles']}；猎人开枪：{gameplay['hunter_shots']} / {gameplay['hunter_opportunities']}。",
        f"- 预言家警徽交给本人已验狼人：{gameplay['seer_badge_to_checked_wolf']} 次。",
        "",
        "## 逐局结果",
        "",
        "| Seed | 状态 | 胜方 | 天数 | 决策 | L2 | L3 | 模型延迟(s) |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for game in summary["games"]:
        lines.append(
            f"| {game['seed']} | {game['status']} | {game['winner'] or '-'} | "
            f"{game['days']} | {game['decisions']} | {game['l2_repairs']} | "
            f"{game['l3_fallbacks']} | {game['model_latency_ms'] / 1000:.1f} |",
        )
    if not summary["games"]:
        lines.append("| - | - | - | - | - | - | - | - |")
    lines.extend(
        [
            "",
            "## 分任务稳定性",
            "",
            "| 任务 | 调用 | 最终成功率 | 首次成功率 | L2 | L3 |",
            "|---|---:|---:|---:|---:|---:|",
        ],
    )
    for task, stats in summary["by_task"].items():
        lines.append(
            f"| `{task}` | {stats['calls']} | "
            f"{_percent(stats['success_rate'])} | "
            f"{_percent(stats['first_attempt_success_rate'])} | "
            f"{stats['l2_repairs']} | {stats['l3_fallbacks']} |",
        )
    lines.extend(["", "## 测量说明", ""])
    lines.extend(f"- {note}" for note in summary["measurement_notes"])
    if summary["failures"]:
        lines.extend(["", "## 失败任务", ""])
        lines.extend(
            f"- Seed {item['seed']}: `{item['error_type']}` — {item['message']}"
            for item in summary["failures"]
        )
    return "\n".join(lines) + "\n"


async def run_evaluation(
    *,
    seeds: tuple[int, ...],
    output_dir: Path,
    max_days: int,
    vote_context_mode: VoteContextMode,
    model_profile: ModelProfile,
    resume: bool,
    fail_fast: bool,
) -> dict[str, Any]:
    diagnostics_dir = output_dir / "diagnostics"
    replay_dir = output_dir / "replays"
    failures_dir = output_dir / "failures"
    for path in (diagnostics_dir, replay_dir, failures_dir):
        path.mkdir(parents=True, exist_ok=True)
    config = {
        "report_version": REPORT_VERSION,
        "seeds": list(seeds),
        "max_days": max_days,
        "vote_context_mode": vote_context_mode.value,
        "model_profile": model_profile.value,
    }
    config_path = output_dir / "config.json"
    if config_path.exists():
        existing = _read_json(config_path)
        if not resume:
            raise FileExistsError(
                f"评测目录已存在：{output_dir}；请更换目录或使用 --resume",
            )
        if existing != config:
            raise ValueError("--resume 的 seeds、模型、上下文或 max-days 与原配置不一致")
    else:
        _write_json(config_path, config)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, seed in enumerate(seeds, start=1):
        diagnostic_path = diagnostics_dir / f"seed-{seed}.json"
        replay_path = replay_dir / f"seed-{seed}.json"
        if resume and diagnostic_path.exists():
            cached = _read_json(diagnostic_path)
            if cached.get("seed") == seed and cached.get("status"):
                (failures_dir / f"seed-{seed}.json").unlink(missing_ok=True)
                print(f"[{index}/{len(seeds)}] seed={seed} 已完成，跳过")
                results.append(cached)
                continue
        print(f"[{index}/{len(seeds)}] seed={seed} 开始")
        try:
            result = await run_full_game(
                seed=seed,
                max_days=max_days,
                vote_context_mode=vote_context_mode,
                replay_output=replay_path,
                model_profile=model_profile,
            )
        except Exception as error:  # noqa: BLE001 - benchmark must preserve batch
            failure = {
                "seed": seed,
                "error_type": type(error).__name__,
                "message": str(error),
            }
            failures.append(failure)
            _write_json(failures_dir / f"seed-{seed}.json", failure)
            print(f"[{index}/{len(seeds)}] seed={seed} 失败：{type(error).__name__}")
            if fail_fast:
                _write_outputs(output_dir, config, seeds, results, failures)
                raise
        else:
            if "gameplay_metrics" not in result:
                result["gameplay_metrics"] = analyze_replay(replay_path)
            _write_json(diagnostic_path, result)
            (failures_dir / f"seed-{seed}.json").unlink(missing_ok=True)
            results.append(result)
            print(
                f"[{index}/{len(seeds)}] seed={seed} 完成："
                f"winner={result.get('winner')} days={result.get('days')}",
            )
        _write_outputs(output_dir, config, seeds, results, failures)
    return _write_outputs(output_dir, config, seeds, results, failures)


def aggregate_directory(output_dir: Path) -> dict[str, Any]:
    config = _read_json(output_dir / "config.json")
    seeds = tuple(config["seeds"])
    results = []
    for path in sorted((output_dir / "diagnostics").glob("seed-*.json")):
        result = _read_json(path)
        replay_path = Path(result.get("replay_output", ""))
        if "gameplay_metrics" not in result and replay_path.is_file():
            result["gameplay_metrics"] = analyze_replay(replay_path)
            _write_json(path, result)
        results.append(result)
    failures = [
        _read_json(path)
        for path in sorted((output_dir / "failures").glob("seed-*.json"))
    ]
    return _write_outputs(output_dir, config, seeds, results, failures)


def analyze_replay(path: Path) -> dict[str, int | float | None]:
    """Extract deterministic gameplay-quality counters from one GOD replay."""

    replay = _read_json(path)
    roles = {int(seat): role for seat, role in replay["roles"].items()}
    metrics = {key: 0 for key in GAMEPLAY_COUNT_KEYS}
    seer_checks: dict[int, dict[int, str]] = {}
    for event in replay["events"]:
        event_type = event["event_type"]
        data = event.get("data", {})
        if event_type == "exile_votes":
            votes = data.get("votes", [])
            metrics["votes"] += len(votes)
            metrics["abstentions"] += sum(
                vote.get("target") is None for vote in votes
            )
        elif event_type == "player_exiled":
            metrics["exiles"] += 1
            key = "wolf_exiles" if roles[event["actor"]] == "werewolf" else "good_exiles"
            metrics[key] += 1
        elif event_type == "seer_result":
            metrics["seer_checks"] += 1
            alignment = data.get("alignment")
            if alignment == "werewolf":
                metrics["seer_wolf_checks"] += 1
            seer_checks.setdefault(event["actor"], {})[event["target"]] = alignment
        elif event_type == "witch_action":
            action = data.get("action")
            if action == "save":
                metrics["witch_saves"] += 1
            elif action == "poison":
                metrics["witch_poisons"] += 1
                target = data.get("target")
                if target is not None:
                    key = (
                        "witch_poison_wolf_hits"
                        if roles[target] == "werewolf"
                        else "witch_poison_good_hits"
                    )
                    metrics[key] += 1
        elif event_type == "hunter_shot":
            metrics["hunter_opportunities"] += 1
            metrics["hunter_shots"] += 1
            target = data["target"]
            key = "hunter_wolf_hits" if roles[target] == "werewolf" else "hunter_good_hits"
            metrics[key] += 1
        elif event_type == "hunter_did_not_shoot":
            metrics["hunter_opportunities"] += 1
        elif event_type == "badge_transferred" and roles[event["actor"]] == "seer":
            metrics["seer_badge_transfers"] += 1
            alignment = seer_checks.get(event["actor"], {}).get(event["target"])
            key = {
                "good": "seer_badge_to_checked_good",
                "werewolf": "seer_badge_to_checked_wolf",
            }.get(alignment, "seer_badge_to_unknown")
            metrics[key] += 1
    return {
        **metrics,
        "abstention_rate": _rate(metrics["abstentions"], metrics["votes"]),
        "wolf_exile_rate": _rate(metrics["wolf_exiles"], metrics["exiles"]),
        "hunter_shot_rate": _rate(
            metrics["hunter_shots"],
            metrics["hunter_opportunities"],
        ),
    }


def _write_outputs(
    output_dir: Path,
    config: dict[str, Any],
    seeds: tuple[int, ...],
    results: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = aggregate_games(results, requested_seeds=seeds, failures=failures)
    _write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(
        render_report(summary, config),
        encoding="utf-8",
    )
    return summary


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _average(values: Iterable[int | float]) -> float | None:
    items = list(values)
    return round(mean(items), 2) if items else None


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _percent(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "-"


def _default_output_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("artifacts/evaluation") / f"run-{stamp}"


def main() -> None:
    parser = argparse.ArgumentParser(description="WolfScope 完整 Agent 对局自动评测")
    seed_group = parser.add_mutually_exclusive_group()
    seed_group.add_argument("--seeds", type=parse_seeds, help="逗号分隔的固定 seeds")
    seed_group.add_argument("--games", type=int, help="从 start-seed 开始的局数")
    parser.add_argument("--start-seed", type=int, default=1)
    parser.add_argument("--max-days", type=int, default=8)
    parser.add_argument(
        "--vote-context-mode",
        choices=tuple(item.value for item in VoteContextMode),
        default=VoteContextMode.BALANCED.value,
    )
    parser.add_argument(
        "--model-profile",
        choices=tuple(item.value for item in ModelProfile),
        default=ModelProfile.PRODUCTION.value,
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument(
        "--aggregate-only",
        action="store_true",
        help="不调用 API，只从 output-dir 重新生成汇总",
    )
    args = parser.parse_args()
    output_dir = args.output_dir or _default_output_dir()
    if args.aggregate_only:
        if args.output_dir is None:
            parser.error("--aggregate-only 必须提供 --output-dir")
        summary = aggregate_directory(output_dir)
    else:
        games = args.games if args.games is not None else 3
        if games < 1:
            parser.error("--games 必须大于 0")
        seeds = args.seeds or tuple(range(args.start_seed, args.start_seed + games))
        summary = asyncio.run(
            run_evaluation(
                seeds=seeds,
                output_dir=output_dir,
                max_days=args.max_days,
                vote_context_mode=VoteContextMode(args.vote_context_mode),
                model_profile=ModelProfile(args.model_profile),
                resume=args.resume,
                fail_fast=args.fail_fast,
            ),
        )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "completed_games": summary["completed_games"],
                "failed_games": summary["failed_games"],
                "summary": str(output_dir / "summary.json"),
                "report": str(output_dir / "report.md"),
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


if __name__ == "__main__":
    main()
