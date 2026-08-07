"""Strict, LLM-free decision provider for deterministic full-game scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .game.day import (
    DayTurnAction,
    ExileVoteRound,
    SpeechDirection,
)
from .game.night import WitchAction


class MissingScriptedAction(KeyError):
    """Raised when the engine asks for a rule-relevant choice absent from the script."""


class UnusedScriptedAction(ValueError):
    """Raised when configured rule-relevant actions were never requested."""


@dataclass(frozen=True, slots=True)
class NightScript:
    wolf_target: int
    seer_target: int | None
    witch_action: WitchAction | None


@dataclass(frozen=True, slots=True)
class SheriffScript:
    signups: frozenset[int] = frozenset()
    speeches: Mapping[int, str] = field(default_factory=dict)
    default_speech: str | None = "{seat}号竞选发言"
    withdrawals: frozenset[int] = frozenset()
    votes: Mapping[int, int | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DayScript:
    direction: SpeechDirection | None = None
    turns: Mapping[int, DayTurnAction] = field(default_factory=dict)
    default_speech: str | None = "{seat}号白天发言"
    votes: Mapping[int, int | None] = field(default_factory=dict)
    pk_speeches: Mapping[int, str] = field(default_factory=dict)
    default_pk_speech: str | None = "{seat}号PK发言"
    revotes: Mapping[int, int | None] = field(default_factory=dict)
    last_words: Mapping[int, str] = field(default_factory=dict)
    default_last_words: str | None = "{seat}号遗言"


@dataclass(frozen=True, slots=True)
class DeathScript:
    night_last_words: Mapping[tuple[int, int], str] = field(default_factory=dict)
    default_night_last_words: str | None = "{seat}号首夜遗言"
    hunter_targets: Mapping[tuple[int, int], int | None] = field(default_factory=dict)
    badge_targets: Mapping[tuple[int, int], int | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScriptedGame:
    game_id: str
    seed: int
    max_days: int
    nights: Mapping[int, NightScript]
    sheriff: SheriffScript
    days: Mapping[int, DayScript]
    deaths: DeathScript = field(default_factory=DeathScript)


class ScriptedProvider:
    """Consume typed choices using observations only, never authoritative state."""

    def __init__(self, script: ScriptedGame) -> None:
        self.script = script
        self.calls: list[tuple[str, int, int | None, object]] = []
        self._configured = self._configured_action_keys()
        self._consumed: set[tuple[object, ...]] = set()

    async def choose_wolf_target(self, observation) -> int:
        night = self._night(observation.day)
        self._consume(("night", observation.day, "wolf_target"))
        return self._record("wolf_target", observation.day, None, night.wolf_target)

    async def choose_seer_target(self, observation) -> int:
        night = self._night(observation.day)
        if night.seer_target is None:
            self._missing(observation.day, "seer_target", observation.seer_seat)
        self._consume(("night", observation.day, "seer_target"))
        return self._record(
            "seer_target",
            observation.day,
            observation.seer_seat,
            night.seer_target,
        )

    async def choose_witch_action(self, observation) -> WitchAction:
        night = self._night(observation.day)
        if night.witch_action is None:
            self._missing(observation.day, "witch_action", observation.witch_seat)
        self._consume(("night", observation.day, "witch_action"))
        return self._record(
            "witch_action",
            observation.day,
            observation.witch_seat,
            night.witch_action,
        )

    async def choose_signup(self, observation) -> bool:
        choice = observation.actor in self.script.sheriff.signups
        if choice:
            self._consume(("sheriff_signup", observation.actor))
        return self._record("sheriff_signup", observation.day, observation.actor, choice)

    async def campaign_speech(self, observation) -> str:
        sheriff = self.script.sheriff
        if observation.actor in sheriff.speeches:
            self._consume(("sheriff_speech", observation.actor))
            text = sheriff.speeches[observation.actor]
        elif sheriff.default_speech is not None:
            text = sheriff.default_speech.format(seat=observation.actor)
        else:
            self._missing(observation.day, "campaign_speech", observation.actor)
        return self._record("campaign_speech", observation.day, observation.actor, text)

    async def choose_withdrawal(self, observation) -> bool:
        choice = observation.actor in self.script.sheriff.withdrawals
        if choice:
            self._consume(("sheriff_withdrawal", observation.actor))
        return self._record("sheriff_withdrawal", observation.day, observation.actor, choice)

    async def choose_sheriff_vote(self, observation) -> int | None:
        if observation.voter not in self.script.sheriff.votes:
            self._missing(observation.day, "sheriff_vote", observation.voter)
        self._consume(("sheriff_vote", observation.voter))
        return self._record(
            "sheriff_vote",
            observation.day,
            observation.voter,
            self.script.sheriff.votes[observation.voter],
        )

    async def choose_speech_direction(self, observation) -> SpeechDirection:
        day = self._day(observation.day)
        if day.direction is None:
            self._missing(observation.day, "speech_direction", observation.sheriff)
        self._consume(("day", observation.day, "direction"))
        return self._record(
            "speech_direction",
            observation.day,
            observation.sheriff,
            day.direction,
        )

    async def take_day_turn(self, observation) -> DayTurnAction:
        day = self._day(observation.day)
        if observation.actor in day.turns:
            self._consume(("day_turn", observation.day, observation.actor))
            action = day.turns[observation.actor]
        elif day.default_speech is not None:
            action = DayTurnAction.speak(day.default_speech.format(seat=observation.actor))
        else:
            self._missing(observation.day, "day_turn", observation.actor)
        return self._record("day_turn", observation.day, observation.actor, action)

    async def choose_exile_vote(self, observation) -> int | None:
        day = self._day(observation.day)
        mapping = day.revotes if observation.vote_round is ExileVoteRound.REVOTE else day.votes
        label = "revote" if observation.vote_round is ExileVoteRound.REVOTE else "vote"
        if observation.voter not in mapping:
            self._missing(observation.day, label, observation.voter)
        self._consume((label, observation.day, observation.voter))
        return self._record(label, observation.day, observation.voter, mapping[observation.voter])

    async def pk_speech(self, observation) -> str:
        day = self._day(observation.day)
        if observation.actor in day.pk_speeches:
            self._consume(("pk_speech", observation.day, observation.actor))
            text = day.pk_speeches[observation.actor]
        elif day.default_pk_speech is not None:
            text = day.default_pk_speech.format(seat=observation.actor)
        else:
            self._missing(observation.day, "pk_speech", observation.actor)
        return self._record("pk_speech", observation.day, observation.actor, text)

    async def last_words(self, observation) -> str:
        day = self._day(observation.day)
        if observation.actor in day.last_words:
            self._consume(("last_words", observation.day, observation.actor))
            text = day.last_words[observation.actor]
        elif day.default_last_words is not None:
            text = day.default_last_words.format(seat=observation.actor)
        else:
            self._missing(observation.day, "last_words", observation.actor)
        return self._record("last_words", observation.day, observation.actor, text)

    async def death_last_words(self, observation) -> str:
        key = (observation.day, observation.actor)
        deaths = self.script.deaths
        if key in deaths.night_last_words:
            self._consume(("night_last_words", *key))
            text = deaths.night_last_words[key]
        elif deaths.default_night_last_words is not None:
            text = deaths.default_night_last_words.format(seat=observation.actor)
        else:
            self._missing(observation.day, "night_last_words", observation.actor)
        return self._record("night_last_words", observation.day, observation.actor, text)

    async def choose_hunter_target(self, observation) -> int | None:
        key = (observation.day, observation.hunter)
        if key not in self.script.deaths.hunter_targets:
            self._missing(observation.day, "hunter_target", observation.hunter)
        self._consume(("hunter_target", *key))
        choice = self.script.deaths.hunter_targets[key]
        return self._record("hunter_target", observation.day, observation.hunter, choice)

    async def choose_badge_transfer(self, observation) -> int | None:
        key = (observation.day, observation.former_sheriff)
        if key not in self.script.deaths.badge_targets:
            self._missing(observation.day, "badge_target", observation.former_sheriff)
        self._consume(("badge_target", *key))
        choice = self.script.deaths.badge_targets[key]
        return self._record("badge_target", observation.day, observation.former_sheriff, choice)

    def assert_all_consumed(self) -> None:
        unused = sorted(self._configured - self._consumed, key=repr)
        if unused:
            raise UnusedScriptedAction(f"unused scripted actions: {unused!r}")

    def _night(self, day: int) -> NightScript:
        if day not in self.script.nights:
            self._missing(day, "night", None)
        return self.script.nights[day]

    def _day(self, day: int) -> DayScript:
        if day not in self.script.days:
            self._missing(day, "day", None)
        return self.script.days[day]

    def _record(self, action: str, day: int, actor: int | None, value):
        self.calls.append((action, day, actor, value))
        return value

    def _consume(self, key: tuple[object, ...]) -> None:
        self._consumed.add(key)

    def _missing(self, day: int, action: str, actor: int | None) -> None:
        raise MissingScriptedAction(
            f"missing scripted action: day={day}, action={action}, actor={actor}",
        )

    def _configured_action_keys(self) -> set[tuple[object, ...]]:
        keys: set[tuple[object, ...]] = set()
        for day, night in self.script.nights.items():
            keys.add(("night", day, "wolf_target"))
            if night.seer_target is not None:
                keys.add(("night", day, "seer_target"))
            if night.witch_action is not None:
                keys.add(("night", day, "witch_action"))
        keys.update(("sheriff_signup", seat) for seat in self.script.sheriff.signups)
        keys.update(
            ("sheriff_withdrawal", seat)
            for seat in self.script.sheriff.withdrawals
        )
        for seat in self.script.sheriff.speeches:
            keys.add(("sheriff_speech", seat))
        for voter in self.script.sheriff.votes:
            keys.add(("sheriff_vote", voter))
        for day, script in self.script.days.items():
            if script.direction is not None:
                keys.add(("day", day, "direction"))
            keys.update(("day_turn", day, seat) for seat in script.turns)
            keys.update(("vote", day, seat) for seat in script.votes)
            keys.update(("pk_speech", day, seat) for seat in script.pk_speeches)
            keys.update(("revote", day, seat) for seat in script.revotes)
            keys.update(("last_words", day, seat) for seat in script.last_words)
        keys.update(("night_last_words", *key) for key in self.script.deaths.night_last_words)
        keys.update(("hunter_target", *key) for key in self.script.deaths.hunter_targets)
        keys.update(("badge_target", *key) for key in self.script.deaths.badge_targets)
        return keys
