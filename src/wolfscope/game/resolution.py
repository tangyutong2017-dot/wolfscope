"""M1-5 death-chain abilities, badge transfer and terminal win checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from wolfscope.contracts import GameEvent, Visibility

from .events import EventLog
from .state import GameState
from .types import Camp, DeathCause, Faction, Phase, RoleType, WinReason


@dataclass(frozen=True, slots=True)
class DeathLastWordsObservation:
    day: int
    actor: int
    deaths: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class HunterShotObservation:
    day: int
    hunter: int
    death_cause: DeathCause
    eligible_targets: tuple[int, ...]
    last_words: str | None = None


@dataclass(frozen=True, slots=True)
class BadgeTransferObservation:
    day: int
    former_sheriff: int
    eligible_targets: tuple[int, ...]
    hunter_target: int | None = None


class DeathResolutionProvider(Protocol):
    async def death_last_words(self, observation: DeathLastWordsObservation) -> str:
        ...

    async def choose_hunter_target(self, observation: HunterShotObservation) -> int | None:
        ...

    async def choose_badge_transfer(
        self,
        observation: BadgeTransferObservation,
    ) -> int | None:
        ...


@dataclass(frozen=True, slots=True)
class DeathResolutionResult:
    initial_deaths: tuple[int, ...]
    all_deaths: tuple[int, ...]
    last_words: tuple[tuple[int, str], ...]
    hunter_target: int | None
    badge_holder: int | None
    badge_destroyed: bool
    winner: Camp | None
    win_reason: WinReason | None
    events: tuple[GameEvent, ...]


class DeathResolutionEngine:
    """Finish one already-announced death batch before checking victory."""

    def __init__(self, state: GameState, events: EventLog) -> None:
        self.state = state
        self.events = events

    async def resolve(
        self,
        deaths: tuple[int, ...],
        provider: DeathResolutionProvider,
        *,
        last_words_seats: tuple[int, ...] = (),
    ) -> DeathResolutionResult:
        if self.state.winner is not None:
            raise RuntimeError("cannot resolve deaths after the game has finished")
        initial_deaths = tuple(sorted(set(deaths)))
        if not initial_deaths:
            return self._finish((), (), (), None, False, len(self.events))
        for seat in initial_deaths:
            if self.state.get_player(seat).alive:
                raise ValueError(f"death batch contains living player {seat}")
        if not set(last_words_seats).issubset(initial_deaths):
            raise ValueError("last words can only be granted to this death batch")

        start_index = len(self.events)
        original_phase = self.state.phase
        holder = self.state.sheriff.holder
        if holder is not None and holder in initial_deaths:
            self.state.sheriff.transfer_pending_from = holder
        spoken: list[tuple[int, str]] = []
        self.state.phase = Phase.DEATH_LAST_WORDS
        for seat in sorted(set(last_words_seats)):
            words = await provider.death_last_words(
                DeathLastWordsObservation(
                    day=self.state.day,
                    actor=seat,
                    deaths=initial_deaths,
                ),
            )
            text = words.strip() if isinstance(words, str) and words.strip() else "无遗言"
            spoken.append((seat, text))
            self.events.emit(
                day=self.state.day,
                phase=Phase.DEATH_LAST_WORDS,
                event_type="last_words",
                visibility=Visibility.PUBLIC,
                actor=seat,
                content=text,
            )

        all_deaths = list(initial_deaths)
        hunter_target: int | None = None
        hunter = self.state.find_role(RoleType.HUNTER)
        if (
            hunter is not None
            and hunter.seat in initial_deaths
            and hunter.death_cause is not None
            and self.state.hunter.can_shoot(hunter.death_cause)
        ):
            self.state.phase = Phase.HUNTER_SHOT
            eligible = tuple(self.state.alive_seats())
            observation = HunterShotObservation(
                day=self.state.day,
                hunter=hunter.seat,
                death_cause=hunter.death_cause,
                eligible_targets=eligible,
                last_words=self._latest_last_words(hunter.seat),
            )
            choice = None
            for attempt in range(2):
                choice = await provider.choose_hunter_target(observation)
                if choice is None or choice in eligible:
                    break
                if attempt == 0:
                    self._emit_invalid_retry("hunter_target", hunter.seat, choice)
                else:
                    self._emit_invalid_fallback("hunter_target", hunter.seat, choice)
                    choice = None
            self.state.hunter.gun_available = False
            if choice is None:
                self.events.emit(
                    day=self.state.day,
                    phase=Phase.HUNTER_SHOT,
                    event_type="hunter_did_not_shoot",
                    visibility=Visibility.PUBLIC,
                    actor=hunter.seat,
                    content=f"{hunter.seat}号猎人选择不开枪",
                )
            else:
                hunter_target = choice
                self.state.mark_dead(choice, DeathCause.HUNTER_SHOT)
                all_deaths.append(choice)
                self.events.emit(
                    day=self.state.day,
                    phase=Phase.HUNTER_SHOT,
                    event_type="hunter_shot",
                    visibility=Visibility.PUBLIC,
                    actor=hunter.seat,
                    target=choice,
                    content=f"{hunter.seat}号猎人开枪带走{choice}号",
                    data={"hunter": hunter.seat, "target": choice},
                )
                if self.state.sheriff.holder == choice:
                    self.state.sheriff.transfer_pending_from = choice

        badge_destroyed = False
        pending_sheriff = self.state.sheriff.transfer_pending_from
        if pending_sheriff is not None:
            if self.state.sheriff.holder != pending_sheriff:
                raise RuntimeError("pending badge owner does not match sheriff holder")
            self.state.phase = Phase.BADGE_TRANSFER
            eligible = tuple(self.state.alive_seats())
            observation = BadgeTransferObservation(
                day=self.state.day,
                former_sheriff=pending_sheriff,
                eligible_targets=eligible,
                hunter_target=hunter_target,
            )
            choice = None
            for attempt in range(2):
                choice = await provider.choose_badge_transfer(observation)
                if choice is None or choice in eligible:
                    break
                if attempt == 0:
                    self._emit_invalid_retry("badge_target", pending_sheriff, choice)
                else:
                    self._emit_invalid_fallback("badge_target", pending_sheriff, choice)
                    choice = None
            self.state.sheriff.transfer_pending_from = None
            badge_flow = self._seer_badge_flow_signal(pending_sheriff, choice)
            if choice is None:
                badge_destroyed = True
                self.state.sheriff.holder = None
                self.state.sheriff.badge_exists = False
                self.events.emit(
                    day=self.state.day,
                    phase=Phase.BADGE_TRANSFER,
                    event_type="badge_destroyed",
                    visibility=Visibility.PUBLIC,
                    actor=pending_sheriff,
                    content=(
                        f"{pending_sheriff}号撕毁警徽；按公共警徽流，"
                        f"其最后查验声明为{badge_flow['check_target']}号狼人"
                        if badge_flow is not None
                        else f"{pending_sheriff}号撕毁警徽"
                    ),
                    data={"badge_flow": badge_flow} if badge_flow is not None else {},
                )
            else:
                self.state.sheriff.holder = choice
                self.state.sheriff.badge_exists = True
                self.events.emit(
                    day=self.state.day,
                    phase=Phase.BADGE_TRANSFER,
                    event_type="badge_transferred",
                    visibility=Visibility.PUBLIC,
                    actor=pending_sheriff,
                    target=choice,
                    content=(
                        f"{pending_sheriff}号将警徽移交给{choice}号；按公共警徽流，"
                        f"其最后查验声明为{badge_flow['check_target']}号"
                        f"{'好人' if badge_flow['alignment'] == 'good' else '狼人'}"
                        if badge_flow is not None
                        else f"{pending_sheriff}号将警徽移交给{choice}号"
                    ),
                    data={
                        "from": pending_sheriff,
                        "to": choice,
                        **({"badge_flow": badge_flow} if badge_flow is not None else {}),
                    },
                )

        self._check_winner()
        if self.state.winner is None:
            self.state.phase = original_phase
        return self._finish(
            initial_deaths,
            tuple(all_deaths),
            tuple(spoken),
            hunter_target,
            badge_destroyed,
            start_index,
        )

    def _seer_badge_flow_signal(
        self,
        former_sheriff: int,
        choice: int | None,
    ) -> dict[str, int | str] | None:
        """Decode a dead seer's standard badge flow into a public claim."""

        if self.state.get_player(former_sheriff).role is not RoleType.SEER:
            return None
        checks = [
            event
            for event in self.events
            if event.event_type == "seer_result" and event.actor == former_sheriff
        ]
        if not checks:
            return None
        latest = checks[-1]
        alignment = latest.data.get("alignment")
        if alignment == Camp.GOOD.value and choice == latest.target:
            return {"check_target": latest.target, "alignment": Camp.GOOD.value}
        if alignment != Camp.WEREWOLF.value:
            return None
        eligible = set(self.state.alive_seats())
        prior_good = next(
            (
                event.target
                for event in reversed(checks[:-1])
                if event.target in eligible
                and event.data.get("alignment") == Camp.GOOD.value
            ),
            None,
        )
        if choice == prior_good:
            return {"check_target": latest.target, "alignment": Camp.WEREWOLF.value}
        return None

    def _latest_last_words(self, seat: int) -> str | None:
        return next(
            (
                event.content
                for event in reversed(self.events.events)
                if event.event_type == "last_words" and event.actor == seat
            ),
            None,
        )

    def check_winner(self) -> Camp | None:
        """Public entrypoint for a stable state with no pending death chain."""

        if self.state.pending_deaths:
            raise RuntimeError("cannot check victory before pending deaths are announced")
        if self.state.sheriff.transfer_pending_from is not None:
            raise RuntimeError("cannot check victory before badge resolution")
        original_phase = self.state.phase
        self._check_winner()
        if self.state.winner is None:
            self.state.phase = original_phase
        return self.state.winner

    def _check_winner(self) -> None:
        if self.state.winner is not None:
            return
        self.state.phase = Phase.WIN_CHECK
        counts = self.state.count_alive_by_faction()
        # Good wins ties: wolf elimination is evaluated first for the completed batch.
        if counts[Faction.WEREWOLF] == 0:
            winner, reason = Camp.GOOD, WinReason.ALL_WOLVES_DEAD
        elif counts[Faction.DEITY] == 0:
            winner, reason = Camp.WEREWOLF, WinReason.ALL_DEITIES_DEAD
        elif counts[Faction.CIVILIAN] == 0:
            winner, reason = Camp.WEREWOLF, WinReason.ALL_CIVILIANS_DEAD
        else:
            return

        self.state.winner = winner
        self.state.win_reason = reason
        self.state.phase = Phase.FINISHED
        self.events.emit(
            day=self.state.day,
            phase=Phase.FINISHED,
            event_type="game_finished",
            visibility=Visibility.PUBLIC,
            content=f"游戏结束：{winner.value}阵营获胜",
            data={
                "winner": winner.value,
                "reason": reason.value,
                "roles": [
                    {"seat": player.seat, "role": player.role.value}
                    for player in self.state.players
                ],
            },
        )

    def _emit_invalid_fallback(self, decision: str, actor: int, choice: object) -> None:
        self.events.emit(
            day=self.state.day,
            phase=self.state.phase,
            event_type="invalid_decision_fallback",
            visibility=Visibility.GOD,
            actor=actor,
            content="非法决策已使用确定性放弃兜底",
            data={"decision": decision, "choice": choice, "fallback": None},
        )

    def _emit_invalid_retry(self, decision: str, actor: int, choice: object) -> None:
        self.events.emit(
            day=self.state.day,
            phase=self.state.phase,
            event_type="invalid_decision_retry",
            visibility=Visibility.GOD,
            actor=actor,
            content="非法决策已拒绝，允许重试",
            data={"decision": decision, "choice": choice},
        )

    def _finish(
        self,
        initial_deaths: tuple[int, ...],
        all_deaths: tuple[int, ...],
        last_words: tuple[tuple[int, str], ...],
        hunter_target: int | None,
        badge_destroyed: bool,
        start_index: int,
    ) -> DeathResolutionResult:
        return DeathResolutionResult(
            initial_deaths=initial_deaths,
            all_deaths=all_deaths,
            last_words=last_words,
            hunter_target=hunter_target,
            badge_holder=self.state.sheriff.holder,
            badge_destroyed=badge_destroyed,
            winner=self.state.winner,
            win_reason=self.state.win_reason,
            events=self.events.events[start_index:],
        )
