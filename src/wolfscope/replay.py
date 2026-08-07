"""Minimal deterministic GOD-view JSON replay persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .contracts import GameEvent, Seat, StrictModel
from .game.engine import GameResult, GameRunStatus
from .game.types import Camp, RoleType, WinReason


class ReplayDocument(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    game_id: str = Field(min_length=1)
    seed: int
    status: GameRunStatus
    winner: Camp | None
    win_reason: WinReason | None
    days: int = Field(ge=1)
    roles: dict[Seat, RoleType]
    final_alive: tuple[Seat, ...]
    events: tuple[GameEvent, ...]

    @model_validator(mode="after")
    def result_and_events_are_consistent(self) -> ReplayDocument:
        ids = [event.event_id for event in self.events]
        if ids != list(range(1, len(ids) + 1)):
            raise ValueError("replay event IDs must be continuous from one")
        if self.status is GameRunStatus.FINISHED:
            if self.winner is None or self.win_reason is None:
                raise ValueError("finished replay requires winner and win_reason")
        elif self.winner is not None or self.win_reason is not None:
            raise ValueError("unfinished replay cannot contain a winner")
        if set(self.roles) != set(range(1, 10)):
            raise ValueError("replay must contain roles for seats 1 through 9")
        if not set(self.final_alive).issubset(self.roles):
            raise ValueError("final_alive contains an unknown seat")
        return self

    @classmethod
    def from_result(cls, result: GameResult) -> ReplayDocument:
        return cls(
            game_id=result.game_id,
            seed=result.seed,
            status=result.status,
            winner=result.winner,
            win_reason=result.win_reason,
            days=result.days,
            roles=dict(result.roles),
            final_alive=result.final_alive,
            events=result.events,
        )


class ReplayWriter:
    @staticmethod
    def write(
        result: GameResult,
        path: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        destination = Path(path)
        if destination.exists() and not overwrite:
            raise FileExistsError(f"replay already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        document = ReplayDocument.from_result(result)
        payload = json.dumps(
            document.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        return destination

    @staticmethod
    def read(path: str | Path) -> ReplayDocument:
        payload = Path(path).read_text(encoding="utf-8")
        return ReplayDocument.model_validate_json(payload)
