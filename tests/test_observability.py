from __future__ import annotations

import time
import unittest
from unittest.mock import Mock

from arena_agent.core.models import (
    AccountSnapshot,
    CompetitionSnapshot,
    ExecutionResult,
    MarketSnapshot,
    RuntimeConfig,
    SignalState,
)
from arena_agent.core.runtime_loop import build_transition_event
from arena_agent.interfaces.action_schema import Action, ActionType
from arena_agent.observability.runtime_monitor import RuntimeMonitor
from arena_agent.tui.controller import ArenaMonitorController


class ObservabilityTest(unittest.TestCase):
    def test_runtime_monitor_captures_snapshots_even_when_stream_is_unavailable(self) -> None:
        monitor = RuntimeMonitor({"enabled": True, "host": "127.0.0.1", "port": 0})
        runtime_config = RuntimeConfig.from_mapping({"competition_id": 4, "symbol": "BTCUSDT"})
        monitor.start(runtime_config=runtime_config, policy_name="stub")

        state_before = _make_state(100.0)
        state_after = _make_state(101.0)
        action = Action(type=ActionType.OPEN_LONG, metadata={"reason": "test"})
        execution = ExecutionResult(
            action_type=action.type.value,
            accepted=True,
            executed=True,
            message="ok",
            timestamp=time.time(),
            realized_pnl=1.25,
            fee=0.1,
            order_size=0.01,
        )
        transition = build_transition_event(state_before, action, execution, state_after)

        initial = monitor.current_snapshot()
        self.assertEqual(initial["runtime"]["policy_name"], "stub")
        monitor.record_state(
            iteration=1,
            decisions=0,
            executed_actions=0,
            policy_name="stub",
            state=state_before,
        )
        update = monitor.current_snapshot()
        self.assertAlmostEqual(update["decision_state"]["market"]["last_price"], 100.0)
        monitor.record_transition(
            iteration=1,
            decisions=1,
            executed_actions=1,
            next_state=state_after,
            action=action,
            execution_result=execution,
            transition=transition,
        )
        transition_update = monitor.current_snapshot()
        self.assertEqual(transition_update["transitions"][0]["action"]["type"], "OPEN_LONG")

        monitor.stop(report=None, final_state=state_after, reason="stopped")

    def test_controller_formats_snapshot_for_panels(self) -> None:
        datasource = Mock()
        snapshot = {
            "runtime": {
                "status": "running",
                "policy_name": "stub",
                "iteration": 2,
                "decisions": 1,
                "executed_actions": 1,
            },
            "connection": {"status": "connected", "host": "127.0.0.1", "port": 8765, "error": None},
            "decision_state": {
                "market": {"symbol": "BTCUSDT", "last_price": 102.5, "recent_candles": []},
                "account": {"equity": 1000.0, "balance": 999.0, "unrealized_pnl": 1.0, "realized_pnl": 0.5, "trade_count": 2},
                "position": None,
                "competition": {"max_trades_remaining": 38, "time_remaining_seconds": 120.0, "status": "live"},
                "signal_state": {"backend": "builtin", "warmup_complete": True, "values": {"sma_20": 101.5}, "metadata": {}},
            },
            "current_state": {
                "market": {"symbol": "BTCUSDT", "last_price": 102.8, "recent_candles": []},
                "account": {"equity": 1001.0, "balance": 999.0, "unrealized_pnl": 2.0, "realized_pnl": 0.5, "trade_count": 2},
                "position": {"direction": "long", "size": 0.01, "entry_price": 100.0},
                "competition": {"max_trades_remaining": 38},
                "signal_state": {"backend": "builtin", "warmup_complete": True, "values": {"sma_20": 101.5}, "metadata": {}},
            },
            "last_decision": {
                "policy_name": "stub",
                "action": {"type": "OPEN_LONG", "size": 0.01, "metadata": {"reason": "momentum"}},
                "reason": "momentum",
                "confidence": 0.8,
            },
            "last_execution": {"accepted": True, "executed": True, "message": "ok"},
            "transitions": [{"timestamp": 1.0, "action": {"type": "OPEN_LONG"}, "metrics": {"realized_pnl_delta": 1.25}, "equity_after": 1001.0, "price_after": 102.8}],
            "logs": [{"timestamp": 1.0, "level": "WARNING", "logger": "arena_agent.tap", "message": "tap_error:timeout"}],
        }
        datasource.poll_latest.return_value = snapshot
        controller = ArenaMonitorController(datasource)

        self.assertTrue(controller.poll())
        self.assertEqual(controller.market_state()["symbol"], "BTCUSDT")
        self.assertEqual(controller.account_state()["position"]["direction"], "long")
        self.assertEqual(controller.feature_state()["values"]["sma_20"], 101.5)
        self.assertEqual(controller.decision_state()["action_type"], "OPEN_LONG")
        self.assertEqual(controller.transition_rows()[0]["action"]["type"], "OPEN_LONG")
        self.assertIn("connection=connected", controller.status_line())


def _make_state(price: float):
    return type(
        "State",
        (),
        {
            "timestamp": time.time(),
            "market": MarketSnapshot(
                symbol="BTCUSDT",
                interval="1m",
                last_price=price,
                mark_price=price,
                volatility=0.01,
                orderbook_imbalance=0.2,
                recent_candles=[],
            ),
            "account": AccountSnapshot(
                balance=1000.0,
                equity=1000.0,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                trade_count=1,
            ),
            "position": None,
            "competition": CompetitionSnapshot(
                competition_id=4,
                symbol="BTCUSDT",
                status="live",
                is_live=True,
                is_close_only=False,
                current_trades=1,
                max_trades=40,
                max_trades_remaining=39,
                time_remaining_seconds=300.0,
            ),
            "signal_state": SignalState(
                version="signal_state.v1",
                backend="builtin",
                requested=[],
                values={"sma_20": price},
                warmup_complete=True,
                metadata={},
            ),
        },
    )()


if __name__ == "__main__":
    unittest.main()
