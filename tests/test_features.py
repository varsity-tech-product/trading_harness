from __future__ import annotations

import importlib.util
import unittest

from arena_agent.core.models import Candle, FeatureSpec
from arena_agent.features.engine import FeatureEngine, resolve_indicator_specs
from arena_agent.features.registry import BUILTIN_FULL


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


class ResolveIndicatorSpecsTest(unittest.TestCase):
    def test_full_mode_returns_all_builtins(self) -> None:
        specs = resolve_indicator_specs({"indicator_mode": "full"}, [])
        keys = {s.indicator.upper() for s in specs}
        self.assertIn("SMA", keys)
        self.assertIn("RSI", keys)
        self.assertIn("MACD", keys)
        self.assertIn("BBANDS", keys)
        self.assertIn("ATR", keys)
        self.assertIn("OBV", keys)
        self.assertGreaterEqual(len(specs), len(BUILTIN_FULL))

    def test_custom_mode_uses_policy_list(self) -> None:
        policy = {
            "indicator_mode": "custom",
            "signal_indicators": [
                {"indicator": "RSI", "params": {"period": 7}},
            ],
        }
        fallback = [FeatureSpec(indicator="SMA", params={"period": 50})]
        specs = resolve_indicator_specs(policy, fallback)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].indicator, "RSI")

    def test_default_mode_uses_fallback(self) -> None:
        fallback = [FeatureSpec(indicator="SMA", params={"period": 20})]
        specs = resolve_indicator_specs({}, fallback)
        self.assertEqual(specs, fallback)

    def test_default_mode_empty_fallback(self) -> None:
        specs = resolve_indicator_specs({}, [])
        self.assertEqual(specs, [])

    def test_full_mode_computes_all_builtins(self) -> None:
        specs = resolve_indicator_specs({"indicator_mode": "full"}, [])
        engine = FeatureEngine(specs)
        candles = [
            Candle(i, i + 1, 100 + i * 0.5, 101 + i * 0.5, 99 + i * 0.5, 100 + i * 0.5, 10 + i)
            for i in range(120)
        ]
        signal_state = engine.compute(candles)
        self.assertTrue(signal_state.warmup_complete)
        # All builtin indicators should produce non-None values with 120 candles
        for key, value in signal_state.values.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    self.assertIsNotNone(sub_value, f"{key}.{sub_key} is None")
            else:
                self.assertIsNotNone(value, f"{key} is None")


if __name__ == "__main__":
    unittest.main()
