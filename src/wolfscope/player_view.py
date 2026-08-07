"""Build immutable player-authorized snapshots from the GOD state and event log."""

from __future__ import annotations

from .contracts import (
    HunterPrivateState,
    OwnRoleState,
    PlayerView,
    PublicPlayer,
    SeerPrivateState,
    VillagerPrivateState,
    WerewolfPrivateState,
    WitchPrivateState,
)
from .game.events import EventLog
from .game.state import GameState
from .game.types import RoleType
from .message_router import GameMessageRouter


class DeadPlayerViewError(ValueError):
    """Raised when current live-game information is requested for a dead seat."""


class ViewRevisionError(ValueError):
    """Raised when a local event reference does not match the latest built view."""


class PlayerViewBuilder:
    def __init__(self, state: GameState, events: EventLog) -> None:
        self.state = state
        self.events = events
        self._source_event_ids: dict[int, tuple[int, ...]] = {}

    def build(self, viewer_seat: int) -> PlayerView:
        return self._build(viewer_seat, allow_dead=False)

    def build_terminal_action(self, viewer_seat: int) -> PlayerView:
        """Build a scoped view only while Engine is resolving this dead actor."""

        return self._build(viewer_seat, allow_dead=True)

    def _build(self, viewer_seat: int, *, allow_dead: bool) -> PlayerView:
        viewer = self.state.get_player(viewer_seat)
        if not viewer.alive and not allow_dead:
            raise DeadPlayerViewError(
                f"cannot build a current player view for dead seat {viewer_seat}",
            )
        wolves = {
            player.seat
            for player in self.state.players
            if player.role is RoleType.WEREWOLF
        }
        visible = GameMessageRouter(wolves).project(self.events.events, viewer_seat)
        source_ids = tuple(event.event_id for event in visible)
        local_events = []
        for local_id, event in enumerate(visible, start=1):
            copied = event.model_copy(deep=True)
            copied.event_id = local_id
            local_events.append(copied)
        self._source_event_ids[viewer_seat] = source_ids
        return PlayerView(
            viewer_seat=viewer_seat,
            view_revision=len(local_events),
            ruleset=self.state.rules.ruleset_id,
            day=self.state.day,
            phase=self.state.phase,
            own_role=viewer.role,
            own_role_state=self._private_state(viewer.role),
            players=tuple(
                PublicPlayer(
                    seat=player.seat,
                    alive=player.alive,
                    is_sheriff=self.state.sheriff.holder == player.seat,
                )
                for player in self.state.players
            ),
            visible_events=tuple(local_events),
        )

    def source_event_id(
        self,
        viewer_seat: int,
        view_event_id: int,
        *,
        view_revision: int,
    ) -> int:
        """Resolve a player-local reference without exposing the mapping to Agent input."""

        mapping = self._source_event_ids.get(viewer_seat)
        if mapping is None or len(mapping) != view_revision:
            raise ViewRevisionError("player view revision is missing or stale")
        if not 1 <= view_event_id <= len(mapping):
            raise ViewRevisionError("view event ID is outside the current revision")
        return mapping[view_event_id - 1]

    def _private_state(self, role: RoleType) -> OwnRoleState:
        if role is RoleType.WEREWOLF:
            return WerewolfPrivateState(
                teammate_seats=tuple(
                    player.seat
                    for player in self.state.players
                    if player.role is RoleType.WEREWOLF
                ),
            )
        if role is RoleType.SEER:
            return SeerPrivateState(
                checked_seats=tuple(sorted(self.state.seer.checked_seats)),
            )
        if role is RoleType.WITCH:
            return WitchPrivateState(
                antidote_available=self.state.witch.antidote_available,
                poison_available=self.state.witch.poison_available,
            )
        if role is RoleType.HUNTER:
            return HunterPrivateState(gun_available=self.state.hunter.gun_available)
        return VillagerPrivateState()
