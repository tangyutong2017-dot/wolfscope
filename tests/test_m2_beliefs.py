from __future__ import annotations

import unittest

from wolfscope.cognition.beliefs import BeliefStateBuilder
from wolfscope.cognition.claims import ClaimPolarity, RoleClaim
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


if __name__ == "__main__":
    unittest.main()
