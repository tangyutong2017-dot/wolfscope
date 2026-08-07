"""M1-2 night action collection and deterministic resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from wolfscope.contracts import GameEvent, Visibility

from .events import EventLog
from .state import GameState, PendingDeath
from .types import Camp, DeathCause, Phase, RoleType


class IllegalNightAction(ValueError):
    """Raised when a provider submits an action outside its legal choices."""


class WitchActionType(StrEnum):
    PASS = "pass"
    SAVE = "save"
    POISON = "poison"


@dataclass(frozen=True, slots=True)
class WitchAction:
    action: WitchActionType
    target: int | None = None

    def __post_init__(self) -> None:
        if self.action is WitchActionType.PASS and self.target is not None:
            raise ValueError("pass action cannot contain a target")
        if self.action is not WitchActionType.PASS and self.target is None:
            raise ValueError("save and poison actions require a target")

    @classmethod
    def pass_night(cls) -> WitchAction:
        return cls(action=WitchActionType.PASS)


@dataclass(frozen=True, slots=True)
class WolfNightObservation:
    day: int
    wolf_seats: tuple[int, ...]
    eligible_targets: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SeerNightObservation:
    day: int
    seer_seat: int
    checked_seats: tuple[int, ...]
    eligible_targets: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WitchNightObservation:
    day: int
    witch_seat: int
    night_victim: int | None
    antidote_available: bool
    poison_available: bool
    can_save: bool
    poison_targets: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class NightActions:
    wolf_target: int
    seer_target: int | None
    witch_action: WitchAction


@dataclass(frozen=True, slots=True)
class NightResolution:
    actions: NightActions
    pending_deaths: tuple[PendingDeath, ...]
    events: tuple[GameEvent, ...]


class NightActionProvider(Protocol):
    """Role-scoped decision source; implementations never receive GameState."""

    async def choose_wolf_target(self, observation: WolfNightObservation) -> int:
        ...

    async def choose_seer_target(self, observation: SeerNightObservation) -> int:
        ...

    async def choose_witch_action(self, observation: WitchNightObservation) -> WitchAction:
        ...


class NightEngine:
    def __init__(self, state: GameState, events: EventLog) -> None:
        self.state = state
        self.events = events

    def wolf_observation(self) -> WolfNightObservation:
        return WolfNightObservation(
            day=self.state.day,
            wolf_seats=tuple(player.seat for player in self.state.alive_wolves()),
            eligible_targets=tuple(self.state.alive_seats()),
        )

    def seer_observation(self) -> SeerNightObservation | None:
        seer = self.state.find_role(RoleType.SEER)
        if seer is None or not seer.alive:
            return None
        eligible = tuple(
            seat
            for seat in self.state.alive_seats()
            if (self.state.rules.seer_can_check_self or seat != seer.seat)
            and (
                self.state.rules.seer_can_repeat_check
                or seat not in self.state.seer.checked_seats
            )
        )
        return SeerNightObservation(
            day=self.state.day,
            seer_seat=seer.seat,
            checked_seats=tuple(sorted(self.state.seer.checked_seats)),
            eligible_targets=eligible,
        )

    def witch_observation(self, wolf_target: int) -> WitchNightObservation | None:
        witch = self.state.find_role(RoleType.WITCH)
        if witch is None or not witch.alive:
            return None
        knows_victim = (
            self.state.witch.antidote_available
            or not self.state.rules.witch_knows_victim_only_with_antidote
        )
        visible_victim = wolf_target if knows_victim else None
        can_save = (
            self.state.witch.antidote_available
            and (
                self.state.rules.witch_can_self_save
                or wolf_target != witch.seat
            )
        )
        return WitchNightObservation(
            day=self.state.day,
            witch_seat=witch.seat,
            night_victim=visible_victim,
            antidote_available=self.state.witch.antidote_available,
            poison_available=self.state.witch.poison_available,
            can_save=can_save,
            poison_targets=tuple(
                seat for seat in self.state.alive_seats() if seat != witch.seat
            ),
        )

    async def run(self, provider: NightActionProvider) -> NightResolution:
        """Ask role-scoped providers sequentially, then resolve atomically."""

        original_phase = self.state.phase
        if self.state.pending_deaths:
            raise RuntimeError("pending deaths must be announced before a new night")
        if not self.state.alive_wolves():
            raise RuntimeError("a night cannot start without a living werewolf")

        try:
            self.state.phase = Phase.NIGHT_WOLF
            wolf_target = await provider.choose_wolf_target(self.wolf_observation())
            self._validate_wolf_target(wolf_target)

            self.state.phase = Phase.NIGHT_SEER
            seer_observation = self.seer_observation()
            seer_target = (
                await provider.choose_seer_target(seer_observation)
                if seer_observation is not None
                else None
            )
            self._validate_seer_target(seer_target)

            self.state.phase = Phase.NIGHT_WITCH
            witch_observation = self.witch_observation(wolf_target)
            witch_action = (
                await provider.choose_witch_action(witch_observation)
                if witch_observation is not None
                else WitchAction.pass_night()
            )
            self._validate_witch_action(witch_action, wolf_target)

            actions = NightActions(
                wolf_target=wolf_target,
                seer_target=seer_target,
                witch_action=witch_action,
            )
            self.validate(actions)
            self.state.phase = Phase.NIGHT_RESOLUTION
            return self._apply(actions, witch_observation)
        except Exception:
            self.state.phase = original_phase
            raise

    def validate(self, actions: NightActions) -> None:
        """Validate the complete command without mutating game state."""

        self._validate_wolf_target(actions.wolf_target)
        self._validate_seer_target(actions.seer_target)
        self._validate_witch_action(actions.witch_action, actions.wolf_target)

    def _validate_wolf_target(self, target: int) -> None:
        if target not in self.state.alive_seats():
            raise IllegalNightAction(f"illegal wolf target: {target}")
        if (
            not self.state.rules.wolf_can_target_wolf
            and self.state.get_player(target).role is RoleType.WEREWOLF
        ):
            raise IllegalNightAction("wolf-on-wolf target is disabled")

    def _validate_seer_target(self, target: int | None) -> None:
        observation = self.seer_observation()
        if observation is None:
            if target is not None:
                raise IllegalNightAction("dead seer cannot submit a target")
            return
        if target is None:
            raise IllegalNightAction("living seer must submit a target")
        if target not in observation.eligible_targets:
            raise IllegalNightAction(f"illegal seer target: {target}")

    def _validate_witch_action(self, action: WitchAction, wolf_target: int) -> None:
        observation = self.witch_observation(wolf_target)
        if observation is None:
            if action.action is not WitchActionType.PASS:
                raise IllegalNightAction("dead witch cannot act")
            return
        if action.action is WitchActionType.PASS:
            return
        if action.action is WitchActionType.SAVE:
            if not observation.antidote_available:
                raise IllegalNightAction("antidote is unavailable")
            if not observation.can_save:
                raise IllegalNightAction("witch cannot save herself")
            if action.target != wolf_target:
                raise IllegalNightAction("antidote can only target tonight's victim")
            return
        if action.action is WitchActionType.POISON:
            if not observation.poison_available:
                raise IllegalNightAction("poison is unavailable")
            if action.target not in observation.poison_targets:
                raise IllegalNightAction("witch can only poison another living player")
            return
        raise IllegalNightAction(f"unsupported witch action: {action.action}")

    def _apply(
        self,
        actions: NightActions,
        witch_observation: WitchNightObservation | None = None,
    ) -> NightResolution:
        """Apply previously validated actions and append private audit events."""

        start_index = len(self.events)
        pending: dict[int, PendingDeath] = {
            actions.wolf_target: PendingDeath(
                seat=actions.wolf_target,
                causes={DeathCause.WEREWOLF},
            ),
        }

        wolf_recipients = tuple(player.seat for player in self.state.alive_wolves())
        self.events.emit(
            day=self.state.day,
            phase=Phase.NIGHT_WOLF,
            event_type="wolf_target",
            visibility=Visibility.WOLVES,
            target=actions.wolf_target,
            content=f"狼队选择袭击 {actions.wolf_target} 号",
            data={"target": actions.wolf_target},
        )

        seer = self.state.find_role(RoleType.SEER)
        if seer is not None and seer.alive and actions.seer_target is not None:
            self.state.seer.checked_seats.add(actions.seer_target)
            target = self.state.get_player(actions.seer_target)
            alignment = (
                Camp.WEREWOLF.value
                if target.role is RoleType.WEREWOLF
                else Camp.GOOD.value
            )
            self.events.emit(
                day=self.state.day,
                phase=Phase.NIGHT_SEER,
                event_type="seer_result",
                visibility=Visibility.PRIVATE,
                recipients=(seer.seat,),
                actor=seer.seat,
                target=target.seat,
                content=f"查验 {target.seat} 号的结果为 {alignment}",
                data={"target": target.seat, "alignment": alignment},
            )

        witch = self.state.find_role(RoleType.WITCH)
        if witch is not None and witch.alive:
            observation = witch_observation or self.witch_observation(actions.wolf_target)
            assert observation is not None
            if observation.night_victim is not None:
                self.events.emit(
                    day=self.state.day,
                    phase=Phase.NIGHT_WITCH,
                    event_type="witch_night_victim",
                    visibility=Visibility.PRIVATE,
                    recipients=(witch.seat,),
                    actor=witch.seat,
                    target=observation.night_victim,
                    content=f"今晚狼队袭击了 {observation.night_victim} 号",
                    data={"target": observation.night_victim},
                )

            if actions.witch_action.action is WitchActionType.SAVE:
                self.state.witch.antidote_available = False
                pending.pop(actions.wolf_target, None)
            elif actions.witch_action.action is WitchActionType.POISON:
                self.state.witch.poison_available = False
                poison_target = actions.witch_action.target
                assert poison_target is not None
                if poison_target in pending:
                    pending[poison_target].add_cause(DeathCause.POISON)
                else:
                    pending[poison_target] = PendingDeath(
                        seat=poison_target,
                        causes={DeathCause.POISON},
                    )

            self.events.emit(
                day=self.state.day,
                phase=Phase.NIGHT_WITCH,
                event_type="witch_action",
                visibility=Visibility.PRIVATE,
                recipients=(witch.seat,),
                actor=witch.seat,
                target=actions.witch_action.target,
                content=f"女巫选择 {actions.witch_action.action.value}",
                data={
                    "action": actions.witch_action.action.value,
                    "target": actions.witch_action.target,
                },
            )

        self.state.pending_deaths = pending
        self.events.emit(
            day=self.state.day,
            phase=Phase.NIGHT_RESOLUTION,
            event_type="night_resolution",
            visibility=Visibility.GOD,
            content="夜间内部结算完成，死亡尚未公布",
            data={
                "pending_deaths": [
                    {
                        "seat": item.seat,
                        "causes": sorted(cause.value for cause in item.causes),
                        "effective_cause": item.effective_cause.value,
                    }
                    for item in sorted(pending.values(), key=lambda value: value.seat)
                ],
                "wolf_recipients": list(wolf_recipients),
            },
        )
        return NightResolution(
            actions=actions,
            pending_deaths=tuple(sorted(pending.values(), key=lambda item: item.seat)),
            events=self.events.events[start_index:],
        )
