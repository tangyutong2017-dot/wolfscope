"""Stable domain enums for the nine-player ruleset."""

from enum import StrEnum


class Faction(StrEnum):
    WEREWOLF = "werewolf"
    DEITY = "deity"
    CIVILIAN = "civilian"


class Camp(StrEnum):
    WEREWOLF = "werewolf"
    GOOD = "good"


class RoleType(StrEnum):
    WEREWOLF = "werewolf"
    VILLAGER = "villager"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"

    @property
    def faction(self) -> Faction:
        return {
            RoleType.WEREWOLF: Faction.WEREWOLF,
            RoleType.VILLAGER: Faction.CIVILIAN,
            RoleType.SEER: Faction.DEITY,
            RoleType.WITCH: Faction.DEITY,
            RoleType.HUNTER: Faction.DEITY,
        }[self]

    @property
    def camp(self) -> Camp:
        return Camp.WEREWOLF if self is RoleType.WEREWOLF else Camp.GOOD


class DeathCause(StrEnum):
    WEREWOLF = "werewolf"
    POISON = "poison"
    EXILE = "exile"
    HUNTER_SHOT = "hunter_shot"
    WOLF_EXPLODE = "wolf_explode"


class Phase(StrEnum):
    SETUP = "setup"

    NIGHT_WOLF = "night_wolf"
    NIGHT_SEER = "night_seer"
    NIGHT_WITCH = "night_witch"
    NIGHT_RESOLUTION = "night_resolution"

    SHERIFF_SIGNUP = "sheriff_signup"
    SHERIFF_SPEECH = "sheriff_speech"
    SHERIFF_WITHDRAWAL = "sheriff_withdrawal"
    SHERIFF_VOTE = "sheriff_vote"

    DAWN_ANNOUNCEMENT = "dawn_announcement"
    DAY_SPEECH = "day_speech"
    DAY_VOTE = "day_vote"
    DAY_PK_SPEECH = "day_pk_speech"
    DAY_REVOTE = "day_revote"

    DEATH_LAST_WORDS = "death_last_words"
    HUNTER_SHOT = "hunter_shot"
    BADGE_TRANSFER = "badge_transfer"
    WIN_CHECK = "win_check"

    FINISHED = "finished"


class WinReason(StrEnum):
    ALL_WOLVES_DEAD = "all_wolves_dead"
    ALL_DEITIES_DEAD = "all_deities_dead"
    ALL_CIVILIANS_DEAD = "all_civilians_dead"
