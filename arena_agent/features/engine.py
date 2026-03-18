"""Versioned signal-state feature engine backed by TA-Lib."""

from __future__ import annotations

import math
import time
from typing import Any

from arena_agent.core.models import Candle, FeatureSpec, SignalState
from arena_agent.features.registry import (
    REGISTRY,
    feature_key,
    get_full_indicator_specs,
    get_indicator_definition,
    indicator_requires_supported_inputs,
    lookback_required,
    normalize_indicator_name,
    normalize_params,
)


# API docs state max=1500, but tested: size>1000 silently falls back to 500.
# Using 1000 as the safe maximum until the backend fix is deployed.
API_MAX_KLINES = 1000


def compute_kline_limit(
    feature_specs: list[FeatureSpec],
    minimum: int = 120,
    margin: int = 20,
) -> int:
    """Compute the optimal kline_limit so every indicator has enough history.

    ``kline_limit = max(max_lookback + margin, minimum)`` capped at the API max (1000).
    """
    if not feature_specs:
        return min(minimum, API_MAX_KLINES)

    max_lb = 0
    for spec in feature_specs:
        lb = lookback_required(
            normalize_indicator_name(spec.indicator),
            normalize_params(spec.params),
        )
        if lb > max_lb:
            max_lb = lb

    needed = max(max_lb + margin, minimum)
    return min(needed, API_MAX_KLINES)


def resolve_indicator_specs(
    policy_config: dict[str, Any],
    fallback_specs: list[FeatureSpec],
) -> list[FeatureSpec]:
    """Resolve which indicators to compute based on policy config.

    Modes:
      - ``"full"``    — all curated TA-Lib indicators.
      - ``"custom"``  — use ``policy.signal_indicators`` list.
      - (default)     — use *fallback_specs* (top-level ``signal_indicators``).
    """
    mode = str(policy_config.get("indicator_mode", "")).lower()

    if mode == "full":
        return [FeatureSpec.from_mapping(s) for s in get_full_indicator_specs()]

    if mode == "custom":
        raw = policy_config.get("signal_indicators", [])
        return [FeatureSpec.from_mapping(s) for s in raw]

    return list(fallback_specs)


class FeatureEngine:
    def __init__(self, feature_specs: list[FeatureSpec] | None = None) -> None:
        self.feature_specs = list(feature_specs or [])
        self._talib = _load_talib_backend()
        self.backend_name = "talib"

    def compute(self, candles: list[Candle]) -> SignalState:
        if not self.feature_specs:
            return SignalState.empty()

        if not candles:
            return SignalState(
                version="signal_state.v1",
                backend=self.backend_name,
                requested=self.feature_specs,
                values={feature_key(spec.indicator, spec.params, spec.key): None for spec in self.feature_specs},
                warmup_complete=False,
                metadata={
                    "error": "no_candles",
                    "timestamp": time.time(),
                    "indicator_metadata": [
                        self._spec_metadata(spec)
                        for spec in self.feature_specs
                    ],
                },
            )

        series = {
            "open": [candle.open for candle in candles],
            "high": [candle.high for candle in candles],
            "low": [candle.low for candle in candles],
            "close": [candle.close for candle in candles],
            "volume": [candle.volume for candle in candles],
        }

        values: dict[str, Any] = {}
        warmup_complete = True
        for spec in self.feature_specs:
            key = feature_key(spec.indicator, spec.params, spec.key)
            value = self._compute_one(spec, series)
            values[key] = value
            if not _value_is_ready(value):
                warmup_complete = False

        return SignalState(
            version="signal_state.v1",
            backend=self.backend_name,
            requested=self.feature_specs,
            values=values,
            warmup_complete=warmup_complete,
            metadata={
                "timestamp": candles[-1].close_time if candles else time.time(),
                "candle_count": len(candles),
                "indicator_metadata": [
                    self._spec_metadata(spec)
                    for spec in self.feature_specs
                ],
            },
        )

    def _compute_one(self, spec: FeatureSpec, series: dict[str, list[float]]) -> Any:
        indicator = normalize_indicator_name(spec.indicator)
        params = normalize_params(spec.params)
        # MAVP: auto-construct the periods array if not supplied
        if indicator == "MAVP" and "periods" not in params:
            params = {**params}
            params["periods"] = _build_mavp_periods(series, params, self._talib)
        ok, unsupported = indicator_requires_supported_inputs(indicator, params)
        if not ok:
            raise ValueError(
                f"Indicator '{indicator}' requires unsupported inputs: {', '.join(unsupported)}. "
                "Provide those extra series inputs in the indicator params."
            )
        return _compute_talib(self._talib, indicator, params, series, spec.key)

    def _spec_metadata(self, spec: FeatureSpec) -> dict[str, Any]:
        indicator = normalize_indicator_name(spec.indicator)
        params = normalize_params(spec.params)
        definition = get_indicator_definition(indicator)
        ok, unsupported = indicator_requires_supported_inputs(indicator, params)
        return {
            "key": feature_key(spec.indicator, spec.params, spec.key),
            "indicator": indicator,
            "params": params,
            "outputs": list(definition.outputs) if definition else ["value"],
            "lookback_required": lookback_required(indicator, params),
            "supported_inputs_only": ok,
            "unsupported_inputs": unsupported,
        }


