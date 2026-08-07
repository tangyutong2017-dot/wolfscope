"""Game-domain message routing with explicit visibility rules."""

from __future__ import annotations

from collections.abc import Collection, Iterable

from .contracts import GameEvent, Visibility


class GameMessageRouter:
    """Projects the god event stream into one seat's authorized event stream."""

    def __init__(self, wolf_seats: Collection[int]) -> None:
        self._wolf_seats = frozenset(wolf_seats)

    def visible_to(self, event: GameEvent, seat: int) -> bool:
        match event.visibility:
            case Visibility.PUBLIC:
                return True
            case Visibility.WOLVES:
                return seat in self._wolf_seats
            case Visibility.PRIVATE:
                return seat in event.recipients
            case Visibility.GOD:
                return False
        return False

    def project(self, events: Iterable[GameEvent], seat: int) -> tuple[GameEvent, ...]:
        return tuple(event for event in events if self.visible_to(event, seat))
