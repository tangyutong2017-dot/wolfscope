"""Minimal AgentScope 2.0.5 integration spike.

The spike proves that a player-scoped, read-only tool can be registered on an
AgentScope Agent without giving that tool access to the god state. It does not
call a remote model unless a later executable explicitly invokes ``reply``.
"""

from __future__ import annotations

from typing import Any

from agentscope.agent import Agent, ReActConfig
from agentscope.credential import DeepSeekCredential
from agentscope.model import DeepSeekChatModel
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import FunctionTool, Toolkit
from pydantic import SecretStr

from .contracts import PlayerView


class ReadOnlyFunctionTool(FunctionTool):
    """FunctionTool variant explicitly allowed because it cannot mutate state."""

    def __init__(self, func: Any) -> None:
        super().__init__(func=func, is_read_only=True)

    async def check_permissions(self, *_args: Any, **_kwargs: Any) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="WolfScope player tools are immutable, player-scoped views.",
        )


def build_player_toolkit(view: PlayerView) -> Toolkit:
    """Build tools closed over one immutable PlayerView, never the god state."""

    snapshot = view.model_copy(deep=True)

    def get_public_facts() -> dict[str, Any]:
        """Return facts currently visible to this player and no hidden facts."""

        return {
            "viewer_seat": snapshot.viewer_seat,
            "view_revision": snapshot.view_revision,
            "ruleset": snapshot.ruleset,
            "day": snapshot.day,
            "phase": snapshot.phase.value,
            "alive_seats": [player.seat for player in snapshot.players if player.alive],
            "visible_events": [event.model_dump(mode="json") for event in snapshot.visible_events],
        }

    return Toolkit(tools=[ReadOnlyFunctionTool(get_public_facts)])


def build_player_agent(view: PlayerView, api_key: str) -> Agent:
    """Construct, but do not execute, one AgentScope player Agent."""

    model = DeepSeekChatModel(
        credential=DeepSeekCredential(api_key=SecretStr(api_key)),
        model="deepseek-chat",
        parameters=DeepSeekChatModel.Parameters(
            temperature=0.3,
            max_tokens=800,
        ),
        stream=True,
    )
    return Agent(
        name=f"player-{view.viewer_seat}",
        system_prompt=(
            f"你是狼人杀 {view.viewer_seat} 号玩家，身份是 {view.own_role}。"
            "只能依据工具返回的玩家视图分析，不得猜测或索取上帝状态。"
        ),
        model=model,
        toolkit=build_player_toolkit(view),
        react_config=ReActConfig(max_iters=4),
    )
