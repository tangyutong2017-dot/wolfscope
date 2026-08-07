"""Top-level M1 game engine that composes the deterministic phase engines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from wolfscope.contracts import GameEvent, Visibility

from .day import DayActionProvider, DayEngine
from .events import EventLog
from .night import NightActionProvider, NightEngine
from .resolution import DeathResolutionProvider
from .sheriff import DawnAnnouncementEngine, SheriffActionProvider, SheriffElectionEngine
from .state import GameState
from .types import Camp, Phase, RoleType, WinReason


class GameRunStatus(StrEnum):
    FINISHED = "finished"
    MAX_DAYS_REACHED = "max_days_reached"


class GameActionProvider(
    NightActionProvider,
    SheriffActionProvider,
    DayActionProvider,
    DeathResolutionProvider,
    Protocol,
):
    """One adapter implementing every role-scoped phase decision protocol."""


@dataclass(frozen=True, slots=True)
class GameResult:
    game_id: str
    seed: int
    status: GameRunStatus
    winner: Camp | None
    win_reason: WinReason | None
    days: int
    roles: tuple[tuple[int, RoleType], ...]
    final_alive: tuple[int, ...]
    events: tuple[GameEvent, ...]


class GameEngine:
    """Own phase ordering and day advancement; delegate all rules and choices."""

    def __init__(
        self,
        state: GameState,
        provider: GameActionProvider,
        events: EventLog | None = None,
        *,
        max_days: int = 20,
        game_id: str | None = None,
    ) -> None:
        if max_days < 1:
            raise ValueError("max_days must be at least one")
        self.state = state
        self.provider = provider
        self.events = events if events is not None else EventLog()
        self.max_days = max_days
        self.game_id = game_id or f"seed-{state.seed}"

    async def run(self) -> GameResult:
        if self.state.phase is not Phase.SETUP:
            raise RuntimeError("GameEngine can only start from setup")
        self._emit_start_events()

        # First night is deliberately separate: election happens while the
        # internally resolved night deaths are still hidden from every player.
        await NightEngine(self.state, self.events).run(self.provider)
        await SheriffElectionEngine(self.state, self.events).run(self.provider)
        await DawnAnnouncementEngine(self.state, self.events).announce_and_resolve(
            self.provider,
        )
        if self.state.winner is not None:
            return self._result(GameRunStatus.FINISHED)

        await self._run_day()
        if self.state.winner is not None:
            return self._result(GameRunStatus.FINISHED)
        self.state.day += 1

        while self.state.day <= self.max_days:
            await NightEngine(self.state, self.events).run(self.provider)
            await DawnAnnouncementEngine(self.state, self.events).announce_and_resolve(
                self.provider,
            )
            if self.state.winner is not None:
                return self._result(GameRunStatus.FINISHED)

            await self._run_day()
            if self.state.winner is not None:
                return self._result(GameRunStatus.FINISHED)
            self.state.day += 1

        self.state.phase = Phase.FINISHED
        self.events.emit(
            day=self.state.day,
            phase=Phase.FINISHED,
            event_type="game_run_limit_reached",
            visibility=Visibility.PUBLIC,
            content=f"达到运行保护上限 {self.max_days} 天，对局未产生规则胜负",
            data={"max_days": self.max_days},
        )
        return self._result(GameRunStatus.MAX_DAYS_REACHED)

    async def _run_day(self) -> None:
        engine = DayEngine(self.state, self.events)
        outcome = await engine.run(self.provider)
        await engine.resolve_death_chain(outcome, self.provider)

    def _emit_start_events(self) -> None:
        self.events.emit(
            day=self.state.day,
            phase=Phase.SETUP,
            event_type="game_started",
            visibility=Visibility.PUBLIC,
            content="九人狼人杀开始",
            data={"game_id": self.game_id, "seed": self.state.seed},
        )
        wolves = tuple(
            player.seat
            for player in self.state.players
            if player.role is RoleType.WEREWOLF
        )
        self.events.emit(
            day=self.state.day,
            phase=Phase.SETUP,
            event_type="wolf_teammates",
            visibility=Visibility.WOLVES,
            content="狼队成员：" + "、".join(f"{seat}号" for seat in wolves),
            data={"seats": list(wolves)},
        )
        self.events.emit(
            day=self.state.day,
            phase=Phase.SETUP,
            event_type="initial_roles",
            visibility=Visibility.GOD,
            content="初始身份已确定",
            data={
                "roles": [
                    {"seat": player.seat, "role": player.role.value}
                    for player in self.state.players
                ],
            },
        )

    def _result(self, status: GameRunStatus) -> GameResult:
        return GameResult(
            game_id=self.game_id,
            seed=self.state.seed,
            status=status,
            winner=self.state.winner,
            win_reason=self.state.win_reason,
            days=min(self.state.day, self.max_days),
            roles=tuple((player.seat, player.role) for player in self.state.players),
            final_alive=tuple(self.state.alive_seats()),
            events=self.events.events,
        )
