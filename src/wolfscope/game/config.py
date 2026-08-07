"""Immutable configuration for the frozen WolfScope nine-player rules."""

from dataclasses import dataclass

from .types import RoleType


STANDARD_9_ROLES: tuple[RoleType, ...] = (
    RoleType.WEREWOLF,
    RoleType.WEREWOLF,
    RoleType.WEREWOLF,
    RoleType.VILLAGER,
    RoleType.VILLAGER,
    RoleType.VILLAGER,
    RoleType.SEER,
    RoleType.WITCH,
    RoleType.HUNTER,
)


@dataclass(frozen=True, slots=True)
class RuleConfig:
    ruleset_id: str = "standard-9-v1"
    roles: tuple[RoleType, ...] = STANDARD_9_ROLES

    wolf_must_kill: bool = True
    wolf_can_target_wolf: bool = True

    seer_can_check_self: bool = False
    seer_can_repeat_check: bool = False

    witch_can_self_save: bool = False
    witch_knows_victim_only_with_antidote: bool = True

    sheriff_enabled: bool = True
    sheriff_election_before_first_dawn: bool = True
    basic_wolf_explode_enabled: bool = True

    exile_revote_rounds: int = 1
    normal_vote_units: int = 2
    sheriff_vote_units: int = 3

    def __post_init__(self) -> None:
        if len(self.roles) != 9:
            raise ValueError("WolfScope v1 requires exactly nine roles")
        expected = {
            RoleType.WEREWOLF: 3,
            RoleType.VILLAGER: 3,
            RoleType.SEER: 1,
            RoleType.WITCH: 1,
            RoleType.HUNTER: 1,
        }
        actual = {role: self.roles.count(role) for role in RoleType}
        if actual != expected:
            raise ValueError(f"invalid standard nine-player role counts: {actual}")
        if self.exile_revote_rounds < 0:
            raise ValueError("exile_revote_rounds must be non-negative")
        if self.normal_vote_units <= 0:
            raise ValueError("normal_vote_units must be positive")
        if self.sheriff_vote_units < self.normal_vote_units:
            raise ValueError("sheriff vote weight cannot be lower than normal")


STANDARD_9_RULES = RuleConfig()
