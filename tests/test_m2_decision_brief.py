from __future__ import annotations

import unittest

from wolfscope.cognition.brief import DecisionBriefBuilder
from wolfscope.cognition.claims import (
    CheckClaim,
    ClaimAlignment,
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


def game_state() -> GameState:
    return GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
        day=1,
        phase=Phase.DAY_VOTE,
    )


class DecisionBriefTests(unittest.TestCase):
    def test_builds_task_focused_index_without_voting_recommendation(self) -> None:
        events = EventLog()
        speech = events.emit(
            day=1,
            phase=Phase.DAY_SPEECH,
            event_type="day_speech",
            visibility=Visibility.PUBLIC,
            actor=7,
            content="我是预言家，昨夜查杀1号，今天投1号",
        )
        view = PlayerViewBuilder(game_state(), events).build(4)
        ledger = EvidenceLedger(owner=4)
        ledger.sync(view)
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
                CheckClaim(
                    target=1,
                    night=1,
                    result=ClaimAlignment.WEREWOLF,
                    summary="7号声称查杀1号",
                    supporting_text="昨夜查杀1号",
                ),
                VoteIntentClaim(
                    target=1,
                    intent=VoteIntentType.VOTE,
                    conditional=False,
                    summary="7号准备投1号",
                    supporting_text="今天投1号",
                ),
            ),
            extractor_version="test",
        )

        brief = DecisionBriefBuilder().build(
            ledger,
            day=1,
            candidates=(1, 2, 7),
        )

        self.assertEqual(brief.owner, 4)
        self.assertEqual(tuple(item.seat for item in brief.candidates), (1, 2, 7))
        self.assertEqual(brief.checks[0].speaker, 7)
        self.assertEqual(brief.checks[0].target, 1)
        self.assertEqual(brief.latest_vote_intents[0].target, 1)
        self.assertEqual(brief.ledger_revision, brief.belief_revision)
        self.assertNotIn("recommend", brief.model_dump_json())

    def test_keeps_only_latest_vote_intent_per_speaker_for_current_day(self) -> None:
        events = EventLog()
        old = events.emit(
            day=1, phase=Phase.DAY_SPEECH, event_type="day_speech",
            visibility=Visibility.PUBLIC, actor=8, content="我先投1号",
        )
        latest = events.emit(
            day=1, phase=Phase.DAY_PK_SPEECH, event_type="pk_speech",
            visibility=Visibility.PUBLIC, actor=8, content="我改投7号",
        )
        ledger = EvidenceLedger(owner=4)
        ledger.sync(PlayerViewBuilder(game_state(), events).build(4))
        ledger.ingest_public_claims(
            event=old, speaker=8,
            claims=(VoteIntentClaim(target=1, intent="vote", conditional=False, summary="8号投1号", supporting_text="我先投1号"),),
            extractor_version="test-old",
        )
        ledger.ingest_public_claims(
            event=latest, speaker=8,
            claims=(VoteIntentClaim(target=7, intent="vote", conditional=False, summary="8号改投7号", supporting_text="我改投7号"),),
            extractor_version="test-latest",
        )

        brief = DecisionBriefBuilder().build(ledger, day=1, candidates=(1, 7))

        self.assertEqual(len(brief.latest_vote_intents), 1)
        self.assertEqual(brief.latest_vote_intents[0].target, 7)


if __name__ == "__main__":
    unittest.main()
