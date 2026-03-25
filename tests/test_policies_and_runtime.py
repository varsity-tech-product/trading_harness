from __future__ import annotations

import time
import unittest

from arena_agent.core.models import (
    AccountSnapshot,
    AgentState,
    Candle,
    CompetitionSnapshot,
    ExecutionResult,
    MarketSnapshot,
    RuntimeConfig,
    TransitionEvent,
)
from arena_agent.core.runtime_loop import MarketRuntime
from arena_agent.interfaces.action_schema import Action, ActionType
from arena_agent.memory.transition_store import TransitionStore
from arena_agent.memory.trade_journal import TradeJournal


def make_state_from_closes(closes: list[float]) -> AgentState:
    candles = [
        Candle(
            open_time=index,
            close_time=index + 1,
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=1.0,
        )
        for index, close in enumerate(closes)
    ]
    return AgentState(
        timestamp=time.time(),
        market=MarketSnapshot(
            symbol="BTCUSDT",
            interval="1m",
            last_price=closes[-1],
            mark_price=closes[-1],
            volatility=0.01,
            orderbook_imbalance=0.0,
            recent_candles=candles,
        ),
        account=AccountSnapshot(
            balance=1000.0,
            equity=1000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            trade_count=0,
        ),
        position=None,
        competition=CompetitionSnapshot(
            competition_id=4,
            symbol="BTCUSDT",
            status="live",
            is_live=True,
            is_close_only=False,
            current_trades=0,
            max_trades=10,
            max_trades_remaining=10,
            time_remaining_seconds=300.0,
        ),
    )


class StaticStateBuilder:
    def __init__(self, states):
        self.states = list(states)
        self.index = 0

    def build(self):
        state = self.states[min(self.index, len(self.states) - 1)]
        self.index += 1
        return state


class StubPolicy:
    name = "stub"

    def __init__(self):
        self.seen_transitions: list[TransitionEvent] = []

    def reset(self):
        return None

    def decide(self, state):
        return Action(type=ActionType.OPEN_LONG, metadata={"reason": "test"})

    def update(self, memory):
        self.seen_transitions = list(memory)


class StubExecutor:
    def execute(self, action, state):
        return ExecutionResult(
            action_type=action.type.value,
            accepted=True,
            executed=True,
            message="ok",
            timestamp=time.time(),
            realized_pnl=5.0,
            fee=0.5,
            order_size=0.1,
        )


class PoliciesAndRuntimeTest(unittest.TestCase):
    def test_runtime_loop_records_transition(self) -> None:
        first_state = make_state_from_closes([100.0] * 60)
        second_state = make_state_from_closes([100.0] * 59 + [101.0])
        transition_store = TransitionStore()
        policy = StubPolicy()
        runtime = MarketRuntime(
            config=RuntimeConfig.from_mapping(
                {
                    "competition_id": 4,
                    "symbol": "BTCUSDT",
                    "tick_interval_seconds": 0,
                    "max_iterations": 1,
                    "dry_run": True,
                }
            ),
            state_builder=StaticStateBuilder([first_state, second_state]),
            executor=StubExecutor(),
            transition_store=transition_store,
            journal=TradeJournal(),
            policy=policy,
        )

        report = runtime.run()

        self.assertEqual(report.iterations, 1)
        self.assertEqual(report.executed_actions, 1)
        self.assertEqual(report.transitions_recorded, 1)
        self.assertAlmostEqual(report.total_realized_pnl, 5.0)
        self.assertIsNotNone(report.final_equity)
        self.assertEqual(len(transition_store.all()), 1)
        self.assertEqual(len(policy.seen_transitions), 1)
        self.assertAlmostEqual(transition_store.all()[0].metrics.price_delta, 1.0)
        self.assertAlmostEqual(transition_store.all()[0].metrics.realized_pnl_delta, 5.0)


if __name__ == "__main__":
    unittest.main()
