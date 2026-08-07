"""M1-4 deterministic daytime speech, explosion and exile voting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from wolfscope.contracts import GameEvent, Visibility

from .events import EventLog
from .state import GameState
from .types import DeathCause, Phase, RoleType

if TYPE_CHECKING:
    from .resolution import DeathResolutionProvider, DeathResolutionResult


class IllegalDayAction(ValueError):
    """Raised when a provider submits an illegal daytime action."""


class SpeechDirection(StrEnum):
    CLOCKWISE = "clockwise"
    COUNTERCLOCKWISE = "counterclockwise"


class DayTurnActionType(StrEnum):
    SPEAK = "speak"
    EXPLODE = "explode"


class ExileVoteRound(StrEnum):
    FIRST = "first"
    REVOTE = "revote"


@dataclass(frozen=True, slots=True)
class DayTurnAction:
    action: DayTurnActionType
    speech: str | None = None

    def __post_init__(self) -> None:
        if self.action is DayTurnActionType.SPEAK:
            if not isinstance(self.speech, str) or not self.speech.strip():
                raise ValueError("speak action requires non-empty speech")
        elif self.speech is not None:
            raise ValueError("explode action cannot contain speech")

    @classmethod
    def speak(cls, text: str) -> DayTurnAction:
        return cls(action=DayTurnActionType.SPEAK, speech=text.strip())

    @classmethod
    def explode(cls) -> DayTurnAction:
        return cls(action=DayTurnActionType.EXPLODE)


@dataclass(frozen=True, slots=True)
class SpeechDirectionObservation:
    day: int
    sheriff: int
    alive_seats: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DayTurnObservation:
    day: int
    actor: int
    speaking_order: tuple[int, ...]
    previous_speeches: tuple[tuple[int, str], ...]
    can_explode: bool


@dataclass(frozen=True, slots=True)
class ExileVoteObservation:
    day: int
    voter: int
    vote_round: ExileVoteRound
    candidates: tuple[int, ...]
    speeches: tuple[tuple[int, str], ...]


@dataclass(frozen=True, slots=True)
class PkSpeechObservation:
    day: int
    actor: int
    tied_seats: tuple[int, ...]
    day_speeches: tuple[tuple[int, str], ...]
    previous_pk_speeches: tuple[tuple[int, str], ...]


@dataclass(frozen=True, slots=True)
class LastWordsObservation:
    day: int
    actor: int
    day_speeches: tuple[tuple[int, str], ...]
    votes: tuple[tuple[int, int | None], ...]
    revotes: tuple[tuple[int, int | None], ...]


@dataclass(frozen=True, slots=True)
class DayOutcome:
    speaking_order: tuple[int, ...]
    speeches: tuple[tuple[int, str], ...]
    exploded: int | None
    votes: tuple[tuple[int, int | None], ...]
    tied_seats: tuple[int, ...]
    pk_speeches: tuple[tuple[int, str], ...]
    revotes: tuple[tuple[int, int | None], ...]
    exiled: int | None
    last_words: str | None
    hunter_resolution_required: bool
    badge_resolution_required: bool
    events: tuple[GameEvent, ...]


class DayActionProvider(Protocol):
    async def choose_speech_direction(
        self,
        observation: SpeechDirectionObservation,
    ) -> SpeechDirection:
        ...

    async def take_day_turn(self, observation: DayTurnObservation) -> DayTurnAction:
        ...

    async def choose_exile_vote(self, observation: ExileVoteObservation) -> int | None:
        ...

    async def pk_speech(self, observation: PkSpeechObservation) -> str:
        ...

    async def last_words(self, observation: LastWordsObservation) -> str:
        ...


def _circle_from(start: int, direction: SpeechDirection) -> list[int]:
    step = 1 if direction is SpeechDirection.CLOCKWISE else -1
    return [((start - 1 + offset * step) % 9) + 1 for offset in range(9)]


class DayEngine:
    def __init__(self, state: GameState, events: EventLog) -> None:
        self.state = state
        self.events = events

    async def run(self, provider: DayActionProvider) -> DayOutcome:
        self._validate_stable_start()
        start_index = len(self.events)
        speaking_order = await self._speaking_order(provider)

        self.state.phase = Phase.DAY_SPEECH
        speeches: list[tuple[int, str]] = []
        for seat in speaking_order:
            player = self.state.get_player(seat)
            action = await provider.take_day_turn(
                DayTurnObservation(
                    day=self.state.day,
                    actor=seat,
                    speaking_order=tuple(speaking_order),
                    previous_speeches=tuple(speeches),
                    can_explode=(
                        self.state.rules.basic_wolf_explode_enabled
                        and player.role is RoleType.WEREWOLF
                    ),
                ),
            )
            if action.action is DayTurnActionType.EXPLODE:
                if not self.state.rules.basic_wolf_explode_enabled:
                    raise IllegalDayAction("wolf explosion is disabled")
                if player.role is not RoleType.WEREWOLF:
                    raise IllegalDayAction("only a werewolf can explode")
                self.state.mark_dead(seat, DeathCause.WOLF_EXPLODE)
                if self.state.sheriff.holder == seat:
                    self.state.sheriff.transfer_pending_from = seat
                self.events.emit(
                    day=self.state.day,
                    phase=Phase.DAY_SPEECH,
                    event_type="wolf_exploded",
                    visibility=Visibility.PUBLIC,
                    actor=seat,
                    content=f"{seat}号自爆，确认其狼人身份；当天发言和投票结束",
                    data={"seat": seat, "revealed_role": RoleType.WEREWOLF.value},
                )
                return self._outcome(
                    start_index=start_index,
                    speaking_order=speaking_order,
                    speeches=speeches,
                    exploded=seat,
                )

            assert action.speech is not None
            speech = action.speech.strip()
            speeches.append((seat, speech))
            self.events.emit(
                day=self.state.day,
                phase=Phase.DAY_SPEECH,
                event_type="day_speech",
                visibility=Visibility.PUBLIC,
                actor=seat,
                content=speech,
            )

        votes = await self._collect_votes(provider, tuple(speeches))
        tied = self._highest(votes)
        self._emit_votes("exile_votes", votes)

        pk_speeches: list[tuple[int, str]] = []
        revotes: list[tuple[int, int | None]] = []
        exiled: int | None = None
        if len(tied) == 1:
            exiled = tied[0]
        elif len(tied) > 1:
            self.state.phase = Phase.DAY_PK_SPEECH
            pk_order = [seat for seat in speaking_order if seat in tied]
            for seat in pk_order:
                speech = await provider.pk_speech(
                    PkSpeechObservation(
                        day=self.state.day,
                        actor=seat,
                        tied_seats=tuple(tied),
                        day_speeches=tuple(speeches),
                        previous_pk_speeches=tuple(pk_speeches),
                    ),
                )
                if not isinstance(speech, str) or not speech.strip():
                    raise IllegalDayAction("PK speech must be non-empty")
                speech = speech.strip()
                pk_speeches.append((seat, speech))
                self.events.emit(
                    day=self.state.day,
                    phase=Phase.DAY_PK_SPEECH,
                    event_type="pk_speech",
                    visibility=Visibility.PUBLIC,
                    actor=seat,
                    content=speech,
                    data={"tied_seats": tied},
                )

            self.state.phase = Phase.DAY_REVOTE
            voters = [seat for seat in self.state.alive_seats() if seat not in tied]
            for voter in voters:
                target = await provider.choose_exile_vote(
                    ExileVoteObservation(
                        day=self.state.day,
                        voter=voter,
                        vote_round=ExileVoteRound.REVOTE,
                        candidates=tuple(tied),
                        speeches=tuple(speeches + pk_speeches),
                    ),
                )
                self._validate_vote(voter, target, tied)
                revotes.append((voter, target))
            self._emit_votes("exile_revotes", revotes)
            revote_highest = self._highest(revotes)
            if len(revote_highest) == 1:
                exiled = revote_highest[0]

        last_words: str | None = None
        if exiled is not None:
            self.state.phase = Phase.DAY_VOTE
            # Collect and validate the final model output before mutating the
            # authoritative state, so an invalid response cannot leave a
            # half-resolved exile behind.
            last_words = await provider.last_words(
                LastWordsObservation(
                    day=self.state.day,
                    actor=exiled,
                    day_speeches=tuple(speeches + pk_speeches),
                    votes=tuple(votes),
                    revotes=tuple(revotes),
                ),
            )
            if not isinstance(last_words, str) or not last_words.strip():
                raise IllegalDayAction("exiled player must provide last words")
            last_words = last_words.strip()

            player = self.state.mark_dead(exiled, DeathCause.EXILE)
            if self.state.sheriff.holder == exiled:
                self.state.sheriff.transfer_pending_from = exiled
            self.events.emit(
                day=self.state.day,
                phase=Phase.DAY_VOTE,
                event_type="player_exiled",
                visibility=Visibility.PUBLIC,
                actor=exiled,
                content=f"{exiled}号被放逐",
                data={"seat": exiled},
            )
            self.events.emit(
                day=self.state.day,
                phase=Phase.DAY_VOTE,
                event_type="last_words",
                visibility=Visibility.PUBLIC,
                actor=exiled,
                content=last_words,
            )
            hunter_required = (
                player.role is RoleType.HUNTER
                and self.state.hunter.can_shoot(DeathCause.EXILE)
            )
        else:
            hunter_required = False
            self.events.emit(
                day=self.state.day,
                phase=self.state.phase,
                event_type="no_exile",
                visibility=Visibility.PUBLIC,
                content="本日无人被放逐",
            )

        return self._outcome(
            start_index=start_index,
            speaking_order=speaking_order,
            speeches=speeches,
            votes=votes,
            tied_seats=tied,
            pk_speeches=pk_speeches,
            revotes=revotes,
            exiled=exiled,
            last_words=last_words,
            hunter_resolution_required=hunter_required,
            badge_resolution_required=(
                exiled is not None and self.state.sheriff.transfer_pending_from == exiled
            ),
        )

    async def resolve_death_chain(
        self,
        outcome: DayOutcome,
        provider: DeathResolutionProvider,
    ) -> DeathResolutionResult | None:
        """Finish hunter, badge and victory effects after a day outcome."""

        from .resolution import DeathResolutionEngine

        death = outcome.exploded if outcome.exploded is not None else outcome.exiled
        if death is None:
            return None
        return await DeathResolutionEngine(self.state, self.events).resolve(
            (death,),
            provider,
        )

    def _validate_stable_start(self) -> None:
        if self.state.pending_deaths:
            raise RuntimeError("dawn deaths must be announced before daytime")
        pending_badge = self.state.sheriff.transfer_pending_from
        if pending_badge is not None:
            raise RuntimeError("pending badge transfer must be resolved before daytime")
        holder = self.state.sheriff.holder
        if holder is not None and not self.state.get_player(holder).alive:
            raise RuntimeError("dead sheriff cannot start daytime without badge resolution")

    async def _speaking_order(self, provider: DayActionProvider) -> list[int]:
        alive = self.state.alive_seats()
        sheriff = self.state.sheriff.holder
        if sheriff is None:
            start = self.state.choose_seeded_start(alive)
            order = [seat for seat in _circle_from(start, SpeechDirection.CLOCKWISE) if seat in alive]
            self.events.emit(
                day=self.state.day,
                phase=Phase.DAY_SPEECH,
                event_type="speaking_order",
                visibility=Visibility.PUBLIC,
                content=f"无警长，从{start}号开始顺时针发言",
                data={"start": start, "direction": SpeechDirection.CLOCKWISE.value, "order": order},
            )
            return order

        direction = await provider.choose_speech_direction(
            SpeechDirectionObservation(
                day=self.state.day,
                sheriff=sheriff,
                alive_seats=tuple(alive),
            ),
        )
        if not isinstance(direction, SpeechDirection):
            raise IllegalDayAction("invalid speaking direction")
        ring = _circle_from(sheriff, direction)
        order = [seat for seat in ring[1:] if seat in alive and seat != sheriff] + [sheriff]
        self.events.emit(
            day=self.state.day,
            phase=Phase.DAY_SPEECH,
            event_type="speaking_order",
            visibility=Visibility.PUBLIC,
            actor=sheriff,
            content=f"警长选择{direction.value}方向，警长最后发言",
            data={"sheriff": sheriff, "direction": direction.value, "order": order},
        )
        return order

    async def _collect_votes(
        self,
        provider: DayActionProvider,
        speeches: tuple[tuple[int, str], ...],
    ) -> list[tuple[int, int | None]]:
        self.state.phase = Phase.DAY_VOTE
        alive = self.state.alive_seats()
        votes: list[tuple[int, int | None]] = []
        # Simultaneous semantics: observations contain no choices collected so far.
        for voter in alive:
            candidates = [seat for seat in alive if seat != voter]
            target = await provider.choose_exile_vote(
                ExileVoteObservation(
                    day=self.state.day,
                    voter=voter,
                    vote_round=ExileVoteRound.FIRST,
                    candidates=tuple(candidates),
                    speeches=speeches,
                ),
            )
            self._validate_vote(voter, target, candidates)
            votes.append((voter, target))
        return votes

    def _validate_vote(
        self,
        voter: int,
        target: int | None,
        candidates: list[int],
    ) -> None:
        if target is None:
            return
        if target == voter:
            raise IllegalDayAction("self-vote is forbidden")
        if target not in candidates:
            raise IllegalDayAction(f"illegal exile target: {target}")

    def _vote_units(self, voter: int) -> int:
        return (
            self.state.rules.sheriff_vote_units
            if voter == self.state.sheriff.holder
            else self.state.rules.normal_vote_units
        )

    def _highest(self, votes: list[tuple[int, int | None]]) -> list[int]:
        counts: dict[int, int] = {}
        for voter, target in votes:
            if target is not None:
                counts[target] = counts.get(target, 0) + self._vote_units(voter)
        if not counts:
            return []
        highest = max(counts.values())
        return sorted(seat for seat, units in counts.items() if units == highest)

    def _emit_votes(self, event_type: str, votes: list[tuple[int, int | None]]) -> None:
        counts: dict[int, int] = {}
        details = []
        for voter, target in votes:
            units = self._vote_units(voter)
            details.append({"voter": voter, "target": target, "units": units})
            if target is not None:
                counts[target] = counts.get(target, 0) + units
        self.events.emit(
            day=self.state.day,
            phase=self.state.phase,
            event_type=event_type,
            visibility=Visibility.PUBLIC,
            content="放逐投票结果公布",
            data={
                "votes": details,
                "vote_units": {str(seat): units for seat, units in counts.items()},
            },
        )

    def _outcome(
        self,
        *,
        start_index: int,
        speaking_order: list[int],
        speeches: list[tuple[int, str]],
        exploded: int | None = None,
        votes: list[tuple[int, int | None]] | None = None,
        tied_seats: list[int] | None = None,
        pk_speeches: list[tuple[int, str]] | None = None,
        revotes: list[tuple[int, int | None]] | None = None,
        exiled: int | None = None,
        last_words: str | None = None,
        hunter_resolution_required: bool = False,
        badge_resolution_required: bool = False,
    ) -> DayOutcome:
        if exploded is not None:
            badge_resolution_required = self.state.sheriff.transfer_pending_from == exploded
        return DayOutcome(
            speaking_order=tuple(speaking_order),
            speeches=tuple(speeches),
            exploded=exploded,
            votes=tuple(votes or ()),
            tied_seats=tuple(tied_seats or ()),
            pk_speeches=tuple(pk_speeches or ()),
            revotes=tuple(revotes or ()),
            exiled=exiled,
            last_words=last_words,
            hunter_resolution_required=hunter_resolution_required,
            badge_resolution_required=badge_resolution_required,
            events=self.events.events[start_index:],
        )
