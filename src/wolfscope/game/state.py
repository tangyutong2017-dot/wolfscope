"""Mutable state snapshot for the deterministic game engine.

Conversation, votes, claims and ability-result history do not live here. They
belong to the append-only event log. This module stores only the current
snapshot and the minimum role state required to enforce rules.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import random

from .config import RuleConfig, STANDARD_9_RULES
from .randomness import derive_seed
from .types import Camp, DeathCause, Faction, Phase, RoleType, WinReason


@dataclass(slots=True)
class PlayerState:
    seat: int
    role: RoleType
    alive: bool = True
    death_cause: DeathCause | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.seat <= 9:
            raise ValueError("seat must be between 1 and 9")
        if self.alive and self.death_cause is not None:
            raise ValueError("an alive player cannot have a death cause")
        if not self.alive and self.death_cause is None:
            raise ValueError("a dead player must have a death cause")


@dataclass(slots=True)
class WitchState:
    antidote_available: bool = True
    poison_available: bool = True


@dataclass(slots=True)
class SeerState:
    checked_seats: set[int] = field(default_factory=set)


@dataclass(slots=True)
class HunterState:
    gun_available: bool = True

    def can_shoot(self, death_cause: DeathCause) -> bool:
        """The hunter may shoot after every death cause except poison."""

        return self.gun_available and death_cause is not DeathCause.POISON


@dataclass(slots=True)
class SheriffState:
    holder: int | None = None
    badge_exists: bool = True
    election_completed: bool = False
    transfer_pending_from: int | None = None


_DEATH_CAUSE_PRIORITY: tuple[DeathCause, ...] = (
    DeathCause.POISON,
    DeathCause.WEREWOLF,
    DeathCause.HUNTER_SHOT,
    DeathCause.EXILE,
    DeathCause.WOLF_EXPLODE,
)


@dataclass(slots=True)
class PendingDeath:
    """Internally resolved death that has not yet been announced publicly."""

    seat: int
    causes: set[DeathCause]

    def __post_init__(self) -> None:
        if not 1 <= self.seat <= 9:
            raise ValueError("seat must be between 1 and 9")
        if not self.causes:
            raise ValueError("pending death must contain at least one cause")

    @property
    def effective_cause(self) -> DeathCause:
        for cause in _DEATH_CAUSE_PRIORITY:
            if cause in self.causes:
                return cause
        raise RuntimeError("pending death contains an unsupported cause")

    def add_cause(self, cause: DeathCause) -> None:
        self.causes.add(cause)


@dataclass(slots=True)
class GameState:
    players: list[PlayerState]
    rules: RuleConfig = STANDARD_9_RULES
    seed: int = 0
    day: int = 1
    phase: Phase = Phase.SETUP

    witch: WitchState = field(default_factory=WitchState)
    seer: SeerState = field(default_factory=SeerState)
    hunter: HunterState = field(default_factory=HunterState)
    sheriff: SheriffState = field(default_factory=SheriffState)

    pending_deaths: dict[int, PendingDeath] = field(default_factory=dict)
    winner: Camp | None = None
    win_reason: WinReason | None = None
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(derive_seed(self.seed, "order"))
        if self.day < 1:
            raise ValueError("day must start at 1")
        if len(self.players) != 9:
            raise ValueError("GameState requires exactly nine players")
        seats = [player.seat for player in self.players]
        if sorted(seats) != list(range(1, 10)):
            raise ValueError("players must occupy each seat from 1 through 9 exactly once")
        actual_roles = Counter(player.role for player in self.players)
        expected_roles = Counter(self.rules.roles)
        if actual_roles != expected_roles:
            raise ValueError("player roles do not match RuleConfig.roles")

    def get_player(self, seat: int) -> PlayerState:
        if not 1 <= seat <= 9:
            raise ValueError("seat must be between 1 and 9")
        return self.players[seat - 1]

    def mark_dead(self, seat: int, cause: DeathCause) -> PlayerState:
        """Apply one publicly effective death through the single state entrypoint."""

        player = self.get_player(seat)
        if not player.alive:
            raise ValueError(f"player {seat} is already dead")
        player.alive = False
        player.death_cause = cause
        return player

    def alive_seats(self) -> list[int]:
        return [player.seat for player in self.players if player.alive]

    def pending_death_seats(self) -> list[int]:
        return sorted(self.pending_deaths)

    def find_role(self, role: RoleType) -> PlayerState | None:
        return next((player for player in self.players if player.role is role), None)

    def alive_wolves(self) -> list[PlayerState]:
        return [
            player
            for player in self.players
            if player.alive and player.role is RoleType.WEREWOLF
        ]

    def count_alive_by_faction(self) -> dict[Faction, int]:
        counts = {faction: 0 for faction in Faction}
        for player in self.players:
            if player.alive:
                counts[player.role.faction] += 1
        return counts

    def sheriff_election_eligible_seats(self) -> list[int]:
        """Pending first-night deaths remain eligible until dawn announcement."""

        return self.alive_seats()

    def choose_seeded_start(self, seats: list[int]) -> int:
        """Choose a reproducible start seat using this game's random stream."""

        if not seats:
            raise ValueError("cannot choose a start from an empty seat list")
        return self._rng.choice(sorted(seats))
