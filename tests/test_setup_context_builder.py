from __future__ import annotations

import unittest
from unittest.mock import patch

from arena_agent.setup.context_builder import build_setup_context


class SetupContextBuilderTest(unittest.TestCase):
    @patch("arena_agent.setup.context_builder.varsity_tools.get_chat_history", return_value=[])
    @patch("arena_agent.setup.context_builder.varsity_tools.get_competition_leaderboard_me", return_value={})
    @patch("arena_agent.setup.context_builder.varsity_tools.get_klines")
    @patch("arena_agent.setup.context_builder.varsity_tools.get_competition_detail")
    @patch("arena_agent.setup.context_builder.varsity_tools.get_live_position")
    @patch("arena_agent.setup.context_builder.varsity_tools.get_live_account")
    @patch("arena_agent.setup.context_builder.varsity_tools.get_trade_history")
    def test_build_setup_context_includes_recent_trades(
        self,
        mock_trade_history,
        mock_live_account,
        mock_live_position,
        mock_competition_detail,
        mock_get_klines,
        _mock_lb,
        _mock_chat,
    ) -> None:
        mock_live_account.return_value = {
            "capital": 10050.0,
            "walletBalance": 10050.0,
            "initialBalance": 10000.0,
            "unrealizedPnl": 0.0,
            "tradesCount": 2,
        }
        mock_live_position.return_value = None
        mock_competition_detail.return_value = {
            "title": "Agent Test",
            "status": "live",
            "symbol": "SOLUSDT",
            "maxTradesPerMatch": 40,
            "startingCapital": 10000.0,
            "feeRate": 0.0004,
        }
        mock_get_klines.return_value = {
            "klines": [
                {"open": 82.0, "high": 82.1, "low": 81.9, "close": 82.0},
                {"open": 82.0, "high": 82.2, "low": 81.95, "close": 82.1},
                {"open": 82.1, "high": 82.2, "low": 82.0, "close": 82.05},
                {"open": 82.05, "high": 82.15, "low": 82.0, "close": 82.08},
                {"open": 82.08, "high": 82.12, "low": 82.01, "close": 82.1},
                {"open": 82.1, "high": 82.14, "low": 82.02, "close": 82.11},
                {"open": 82.11, "high": 82.18, "low": 82.05, "close": 82.12},
                {"open": 82.12, "high": 82.19, "low": 82.06, "close": 82.13},
                {"open": 82.13, "high": 82.2, "low": 82.07, "close": 82.14},
                {"open": 82.14, "high": 82.22, "low": 82.08, "close": 82.15},
            ]
        }
        mock_trade_history.return_value = [
            {
                "direction": "long",
                "size": 85.0,
                "entryPrice": 81.76,
                "exitPrice": 81.79,
                "pnl": 2.55,
                "pnlPct": 0.0367,
                "fee": 6.950875,
                "holdDuration": 190577,
                "closeReason": "manual",
                "openTime": 1776077076037,
                "closeTime": 1776077266614,
            },
            {
                "direction": "short",
                "size": 84.82,
                "entryPrice": 82.03,
                "exitPrice": 81.95,
                "pnl": 6.7856,
                "pnlPct": 0.0975,
                "fee": 6.9543918,
                "holdDuration": 567938,
                "closeReason": "manual",
                "openTime": 1776072089289,
                "closeTime": 1776072657227,
            },
        ]

        context = build_setup_context(
            competition_id=10,
            config={
                "symbol": "BTCUSDT",
                "interval": "1m",
                "_strategy_start_trade_count": 0,
            },
            memory=[],
        )

        self.assertIn("recent_trades", context)
        self.assertEqual(len(context["recent_trades"]), 2)
        first = context["recent_trades"][0]
        self.assertEqual(first["direction"], "long")
        self.assertEqual(first["close_reason"], "manual")
        self.assertAlmostEqual(first["fee"], 6.9509)
        self.assertAlmostEqual(first["hold_seconds"], 190.6)
        self.assertTrue(first["under_current_strategy"])
        self.assertIn("performance", context)
        self.assertAlmostEqual(context["performance"]["total_fees"], 13.9053)


if __name__ == "__main__":
    unittest.main()
