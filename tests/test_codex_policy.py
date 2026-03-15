from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from arena_agent.agents.codex_policy import CodexExecPolicy
from arena_agent.agents.rule_agent import build_policy
from arena_agent.core.models import (
    AccountSnapshot,
    AgentState,
    CompetitionSnapshot,
    MarketSnapshot,
    RiskLimits,
    RuntimeConfig,
    SignalState,
)
from arena_agent.core.runtime_loop import build_transition_event
from arena_agent.interfaces.action_schema import Action, ActionType


def make_state() -> AgentState:
    return AgentState(
        timestamp=time.time(),
        market=MarketSnapshot(
            symbol="BTCUSDT",
            interval="1m",
            last_price=101.5,
            mark_price=101.4,
            volatility=0.02,
            orderbook_imbalance=0.12,
            recent_candles=[],
        ),
        signal_state=SignalState(
            version="signal_state.v1",
            backend="builtin",
            requested=[],
            values={"sma_20": 100.1, "rsi_14": 63.0},
            warmup_complete=True,
            metadata={},
        ),
        account=AccountSnapshot(
            balance=1000.0,
            equity=1002.0,
            unrealized_pnl=2.0,
            realized_pnl=0.0,
            trade_count=3,
        ),
        position=None,
        competition=CompetitionSnapshot(
            competition_id=4,
            symbol="BTCUSDT",
            status="live",
            is_live=True,
            is_close_only=False,
            current_trades=3,
            max_trades=40,
            max_trades_remaining=37,
            time_remaining_seconds=600.0,
        ),
    )


class CodexPolicyTest(unittest.TestCase):
    def test_codex_policy_parses_structured_action_and_includes_memory(self) -> None:
        captured = {}
        state = make_state()
        next_state = make_state()
        action = Action(type=ActionType.HOLD, metadata={"reason": "wait"})
        execution_result = type(
            "ExecutionResultStub",
            (),
            {
                "accepted": True,
                "executed": False,
                "message": "hold",
                "realized_pnl": 0.0,
                "fee": 0.0,
            },
        )()
        transition = build_transition_event(state, action, execution_result, next_state)

        def runner(command, **kwargs):
            captured["command"] = command
            captured["input"] = kwargs["input"]
            output_index = command.index("-o") + 1
            output_path = Path(command[output_index])
            output_path.write_text(
                json.dumps(
                    {
                        "action": {
                            "type": "OPEN_LONG",
                            "size": 0.01,
                            "take_profit": 105.0,
                            "stop_loss": 99.0,
                            "reason": "momentum confirmed",
                            "confidence": 0.82,
                        }
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        policy = CodexExecPolicy(
            model="gpt-5",
            risk_limits=RiskLimits(max_absolute_size=0.01),
            subprocess_runner=runner,
            recent_transition_limit=5,
            cwd="/tmp",
        )
        policy.reset()
        policy.update([transition])

        result = policy.decide(state)

        self.assertEqual(result.type, ActionType.OPEN_LONG)
        self.assertAlmostEqual(result.size or 0.0, 0.01)
        self.assertAlmostEqual(result.take_profit or 0.0, 105.0)
        self.assertEqual(result.metadata["reason"], "momentum confirmed")
        self.assertEqual(result.metadata["source"], "codex_exec")
        self.assertEqual(result.metadata["codex_model"], "gpt-5")
        self.assertAlmostEqual(result.metadata["confidence"], 0.82)
        self.assertIn('"recent_transitions"', captured["input"])
        self.assertIn('"last_action": "HOLD"', captured["input"])
        self.assertIn("Action schema JSON:", captured["input"])
        self.assertIn("Additional policy instructions:", captured["input"])
        self.assertIn("--output-schema", captured["command"])

    def test_codex_policy_fails_open_to_hold(self) -> None:
        def runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, timeout=1.0)

        policy = CodexExecPolicy(subprocess_runner=runner, fail_open_to_hold=True)

        result = policy.decide(make_state())

        self.assertEqual(result.type, ActionType.HOLD)
        self.assertIn("codex_error", result.metadata["reason"])

    def test_policy_factory_builds_codex_policy(self) -> None:
        runtime_config = RuntimeConfig.from_mapping(
            {
                "competition_id": 4,
                "symbol": "BTCUSDT",
                "storage": {"transition_path": "/tmp/transitions.jsonl"},
                "policy": {
                    "type": "codex_exec",
                    "timeout_seconds": 12,
                    "recent_transition_limit": 4,
                },
            }
        )

        policy = build_policy(runtime_config.policy, runtime_config=runtime_config)

        self.assertIsInstance(policy, CodexExecPolicy)
        self.assertEqual(policy.timeout_seconds, 12.0)
        self.assertEqual(policy.recent_transition_limit, 4)
        self.assertEqual(policy.transition_path, "/tmp/transitions.jsonl")

    def test_codex_policy_bootstraps_transition_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "transitions.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "timestamp": 1.0,
                        "action": {"type": "OPEN_LONG", "metadata": {"reason": "boot"}},
                        "execution_result": {"accepted": True, "executed": True, "message": "ok"},
                        "metrics": {
                            "realized_pnl_delta": 1.0,
                            "equity_delta": 1.0,
                            "price_delta": 1.0,
                            "position_changed": True
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            policy = CodexExecPolicy(
                subprocess_runner=lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="", stderr=""),
                transition_path=str(path),
                bootstrap_from_transition_log=True,
            )
            policy.reset()

            self.assertEqual(policy._recent_transition_summaries[0]["action"], "OPEN_LONG")


if __name__ == "__main__":
    unittest.main()
