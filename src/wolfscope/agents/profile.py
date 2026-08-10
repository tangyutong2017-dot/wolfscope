"""Small seed-derived behavior parameters assigned independently of roles."""

from __future__ import annotations

import random
from enum import StrEnum

from pydantic import Field

from wolfscope.contracts import Seat, StrictModel
from wolfscope.game.randomness import derive_seed


class SheriffInitiative(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PlayerTendencyProfile(StrictModel):
    seat: Seat
    sheriff_initiative: SheriffInitiative


class PlayerTendencyRegistry:
    """Generate profiles from seat and game seed without reading dealt roles."""

    def __init__(self, profiles: tuple[PlayerTendencyProfile, ...]) -> None:
        if {profile.seat for profile in profiles} != set(range(1, 10)):
            raise ValueError("tendency profiles must cover seats 1 through 9")
        self._profiles = {profile.seat: profile for profile in profiles}

    @classmethod
    def from_seed(cls, seed: int) -> PlayerTendencyRegistry:
        values = [
            SheriffInitiative.HIGH,
            SheriffInitiative.HIGH,
            SheriffInitiative.MEDIUM,
            SheriffInitiative.MEDIUM,
            SheriffInitiative.MEDIUM,
            SheriffInitiative.LOW,
            SheriffInitiative.LOW,
            SheriffInitiative.LOW,
            SheriffInitiative.LOW,
        ]
        random.Random(derive_seed(seed, "player-tendency:sheriff")).shuffle(values)
        return cls(
            tuple(
                PlayerTendencyProfile(seat=seat, sheriff_initiative=value)
                for seat, value in enumerate(values, start=1)
            ),
        )

    def get(self, seat: int) -> PlayerTendencyProfile:
        return self._profiles[seat]

