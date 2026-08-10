from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wolfscope.agents.agent_game import AgentGameProvider
from wolfscope.agents.runtime import PlayerRuntimeRegistry
from wolfscope.agents.schemas import DecisionTask
from wolfscope.game import GameState, PlayerState
from wolfscope.game.config import STANDARD_9_RULES
from wolfscope.game.engine import GameEngine, GameRunStatus
from wolfscope.game.events import EventLog
from wolfscope.game.types import Camp, WinReason
from wolfscope.models.config import ModelProfile, model_config_for
from wolfscope.models.gateway import ModelCallRecord, ModelCallResult
from wolfscope.player_view import PlayerViewBuilder
from wolfscope.replay import ReplayWriter


class AdaptiveFakeGateway:
    """Generate legal structured decisions from only the authorized task input."""

    def __init__(self) -> None:
        self.records = []

    async def structured_call(
        self,
        *,
        player,
        task,
        decision_input,
        output_schema,
        config,
    ):
        observation = decision_input.observation
        payload = self._payload(player, task, observation, decision_input)
        record = ModelCallRecord(
            call_id=len(self.records) + 1,
            player=player,
            task=task,
            model_name=config.model_name,
            thinking_enabled=config.thinking_enabled,
            success=True,
            latency_ms=0,
        )
        self.records.append(record)
        return ModelCallResult(
            value=output_schema.model_validate(payload),
            record=record,
        )

    @staticmethod
    def _payload(player, task, observation, decision_input):
        common = {"confidence": 0.8, "reason": "自适应本地终局测试"}
        if task is DecisionTask.WOLF_TARGET:
            target = next(
                (seat for seat in (7, 8, 9) if seat in observation.eligible_targets),
                next(
                    seat
                    for seat in observation.eligible_targets
                    if seat not in observation.wolf_seats
                ),
            )
            return {
                "action": "wolf_target",
                "target": target,
                "team_plan": {
                    "day": decision_input.player_view.day,
                    "objective": "hide",
                    "primary_claimant": None,
                    "claimed_role": None,
                    "fake_check_target": None,
                    "fake_check_alignment": None,
                    "focus_target": target,
                    "plan_reason": "隐藏身份并推进当前刀口",
                    "assignments": [
                        {"seat": seat, "posture": "hide"}
                        for seat in observation.wolf_seats
                    ],
                },
                **common,
            }
        if task is DecisionTask.SEER_TARGET:
            return {
                "action": "seer_target",
                "target": observation.eligible_targets[0],
                **common,
            }
        if task is DecisionTask.WITCH_ACTION:
            return {"action": "pass", "target": None, **common}
        if task is DecisionTask.SHERIFF_SIGNUP:
            return {"action": "sheriff_signup", "signup": False, **common}
        if task is DecisionTask.SHERIFF_CAMPAIGN:
            return {
                "action": "sheriff_campaign",
                "speech": f"{player}号测试竞选发言。",
                "intent": "本地终局测试",
                "confidence": 0.8,
            }
        if task is DecisionTask.SHERIFF_WITHDRAWAL:
            return {"action": "sheriff_withdrawal", "withdraw": False, **common}
        if task is DecisionTask.SHERIFF_VOTE:
            return {"action": "sheriff_vote", "target": None, **common}
        if task is DecisionTask.SPEECH_DIRECTION:
            return {"action": "speech_direction", "direction": "clockwise", **common}
        if task is DecisionTask.SPEECH:
            return {
                "action": "speak",
                "speech": f"{player}号进行本轮测试发言。",
                "intent": "推动确定性终局",
                "confidence": 0.8,
            }
        if task is DecisionTask.VOTE:
            target = next(
                (seat for seat in (4, 5, 6) if seat in observation.candidates),
                observation.candidates[0],
            )
            return {"action": "vote", "target": target, **common}
        if task is DecisionTask.PK_SPEECH:
            return {
                "action": "pk_speech",
                "speech": f"{player}号测试PK发言。",
                "intent": "结束平票",
                "confidence": 0.8,
            }
        if task in {DecisionTask.LAST_WORDS, DecisionTask.DEATH_LAST_WORDS}:
            return {
                "action": task.value,
                "speech": f"{player}号测试遗言。",
                "intent": "留下公开信息",
                "confidence": 0.8,
            }
        if task is DecisionTask.HUNTER_TARGET:
            return {"action": "hunter_target", "target": None, **common}
        if task is DecisionTask.BADGE_TRANSFER:
            return {"action": "badge_transfer", "target": None, **common}
        raise AssertionError(f"unhandled task: {task}")
class FullHybridGameTests(unittest.IsolatedAsyncioTestCase):
    async def test_hybrid_provider_reaches_terminal_result_and_roundtrips_replay(self) -> None:
        state = GameState(
            seed=42,
            players=[
                PlayerState(seat=seat, role=role)
                for seat, role in enumerate(STANDARD_9_RULES.roles, start=1)
            ],
        )
        events = EventLog()
        runtimes = PlayerRuntimeRegistry.create(
            model_config_for(ModelProfile.TEST),
            lambda _seat: AdaptiveFakeGateway(),
        )
        provider = AgentGameProvider(
            view_builder=PlayerViewBuilder(state, events),
            runtimes=runtimes,
        )
        result = await GameEngine(
            state,
            provider,
            events,
            max_days=5,
            game_id="m2-adaptive-full-game",
        ).run()

        self.assertIs(result.status, GameRunStatus.FINISHED)
        self.assertIs(result.winner, Camp.WEREWOLF)
        self.assertIs(result.win_reason, WinReason.ALL_DEITIES_DEAD)
        self.assertEqual(result.days, 3)
        self.assertEqual(len(provider.wolf_team_plan_history), 3)
        self.assertTrue(
            all(
                {item.seat for item in plan.assignments}
                for plan in provider.wolf_team_plan_history
            ),
        )
        self.assertGreater(
            sum(len(runtimes.get(seat).call_records) for seat in runtimes.seats),
            30,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = ReplayWriter.write(result, Path(directory) / "full-game.json")
            replay = ReplayWriter.read(path)
        self.assertEqual(replay.status, GameRunStatus.FINISHED)
        self.assertEqual(replay.winner, Camp.WEREWOLF)
        self.assertEqual(replay.events[-1].event_type, "game_finished")


if __name__ == "__main__":
    unittest.main()
