"""M1-3 first-day sheriff election and dawn announcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from wolfscope.contracts import GameEvent, Visibility

from .events import EventLog
from .state import GameState
from .types import Phase

if TYPE_CHECKING:
    from .resolution import DeathResolutionProvider, DeathResolutionResult


class IllegalSheriffAction(ValueError):
    """Raised when a provider submits an invalid election action."""


@dataclass(frozen=True, slots=True)
class SheriffSignupObservation:
    day: int
    actor: int
    eligible_seats: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CampaignSpeechObservation:
    day: int
    actor: int
    candidates: tuple[int, ...]
    previous_speeches: tuple[tuple[int, str], ...]


@dataclass(frozen=True, slots=True)
class SheriffWithdrawalObservation:
    day: int
    actor: int
    candidates: tuple[int, ...]
    campaign_speeches: tuple[tuple[int, str], ...]


@dataclass(frozen=True, slots=True)
class SheriffVoteObservation:
    day: int
    voter: int
    candidates: tuple[int, ...]
    campaign_speeches: tuple[tuple[int, str], ...]
    withdrawn: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SheriffElectionResult:
    original_candidates: tuple[int, ...]
    remaining_candidates: tuple[int, ...]
    withdrawn: tuple[int, ...]
    speech_order: tuple[int, ...]
    speeches: tuple[tuple[int, str], ...]
    votes: tuple[tuple[int, int | None], ...]
    sheriff: int | None
    reason: str
    events: tuple[GameEvent, ...]


@dataclass(frozen=True, slots=True)
class DawnAnnouncementResult:
    deaths: tuple[int, ...]
    events: tuple[GameEvent, ...]


class SheriffActionProvider(Protocol):
    """Structured election choices; implementations never receive GameState."""

    async def choose_signup(self, observation: SheriffSignupObservation) -> bool:
        ...

    async def campaign_speech(self, observation: CampaignSpeechObservation) -> str:
        ...

    async def choose_withdrawal(
        self,
        observation: SheriffWithdrawalObservation,
    ) -> bool:
        ...

    async def choose_sheriff_vote(
        self,
        observation: SheriffVoteObservation,
    ) -> int | None:
        ...


def _circular_order(seats: list[int], start: int) -> list[int]:
    """Return selected seats clockwise from a fixed seat on the 1..9 ring."""

    selected = set(seats)
    return [
        seat
        for offset in range(9)
        if (seat := (start - 1 + offset) % 9 + 1) in selected
    ]


class SheriffElectionEngine:
    def __init__(self, state: GameState, events: EventLog) -> None:
        self.state = state
        self.events = events

    async def run(self, provider: SheriffActionProvider) -> SheriffElectionResult:
        if self.state.day != 1:
            raise RuntimeError("sheriff election can only run on day one")
        if self.state.sheriff.election_completed:
            raise RuntimeError("sheriff election has already completed")
        if not self.state.rules.sheriff_enabled:
            self.state.sheriff.election_completed = True
            self.state.sheriff.badge_exists = False
            return self._result(reason="sheriff_disabled")

        start_index = len(self.events)
        eligible = self.state.sheriff_election_eligible_seats()

        # Signup is simultaneous in game semantics: every observation contains
        # the same public state and none of the choices collected so far.
        self.state.phase = Phase.SHERIFF_SIGNUP
        signup_choices: dict[int, bool] = {}
        for seat in eligible:
            observation = SheriffSignupObservation(
                day=self.state.day,
                actor=seat,
                eligible_seats=tuple(eligible),
            )
            choice = await provider.choose_signup(observation)
            if not isinstance(choice, bool):
                raise IllegalSheriffAction("signup choice must be boolean")
            signup_choices[seat] = choice

        original_candidates = [seat for seat in eligible if signup_choices[seat]]
        self.events.emit(
            day=self.state.day,
            phase=Phase.SHERIFF_SIGNUP,
            event_type="sheriff_candidates",
            visibility=Visibility.PUBLIC,
            content=(
                "上警玩家：" + "、".join(f"{seat}号" for seat in original_candidates)
                if original_candidates
                else "无人上警"
            ),
            data={"candidates": original_candidates},
        )
        if not original_candidates:
            return self._finish_no_sheriff(
                original_candidates=(),
                reason="no_candidates",
                start_index=start_index,
            )

        # Candidates speak sequentially from a seed-fixed random start. Later
        # speakers may observe earlier public speeches.
        self.state.phase = Phase.SHERIFF_SPEECH
        start = self.state.choose_seeded_start(original_candidates)
        speech_order = _circular_order(original_candidates, start)
        speeches: list[tuple[int, str]] = []
        for seat in speech_order:
            speech = await provider.campaign_speech(
                CampaignSpeechObservation(
                    day=self.state.day,
                    actor=seat,
                    candidates=tuple(original_candidates),
                    previous_speeches=tuple(speeches),
                ),
            )
            if not isinstance(speech, str) or not speech.strip():
                raise IllegalSheriffAction("campaign speech must be non-empty")
            speech = speech.strip()
            speeches.append((seat, speech))
            self.events.emit(
                day=self.state.day,
                phase=Phase.SHERIFF_SPEECH,
                event_type="sheriff_campaign_speech",
                visibility=Visibility.PUBLIC,
                actor=seat,
                content=speech,
            )

        # Withdrawal is simultaneous: no observation includes choices already
        # collected from another candidate.
        self.state.phase = Phase.SHERIFF_WITHDRAWAL
        withdrawal_choices: dict[int, bool] = {}
        common_speeches = tuple(speeches)
        for seat in original_candidates:
            choice = await provider.choose_withdrawal(
                SheriffWithdrawalObservation(
                    day=self.state.day,
                    actor=seat,
                    candidates=tuple(original_candidates),
                    campaign_speeches=common_speeches,
                ),
            )
            if not isinstance(choice, bool):
                raise IllegalSheriffAction("withdrawal choice must be boolean")
            withdrawal_choices[seat] = choice

        withdrawn = [seat for seat in original_candidates if withdrawal_choices[seat]]
        remaining = [seat for seat in original_candidates if not withdrawal_choices[seat]]
        self.events.emit(
            day=self.state.day,
            phase=Phase.SHERIFF_WITHDRAWAL,
            event_type="sheriff_withdrawals",
            visibility=Visibility.PUBLIC,
            content=(
                "退水玩家：" + "、".join(f"{seat}号" for seat in withdrawn)
                if withdrawn
                else "无人退水"
            ),
            data={"withdrawn": withdrawn, "remaining": remaining},
        )

        if not remaining:
            return self._finish_no_sheriff(
                original_candidates=tuple(original_candidates),
                remaining_candidates=(),
                withdrawn=tuple(withdrawn),
                speech_order=tuple(speech_order),
                speeches=tuple(speeches),
                reason="all_withdrew",
                start_index=start_index,
            )
        if len(remaining) == 1:
            return self._finish_with_sheriff(
                sheriff=remaining[0],
                original_candidates=tuple(original_candidates),
                remaining_candidates=tuple(remaining),
                withdrawn=tuple(withdrawn),
                speech_order=tuple(speech_order),
                speeches=tuple(speeches),
                votes=(),
                reason="sole_candidate",
                start_index=start_index,
            )

        # Original signup participants cannot vote even after withdrawing.
        self.state.phase = Phase.SHERIFF_VOTE
        voters = [seat for seat in eligible if seat not in original_candidates]
        votes: list[tuple[int, int | None]] = []
        for voter in voters:
            target = await provider.choose_sheriff_vote(
                SheriffVoteObservation(
                    day=self.state.day,
                    voter=voter,
                    candidates=tuple(remaining),
                    campaign_speeches=tuple(speeches),
                    withdrawn=tuple(withdrawn),
                ),
            )
            if target is not None and target not in remaining:
                raise IllegalSheriffAction(f"illegal sheriff vote target: {target}")
            votes.append((voter, target))

        counts = {candidate: 0 for candidate in remaining}
        for _, target in votes:
            if target is not None:
                counts[target] += self.state.rules.normal_vote_units
        self.events.emit(
            day=self.state.day,
            phase=Phase.SHERIFF_VOTE,
            event_type="sheriff_votes",
            visibility=Visibility.PUBLIC,
            content="警长竞选投票完成",
            data={
                "votes": [{"voter": voter, "target": target} for voter, target in votes],
                "vote_units": {
                    str(seat): units for seat, units in counts.items()
                },
            },
        )

        highest = max(counts.values(), default=0)
        winners = [seat for seat, units in counts.items() if units == highest and units > 0]
        if len(winners) != 1:
            reason = "no_valid_votes" if not winners else "tie"
            return self._finish_no_sheriff(
                original_candidates=tuple(original_candidates),
                remaining_candidates=tuple(remaining),
                withdrawn=tuple(withdrawn),
                speech_order=tuple(speech_order),
                speeches=tuple(speeches),
                votes=tuple(votes),
                reason=reason,
                start_index=start_index,
            )
        return self._finish_with_sheriff(
            sheriff=winners[0],
            original_candidates=tuple(original_candidates),
            remaining_candidates=tuple(remaining),
            withdrawn=tuple(withdrawn),
            speech_order=tuple(speech_order),
            speeches=tuple(speeches),
            votes=tuple(votes),
            reason="elected",
            start_index=start_index,
        )

    def _finish_with_sheriff(
        self,
        *,
        sheriff: int,
        original_candidates: tuple[int, ...],
        remaining_candidates: tuple[int, ...],
        withdrawn: tuple[int, ...],
        speech_order: tuple[int, ...],
        speeches: tuple[tuple[int, str], ...],
        votes: tuple[tuple[int, int | None], ...],
        reason: str,
        start_index: int,
    ) -> SheriffElectionResult:
        self.state.sheriff.holder = sheriff
        self.state.sheriff.badge_exists = True
        self.state.sheriff.election_completed = True
        self.events.emit(
            day=self.state.day,
            phase=Phase.SHERIFF_VOTE,
            event_type="sheriff_elected",
            visibility=Visibility.PUBLIC,
            actor=sheriff,
            content=f"{sheriff}号当选警长",
            data={"sheriff": sheriff, "reason": reason},
        )
        return SheriffElectionResult(
            original_candidates=original_candidates,
            remaining_candidates=remaining_candidates,
            withdrawn=withdrawn,
            speech_order=speech_order,
            speeches=speeches,
            votes=votes,
            sheriff=sheriff,
            reason=reason,
            events=self.events.events[start_index:],
        )

    def _finish_no_sheriff(
        self,
        *,
        original_candidates: tuple[int, ...],
        remaining_candidates: tuple[int, ...] = (),
        withdrawn: tuple[int, ...] = (),
        speech_order: tuple[int, ...] = (),
        speeches: tuple[tuple[int, str], ...] = (),
        votes: tuple[tuple[int, int | None], ...] = (),
        reason: str,
        start_index: int,
    ) -> SheriffElectionResult:
        self.state.sheriff.holder = None
        self.state.sheriff.badge_exists = False
        self.state.sheriff.election_completed = True
        self.events.emit(
            day=self.state.day,
            phase=Phase.SHERIFF_VOTE,
            event_type="sheriff_failed",
            visibility=Visibility.PUBLIC,
            content="本局流警，无警长",
            data={"reason": reason},
        )
        return SheriffElectionResult(
            original_candidates=original_candidates,
            remaining_candidates=remaining_candidates,
            withdrawn=withdrawn,
            speech_order=speech_order,
            speeches=speeches,
            votes=votes,
            sheriff=None,
            reason=reason,
            events=self.events.events[start_index:],
        )

    def _result(self, reason: str) -> SheriffElectionResult:
        return SheriffElectionResult(
            original_candidates=(),
            remaining_candidates=(),
            withdrawn=(),
            speech_order=(),
            speeches=(),
            votes=(),
            sheriff=None,
            reason=reason,
            events=(),
        )


class DawnAnnouncementEngine:
    """Publish pending deaths without triggering hunter or badge transfer."""

    def __init__(self, state: GameState, events: EventLog) -> None:
        self.state = state
        self.events = events

    def announce(self) -> DawnAnnouncementResult:
        start_index = len(self.events)
        pending = sorted(self.state.pending_deaths.values(), key=lambda item: item.seat)
        for item in pending:
            if not self.state.get_player(item.seat).alive:
                raise RuntimeError(f"pending death target {item.seat} is already dead")

        self.state.phase = Phase.DAWN_ANNOUNCEMENT
        for item in pending:
            self.state.mark_dead(item.seat, item.effective_cause)

        deaths = tuple(item.seat for item in pending)
        if deaths:
            self.events.emit(
                day=self.state.day,
                phase=Phase.DAWN_ANNOUNCEMENT,
                event_type="dawn_deaths",
                visibility=Visibility.PUBLIC,
                content="昨夜死亡：" + "、".join(f"{seat}号" for seat in deaths),
                data={"deaths": list(deaths)},
            )
        else:
            self.events.emit(
                day=self.state.day,
                phase=Phase.DAWN_ANNOUNCEMENT,
                event_type="peaceful_night",
                visibility=Visibility.PUBLIC,
                content="昨夜是平安夜",
                data={"deaths": []},
            )

        self.events.emit(
            day=self.state.day,
            phase=Phase.DAWN_ANNOUNCEMENT,
            event_type="dawn_death_causes",
            visibility=Visibility.GOD,
            content="首夜死亡原因已结算",
            data={
                "deaths": [
                    {
                        "seat": item.seat,
                        "causes": sorted(cause.value for cause in item.causes),
                        "effective_cause": item.effective_cause.value,
                    }
                    for item in pending
                ],
            },
        )

        holder = self.state.sheriff.holder
        if holder is not None and not self.state.get_player(holder).alive:
            self.state.sheriff.transfer_pending_from = holder

        self.state.pending_deaths.clear()
        return DawnAnnouncementResult(
            deaths=deaths,
            events=self.events.events[start_index:],
        )

    async def announce_and_resolve(
        self,
        provider: DeathResolutionProvider,
    ) -> tuple[DawnAnnouncementResult, DeathResolutionResult]:
        """Announce a night batch, then finish its M1-5 death chain."""

        from .resolution import DeathResolutionEngine

        announcement = self.announce()
        resolution = await DeathResolutionEngine(self.state, self.events).resolve(
            announcement.deaths,
            provider,
            last_words_seats=announcement.deaths if self.state.day == 1 else (),
        )
        return announcement, resolution
