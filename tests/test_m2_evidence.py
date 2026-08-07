from __future__ import annotations

import unittest

from wolfscope.cognition.evidence import (
    ActualVoteFact,
    HunterDidNotShootFact,
    OwnRoleFact,
    RawSpeech,
    WitchPoisonUsedDeducedFact,
    WitchSaveDeducedFact,
    WolfTeammateFact,
    WitchVictimFact,
)
from wolfscope.cognition.ledger import EvidenceLedger, EvidenceLedgerRegistry
from wolfscope.contracts import Visibility
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.types import Phase
from wolfscope.player_view import PlayerViewBuilder


def fixed_state() -> GameState:
    return GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
    )


class EvidenceLedgerTests(unittest.TestCase):
    def test_registry_owns_nine_isolated_ledgers(self) -> None:
        registry = EvidenceLedgerRegistry()

        self.assertEqual(registry.seats, tuple(range(1, 10)))
        self.assertIsNot(registry.get(1), registry.get(2))
        registry.sync(PlayerViewBuilder(fixed_state(), EventLog()).build(1))
        self.assertGreater(len(registry.get(1).records), 0)
        self.assertEqual(registry.get(2).records, [])

    def test_role_seed_is_private_stable_and_deduplicated(self) -> None:
        state = fixed_state()
        events = EventLog()
        builder = PlayerViewBuilder(state, events)
        wolf_ledger = EvidenceLedger(owner=1)
        villager_ledger = EvidenceLedger(owner=4)

        first = wolf_ledger.sync(builder.build(1))
        second = wolf_ledger.sync(builder.build(1))
        villager_ledger.sync(builder.build(4))

        self.assertEqual(len(first), 3)
        self.assertEqual(second, ())
        self.assertIsInstance(first[0].content, OwnRoleFact)
        teammates = {
            record.content.teammate
            for record in first
            if isinstance(record.content, WolfTeammateFact)
        }
        self.assertEqual(teammates, {2, 3})
        self.assertFalse(
            any(
                isinstance(record.content, WolfTeammateFact)
                for record in villager_ledger.records
            ),
        )
        self.assertEqual(
            [record.evidence_id for record in wolf_ledger.records],
            ["p1-e1", "p1-e2", "p1-e3"],
        )

    def test_public_speech_and_votes_become_granular_evidence(self) -> None:
        state = fixed_state()
        events = EventLog()
        events.emit(
            day=1,
            phase=Phase.DAY_SPEECH,
            event_type="day_speech",
            visibility=Visibility.PUBLIC,
            actor=7,
            content="我是预言家，昨夜查验1号是狼人。",
        )
        events.emit(
            day=1,
            phase=Phase.DAY_VOTE,
            event_type="exile_votes",
            visibility=Visibility.PUBLIC,
            content="放逐投票结果公布",
            data={
                "votes": [
                    {"voter": 1, "target": 7, "units": 2},
                    {"voter": 2, "target": 7, "units": 2},
                ],
            },
        )
        ledger = EvidenceLedger(owner=4)

        ledger.sync(PlayerViewBuilder(state, events).build(4))

        speeches = [
            record.content
            for record in ledger.records
            if isinstance(record.content, RawSpeech)
        ]
        votes = [
            record.content
            for record in ledger.records
            if isinstance(record.content, ActualVoteFact)
        ]
        self.assertEqual(len(speeches), 1)
        self.assertEqual(speeches[0].speaker, 7)
        self.assertEqual([(vote.voter, vote.target) for vote in votes], [(1, 7), (2, 7)])

    def test_rule_certain_witch_deductions_are_separate_records(self) -> None:
        state = fixed_state()
        events = EventLog()
        events.emit(
            day=1,
            phase=Phase.DAWN_ANNOUNCEMENT,
            event_type="peaceful_night",
            visibility=Visibility.PUBLIC,
            content="昨夜是平安夜",
            data={"deaths": []},
        )
        events.emit(
            day=2,
            phase=Phase.DAWN_ANNOUNCEMENT,
            event_type="dawn_deaths",
            visibility=Visibility.PUBLIC,
            content="昨夜死亡：4号、5号",
            data={"deaths": [4, 5]},
        )
        ledger = EvidenceLedger(owner=6)

        ledger.sync(PlayerViewBuilder(state, events).build(6))

        save = next(
            record
            for record in ledger.records
            if isinstance(record.content, WitchSaveDeducedFact)
        )
        poison = next(
            record
            for record in ledger.records
            if isinstance(record.content, WitchPoisonUsedDeducedFact)
        )
        self.assertEqual(save.extraction_method, "rule_derivation")
        self.assertEqual(poison.extraction_method, "rule_derivation")

    def test_hunter_did_not_shoot_confirms_hunter_identity(self) -> None:
        state = fixed_state()
        events = EventLog()
        events.emit(
            day=1,
            phase=Phase.HUNTER_SHOT,
            event_type="hunter_did_not_shoot",
            visibility=Visibility.PUBLIC,
            actor=9,
            content="9号猎人选择不开枪",
        )
        ledger = EvidenceLedger(owner=4)

        ledger.sync(PlayerViewBuilder(state, events).build(4))

        fact = next(
            record.content
            for record in ledger.records
            if isinstance(record.content, HunterDidNotShootFact)
        )
        self.assertEqual(fact.hunter, 9)

    def test_witch_victim_occurs_before_it_becomes_known(self) -> None:
        state = fixed_state()
        events = EventLog()
        events.emit(
            day=1,
            phase=Phase.NIGHT_WITCH,
            event_type="witch_night_victim",
            visibility=Visibility.PRIVATE,
            recipients=(8,),
            actor=8,
            target=4,
            content="今晚狼队袭击了4号",
            data={"target": 4},
        )
        ledger = EvidenceLedger(owner=8)

        ledger.sync(PlayerViewBuilder(state, events).build(8))

        record = next(
            record
            for record in ledger.records
            if isinstance(record.content, WitchVictimFact)
        )
        self.assertIs(record.occurred_at.phase, Phase.NIGHT_WOLF)
        self.assertIs(record.known_at.phase, Phase.NIGHT_WITCH)

    def test_stale_view_is_rejected(self) -> None:
        state = fixed_state()
        events = EventLog()
        builder = PlayerViewBuilder(state, events)
        old_view = builder.build(4)
        events.emit(
            day=1,
            phase=Phase.DAY_SPEECH,
            event_type="day_speech",
            visibility=Visibility.PUBLIC,
            actor=1,
            content="新增发言",
        )
        ledger = EvidenceLedger(owner=4)
        ledger.sync(builder.build(4))

        with self.assertRaisesRegex(ValueError, "stale"):
            ledger.sync(old_view)


if __name__ == "__main__":
    unittest.main()
