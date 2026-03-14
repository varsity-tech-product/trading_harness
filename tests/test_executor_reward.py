from __future__ import annotations

import time
import unittest

from arena_agent.agents.reward_models import RewardWeights, TransitionRewardModel
from arena_agent.core.models import (
    AccountSnapshot,
    AgentState,
    CompetitionSnapshot,
    ExecutionResult,
    MarketSnapshot,
    PositionSnapshot,
    TransitionEvent,
    TransitionMetrics,
    RiskLimits,
)
from arena_agent.execution.order_executor import OrderExecutor
from arena_agent.interfaces.action_schema import Action, ActionType


class FakeAdapter:
    def trade_open(self, competition_id, direction, size, take_profit=None, stop_loss=None):
        return {
            "direction": direction,
            "size": size,
            "takeProfit": take_profit,
            "stopLoss": stop_loss,
            "fee": 1.5,
            "pnl": 0.0,
        }

    def trade_close(self, competition_id):
        return {"pnl": 12.0, "fee": 0.8}

    def trade_update_tpsl(self, competition_id, take_profit=None, stop_loss=None):
        return {"takeProfit": take_profit, "stopLoss": stop_loss}


class ErroringAdapter(FakeAdapter):
    def trade_close(self, competition_id):
        raise RuntimeError("no position")


def make_state(position: PositionSnapshot | None = None, equity: float = 1000.0) -> AgentState:
    return AgentState(
        timestamp=time.time(),
        market=MarketSnapshot(
            symbol="BTCUSDT",
            interval="1m",
            last_price=100.0,
            mark_price=99.5,
            volatility=0.02,
            orderbook_imbalance=0.1,
            recent_candles=[],
        ),
        account=AccountSnapshot(
            balance=1000.0,
            equity=equity,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            trade_count=1,
        ),
        position=position,
        competition=CompetitionSnapshot(
            competition_id=4,
            symbol="BTCUSDT",
            status="live",
            is_live=True,
            is_close_only=False,
            current_trades=1,
            max_trades=10,
            max_trades_remaining=9,
            time_remaining_seconds=600.0,
        ),
    )


class ExecutorAndRewardTest(unittest.TestCase):
    def test_executor_sizes_open_orders_from_risk_limits(self) -> None:
        executor = OrderExecutor(
            adapter=FakeAdapter(),
            competition_id=4,
            risk_limits=RiskLimits(
                max_position_size_pct=0.1,
                max_absolute_size=None,
                min_size=0.001,
                quantity_precision=3,
                price_precision=2,
                max_trades=10,
                min_seconds_between_trades=0.0,
                allow_long=True,
                allow_short=True,
            ),
            dry_run=False,
        )
        result = executor.execute(Action(type=ActionType.OPEN_LONG), make_state())
        self.assertTrue(result.accepted)
        self.assertTrue(result.executed)
        self.assertAlmostEqual(result.order_size or 0.0, 1.0)
        self.assertAlmostEqual(result.fee, 1.5)

    def test_transition_reward_model_accounts_for_pnl_and_invalid_actions(self) -> None:
        reward_model = TransitionRewardModel(RewardWeights(invalid_action_penalty=2.0))
        previous = make_state(position=PositionSnapshot("long", 1.0, 100.0, 0.0), equity=1000.0)
        next_state = make_state(position=None, equity=1010.0)
        transition = TransitionEvent(
            timestamp=time.time(),
            state_before=previous,
            action=Action(type=ActionType.CLOSE_POSITION),
            execution_result=ExecutionResult(
                action_type=ActionType.CLOSE_POSITION.value,
                accepted=True,
                executed=True,
                message="closed",
                timestamp=time.time(),
                realized_pnl=10.0,
                fee=1.0,
            ),
            state_after=next_state,
            metrics=TransitionMetrics(
                market_price_before=100.0,
                market_price_after=100.0,
                price_delta=0.0,
                balance_before=1000.0,
                balance_after=1010.0,
                balance_delta=10.0,
                equity_before=1000.0,
                equity_after=1010.0,
                equity_delta=10.0,
                unrealized_pnl_before=0.0,
                unrealized_pnl_after=0.0,
                unrealized_pnl_delta=0.0,
                realized_pnl_delta=10.0,
                fee=1.0,
                trade_count_before=1,
                trade_count_after=2,
                trade_count_delta=1,
                position_changed=True,
            ),
        )

        reward = reward_model.score(transition)

        self.assertGreater(reward, 0.0)

        invalid_reward = reward_model.score(
            TransitionEvent(
                timestamp=time.time(),
                state_before=next_state,
                action=Action(type=ActionType.OPEN_LONG),
                execution_result=ExecutionResult(
                    action_type=ActionType.OPEN_LONG.value,
                    accepted=False,
                    executed=False,
                    message="rejected",
                    timestamp=time.time(),
                ),
                state_after=next_state,
                metrics=TransitionMetrics(
                    market_price_before=100.0,
                    market_price_after=100.0,
                    price_delta=0.0,
                    balance_before=1000.0,
                    balance_after=1000.0,
                    balance_delta=0.0,
                    equity_before=1010.0,
                    equity_after=1010.0,
                    equity_delta=0.0,
                    unrealized_pnl_before=0.0,
                    unrealized_pnl_after=0.0,
                    unrealized_pnl_delta=0.0,
                    realized_pnl_delta=0.0,
                    fee=0.0,
                    trade_count_before=1,
                    trade_count_after=1,
                    trade_count_delta=0,
                    position_changed=False,
                ),
            ),
        )
        self.assertLess(invalid_reward, 0.0)

    def test_executor_converts_adapter_errors_to_rejected_results(self) -> None:
        executor = OrderExecutor(
            adapter=ErroringAdapter(),
            competition_id=4,
            risk_limits=RiskLimits(),
            dry_run=False,
        )
        result = executor.execute(
            Action(type=ActionType.CLOSE_POSITION),
            make_state(position=PositionSnapshot("long", 1.0, 100.0, 0.0)),
        )
        self.assertFalse(result.accepted)
        self.assertFalse(result.executed)
        self.assertIn("trade_close failed", result.message)


if __name__ == "__main__":
    unittest.main()
