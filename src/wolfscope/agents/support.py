"""Temporary strategy-free actions for M2 decisions not yet owned by agents."""

from __future__ import annotations

from wolfscope.game.day import DayTurnAction, SpeechDirection
from wolfscope.game.night import WitchAction


class DeterministicSupportProvider:
    """Return simple legal choices without inspecting authoritative GameState."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int | None]] = []

    def _record(self, action: str, day: int, actor: int | None = None) -> None:
        self.calls.append((action, day, actor))

    async def choose_wolf_target(self, observation) -> int:
        self._record("wolf_target", observation.day)
        non_wolves = [
            seat
            for seat in observation.eligible_targets
            if seat not in observation.wolf_seats
        ]
        choices = non_wolves or list(observation.eligible_targets)
        return choices[0]

    async def choose_seer_target(self, observation) -> int:
        self._record("seer_target", observation.day, observation.seer_seat)
        return observation.eligible_targets[0]

    async def choose_witch_action(self, observation) -> WitchAction:
        self._record("witch_action", observation.day, observation.witch_seat)
        return WitchAction.pass_night()

    async def choose_signup(self, observation) -> bool:
        self._record("sheriff_signup", observation.day, observation.actor)
        return False

    async def campaign_speech(self, observation) -> str:
        self._record("campaign_speech", observation.day, observation.actor)
        return f"{observation.actor}号竞选发言"

    async def choose_withdrawal(self, observation) -> bool:
        self._record("sheriff_withdrawal", observation.day, observation.actor)
        return False

    async def choose_sheriff_vote(self, observation) -> int | None:
        self._record("sheriff_vote", observation.day, observation.voter)
        return None

    async def choose_speech_direction(self, observation) -> SpeechDirection:
        self._record("speech_direction", observation.day, observation.sheriff)
        return SpeechDirection.CLOCKWISE

    async def take_day_turn(self, observation) -> DayTurnAction:
        self._record("support_day_turn", observation.day, observation.actor)
        return DayTurnAction.speak(f"{observation.actor}号暂无新增信息。")

    async def choose_exile_vote(self, observation) -> int | None:
        self._record("support_exile_vote", observation.day, observation.voter)
        return None

    async def pk_speech(self, observation) -> str:
        self._record("pk_speech", observation.day, observation.actor)
        return f"{observation.actor}号PK阶段暂无新增信息。"

    async def last_words(self, observation) -> str:
        self._record("last_words", observation.day, observation.actor)
        return f"{observation.actor}号没有更多遗言。"

    async def death_last_words(self, observation) -> str:
        self._record("death_last_words", observation.day, observation.actor)
        return f"{observation.actor}号没有更多遗言。"

    async def choose_hunter_target(self, observation) -> int | None:
        self._record("hunter_target", observation.day, observation.hunter)
        return None

    async def choose_badge_transfer(self, observation) -> int | None:
        self._record("badge_transfer", observation.day, observation.former_sheriff)
        return None
