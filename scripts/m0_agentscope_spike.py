"""Run the offline M0 AgentScope construction and tool-isolation spike."""

from __future__ import annotations

import asyncio

from wolfscope.agentscope_spike import build_player_agent, build_player_toolkit
from wolfscope.contracts import (
    GameEvent,
    PlayerView,
    PublicPlayer,
    Visibility,
    VillagerPrivateState,
)
from wolfscope.game.types import Phase, RoleType


def sample_view() -> PlayerView:
    players = tuple(PublicPlayer(seat=seat, alive=True) for seat in range(1, 10))
    return PlayerView(
        viewer_seat=4,
        view_revision=1,
        ruleset="standard-9-v1",
        day=1,
        phase=Phase.DAY_SPEECH,
        own_role=RoleType.VILLAGER,
        own_role_state=VillagerPrivateState(),
        players=players,
        visible_events=(
            GameEvent(
                event_id=1,
                day=1,
                phase=Phase.DAY_SPEECH,
                event_type="speech",
                visibility=Visibility.PUBLIC,
                actor=2,
                content="2号声称自己是预言家。",
            ),
        ),
    )


async def main() -> None:
    view = sample_view()
    toolkit = build_player_toolkit(view)
    tool = await toolkit.get_tool("get_public_facts")
    chunk = await tool()
    agent = build_player_agent(view, api_key="m0-offline-placeholder")

    assert tool.is_read_only is True
    assert "预言家" in chunk.content[0].text
    assert agent.name == "player-4"
    print("M0 spike passed: AgentScope Agent constructed; player-scoped tool returned only PlayerView facts.")


if __name__ == "__main__":
    asyncio.run(main())
