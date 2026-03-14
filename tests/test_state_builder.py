from __future__ import annotations

import unittest

from arena_agent.core.environment_adapter import EnvironmentAdapter
from arena_agent.core.models import RuntimeConfig
from arena_agent.core.state_builder import StateBuilder


class FakeArenaClient:
    def get_market_info(self, symbol: str):
        return {
            "symbol": symbol,
            "lastPrice": 105.0,
            "markPrice": 104.5,
            "fundingRate": 0.0001,
        }

    def get_klines(self, symbol: str, interval: str, size: int = 120):
        return {
            "klines": [
                {
                    "openTime": 1,
                    "closeTime": 2,
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100,
                    "volume": 10,
                    "isFinal": True,
                },
                {
                    "openTime": 3,
                    "closeTime": 4,
                    "open": 100,
                    "high": 103,
                    "low": 99,
                    "close": 102,
                    "volume": 11,
                    "isFinal": True,
                },
                {
                    "openTime": 5,
                    "closeTime": 6,
                    "open": 102,
                    "high": 106,
                    "low": 101,
                    "close": 105,
                    "volume": 12,
                    "isFinal": True,
                },
            ]
        }

    def get_orderbook(self, symbol: str, depth: int = 20):
        return {
            "bids": [["104.9", "2.0"], ["104.8", "1.0"]],
            "asks": [["105.1", "1.0"], ["105.2", "1.0"]],
        }

    def get_live_account(self, competition_id: int):
        return {
            "availableBalance": 1000.0,
            "equity": 1015.0,
            "unrealizedPnl": 15.0,
            "tradeCount": 2,
        }

    def get_live_position(self, competition_id: int):
        return {
            "direction": "long",
            "size": 0.02,
            "entryPrice": 100.0,
            "takeProfit": 110.0,
            "stopLoss": 97.0,
        }

    def get_live_trades(self, competition_id: int):
        return [{"id": 1}, {"id": 2}]

    def get_competition_detail(self, competition_id: int):
        return {
            "id": competition_id,
            "status": "live",
            "symbol": "BTCUSDT",
            "currentTrades": 2,
            "maxTrades": 10,
            "closeOnlyMode": False,
            "endTime": 4102444800000,
        }


class InferredPositionArenaClient(FakeArenaClient):
    def get_live_position(self, competition_id: int):
        return None

    def get_live_account(self, competition_id: int):
        return {
            "availableBalance": 1000.0,
            "equity": 1015.0,
            "unrealizedPnl": 15.0,
            "tradesCount": 2,
        }

    def get_live_trades(self, competition_id: int):
        return [
            {
                "id": "open-a",
                "direction": "long",
                "size": 0.001,
                "entryPrice": 100.0,
                "exitPrice": None,
                "closeTime": None,
                "pnl": 4.0,
            },
            {
                "id": "open-b",
                "direction": "long",
                "size": 0.002,
                "entryPrice": 103.0,
                "exitPrice": None,
                "closeTime": None,
                "pnl": 6.0,
            },
        ]


class StaleUnresolvedTradesArenaClient(InferredPositionArenaClient):
    def get_live_account(self, competition_id: int):
        return {
            "availableBalance": 1000.0,
            "equity": 1000.0,
            "unrealizedPnl": 0.0,
            "tradesCount": 2,
        }

    def get_live_trades(self, competition_id: int):
        return [
            {
                "id": "stale-a",
                "direction": "long",
                "size": 0.001,
                "entryPrice": 100.0,
                "exitPrice": None,
                "closeTime": None,
                "openTime": 1,
                "pnl": 0.0,
            },
            {
                "id": "stale-b",
                "direction": "long",
                "size": 0.002,
                "entryPrice": 103.0,
                "exitPrice": None,
                "closeTime": None,
                "openTime": 1,
                "pnl": 0.0,
            },
        ]


class StateBuilderTest(unittest.TestCase):
    def test_build_normalizes_market_account_position_and_competition(self) -> None:
        config = RuntimeConfig.from_mapping({"competition_id": 4, "symbol": "BTCUSDT"})
        adapter = EnvironmentAdapter(client=FakeArenaClient())
        builder = StateBuilder(adapter, config)

        state = builder.build()

        self.assertEqual(state.market.symbol, "BTCUSDT")
        self.assertAlmostEqual(state.market.last_price, 105.0)
        self.assertGreater(state.market.volatility, 0.0)
        self.assertAlmostEqual(state.market.orderbook_imbalance, 0.2)
        self.assertEqual(state.account.trade_count, 2)
        self.assertIsNotNone(state.position)
        self.assertEqual(state.position.direction, "long")
        self.assertEqual(state.competition.max_trades_remaining, 8)
        self.assertTrue(state.competition.is_live)

    def test_build_infers_position_from_unresolved_trades(self) -> None:
        config = RuntimeConfig.from_mapping({"competition_id": 4, "symbol": "BTCUSDT"})
        adapter = EnvironmentAdapter(client=InferredPositionArenaClient())
        builder = StateBuilder(adapter, config)

        state = builder.build()

        self.assertIsNotNone(state.position)
        assert state.position is not None
        self.assertEqual(state.position.direction, "long")
        self.assertAlmostEqual(state.position.size, 0.003)
        self.assertAlmostEqual(state.position.entry_price, 102.0)
        self.assertAlmostEqual(state.position.unrealized_pnl, 10.0)
        self.assertTrue(state.position.metadata["inferred"])
        self.assertEqual(state.account.trade_count, 2)

    def test_build_includes_signal_state(self) -> None:
        config = RuntimeConfig.from_mapping(
            {
                "competition_id": 4,
                "symbol": "BTCUSDT",
                "signal_indicators": [
                    {"indicator": "SMA", "params": {"period": 2}},
                    {"indicator": "OBV", "params": {}},
                ],
            }
        )
        adapter = EnvironmentAdapter(client=FakeArenaClient())
        builder = StateBuilder(adapter, config)

        state = builder.build()

        self.assertEqual(state.signal_state.version, "signal_state.v1")
        self.assertTrue(state.signal_state.warmup_complete)
        self.assertAlmostEqual(state.signal_state.values["sma_2"], 103.5)
        self.assertAlmostEqual(state.signal_state.values["obv"], 23.0)

    def test_build_does_not_infer_stale_flat_position(self) -> None:
        config = RuntimeConfig.from_mapping({"competition_id": 4, "symbol": "BTCUSDT"})
        adapter = EnvironmentAdapter(client=StaleUnresolvedTradesArenaClient())
        builder = StateBuilder(adapter, config)

        state = builder.build()

        self.assertIsNone(state.position)


if __name__ == "__main__":
    unittest.main()
