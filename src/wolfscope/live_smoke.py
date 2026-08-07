"""Opt-in live DeepSeek smoke tests; never loaded by automated tests."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from wolfscope.agents.runtime import PlayerRuntime
from wolfscope.agents.agent_game import AgentGameProvider
from wolfscope.agents.runtime import PlayerRuntimeRegistry
from wolfscope.agents.schemas import (
    AgentDecisionInput,
    DecisionTask,
    PublicGameSummary,
    SpeechDecision,
    SpeechTaskObservation,
    VoteDecision,
    VoteTaskObservation,
    VoteContextMode,
)
from wolfscope.cognition.claims import SpeechExtractionItem
from wolfscope.cognition.claims import CheckClaim, ClaimAlignment
from wolfscope.cognition.context import EvidenceContextBuilder
from wolfscope.cognition.extraction import (
    EvidencePipeline,
    PublicSpeechAnnotationCache,
)
from wolfscope.cognition.ledger import EvidenceLedgerRegistry
from wolfscope.cognition.ledger import EvidenceLedger
from wolfscope.contracts import Visibility
from wolfscope.game import DeathCause, GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.day import ExileVoteRound
from wolfscope.game.events import EventLog
from wolfscope.game.engine import GameEngine
from wolfscope.game.factory import GameFactory
from wolfscope.game.night import NightEngine
from wolfscope.game.sheriff import SheriffElectionEngine
from wolfscope.game.types import Phase
from wolfscope.game.resolution import DeathResolutionEngine
from wolfscope.models.agentscope_gateway import AgentScopeModelGateway
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.claim_extractor import AgentScopePublicClaimExtractor
from wolfscope.player_view import PlayerViewBuilder
from wolfscope.replay import ReplayWriter


def _terminal_result(result: dict[str, Any], *, summary_only: bool) -> dict[str, Any]:
    """Keep costly live traces on disk while making terminal output readable."""
    if not summary_only:
        return result
    return {
        key: value
        for key, value in result.items()
        if key not in {"traces", "extraction_traces"}
    }


def _emit_result(
    result: dict[str, Any],
    *,
    output: Path | None,
    summary_only: bool,
) -> None:
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")
    print(
        json.dumps(
            _terminal_result(result, summary_only=summary_only),
            ensure_ascii=False,
            indent=2,
        ),
    )


def _speech_input() -> AgentDecisionInput:
    state = GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
        phase=Phase.DAY_SPEECH,
    )
    events = EventLog()
    events.emit(
        day=1,
        phase=Phase.DAY_SPEECH,
        event_type="day_speech",
        visibility=Visibility.PUBLIC,
        actor=1,
        content="1号认为首轮信息较少，希望后置位提供更多判断。",
    )
    view = PlayerViewBuilder(state, events).build(4)
    return AgentDecisionInput(
        player_view=view,
        public_summary=PublicGameSummary.from_view(view),
        observation=SpeechTaskObservation(
            actor=4,
            speaking_order=tuple(range(1, 10)),
            previous_speeches=((1, "1号认为首轮信息较少，希望后置位提供更多判断。"),),
            can_explode=False,
        ),
    )


def _evidence_speech_input() -> AgentDecisionInput:
    state = GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
        phase=Phase.DAY_SPEECH,
    )
    events = EventLog()
    events.emit(
        day=1,
        phase=Phase.DAY_SPEECH,
        event_type="day_speech",
        visibility=Visibility.PUBLIC,
        actor=7,
        content="我是7号预言家，昨夜查验1号是狼人。",
    )
    view = PlayerViewBuilder(state, events).build(4)
    ledger = EvidenceLedger(owner=4)
    ledger.sync(view)
    speech_event = next(
        event for event in view.visible_events if event.event_type == "day_speech"
    )
    ledger.ingest_public_claims(
        event=speech_event,
        speaker=7,
        claims=(
            CheckClaim(
                target=1,
                night=1,
                result=ClaimAlignment.WEREWOLF,
                summary="7号声称首夜查验1号为狼人",
                supporting_text="昨夜查验1号是狼人",
            ),
        ),
        extractor_version="live-smoke",
    )
    return AgentDecisionInput(
        player_view=view,
        public_summary=PublicGameSummary.from_view(view),
        observation=SpeechTaskObservation(
            actor=4,
            speaking_order=tuple(range(1, 10)),
            previous_speeches=((7, "我是7号预言家，昨夜查验1号是狼人。"),),
            can_explode=False,
        ),
        evidence_context=EvidenceContextBuilder().build(ledger),
    )


def _vote_input() -> AgentDecisionInput:
    state = GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
        phase=Phase.DAY_VOTE,
    )
    speeches = (
        (1, "我是预言家，昨夜查验7号是狼人，今天请全票放逐7号。"),
        (2, "我更相信1号的发言，今天倾向投7号。"),
        (3, "1号没有讲清楚警徽流，我认为1号的预言家面偏低。"),
        (7, "我才是预言家，昨夜查验1号是狼人，1号是在悍跳。"),
    )
    events = EventLog()
    for actor, speech in speeches:
        events.emit(
            day=1,
            phase=Phase.DAY_SPEECH,
            event_type="day_speech",
            visibility=Visibility.PUBLIC,
            actor=actor,
            content=speech,
        )
    view = PlayerViewBuilder(state, events).build(4)
    return AgentDecisionInput(
        player_view=view,
        public_summary=PublicGameSummary.from_view(view),
        observation=VoteTaskObservation(
            voter=4,
            vote_round=ExileVoteRound.FIRST,
            candidates=(1, 7),
            speeches=speeches,
        ),
    )


async def run_speech() -> dict:
    config = model_config_for(ModelProfile.TEST)
    gateway = AgentScopeModelGateway.from_environment(config)
    runtime = PlayerRuntime(4, config, gateway)
    decision = await runtime.decide(
        task=DecisionTask.SPEECH,
        decision_input=_speech_input(),
        output_schema=SpeechDecision,
        use_safe_fallback=False,
    )
    return {
        "decision": decision.model_dump(mode="json"),
        "trace": runtime.call_records[-1].model_dump(mode="json"),
    }


async def run_evidence_speech() -> dict:
    config = model_config_for(ModelProfile.TEST)
    gateway = AgentScopeModelGateway.from_environment(config)
    runtime = PlayerRuntime(4, config, gateway)
    decision_input = _evidence_speech_input()
    decision = await runtime.decide(
        task=DecisionTask.SPEECH,
        decision_input=decision_input,
        output_schema=SpeechDecision,
        use_safe_fallback=False,
    )
    return {
        "available_evidence_ids": list(decision_input.evidence_context.evidence_ids),
        "decision": decision.model_dump(mode="json"),
        "trace": runtime.call_records[-1].model_dump(mode="json"),
    }


async def run_vote() -> dict:
    config = model_config_for(ModelProfile.TEST)
    gateway = AgentScopeModelGateway.from_environment(config)
    runtime = PlayerRuntime(4, config, gateway)
    decision = await runtime.decide(
        task=DecisionTask.VOTE,
        decision_input=_vote_input(),
        output_schema=VoteDecision,
        use_safe_fallback=False,
    )
    return {
        "decision": decision.model_dump(mode="json"),
        "trace": runtime.call_records[-1].model_dump(mode="json"),
    }


async def run_hybrid_day(
    vote_context_mode: VoteContextMode = VoteContextMode.FULL,
) -> dict:
    config = model_config_for(ModelProfile.TEST)
    state = GameState(
        seed=42,
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )
    events = EventLog()
    runtimes = PlayerRuntimeRegistry.create(
        config,
        lambda _seat: AgentScopeModelGateway.from_environment(config),
    )
    view_builder = PlayerViewBuilder(state, events)
    claim_extractor = AgentScopePublicClaimExtractor.from_environment(config)
    annotation_cache = PublicSpeechAnnotationCache()
    ledgers = EvidenceLedgerRegistry()
    provider = AgentGameProvider(
        view_builder=view_builder,
        runtimes=runtimes,
        evidence_pipeline=EvidencePipeline(
            ledgers=ledgers,
            cache=annotation_cache,
            extractor=claim_extractor,
            source_resolver=view_builder,
        ),
        vote_context_mode=vote_context_mode,
    )
    result = await GameEngine(
        state,
        provider,
        events,
        max_days=1,
        game_id="m2-hybrid-flash-day-1",
    ).run()
    records = [
        record
        for seat in runtimes.seats
        for record in runtimes.get(seat).call_records
    ]
    extraction_records = claim_extractor.traces
    return {
        "game_id": result.game_id,
        "vote_context_mode": vote_context_mode.value,
        "status": result.status.value,
        "winner": result.winner.value if result.winner else None,
        "win_reason": result.win_reason.value if result.win_reason else None,
        "final_alive": list(result.final_alive),
        "speeches": [
            {"seat": event.actor, "content": event.content}
            for event in result.events
            if event.event_type == "day_speech"
        ],
        "votes": next(
            (
                event.data.get("votes", [])
                for event in result.events
                if event.event_type == "exile_votes"
            ),
            [],
        ),
        "trace_summary": {
            "calls": len(records),
            "successful": sum(record.success for record in records),
            "fallbacks": sum(record.fallback_used for record in records),
            "input_tokens": sum(
                record.token_usage.input_tokens for record in records
            ),
            "output_tokens": sum(
                record.token_usage.output_tokens for record in records
            ),
            "latency_ms": sum(record.latency_ms for record in records),
            "brief_evidence_references": sum(
                len(record.accepted_brief_evidence_ids) for record in records
            ),
            "context_only_evidence_references": sum(
                len(record.accepted_context_only_evidence_ids)
                for record in records
            ),
            "strategy_references": sum(
                len(record.accepted_strategy_ids) for record in records
            ),
            "invalid_strategy_references": sum(
                len(record.invalid_strategy_ids) for record in records
            ),
        },
        "extraction_summary": {
            "calls": len(extraction_records),
            "successful": sum(record.success for record in extraction_records),
            "annotations": len(annotation_cache),
            "claims": sum(
                len(annotation.claims) for annotation in annotation_cache.values
            ),
            "input_tokens": sum(
                record.token_usage.input_tokens for record in extraction_records
            ),
            "output_tokens": sum(
                record.token_usage.output_tokens for record in extraction_records
            ),
            "latency_ms": sum(record.latency_ms for record in extraction_records),
            "evidence_by_seat": {
                str(seat): len(ledgers.get(seat).records)
                for seat in ledgers.seats
            },
        },
        "traces": [record.model_dump(mode="json") for record in records],
        "extraction_traces": [
            record.model_dump(mode="json") for record in extraction_records
        ],
    }


async def run_sheriff_election() -> dict:
    config = model_config_for(ModelProfile.TEST)
    state = GameState(
        seed=42,
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )
    events = EventLog()
    runtimes = PlayerRuntimeRegistry.create(
        config,
        lambda _seat: AgentScopeModelGateway.from_environment(config),
    )
    provider = AgentGameProvider(
        view_builder=PlayerViewBuilder(state, events),
        runtimes=runtimes,
    )
    result = await SheriffElectionEngine(state, events).run(provider)
    records = [
        record
        for seat in runtimes.seats
        for record in runtimes.get(seat).call_records
    ]
    return {
        "scenario": "sheriff-election",
        "model": config.model_name,
        "original_candidates": list(result.original_candidates),
        "remaining_candidates": list(result.remaining_candidates),
        "withdrawn": list(result.withdrawn),
        "speech_order": list(result.speech_order),
        "speeches": [
            {"seat": seat, "content": content}
            for seat, content in result.speeches
        ],
        "votes": [
            {"voter": voter, "target": target}
            for voter, target in result.votes
        ],
        "sheriff": result.sheriff,
        "reason": result.reason,
        "trace_summary": {
            "calls": len(records),
            "successful": sum(record.success for record in records),
            "fallbacks": sum(record.fallback_used for record in records),
            "input_tokens": sum(
                record.token_usage.input_tokens for record in records
            ),
            "output_tokens": sum(
                record.token_usage.output_tokens for record in records
            ),
            "latency_ms": sum(record.latency_ms for record in records),
            "strategy_references": sum(
                len(record.accepted_strategy_ids) for record in records
            ),
            "invalid_strategy_references": sum(
                len(record.invalid_strategy_ids) for record in records
            ),
        },
        "traces": [record.model_dump(mode="json") for record in records],
    }


async def run_night_actions() -> dict:
    config = model_config_for(ModelProfile.TEST)
    state = GameState(
        seed=42,
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )
    events = EventLog()
    runtimes = PlayerRuntimeRegistry.create(
        config,
        lambda _seat: AgentScopeModelGateway.from_environment(config),
    )
    provider = AgentGameProvider(
        view_builder=PlayerViewBuilder(state, events),
        runtimes=runtimes,
    )
    result = await NightEngine(state, events).run(provider)
    records = [
        record
        for seat in runtimes.seats
        for record in runtimes.get(seat).call_records
    ]
    return {
        "scenario": "night-actions",
        "model": config.model_name,
        "actions": {
            "wolf_target": result.actions.wolf_target,
            "seer_target": result.actions.seer_target,
            "witch_action": result.actions.witch_action.action.value,
            "witch_target": result.actions.witch_action.target,
        },
        "pending_deaths": [
            {
                "seat": death.seat,
                "causes": sorted(cause.value for cause in death.causes),
            }
            for death in result.pending_deaths
        ],
        "wolf_team_plan": (
            provider.wolf_team_plan.model_dump(mode="json")
            if provider.wolf_team_plan is not None
            else None
        ),
        "trace_summary": {
            "calls": len(records),
            "successful": sum(record.success for record in records),
            "fallbacks": sum(record.fallback_used for record in records),
            "input_tokens": sum(
                record.token_usage.input_tokens for record in records
            ),
            "output_tokens": sum(
                record.token_usage.output_tokens for record in records
            ),
            "latency_ms": sum(record.latency_ms for record in records),
            "strategy_references": sum(
                len(record.accepted_strategy_ids) for record in records
            ),
            "invalid_strategy_references": sum(
                len(record.invalid_strategy_ids) for record in records
            ),
        },
        "traces": [record.model_dump(mode="json") for record in records],
    }


async def run_terminal_actions() -> dict:
    config = model_config_for(ModelProfile.TEST)
    state = GameState(
        seed=42,
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )
    events = EventLog()
    state.sheriff.holder = 9
    state.sheriff.election_completed = True
    state.mark_dead(9, DeathCause.WEREWOLF)
    state.phase = Phase.DAWN_ANNOUNCEMENT
    events.emit(
        day=1,
        phase=Phase.DAWN_ANNOUNCEMENT,
        event_type="dawn_deaths",
        visibility=Visibility.PUBLIC,
        content="昨夜9号死亡",
        data={"deaths": [9]},
    )
    runtimes = PlayerRuntimeRegistry.create(
        config,
        lambda _seat: AgentScopeModelGateway.from_environment(config),
    )
    provider = AgentGameProvider(
        view_builder=PlayerViewBuilder(state, events),
        runtimes=runtimes,
    )
    result = await DeathResolutionEngine(state, events).resolve(
        (9,),
        provider,
        last_words_seats=(9,),
    )
    records = list(runtimes.get(9).call_records)
    return {
        "scenario": "terminal-actions",
        "model": config.model_name,
        "last_words": [
            {"seat": seat, "content": content}
            for seat, content in result.last_words
        ],
        "hunter_target": result.hunter_target,
        "badge_holder": result.badge_holder,
        "badge_destroyed": result.badge_destroyed,
        "all_deaths": list(result.all_deaths),
        "trace_summary": {
            "calls": len(records),
            "successful": sum(record.success for record in records),
            "fallbacks": sum(record.fallback_used for record in records),
            "input_tokens": sum(
                record.token_usage.input_tokens for record in records
            ),
            "output_tokens": sum(
                record.token_usage.output_tokens for record in records
            ),
            "latency_ms": sum(record.latency_ms for record in records),
            "strategy_references": sum(
                len(record.accepted_strategy_ids) for record in records
            ),
            "invalid_strategy_references": sum(
                len(record.invalid_strategy_ids) for record in records
            ),
        },
        "traces": [record.model_dump(mode="json") for record in records],
    }


async def run_full_game(
    *,
    seed: int,
    max_days: int,
    vote_context_mode: VoteContextMode,
    replay_output: Path | None,
    model_profile: ModelProfile,
) -> dict:
    config = model_config_for(model_profile)
    state = GameFactory.create(seed)
    events = EventLog()
    runtimes = PlayerRuntimeRegistry.create(
        config,
        lambda _seat: AgentScopeModelGateway.from_environment(config),
    )
    view_builder = PlayerViewBuilder(state, events)
    claim_extractor = AgentScopePublicClaimExtractor.from_environment(config)
    annotation_cache = PublicSpeechAnnotationCache()
    ledgers = EvidenceLedgerRegistry()
    provider = AgentGameProvider(
        view_builder=view_builder,
        runtimes=runtimes,
        evidence_pipeline=EvidencePipeline(
            ledgers=ledgers,
            cache=annotation_cache,
            extractor=claim_extractor,
            source_resolver=view_builder,
        ),
        vote_context_mode=vote_context_mode,
    )
    result = await GameEngine(
        state,
        provider,
        events,
        max_days=max_days,
        game_id=f"m2-{config.model_name}-full-seed-{seed}",
    ).run()
    replay_path = None
    if replay_output is not None:
        replay_path = ReplayWriter.write(
            result,
            replay_output,
            overwrite=True,
        )
        ReplayWriter.read(replay_path)
    records = [
        record
        for seat in runtimes.seats
        for record in runtimes.get(seat).call_records
    ]
    extraction_records = claim_extractor.traces
    task_stats = {}
    for task in DecisionTask:
        task_records = [record for record in records if record.task is task]
        if task_records:
            task_stats[task.value] = {
                "calls": len(task_records),
                "successful": sum(record.success for record in task_records),
                "fallbacks": sum(record.fallback_used for record in task_records),
                "input_tokens": sum(
                    record.token_usage.input_tokens for record in task_records
                ),
                "output_tokens": sum(
                    record.token_usage.output_tokens for record in task_records
                ),
            }
    return {
        "scenario": "full-game",
        "game_id": result.game_id,
        "model": config.model_name,
        "model_profile": model_profile.value,
        "temperature": config.temperature,
        "seed": seed,
        "max_days": max_days,
        "vote_context_mode": vote_context_mode.value,
        "status": result.status.value,
        "winner": result.winner.value if result.winner else None,
        "win_reason": result.win_reason.value if result.win_reason else None,
        "days": result.days,
        "final_alive": list(result.final_alive),
        "event_count": len(result.events),
        "replay_output": str(replay_path) if replay_path else None,
        "provider": "AgentGameProvider",
        "legacy_support_used": False,
        "wolf_team_plans": [
            plan.model_dump(mode="json")
            for plan in provider.wolf_team_plan_history
        ],
        "trace_summary": {
            "calls": len(records),
            "successful": sum(record.success for record in records),
            "fallbacks": sum(record.fallback_used for record in records),
            "input_tokens": sum(
                record.token_usage.input_tokens for record in records
            ),
            "output_tokens": sum(
                record.token_usage.output_tokens for record in records
            ),
            "latency_ms": sum(record.latency_ms for record in records),
            "strategy_references": sum(
                len(record.accepted_strategy_ids) for record in records
            ),
            "invalid_strategy_references": sum(
                len(record.invalid_strategy_ids) for record in records
            ),
            "speech_truncations": sum(
                record.speech_truncated for record in records
            ),
            "by_task": task_stats,
        },
        "extraction_summary": {
            "calls": len(extraction_records),
            "successful": sum(record.success for record in extraction_records),
            "annotations": len(annotation_cache),
            "claims": sum(
                len(annotation.claims) for annotation in annotation_cache.values
            ),
            "input_tokens": sum(
                record.token_usage.input_tokens for record in extraction_records
            ),
            "output_tokens": sum(
                record.token_usage.output_tokens for record in extraction_records
            ),
            "latency_ms": sum(record.latency_ms for record in extraction_records),
        },
        "traces": [record.model_dump(mode="json") for record in records],
        "extraction_traces": [
            record.model_dump(mode="json") for record in extraction_records
        ],
    }


async def run_claim_extraction() -> dict:
    config = model_config_for(ModelProfile.TEST)
    extractor = AgentScopePublicClaimExtractor.from_environment(config)
    items = await extractor.extract(
        (
            SpeechExtractionItem(
                item_id="good-alignment",
                day=1,
                speaker=8,
                speech_context="day_speech",
                text="我是8号，一个好人身份。",
            ),
            SpeechExtractionItem(
                item_id="villager-role",
                day=1,
                speaker=6,
                speech_context="day_speech",
                text="我是6号，普通村民。",
            ),
            SpeechExtractionItem(
                item_id="good-check",
                day=1,
                speaker=7,
                speech_context="day_speech",
                text="我是7号预言家，昨夜查验3号是好人。",
            ),
        ),
    )
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "trace": extractor.traces[-1].model_dump(mode="json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="WolfScope opt-in live smoke")
    parser.add_argument(
        "scenario",
        choices=(
            "speech",
            "evidence-speech",
            "vote",
            "hybrid-day",
            "sheriff-election",
            "night-actions",
            "terminal-actions",
            "full-game",
            "claim-extraction",
        ),
    )
    parser.add_argument(
        "--vote-context-mode",
        choices=tuple(mode.value for mode in VoteContextMode),
        default=VoteContextMode.FULL.value,
        help="投票Prompt上下文模式；只影响 hybrid-day",
    )
    parser.add_argument("--seed", type=int, default=42, help="full-game 发牌 seed")
    parser.add_argument(
        "--max-days",
        type=int,
        default=8,
        help="full-game 的 Engine 运行保护上限",
    )
    parser.add_argument(
        "--replay-output",
        type=Path,
        help="full-game 的标准 GOD Replay JSON 路径",
    )
    parser.add_argument(
        "--model-profile",
        choices=tuple(profile.value for profile in ModelProfile),
        help="模型档位；full-game 默认 production，其余场景固定使用 test",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="将完整结果（包括 trace）写入 JSON 文件后再打印",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="终端省略 traces；与 --output 配合可避免大输出丢失",
    )
    args = parser.parse_args()
    if args.scenario == "speech":
        result = asyncio.run(run_speech())
    elif args.scenario == "evidence-speech":
        result = asyncio.run(run_evidence_speech())
    elif args.scenario == "vote":
        result = asyncio.run(run_vote())
    elif args.scenario == "hybrid-day":
        result = asyncio.run(
            run_hybrid_day(VoteContextMode(args.vote_context_mode)),
        )
    elif args.scenario == "claim-extraction":
        result = asyncio.run(run_claim_extraction())
    elif args.scenario == "sheriff-election":
        result = asyncio.run(run_sheriff_election())
    elif args.scenario == "night-actions":
        result = asyncio.run(run_night_actions())
    elif args.scenario == "terminal-actions":
        result = asyncio.run(run_terminal_actions())
    elif args.scenario == "full-game":
        result = asyncio.run(
            run_full_game(
                seed=args.seed,
                max_days=args.max_days,
                vote_context_mode=VoteContextMode(args.vote_context_mode),
                replay_output=args.replay_output,
                model_profile=(
                    ModelProfile(args.model_profile)
                    if args.model_profile
                    else ModelProfile.PRODUCTION
                ),
            ),
        )
    _emit_result(
        result,
        output=args.output,
        summary_only=args.summary_only,
    )


if __name__ == "__main__":
    main()
