from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from arena_agent.core.models import (
    AccountSnapshot,
    AgentState,
    CompetitionSnapshot,
    ExecutionResult,
    MarketSnapshot,
)
from arena_agent.interfaces.action_schema import ActionType
from arena_agent.mcp import tools


def make_state() -> AgentState:
    return AgentState(
        timestamp=time.time(),
        market=MarketSnapshot(
            symbol="BTCUSDT",
            interval="1m",
            last_price=100.0,
            mark_price=99.9,
            volatility=0.01,
            orderbook_imbalance=0.2,
            recent_candles=[],
        ),
        account=AccountSnapshot(
            balance=1000.0,
            equity=1005.0,
            unrealized_pnl=5.0,
            realized_pnl=0.0,
            trade_count=2,
        ),
        position=None,
        competition=CompetitionSnapshot(
            competition_id=4,
            symbol="BTCUSDT",
            status="live",
            is_live=True,
            is_close_only=False,
            current_trades=2,
            max_trades=40,
            max_trades_remaining=38,
            time_remaining_seconds=600.0,
        ),
    )


class StubBuilder:
    def __init__(self, states):
        self.states = list(states)
        self.index = 0

    def build(self):
        state = self.states[min(self.index, len(self.states) - 1)]
        self.index += 1
        return state


class StubExecutor:
    def __init__(self):
        self.dry_run = True

    def execute(self, action, state):
        return ExecutionResult(
            action_type=action.type.value,
            accepted=True,
            executed=False,
            message="ok",
            timestamp=time.time(),
            realized_pnl=0.0,
            fee=0.0,
        )


class StubStore:
    def __init__(self):
        self.items = []

    def append(self, item):
        self.items.append(item)


class MCPToolsTest(unittest.TestCase):
    def test_competition_info_returns_compact_payload(self) -> None:
        with patch("arena_agent.mcp.tools.build_runtime_components") as mocked:
            mocked.return_value = (None, None, StubBuilder([make_state()]), None, None, None)
            payload = tools.competition_info()

        self.assertEqual(payload["competition_id"], 4)
        self.assertEqual(payload["max_trades_remaining"], 38)

    def test_trade_action_builds_transition(self) -> None:
        state_before = make_state()
        state_after = make_state()
        store = StubStore()
        executor = StubExecutor()
        fake_config = type("Config", (), {"dry_run": True})()

        with patch("arena_agent.mcp.tools.build_runtime_components") as mocked:
            mocked.return_value = (fake_config, None, StubBuilder([state_before, state_after]), executor, store, None)
            payload = tools.trade_action(type="hold")

        self.assertEqual(payload["action"].type, ActionType.HOLD)
        self.assertEqual(len(store.items), 1)
        self.assertEqual(payload["transition"].metrics.trade_count_after, 2)


if __name__ == "__main__":
    unittest.main()
