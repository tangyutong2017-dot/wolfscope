"""Opt-in live DeepSeek smoke tests; never loaded by automated tests."""

from __future__ import annotations

import argparse
import asyncio
import json

from wolfscope.agents.runtime import PlayerRuntime
from wolfscope.agents.schemas import (
    AgentDecisionInput,
    DecisionTask,
    PublicGameSummary,
    SpeechDecision,
    SpeechTaskObservation,
    VoteDecision,
    VoteTaskObservation,
)
from wolfscope.contracts import Visibility
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.day import ExileVoteRound
from wolfscope.game.events import EventLog
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


def main() -> None:
    parser = argparse.ArgumentParser(description="WolfScope opt-in live smoke")
    parser.add_argument("scenario", choices=("speech", "vote"))
    args = parser.parse_args()
    if args.scenario == "speech":
        print(json.dumps(asyncio.run(run_speech()), ensure_ascii=False, indent=2))
    elif args.scenario == "vote":
        print(json.dumps(asyncio.run(run_vote()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
