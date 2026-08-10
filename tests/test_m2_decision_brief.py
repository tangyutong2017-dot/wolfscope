from __future__ import annotations

import unittest

from wolfscope.agents.runtime import PlayerRuntime
from wolfscope.agents.prompt import render_decision_prompt
from wolfscope.agents.schemas import (
    AgentDecisionInput,
    DecisionTask,
    PublicGameSummary,
    SeerTargetTaskObservation,
    VoteDecision,
    VoteContextMode,
    VoteTaskObservation,
)
from wolfscope.cognition.brief import DecisionBriefBuilder
from wolfscope.cognition.claims import (
    CheckClaim,
    ClaimAlignment,
    ClaimPolarity,
    RoleClaim,
    StanceClaim,
    StanceType,
    VoteIntentClaim,
    VoteIntentType,
)
from wolfscope.cognition.ledger import EvidenceLedger
from wolfscope.cognition.context import EvidenceContextBuilder
from wolfscope.contracts import Visibility
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.events import EventLog
from wolfscope.game.types import Phase, RoleType
from wolfscope.game.day import ExileVoteRound
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.fake import FakeModelGateway, FakeResponse
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
    def test_bounded_target_prompt_omits_unneeded_evidence_history(self) -> None:
        events = EventLog()
        speech = events.emit(
            day=1, phase=Phase.DAY_SPEECH, event_type="day_speech",
            visibility=Visibility.PUBLIC, actor=8,
            content="只用于确认不会进入验人 Prompt 的历史文本",
        )
        view = PlayerViewBuilder(game_state(), events).build(4)
        ledger = EvidenceLedger(owner=4)
        ledger.sync(view)
        ledger.ingest_public_claims(
            event=speech,
            speaker=8,
            claims=(VoteIntentClaim(target=1, intent="vote", conditional=False, summary="8号投1号", supporting_text="今天投1号"),),
            extractor_version="test",
        )
        decision_input = AgentDecisionInput(
            player_view=view,
            public_summary=PublicGameSummary.from_view(view),
            observation=SeerTargetTaskObservation(
                actor=4,
                checked_seats=(),
                eligible_targets=(1, 2),
            ),
            evidence_context=EvidenceContextBuilder().build(ledger),
        )

        prompt = render_decision_prompt(decision_input, DecisionTask.SEER_TARGET)

        self.assertIn('"evidence_context": null', prompt)
        self.assertNotIn("只用于确认不会进入验人 Prompt 的历史文本", prompt)

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
        self.assertIn(brief.checks[0].evidence_id, brief.evidence_ids)
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

    def test_excludes_claims_unrelated_to_current_vote_candidates(self) -> None:
        events = EventLog()
        speech = events.emit(
            day=1, phase=Phase.DAY_SPEECH, event_type="day_speech",
            visibility=Visibility.PUBLIC, actor=8,
            content="我是预言家，查验9号是好人，今天投9号",
        )
        ledger = EvidenceLedger(owner=4)
        ledger.sync(PlayerViewBuilder(game_state(), events).build(4))
        ledger.ingest_public_claims(
            event=speech,
            speaker=8,
            claims=(
                RoleClaim(subject=8, role="seer", polarity="assert", summary="8号声称预言家", supporting_text="我是预言家"),
                CheckClaim(target=9, night=1, result="good", summary="8号称9号为好人", supporting_text="查验9号是好人"),
                VoteIntentClaim(target=9, intent="vote", conditional=False, summary="8号投9号", supporting_text="今天投9号"),
            ),
            extractor_version="test",
        )

        brief = DecisionBriefBuilder().build(ledger, day=1, candidates=(1, 7))

        self.assertEqual(brief.role_claims, ())
        self.assertEqual(brief.checks, ())
        self.assertEqual(brief.latest_vote_intents, ())

    def test_keeps_latest_current_day_stance_toward_candidates(self) -> None:
        events = EventLog()
        old = events.emit(
            day=1, phase=Phase.DAY_SPEECH, event_type="day_speech",
            visibility=Visibility.PUBLIC, actor=8, content="我先相信7号",
        )
        latest = events.emit(
            day=1, phase=Phase.DAY_PK_SPEECH, event_type="pk_speech",
            visibility=Visibility.PUBLIC, actor=8,
            content="现在我不信7号，但支持9号的分析",
        )
        ledger = EvidenceLedger(owner=4)
        ledger.sync(PlayerViewBuilder(game_state(), events).build(4))
        ledger.ingest_public_claims(
            event=old, speaker=8,
            claims=(StanceClaim(target=7, stance=StanceType.TRUST, summary="8号相信7号", supporting_text="我先相信7号"),),
            extractor_version="test-old",
        )
        ledger.ingest_public_claims(
            event=latest, speaker=8,
            claims=(
                StanceClaim(target=7, stance=StanceType.DISTRUST, summary="8号不信7号", supporting_text="现在我不信7号"),
                StanceClaim(target=9, stance=StanceType.SUPPORT, summary="8号支持9号", supporting_text="支持9号的分析"),
            ),
            extractor_version="test-latest",
        )

        brief = DecisionBriefBuilder().build(ledger, day=1, candidates=(1, 7))

        self.assertEqual(len(brief.latest_stances), 1)
        self.assertEqual(brief.latest_stances[0].speaker, 8)
        self.assertEqual(brief.latest_stances[0].target, 7)
        self.assertEqual(brief.latest_stances[0].stance, StanceType.DISTRUST)
        self.assertIn(brief.latest_stances[0].evidence_id, brief.evidence_ids)


class DecisionBriefTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_distinguishes_brief_and_context_only_references(self) -> None:
        events = EventLog()
        speech = events.emit(
            day=1, phase=Phase.DAY_SPEECH, event_type="day_speech",
            visibility=Visibility.PUBLIC, actor=7, content="我是预言家",
        )
        view = PlayerViewBuilder(game_state(), events).build(4)
        ledger = EvidenceLedger(owner=4)
        ledger.sync(view)
        claim_record = ledger.ingest_public_claims(
            event=speech, speaker=7,
            claims=(RoleClaim(subject=7, role="seer", polarity="assert", summary="7号声称预言家", supporting_text="我是预言家"),),
            extractor_version="test",
        )[0]
        context = EvidenceContextBuilder().build(ledger)
        brief = DecisionBriefBuilder().build(ledger, day=1, candidates=(1, 7))
        context_only_id = next(
            value for value in context.evidence_ids
            if value not in brief.evidence_ids
        )
        decision_input = AgentDecisionInput(
            player_view=view,
            public_summary=PublicGameSummary.from_view(view),
            observation=VoteTaskObservation(
                voter=4,
                vote_round=ExileVoteRound.FIRST,
                candidates=(1, 7),
                speeches=((7, "我是预言家"),),
            ),
            evidence_context=context,
            decision_brief=brief,
        )
        runtime = PlayerRuntime(
            4,
            model_config_for(ModelProfile.TEST),
            FakeModelGateway([
                FakeResponse(payload=VoteDecision(
                    target=7,
                    confidence=0.5,
                    reason="测试来源分类",
                    evidence_ids=(claim_record.evidence_id, context_only_id),
                )),
            ]),
        )

        await runtime.decide(
            task=DecisionTask.VOTE,
            decision_input=decision_input,
            output_schema=VoteDecision,
        )

        trace = runtime.call_records[0]
        self.assertEqual(trace.accepted_brief_evidence_ids, (claim_record.evidence_id,))
        self.assertEqual(trace.accepted_context_only_evidence_ids, (context_only_id,))

    async def test_vote_context_modes_control_rendering_and_hidden_claim_ids(self) -> None:
        events = EventLog()
        speech = events.emit(
            day=1, phase=Phase.DAY_SPEECH, event_type="day_speech",
            visibility=Visibility.PUBLIC, actor=8,
            content="独特原始措辞：我怀疑9号",
        )
        view = PlayerViewBuilder(game_state(), events).build(4)
        ledger = EvidenceLedger(owner=4)
        ledger.sync(view)
        hidden_record = ledger.ingest_public_claims(
            event=speech, speaker=8,
            claims=(StanceClaim(target=9, stance="suspect", summary="8号怀疑9号", supporting_text="我怀疑9号"),),
            extractor_version="test",
        )[0]
        context = EvidenceContextBuilder().build(ledger)
        brief = DecisionBriefBuilder().build(ledger, day=1, candidates=(1, 7))
        base = AgentDecisionInput(
            player_view=view,
            public_summary=PublicGameSummary.from_view(view),
            observation=VoteTaskObservation(
                voter=4,
                vote_round=ExileVoteRound.FIRST,
                candidates=(1, 7),
                speeches=((8, "独特原始措辞：我怀疑9号"),),
            ),
            evidence_context=context,
            decision_brief=brief,
        )
        full_prompt = render_decision_prompt(base, DecisionTask.VOTE)
        self.assertIn("不能仅以‘信息不足’为理由弃票", full_prompt)
        balanced_input = base.model_copy(
            update={"vote_context_mode": VoteContextMode.BALANCED},
        )
        balanced_prompt = render_decision_prompt(
            balanced_input,
            DecisionTask.VOTE,
        )
        compact_prompt = render_decision_prompt(
            base.model_copy(update={"vote_context_mode": VoteContextMode.COMPACT}),
            DecisionTask.VOTE,
        )

        self.assertIn("独特原始措辞", full_prompt)
        self.assertIn('"public_claims"', full_prompt)
        self.assertIn("独特原始措辞", balanced_prompt)
        self.assertNotIn('"public_claims"', balanced_prompt)
        self.assertNotIn("独特原始措辞", compact_prompt)
        self.assertNotIn('"public_claims"', compact_prompt)

        runtime = PlayerRuntime(
            4,
            model_config_for(ModelProfile.TEST),
            FakeModelGateway([
                VoteDecision(
                    target=1,
                    confidence=0.5,
                    reason="测试隐藏引用",
                    evidence_ids=(hidden_record.evidence_id,),
                ),
            ]),
        )
        decision = await runtime.decide(
            task=DecisionTask.VOTE,
            decision_input=balanced_input,
            output_schema=VoteDecision,
        )

        self.assertEqual(decision.evidence_ids, ())
        self.assertEqual(
            runtime.call_records[0].invalid_evidence_ids,
            (hidden_record.evidence_id,),
        )


if __name__ == "__main__":
    unittest.main()
