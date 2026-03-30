from __future__ import annotations

import importlib.util
import unittest

from arena_agent.core.models import Candle, FeatureSpec
from arena_agent.features.engine import FeatureEngine, resolve_indicator_specs
from arena_agent.features.registry import FULL_INDICATOR_SPECS

_HAS_TALIB = importlib.util.find_spec("talib") is not None


@unittest.skipUnless(_HAS_TALIB, "TA-Lib not installed")
class FeatureEngineTest(unittest.TestCase):
    def test_compute_signal_state(self) -> None:
        engine = FeatureEngine(
            [
                FeatureSpec(indicator="SMA", params={"period": 2}),
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
        self.assertEqual(signal_state.backend, "talib")
        self.assertTrue(signal_state.warmup_complete)
        self.assertAlmostEqual(signal_state.values["sma_2"], 103.5)
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

        self.assertEqual(signal_state.backend, "talib")
        self.assertIn("mavp_test", signal_state.values)


class FeatureKeyTest(unittest.TestCase):
    def test_single_timeperiod_indicators_use_short_format(self) -> None:
        from arena_agent.features.registry import feature_key
        for name in ("ADX", "CCI", "DX", "NATR", "TRIX", "CMO", "MFI",
                     "MOM", "ROC", "WILLR", "RSI", "SMA", "EMA", "ATR"):
            key = feature_key(name, {"timeperiod": 14})
            self.assertEqual(key, f"{name.lower()}_14",
                             f"{name} should produce '{name.lower()}_14', got '{key}'")

    def test_multi_word_indicator_short_format(self) -> None:
        from arena_agent.features.registry import feature_key
        self.assertEqual(feature_key("MINUS_DI", {"timeperiod": 14}), "minus_di_14")
        self.assertEqual(feature_key("PLUS_DI", {"timeperiod": 14}), "plus_di_14")

    def test_macd_keeps_special_format(self) -> None:
        from arena_agent.features.registry import feature_key
        key = feature_key("MACD", {"fastperiod": 12, "slowperiod": 26, "signalperiod": 9})
        self.assertEqual(key, "macd_12_26_9")

    def test_bbands_keeps_special_format(self) -> None:
        from arena_agent.features.registry import feature_key
        key = feature_key("BBANDS", {"timeperiod": 20, "nbdevup": 2.0, "nbdevdn": 2.0})
        self.assertEqual(key, "bbands_20_2_2")

    def test_no_params_indicator(self) -> None:
        from arena_agent.features.registry import feature_key
        self.assertEqual(feature_key("OBV", {}), "obv")
        self.assertEqual(feature_key("STOCH", {}), "stoch")

    def test_explicit_key_takes_precedence(self) -> None:
        from arena_agent.features.registry import feature_key
        self.assertEqual(feature_key("RSI", {"timeperiod": 14}, explicit_key="my_rsi"), "my_rsi")


class ResolveIndicatorSpecsTest(unittest.TestCase):
    def test_full_mode_returns_all_indicators(self) -> None:
        specs = resolve_indicator_specs({"indicator_mode": "full"}, [])
        keys = {s.indicator.upper() for s in specs}
        self.assertIn("SMA", keys)
        self.assertIn("RSI", keys)
        self.assertIn("MACD", keys)
        self.assertIn("BBANDS", keys)
        self.assertIn("ATR", keys)
        self.assertIn("OBV", keys)
        self.assertIn("ADX", keys)
        self.assertGreaterEqual(len(specs), len(FULL_INDICATOR_SPECS))

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

    @unittest.skipUnless(_HAS_TALIB, "TA-Lib not installed")
    def test_full_mode_computes_all_indicators(self) -> None:
        specs = resolve_indicator_specs({"indicator_mode": "full"}, [])
        engine = FeatureEngine(specs)
        candles = [
            Candle(i, i + 1, 100 + i * 0.5, 101 + i * 0.5, 99 + i * 0.5, 100 + i * 0.5, 10 + i)
            for i in range(120)
        ]
        signal_state = engine.compute(candles)
        self.assertTrue(signal_state.warmup_complete)
        for key, value in signal_state.values.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    self.assertIsNotNone(sub_value, f"{key}.{sub_key} is None")
            else:
                self.assertIsNotNone(value, f"{key} is None")


if __name__ == "__main__":
    unittest.main()
