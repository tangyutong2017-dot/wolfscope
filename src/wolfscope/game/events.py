"""Append-only game event storage.

The engine owns event creation and sequence numbers. Player views receive only
the projection produced by ``GameMessageRouter``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from wolfscope.contracts import GameEvent, Visibility

from .types import Phase


class EventLog:
    def __init__(self) -> None:
        self._events: list[GameEvent] = []

    def __iter__(self) -> Iterator[GameEvent]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)

    @property
    def events(self) -> tuple[GameEvent, ...]:
        return tuple(self._events)

    def emit(
        self,
        *,
        day: int,
        phase: Phase,
        event_type: str,
        visibility: Visibility,
        recipients: tuple[int, ...] = (),
        actor: int | None = None,
        target: int | None = None,
        content: str = "",
        data: dict[str, Any] | None = None,
    ) -> GameEvent:
        event = GameEvent(
            event_id=len(self._events) + 1,
            day=day,
            phase=phase,
            event_type=event_type,
            visibility=visibility,
            recipients=recipients,
            actor=actor,
            target=target,
            content=content,
            data=data or {},
        )
        self._events.append(event)
        return event
