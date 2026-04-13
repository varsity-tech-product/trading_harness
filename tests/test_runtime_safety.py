from __future__ import annotations

import time
import unittest

from arena_agent.core.models import (
    AccountSnapshot,
    AgentState,
    Candle,
    CompetitionSnapshot,
    MarketSnapshot,
    SignalState,
)
from arena_agent.core.runtime_safety import detect_position_drift, evaluate_state_guard


def make_state(
    *,
    feature_timestamp: int | None,
    position=None,
    trade_count: int = 1,
    market_symbol: str = "BTCUSDT",
    competition_symbol: str = "BTCUSDT",
    raw_market_symbol: str | None = None,
) -> AgentState:
    close_time = 2_000_000_000_000
    candles = [
        Candle(
            open_time=close_time - 60_000,
            close_time=close_time,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1.0,
        )
    ]
    metadata = {}
    if feature_timestamp is not None:
        metadata["timestamp"] = feature_timestamp
    return AgentState(
        timestamp=time.time(),
        market=MarketSnapshot(
            symbol=market_symbol,
            interval="1m",
            last_price=100.5,
            mark_price=100.4,
            volatility=0.01,
            orderbook_imbalance=0.1,
            recent_candles=candles,
        ),
        signal_state=SignalState(
            version="signal_state.v1",
            backend="builtin",
            requested=[type("FeatureSpecStub", (), {"indicator": "SMA", "params": {}, "key": None})()],
            values={"sma_20": 100.0},
            warmup_complete=True,
            metadata=metadata,
        ),
        account=AccountSnapshot(
            balance=1000.0,
            equity=1000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            trade_count=trade_count,
        ),
        position=position,
        competition=CompetitionSnapshot(
            competition_id=4,
            symbol=competition_symbol,
            status="live",
            is_live=True,
            is_close_only=False,
            current_trades=trade_count,
            max_trades=40,
            max_trades_remaining=40 - trade_count,
            time_remaining_seconds=600.0,
        ),
        raw={"market_info": {"symbol": raw_market_symbol or market_symbol}},
    )


class RuntimeSafetyTest(unittest.TestCase):
    def test_state_guard_accepts_matching_feature_timestamp(self) -> None:
        state = make_state(feature_timestamp=2_000_000_000_000)

        result = evaluate_state_guard(state, max_feature_age_seconds=None)

        self.assertTrue(result.ok)

    def test_state_guard_rejects_mismatched_feature_timestamp(self) -> None:
        state = make_state(feature_timestamp=2_000_000_001_000)

        result = evaluate_state_guard(state, max_feature_age_seconds=None)

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "feature_timestamp_mismatch")

    def test_position_drift_detects_position_change(self) -> None:
        previous_state = make_state(feature_timestamp=2000)
        current_position = type("PositionStub", (), {"direction": "long", "size": 0.01, "entry_price": 100.0})()
        current_state = make_state(feature_timestamp=2000, position=current_position)

        message = detect_position_drift(previous_state, current_state)

        self.assertIn("exchange state drift detected", message)

    def test_state_guard_rejects_market_symbol_mismatch(self) -> None:
        state = make_state(
            feature_timestamp=2_000_000_000_000,
            market_symbol="BTCUSDT",
            competition_symbol="SOLUSDT",
        )

        result = evaluate_state_guard(state, max_feature_age_seconds=None)

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "market_symbol_mismatch")

    def test_state_guard_rejects_raw_market_symbol_mismatch(self) -> None:
        state = make_state(
            feature_timestamp=2_000_000_000_000,
            market_symbol="SOLUSDT",
            competition_symbol="SOLUSDT",
            raw_market_symbol="BTCUSDT",
        )

        result = evaluate_state_guard(state, max_feature_age_seconds=None)

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "market_info_symbol_mismatch")


if __name__ == "__main__":
    unittest.main()
