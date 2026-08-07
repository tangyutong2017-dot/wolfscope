"""Deterministic construction of standard WolfScope games."""

from __future__ import annotations

import random

from .config import RuleConfig, STANDARD_9_RULES
from .randomness import derive_seed
from .state import GameState, PlayerState


class GameFactory:
    @staticmethod
    def create(seed: int, rules: RuleConfig = STANDARD_9_RULES) -> GameState:
        roles = list(rules.roles)
        random.Random(derive_seed(seed, "deal")).shuffle(roles)
        return GameState(
            seed=seed,
            rules=rules,
            players=[
                PlayerState(seat=seat, role=role)
                for seat, role in enumerate(roles, start=1)
            ],
        )
