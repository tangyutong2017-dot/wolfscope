"""Opt-in live DeepSeek smoke tests; never loaded by automated tests."""

from __future__ import annotations

import argparse
import asyncio
import json

from wolfscope.agents.runtime import PlayerRuntime
from wolfscope.agents.hybrid import HybridProvider
from wolfscope.agents.runtime import PlayerRuntimeRegistry
from wolfscope.agents.schemas import (
    AgentDecisionInput,
    DecisionTask,
    PublicGameSummary,
    SpeechDecision,
    SpeechTaskObservation,
    VoteDecision,
    VoteTaskObservation,
)
from wolfscope.agents.support import DeterministicSupportProvider
from wolfscope.contracts import Visibility
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.day import ExileVoteRound
from wolfscope.game.events import EventLog
from wolfscope.game.engine import GameEngine
from wolfscope.game.types import Phase
from wolfscope.models.agentscope_gateway import AgentScopeModelGateway
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.player_view import PlayerViewBuilder


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


async def run_hybrid_day() -> dict:
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
    provider = HybridProvider(
        view_builder=PlayerViewBuilder(state, events),
        runtimes=runtimes,
        support=DeterministicSupportProvider(),
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
    return {
        "game_id": result.game_id,
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
        },
        "traces": [record.model_dump(mode="json") for record in records],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="WolfScope opt-in live smoke")
    parser.add_argument("scenario", choices=("speech", "vote", "hybrid-day"))
    args = parser.parse_args()
    if args.scenario == "speech":
        print(json.dumps(asyncio.run(run_speech()), ensure_ascii=False, indent=2))
    elif args.scenario == "vote":
        print(json.dumps(asyncio.run(run_vote()), ensure_ascii=False, indent=2))
    elif args.scenario == "hybrid-day":
        print(json.dumps(asyncio.run(run_hybrid_day()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
