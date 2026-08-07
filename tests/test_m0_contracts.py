from __future__ import annotations

import asyncio
import unittest

from pydantic import ValidationError

from wolfscope.agentscope_spike import build_player_toolkit
from wolfscope.contracts import (
    GameEvent,
    PlayerView,
    PublicPlayer,
    RoleBelief,
    Visibility,
    VillagerPrivateState,
)
from wolfscope.game.types import Phase, RoleType
from wolfscope.message_router import GameMessageRouter


def players() -> tuple[PublicPlayer, ...]:
    return tuple(PublicPlayer(seat=seat, alive=True) for seat in range(1, 10))


class ContractTests(unittest.TestCase):
    def test_role_probabilities_must_sum_to_one(self) -> None:
        with self.assertRaises(ValidationError):
            RoleBelief(seat=2, probabilities={"wolf": 0.8, "villager": 0.4})

    def test_private_event_requires_recipient(self) -> None:
        with self.assertRaises(ValidationError):
            GameEvent(
                event_id=1,
                day=1,
                phase=Phase.NIGHT_SEER,
                event_type="seer_result",
                visibility=Visibility.PRIVATE,
            )

    def test_router_does_not_leak_wolf_or_god_events(self) -> None:
        events = (
            GameEvent(
                event_id=1,
                day=1,
                phase=Phase.DAY_SPEECH,
                event_type="speech",
                visibility=Visibility.PUBLIC,
            ),
            GameEvent(
                event_id=2,
                day=1,
                phase=Phase.NIGHT_WOLF,
                event_type="wolf_chat",
                visibility=Visibility.WOLVES,
            ),
            GameEvent(
                event_id=3,
                day=1,
                phase=Phase.NIGHT_RESOLUTION,
                event_type="role_assignment",
                visibility=Visibility.GOD,
            ),
            GameEvent(
                event_id=4,
                day=1,
                phase=Phase.NIGHT_SEER,
                event_type="seer_result",
                visibility=Visibility.PRIVATE,
                recipients=(2,),
            ),
        )
        router = GameMessageRouter(wolf_seats={1, 5, 9})
        self.assertEqual([event.event_id for event in router.project(events, 4)], [1])
        self.assertEqual([event.event_id for event in router.project(events, 1)], [1, 2])
        self.assertEqual([event.event_id for event in router.project(events, 2)], [1, 4])

    def test_agentscope_tool_is_read_only_and_player_scoped(self) -> None:
        public = GameEvent(
            event_id=1,
            day=1,
            phase=Phase.DAY_SPEECH,
            event_type="speech",
            visibility=Visibility.PUBLIC,
            content="公开信息",
        )
        view = PlayerView(
            viewer_seat=4,
            view_revision=1,
            ruleset="standard-9-v1",
            day=1,
            phase=Phase.DAY_SPEECH,
            own_role=RoleType.VILLAGER,
            own_role_state=VillagerPrivateState(),
            players=players(),
            visible_events=(public,),
        )
        toolkit = build_player_toolkit(view)
        async def invoke() -> str:
            tool = await toolkit.get_tool("get_public_facts")
            chunk = await tool()
            self.assertTrue(tool.is_read_only)
            return chunk.content[0].text

        output = asyncio.run(invoke())
        self.assertIn("公开信息", output)
        self.assertNotIn("own_role", output)


if __name__ == "__main__":
    unittest.main()
