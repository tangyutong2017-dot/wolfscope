from __future__ import annotations

import unittest

from wolfscope.cognition.beliefs import BeliefStateBuilder
from wolfscope.cognition.claims import (
    ClaimPolarity,
    RoleClaim,
    VoteIntentClaim,
    VoteIntentType,
)
from wolfscope.cognition.ledger import EvidenceLedger
from wolfscope.contracts import Visibility
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.types import Phase, RoleType
from wolfscope.player_view import PlayerViewBuilder


def state() -> GameState:
    return GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )


def ledger_for(seat: int, events: EventLog | None = None) -> tuple[EvidenceLedger, object]:
    view = PlayerViewBuilder(state(), events or EventLog()).build(seat)
    ledger = EvidenceLedger(owner=seat)
    ledger.sync(view)
    return ledger, view


class BeliefStateTests(unittest.TestCase):
    def test_villager_prior_conditions_on_own_known_role(self) -> None:
        ledger, _ = ledger_for(4)

        belief = BeliefStateBuilder().build(ledger)

        own = belief.seat_beliefs[3]
        other = belief.seat_beliefs[0]
        self.assertEqual(own.roles.villager, 1.0)
        self.assertAlmostEqual(other.roles.werewolf, 3 / 8)
        self.assertAlmostEqual(other.roles.villager, 2 / 8)
        self.assertEqual(belief.owner, 4)

    def test_wolf_teammates_are_confirmed_without_leaking_to_other_players(self) -> None:
        wolf_ledger, _ = ledger_for(1)
        villager_ledger, _ = ledger_for(4)

        wolf_belief = BeliefStateBuilder().build(wolf_ledger)
        villager_belief = BeliefStateBuilder().build(villager_ledger)

        self.assertEqual(wolf_belief.seat_beliefs[1].roles.werewolf, 1.0)
        self.assertEqual(wolf_belief.seat_beliefs[2].roles.werewolf, 1.0)
        self.assertAlmostEqual(villager_belief.seat_beliefs[1].roles.werewolf, 3 / 8)

    def test_real_seer_checks_apply_hard_camp_constraints(self) -> None:
        events = EventLog()
        events.emit(
            day=1,
            phase=Phase.NIGHT_SEER,
            event_type="seer_result",
            visibility=Visibility.PRIVATE,
            recipients=(7,),
            actor=7,
            target=1,
            content="查验1号为狼人",
            data={"target": 1, "alignment": "werewolf"},
        )
        events.emit(
            day=2,
            phase=Phase.NIGHT_SEER,
            event_type="seer_result",
            visibility=Visibility.PRIVATE,
            recipients=(7,),
            actor=7,
            target=4,
            content="查验4号为好人",
            data={"target": 4, "alignment": "good"},
        )
        ledger, _ = ledger_for(7, events)

        belief = BeliefStateBuilder().build(ledger)

        self.assertEqual(belief.seat_beliefs[0].roles.werewolf, 1.0)
        self.assertEqual(belief.seat_beliefs[3].camps.good, 1.0)
        self.assertEqual(belief.seat_beliefs[3].roles.werewolf, 0.0)
        self.assertGreaterEqual(len(belief.seat_beliefs[0].supporting_evidence_ids), 1)

    def test_public_role_claims_create_conflict_without_changing_priors(self) -> None:
        events = EventLog()
        events.emit(
            day=1,
            phase=Phase.DAY_SPEECH,
            event_type="day_speech",
            visibility=Visibility.PUBLIC,
            actor=1,
            content="1号和7号都声称预言家",
        )
        ledger, view = ledger_for(4, events)
        event = next(item for item in view.visible_events if item.event_type == "day_speech")
        ledger.ingest_public_claims(
            event=event,
            speaker=1,
            claims=(
                RoleClaim(
                    subject=1,
                    role=RoleType.SEER,
                    polarity=ClaimPolarity.ASSERT,
                    summary="1号声称预言家",
                    supporting_text="1号和7号都声称预言家",
                ),
                RoleClaim(
                    subject=7,
                    role=RoleType.SEER,
                    polarity=ClaimPolarity.ASSERT,
                    summary="7号声称预言家",
                    supporting_text="1号和7号都声称预言家",
                ),
            ),
            extractor_version="test",
        )

        belief = BeliefStateBuilder().build(ledger)

        self.assertAlmostEqual(belief.seat_beliefs[0].roles.werewolf, 3 / 8)
        self.assertEqual(len(belief.claimed_roles), 2)
        self.assertEqual(len(belief.conflicts), 1)
        self.assertEqual(belief.conflicts[0].role, "seer")
        self.assertEqual(belief.conflicts[0].seats, (1, 7))

    def test_day_one_single_seer_gets_high_provisional_trust_only(self) -> None:
        events = EventLog()
        speech = events.emit(
            day=1,
            phase=Phase.DAY_SPEECH,
            event_type="day_speech",
            visibility=Visibility.PUBLIC,
            actor=7,
            content="我是预言家",
        )
        ledger, _ = ledger_for(4, events)
        ledger.ingest_public_claims(
            event=speech,
            speaker=7,
            claims=(
                RoleClaim(
                    subject=7,
                    role=RoleType.SEER,
                    polarity=ClaimPolarity.ASSERT,
                    summary="7号声称预言家",
                    supporting_text="我是预言家",
                ),
            ),
            extractor_version="test",
        )

        belief = BeliefStateBuilder().build(ledger)
        claimant = belief.seat_beliefs[6]

        self.assertEqual(claimant.trust_score, 0.75)
        self.assertNotEqual(claimant.roles.seer, 1.0)

    def test_single_seer_provisional_trust_expires_after_day_one(self) -> None:
        events = EventLog()
        speech = events.emit(
            day=1,
            phase=Phase.DAY_SPEECH,
            event_type="day_speech",
            visibility=Visibility.PUBLIC,
            actor=7,
            content="我是预言家",
        )
        events.emit(
            day=2,
            phase=Phase.DAWN_ANNOUNCEMENT,
            event_type="peaceful_night",
            visibility=Visibility.PUBLIC,
            content="昨夜是平安夜",
            data={"deaths": []},
        )
        ledger, _ = ledger_for(4, events)
        ledger.ingest_public_claims(
            event=speech,
            speaker=7,
            claims=(RoleClaim(subject=7, role=RoleType.SEER, polarity="assert", summary="7号声称预言家", supporting_text="我是预言家"),),
            extractor_version="test",
        )

        belief = BeliefStateBuilder().build(ledger)

        self.assertEqual(belief.seat_beliefs[6].trust_score, 0.0)

    def test_belief_revision_and_references_are_player_local(self) -> None:
        ledger, _ = ledger_for(4)

        belief = BeliefStateBuilder().build(ledger)

        self.assertEqual(belief.revision, ledger.revision)
        referenced = [
            evidence_id
            for seat in belief.seat_beliefs
            for evidence_id in seat.supporting_evidence_ids
        ]
        self.assertTrue(referenced)
        self.assertTrue(all(value.startswith("p4-e") for value in referenced))

    def test_conflicting_self_role_claims_are_recorded(self) -> None:
        events = EventLog()
        first = events.emit(
            day=1, phase=Phase.DAY_SPEECH, event_type="day_speech",
            visibility=Visibility.PUBLIC, actor=8, content="我是预言家",
        )
        second = events.emit(
            day=1, phase=Phase.DAY_SPEECH, event_type="day_speech",
            visibility=Visibility.PUBLIC, actor=8, content="我是村民",
        )
        ledger, _ = ledger_for(4, events)
        ledger.ingest_public_claims(
            event=first, speaker=8,
            claims=(RoleClaim(subject=8, role=RoleType.SEER, polarity="assert", summary="8号声称预言家", supporting_text="我是预言家"),),
            extractor_version="test",
        )
        ledger.ingest_public_claims(
            event=second, speaker=8,
            claims=(RoleClaim(subject=8, role=RoleType.VILLAGER, polarity="assert", summary="8号声称村民", supporting_text="我是村民"),),
            extractor_version="test",
        )

        conflicts = BeliefStateBuilder().build(ledger).conflicts

        conflict = next(item for item in conflicts if item.kind == "self_role_claim_conflict")
        self.assertEqual(conflict.seat, 8)
        self.assertEqual((conflict.earlier_role, conflict.later_role), (RoleType.SEER, RoleType.VILLAGER))

    def test_self_assert_then_deny_same_role_conflicts_but_third_party_does_not(self) -> None:
        events = EventLog()
        speech = events.emit(
            day=1, phase=Phase.DAY_SPEECH, event_type="day_speech",
            visibility=Visibility.PUBLIC, actor=8,
            content="我是预言家；我不是预言家；7号是猎人",
        )
        ledger, _ = ledger_for(4, events)
        ledger.ingest_public_claims(
            event=speech, speaker=8,
            claims=(
                RoleClaim(subject=8, role=RoleType.SEER, polarity="assert", summary="8号声称预言家", supporting_text="我是预言家"),
                RoleClaim(subject=8, role=RoleType.SEER, polarity="deny", summary="8号否认预言家", supporting_text="我不是预言家"),
                RoleClaim(subject=7, role=RoleType.HUNTER, polarity="assert", summary="8号称7号是猎人", supporting_text="7号是猎人"),
            ), extractor_version="test",
        )

        conflicts = BeliefStateBuilder().build(ledger).conflicts

        self.assertEqual(sum(item.kind == "self_role_claim_conflict" for item in conflicts), 1)

    def test_latest_unconditional_vote_intent_is_compared_with_actual_vote(self) -> None:
        events = EventLog()
        speech = events.emit(
            day=1, phase=Phase.DAY_SPEECH, event_type="day_speech",
            visibility=Visibility.PUBLIC, actor=8, content="今天我投1号",
        )
        ledger, _ = ledger_for(4, events)
        ledger.ingest_public_claims(
            event=speech, speaker=8,
            claims=(VoteIntentClaim(target=1, intent=VoteIntentType.VOTE, conditional=False, summary="8号决定投1号", supporting_text="今天我投1号"),),
            extractor_version="test",
        )
        events.emit(
            day=1, phase=Phase.DAY_VOTE, event_type="exile_votes",
            visibility=Visibility.PUBLIC, content="放逐投票结束",
            data={"votes": [{"voter": 8, "target": 7, "units": 1}]},
        )
        ledger.sync(PlayerViewBuilder(state(), events).build(4))

        conflicts = BeliefStateBuilder().build(ledger).conflicts

        conflict = next(item for item in conflicts if item.kind == "vote_behavior_conflict")
        self.assertEqual((conflict.declared_target, conflict.actual_target), (1, 7))
        self.assertEqual(conflict.reason, "declared_vote_changed")

    def test_conditional_vote_intent_is_not_a_vote_behavior_conflict(self) -> None:
        events = EventLog()
        speech = events.emit(
            day=1, phase=Phase.DAY_SPEECH, event_type="day_speech",
            visibility=Visibility.PUBLIC, actor=8, content="如果1号不解释，我会投1号",
        )
        ledger, _ = ledger_for(4, events)
        ledger.ingest_public_claims(
            event=speech, speaker=8,
            claims=(VoteIntentClaim(target=1, intent="vote", conditional=True, condition="1号不解释", summary="8号条件性投1号", supporting_text="如果1号不解释，我会投1号"),),
            extractor_version="test",
        )
        events.emit(
            day=1, phase=Phase.DAY_VOTE, event_type="exile_votes",
            visibility=Visibility.PUBLIC, content="放逐投票结束",
            data={"votes": [{"voter": 8, "target": 7, "units": 1}]},
        )
        ledger.sync(PlayerViewBuilder(state(), events).build(4))

        conflicts = BeliefStateBuilder().build(ledger).conflicts

        self.assertFalse(any(item.kind == "vote_behavior_conflict" for item in conflicts))

    def test_declared_avoid_target_then_voting_target_is_a_conflict(self) -> None:
        events = EventLog()
        speech = events.emit(
            day=1, phase=Phase.DAY_SPEECH, event_type="day_speech",
            visibility=Visibility.PUBLIC, actor=8, content="今天我不会投1号",
        )
        ledger, _ = ledger_for(4, events)
        ledger.ingest_public_claims(
            event=speech, speaker=8,
            claims=(VoteIntentClaim(target=1, intent="avoid", conditional=False, summary="8号不会投1号", supporting_text="今天我不会投1号"),),
            extractor_version="test",
        )
        events.emit(
            day=1, phase=Phase.DAY_VOTE, event_type="exile_votes",
            visibility=Visibility.PUBLIC, content="放逐投票结束",
            data={"votes": [{"voter": 8, "target": 1, "units": 1}]},
        )
        ledger.sync(PlayerViewBuilder(state(), events).build(4))

        conflict = next(
            item for item in BeliefStateBuilder().build(ledger).conflicts
            if item.kind == "vote_behavior_conflict"
        )
        self.assertEqual(conflict.reason, "declared_avoid_violated")


if __name__ == "__main__":
    unittest.main()
