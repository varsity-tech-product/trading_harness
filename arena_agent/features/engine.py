"""Versioned signal-state feature engine with optional TA-Lib backend."""

from __future__ import annotations

import math
import statistics
import time
from typing import Any

from arena_agent.core.models import Candle, FeatureSpec, SignalState
from arena_agent.features.registry import (
    REGISTRY,
    feature_key,
    get_indicator_definition,
    indicator_requires_supported_inputs,
    lookback_required,
    normalize_indicator_name,
    normalize_params,
)


class FeatureEngine:
    def __init__(self, feature_specs: list[FeatureSpec] | None = None) -> None:
        self.feature_specs = list(feature_specs or [])
        self._talib = _load_talib_backend()
        self.backend_name = "talib" if self._talib is not None else "builtin"

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
        if self._talib is not None:
            ok, unsupported = indicator_requires_supported_inputs(indicator, params)
            if not ok:
                raise ValueError(
                    f"Indicator '{indicator}' requires unsupported inputs: {', '.join(unsupported)}. "
                    "Provide those extra series inputs in the indicator params."
                )
            return _compute_talib(self._talib, indicator, params, series, spec.key)
        return _compute_builtin(indicator, params, series)

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
    try:
        from talib import abstract as talib_abstract  # type: ignore
    except Exception:
        return None
    return talib_abstract


def _compute_talib(talib_abstract, indicator: str, params: dict[str, Any], series: dict[str, list[float]], explicit_key: str | None) -> Any:
    try:
        import numpy as np
    except ModuleNotFoundError as exc:  # pragma: no cover - talib environment dependency
        raise RuntimeError("TA-Lib backend requires numpy in the current environment.") from exc

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


def _compute_builtin(indicator: str, params: dict[str, Any], series: dict[str, list[float]]) -> Any:
    if indicator == "SMA":
        return _sma(series["close"], int(params.get("timeperiod", 14)))
    if indicator == "EMA":
        return _ema(series["close"], int(params.get("timeperiod", 14)))
    if indicator == "RSI":
        return _rsi(series["close"], int(params.get("timeperiod", 14)))
    if indicator == "MACD":
        fast = int(params.get("fastperiod", 12))
        slow = int(params.get("slowperiod", 26))
        signal = int(params.get("signalperiod", 9))
        macd_line, signal_line, hist = _macd(series["close"], fast, slow, signal)
        return {"macd": macd_line, "signal": signal_line, "hist": hist}
    if indicator == "BBANDS":
        period = int(params.get("timeperiod", 20))
        up = float(params.get("nbdevup", 2.0))
        dn = float(params.get("nbdevdn", 2.0))
        upper, middle, lower = _bbands(series["close"], period, up, dn)
        return {"upper": upper, "middle": middle, "lower": lower}
    if indicator == "ATR":
        return _atr(series["high"], series["low"], series["close"], int(params.get("timeperiod", 14)))
    if indicator == "OBV":
        return _obv(series["close"], series["volume"])
    if indicator == "RETURNS":
        return _returns(series["close"], int(params.get("timeperiod", 1)))
    if indicator == "VOLATILITY":
        return _volatility(series["close"], int(params.get("timeperiod", 20)))
    raise ValueError(f"Indicator '{indicator}' is not supported by the builtin feature engine.")


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


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
    return ema


def _rsi(values: list[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    gains = []
    losses = []
    for previous, current in zip(values, values[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for index in range(period, len(gains)):
        average_gain = ((average_gain * (period - 1)) + gains[index]) / period
        average_loss = ((average_loss * (period - 1)) + losses[index]) / period
    if math.isclose(average_loss, 0.0):
        return 100.0
    rs = average_gain / average_loss
    return 100 - (100 / (1 + rs))


def _macd(values: list[float], fast_period: int, slow_period: int, signal_period: int) -> tuple[float | None, float | None, float | None]:
    if len(values) < slow_period + signal_period:
        return None, None, None
    macd_series = []
    for index in range(len(values)):
        subset = values[: index + 1]
        fast = _ema(subset, fast_period)
        slow = _ema(subset, slow_period)
        macd_series.append(None if fast is None or slow is None else fast - slow)
    clean_macd = [value for value in macd_series if value is not None]
    signal = _ema(clean_macd, signal_period)
    macd_value = clean_macd[-1] if clean_macd else None
    hist = None if macd_value is None or signal is None else macd_value - signal
    return macd_value, signal, hist


def _bbands(values: list[float], period: int, nbdev_up: float, nbdev_down: float) -> tuple[float | None, float | None, float | None]:
    if len(values) < period:
        return None, None, None
    window = values[-period:]
    middle = sum(window) / period
    deviation = statistics.pstdev(window) if len(window) > 1 else 0.0
    return middle + nbdev_up * deviation, middle, middle - nbdev_down * deviation


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> float | None:
    if len(highs) <= period or len(lows) <= period or len(closes) <= period:
        return None
    true_ranges = []
    for index in range(1, len(closes)):
        tr = max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        true_ranges.append(tr)
    if len(true_ranges) < period:
        return None
    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = ((atr * (period - 1)) + tr) / period
    return atr


def _obv(closes: list[float], volumes: list[float]) -> float | None:
    if not closes or len(closes) != len(volumes):
        return None
    obv = 0.0
    for previous, current, volume in zip(closes, closes[1:], volumes[1:]):
        if current > previous:
            obv += volume
        elif current < previous:
            obv -= volume
    return obv


def _returns(closes: list[float], period: int) -> float | None:
    if len(closes) <= period:
        return None
    previous = closes[-(period + 1)]
    if math.isclose(previous, 0.0):
        return None
    return (closes[-1] - previous) / previous


def _volatility(closes: list[float], period: int) -> float | None:
    if len(closes) <= period:
        return None
    window = closes[-(period + 1) :]
    returns = []
    for previous, current in zip(window, window[1:]):
        if math.isclose(previous, 0.0):
            continue
        returns.append((current - previous) / previous)
    if len(returns) < 2:
        return None
    return statistics.pstdev(returns)
