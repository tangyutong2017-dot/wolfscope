from __future__ import annotations

import unittest

from pydantic import ValidationError

from wolfscope.agents.runtime import PlayerRuntime
from wolfscope.agents.schemas import (
    AgentDecisionInput,
    DecisionTask,
    PublicGameSummary,
    SpeechDecision,
    SpeechTaskObservation,
)
from wolfscope.cognition.claims import (
    ClaimPolarity,
    RoleClaim,
    StanceClaim,
    StanceType,
)
from wolfscope.cognition.context import EvidenceContext, EvidenceContextBuilder
from wolfscope.cognition.evidence import PublicClaimEvidence, RawSpeech
from wolfscope.cognition.ledger import EvidenceLedger
from wolfscope.contracts import Visibility
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.types import Phase, RoleType
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.fake import FakeModelGateway, FakeResponse
from wolfscope.player_view import PlayerViewBuilder


def ledger_and_view() -> tuple[EvidenceLedger, object]:
    state = GameState(
        players=[
            PlayerState(seat=seat, role=role)
            for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
        ],
        phase=Phase.DAY_SPEECH,
    )
    events = EventLog()
    events.emit(
        day=1,
        phase=Phase.DAY_SPEECH,
        event_type="day_speech",
        visibility=Visibility.PUBLIC,
        actor=7,
        content="我是7号预言家。",
    )
    view = PlayerViewBuilder(state, events).build(4)
    ledger = EvidenceLedger(owner=4)
    ledger.sync(view)
    speech_event = next(event for event in view.visible_events if event.event_type == "day_speech")
    claims = [
        RoleClaim(
            subject=7,
            role=RoleType.SEER,
            polarity=ClaimPolarity.ASSERT,
            summary="7号声称预言家",
            supporting_text="我是7号预言家",
        ),
    ]
    claims.extend(
        StanceClaim(
            target=(index % 9) + 1,
            stance=StanceType.SUSPECT,
            summary=f"软态度{index}",
            supporting_text="我是7号预言家",
        )
        for index in range(31)
    )
    ledger.ingest_public_claims(
        event=speech_event,
        speaker=7,
        claims=tuple(claims),
        extractor_version="test",
    )
    return ledger, view


class EvidenceContextTests(unittest.IsolatedAsyncioTestCase):
    def test_context_keeps_hard_and_critical_evidence_but_bounds_soft_claims(self) -> None:
        ledger, _ = ledger_and_view()

        context = EvidenceContextBuilder(soft_claim_limit=30).build(ledger)

        self.assertGreaterEqual(len(context.verified_facts), 1)
        self.assertEqual(len(context.public_claims), 31)
        self.assertTrue(
            any(
                isinstance(item.content, PublicClaimEvidence)
                and item.content.claim.kind == "role_claim"
                for item in context.public_claims
            ),
        )
        self.assertFalse(
            any(isinstance(item.content, RawSpeech) for item in context.verified_facts),
        )
        self.assertTrue(all(value.startswith("p4-e") for value in context.evidence_ids))

    def test_context_rejects_another_players_evidence(self) -> None:
        ledger, _ = ledger_and_view()
        context = EvidenceContextBuilder().build(ledger)

        with self.assertRaises(ValidationError):
            EvidenceContext(
                owner=5,
                ledger_revision=context.ledger_revision,
                verified_facts=context.verified_facts,
            )

    def test_decision_input_requires_matching_context_owner(self) -> None:
        ledger, view = ledger_and_view()
        context = EvidenceContextBuilder().build(ledger).model_copy(update={"owner": 5})

        with self.assertRaises(ValidationError):
            AgentDecisionInput(
                player_view=view,
                public_summary=PublicGameSummary.from_view(view),
                observation=SpeechTaskObservation(
                    actor=4,
                    speaking_order=tuple(range(1, 10)),
                    previous_speeches=(),
                    can_explode=False,
                ),
                evidence_context=context,
            )

    async def test_runtime_strips_fabricated_evidence_ids(self) -> None:
        ledger, view = ledger_and_view()
        context = EvidenceContextBuilder().build(ledger)
        valid_id = context.evidence_ids[0]
        decision_input = AgentDecisionInput(
            player_view=view,
            public_summary=PublicGameSummary.from_view(view),
            observation=SpeechTaskObservation(
                actor=4,
                speaking_order=tuple(range(1, 10)),
                previous_speeches=(),
                can_explode=False,
            ),
            evidence_context=context,
        )
        gateway = FakeModelGateway(
            [
                FakeResponse(
                    payload=SpeechDecision(
                        action="speak",
                        speech="引用本地证据发言",
                        intent="测试证据引用",
                        confidence=0.8,
                        evidence_ids=(valid_id, "p9-e999"),
                    ),
                ),
            ],
        )
        runtime = PlayerRuntime(4, model_config_for(ModelProfile.TEST), gateway)

        decision = await runtime.decide(
            task=DecisionTask.SPEECH,
            decision_input=decision_input,
            output_schema=SpeechDecision,
        )

        self.assertEqual(decision.evidence_ids, (valid_id,))
        self.assertEqual(runtime.call_records[0].invalid_evidence_ids, ("p9-e999",))


if __name__ == "__main__":
    unittest.main()