def _load_talib_backend():
    from talib import abstract as talib_abstract  # type: ignore
    return talib_abstract


def _compute_talib(talib_abstract, indicator: str, params: dict[str, Any], series: dict[str, list[float]], explicit_key: str | None) -> Any:
    import numpy as np

    function = getattr(talib_abstract, indicator, None)
    if function is None:
        raise ValueError(f"Indicator '{indicator}' is not available in TA-Lib.")

    function_info = talib_abstract.Function(indicator)
    talib_inputs = _build_talib_inputs(function_info.info["input_names"], series, params, np)
    function_params = {key: value for key, value in params.items() if key not in talib_inputs}
    result = function(talib_inputs, **function_params)
    if isinstance(result, (tuple, list)):
        definition = get_indicator_definition(indicator)
        output_names = definition.outputs if definition is not None else tuple(f"output_{i}" for i in range(len(result)))
        return {
            name: _last_value(item)
            for name, item in zip(output_names, result)
        }
    return _last_value(result)


def _value_is_ready(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return all(item is not None for item in value.values())
    return True


def _last_value(value: Any) -> float | None:
    try:
        last = value[-1]
    except Exception:
        return None
    if last is None:
        return None
    try:
        numeric = float(last)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _build_talib_inputs(input_names: dict[str, Any], series: dict[str, list[float]], params: dict[str, Any], np) -> dict[str, Any]:
    inputs = {name: np.asarray(values, dtype=float) for name, values in series.items()}
    reference_length = len(series["close"])
    for value in input_names.values():
        if isinstance(value, list):
            names = value
        else:
            names = [value]
        for name in names:
            if name in inputs:
                continue
            if name not in params:
                continue
            raw = params[name]
            if isinstance(raw, (list, tuple)):
                if len(raw) != reference_length:
                    raise ValueError(
                        f"Extra input series '{name}' must match candle length {reference_length}, got {len(raw)}."
                    )
                inputs[name] = np.asarray(raw, dtype=float)
            else:
                inputs[name] = np.full(reference_length, float(raw), dtype=float)
    return inputs


def _build_mavp_periods(
    series: dict[str, list[float]],
    params: dict[str, Any],
    talib_abstract: Any,
) -> list[float]:
    """Auto-construct the variable-period array for MAVP.

    Supported methods (via ``period_method`` param):
      - ``"volatility"`` (default): scale period inversely with ATR normalised
        by price.  High volatility → longer period (smoother); low → shorter.
      - ``"trend"``: scale period inversely with ADX.  Strong trend → shorter
        period (responsive); weak/ranging → longer (smoother).

    Extra params:
      - ``min_period`` (default 5): shortest allowed period.
      - ``max_period`` (default 40): longest allowed period.
      - ``scaling_period`` (default 14): lookback for the ATR / ADX computation.
    """
    import numpy as np

    method = str(params.pop("period_method", "volatility")).lower()
    min_p = int(params.pop("min_period", 5))
    max_p = int(params.pop("max_period", 40))
    scaling = int(params.pop("scaling_period", 14))

    close = np.asarray(series["close"], dtype=float)
    high = np.asarray(series["high"], dtype=float)
    low = np.asarray(series["low"], dtype=float)
    n = len(close)

    if method == "trend":
        import talib as _ta  # type: ignore

        adx = _ta.ADX(high, low, close, timeperiod=scaling)
        # ADX 0-100: high ADX → short period, low ADX → long period
        norm = np.where(np.isnan(adx), 0.5, adx / 100.0)
        periods = max_p - norm * (max_p - min_p)
    else:
        # volatility (default)
        import talib as _ta  # type: ignore

        atr = _ta.ATR(high, low, close, timeperiod=scaling)
        natr = np.where(close > 0, atr / close, 0.0)
        natr = np.where(np.isnan(natr), 0.0, natr)
        # Normalise to 0-1 range within this window
        mn, mx = np.nanmin(natr), np.nanmax(natr)
        if mx > mn:
            norm = (natr - mn) / (mx - mn)
        else:
            norm = np.full(n, 0.5)
        # High volatility → longer period
        periods = min_p + norm * (max_p - min_p)

    periods = np.clip(np.round(periods), min_p, max_p).astype(float)
    return periods.tolist()
