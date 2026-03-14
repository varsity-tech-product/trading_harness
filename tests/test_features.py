from __future__ import annotations

import importlib.util
import unittest

from arena_agent.core.models import Candle, FeatureSpec
from arena_agent.features.engine import FeatureEngine


class FeatureEngineTest(unittest.TestCase):
    def test_compute_builtin_signal_state(self) -> None:
        engine = FeatureEngine(
            [
                FeatureSpec(indicator="SMA", params={"period": 2}),
                FeatureSpec(indicator="RETURNS", params={"period": 1}),
                FeatureSpec(indicator="OBV"),
            ]
        )
        candles = [
            Candle(1, 2, 100, 101, 99, 100, 10),
            Candle(3, 4, 100, 103, 99, 102, 11),
            Candle(5, 6, 102, 106, 101, 105, 12),
        ]

        signal_state = engine.compute(candles)

        self.assertEqual(signal_state.version, "signal_state.v1")
        self.assertEqual(signal_state.backend, "builtin")
        self.assertTrue(signal_state.warmup_complete)
        self.assertAlmostEqual(signal_state.values["sma_2"], 103.5)
        self.assertAlmostEqual(signal_state.values["returns_1"], (105.0 - 102.0) / 102.0)
        self.assertAlmostEqual(signal_state.values["obv"], 23.0)
        self.assertIn("timestamp", signal_state.metadata)
        self.assertEqual(signal_state.metadata["indicator_metadata"][0]["lookback_required"], 2)

    def test_compute_multi_output_indicator(self) -> None:
        engine = FeatureEngine(
            [
                FeatureSpec(indicator="MACD", params={"fast_period": 3, "slow_period": 5, "signal_period": 2}),
            ]
        )
        candles = [
            Candle(index, index + 1, 100 + index, 101 + index, 99 + index, 100 + index, 10 + index)
            for index in range(12)
        ]

        signal_state = engine.compute(candles)

        self.assertIn("macd_3_5_2", signal_state.values)
        value = signal_state.values["macd_3_5_2"]
        self.assertIsInstance(value, dict)
        self.assertIn("macd", value)
        self.assertIn("signal", value)
        self.assertIn("hist", value)
        self.assertEqual(signal_state.metadata["indicator_metadata"][0]["lookback_required"], 7)

    @unittest.skipUnless(importlib.util.find_spec("talib") is not None, "TA-Lib not installed in this test environment")
    def test_compute_indicator_with_extra_series_param(self) -> None:
        engine = FeatureEngine(
            [
                FeatureSpec(
                    indicator="MAVP",
                    key="mavp_test",
                    params={
                        "minperiod": 2,
                        "maxperiod": 5,
                        "periods": [2] * 40,
                    },
                ),
            ]
        )
        candles = [
            Candle(index, index + 1, 100 + index, 101 + index, 99 + index, 100 + index, 10 + index)
            for index in range(40)
        ]

        signal_state = engine.compute(candles)

        self.assertEqual(signal_state.backend, "talib" if signal_state.backend == "talib" else "builtin")
        self.assertIn("mavp_test", signal_state.values)


if __name__ == "__main__":
    unittest.main()
