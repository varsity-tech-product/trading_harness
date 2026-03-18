"""Indicator metadata and key generation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any


@dataclass(frozen=True, slots=True)
class IndicatorDefinition:
    name: str
    outputs: tuple[str, ...]
    required_inputs: tuple[str, ...]


REGISTRY: dict[str, IndicatorDefinition] = {
    "SMA": IndicatorDefinition("SMA", ("value",), ("close",)),
    "EMA": IndicatorDefinition("EMA", ("value",), ("close",)),
    "RSI": IndicatorDefinition("RSI", ("value",), ("close",)),
    "MACD": IndicatorDefinition("MACD", ("macd", "signal", "hist"), ("close",)),
    "BBANDS": IndicatorDefinition("BBANDS", ("upper", "middle", "lower"), ("close",)),
    "ATR": IndicatorDefinition("ATR", ("value",), ("high", "low", "close")),
    "OBV": IndicatorDefinition("OBV", ("value",), ("close", "volume")),
}

SUPPORTED_BASE_INPUTS = {"open", "high", "low", "close", "volume"}


def normalize_indicator_name(name: str) -> str:
    return str(name).upper()


def normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "period": "timeperiod",
        "fast_period": "fastperiod",
        "slow_period": "slowperiod",
        "signal_period": "signalperiod",
        "nbdev_up": "nbdevup",
        "nbdev_down": "nbdevdn",
    }
    # Param keys that must be numeric (int or float).
    _INT_KEYS = {"timeperiod", "fastperiod", "slowperiod", "signalperiod",
                 "fastk_period", "slowk_period", "slowd_period",
                 "penetration", "acceleration", "maximum"}
    _FLOAT_KEYS = {"nbdevup", "nbdevdn"}
    normalized = {}
    for key, value in params.items():
        canon = aliases.get(key, key)
        # Sanitize: drop non-numeric values for numeric params
        if canon in _INT_KEYS:
            try:
                value = int(float(value))
            except (TypeError, ValueError):
                continue  # skip malformed param
        elif canon in _FLOAT_KEYS:
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
        normalized[canon] = value
    return normalized


def feature_key(indicator: str, params: dict[str, Any], explicit_key: str | None = None) -> str:
    if explicit_key:
        return explicit_key

    indicator_name = normalize_indicator_name(indicator)
    params = normalize_params(params)

    if indicator_name in {"SMA", "EMA", "RSI", "ATR"}:
        return f"{indicator_name.lower()}_{int(params.get('timeperiod', 14))}"
    if indicator_name == "MACD":
        return "macd_{fast}_{slow}_{signal}".format(
            fast=int(params.get("fastperiod", 12)),
            slow=int(params.get("slowperiod", 26)),
            signal=int(params.get("signalperiod", 9)),
        )
    if indicator_name == "BBANDS":
        return "bbands_{period}_{up:g}_{dn:g}".format(
            period=int(params.get("timeperiod", 20)),
            up=float(params.get("nbdevup", 2.0)),
            dn=float(params.get("nbdevdn", 2.0)),
        )
    if indicator_name == "OBV":
        return "obv"

    if not params:
        return indicator_name.lower()
    rendered = "_".join(f"{key}_{params[key]}" for key in sorted(params))
    return f"{indicator_name.lower()}_{rendered}"


def lookback_required(indicator: str, params: dict[str, Any]) -> int:
    talib_lookback = talib_lookback_required(indicator, params)
    if talib_lookback is not None:
        return talib_lookback

    indicator_name = normalize_indicator_name(indicator)
    params = normalize_params(params)

    if indicator_name in {"SMA", "EMA", "RSI", "ATR", "BBANDS"}:
        return int(params.get("timeperiod", 14))
    if indicator_name == "MACD":
        return int(params.get("slowperiod", 26)) + int(params.get("signalperiod", 9))
    if indicator_name == "OBV":
        return 1
    return 1


def get_indicator_definition(indicator: str) -> IndicatorDefinition | None:
    indicator_name = normalize_indicator_name(indicator)
    if indicator_name in REGISTRY:
        return REGISTRY[indicator_name]

    talib_info = talib_indicator_info(indicator_name)
    if talib_info is None:
        return None
    outputs = tuple(str(name) for name in talib_info["output_names"])
    inputs = tuple(sorted(_flatten_input_names(talib_info["input_names"])))
    return IndicatorDefinition(indicator_name, outputs, inputs)


@lru_cache(maxsize=256)
def talib_indicator_info(indicator: str) -> dict[str, Any] | None:
    try:
        from talib import abstract  # type: ignore
    except Exception:
        return None

    try:
        function = abstract.Function(normalize_indicator_name(indicator))
    except Exception:
        return None
    return dict(function.info)


def talib_lookback_required(indicator: str, params: dict[str, Any]) -> int | None:
    try:
        from talib import abstract  # type: ignore
    except Exception:
        return None

    try:
        function = abstract.Function(normalize_indicator_name(indicator))
        function.set_parameters(normalize_params(params))
        return int(function.lookback)
    except Exception:
        return None


def indicator_requires_supported_inputs(indicator: str, params: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    definition = get_indicator_definition(indicator)
    if definition is None:
        return False, []
    params = normalize_params(params or {})
    unsupported = sorted(
        name
        for name in definition.required_inputs
        if name not in SUPPORTED_BASE_INPUTS and name not in params
    )
    return len(unsupported) == 0, unsupported


def _flatten_input_names(input_names: Any) -> set[str]:
    names: set[str] = set()
    for value in input_names.values():
        if isinstance(value, list):
            names.update(str(item) for item in value)
        else:
            names.add(str(value))
    return names


# ---------------------------------------------------------------------------
# Indicator presets for policy-driven indicator selection
# ---------------------------------------------------------------------------

FULL_INDICATOR_SPECS: list[dict[str, Any]] = [
    # Moving averages
    {"indicator": "SMA", "params": {"period": 9}},
    {"indicator": "SMA", "params": {"period": 20}},
    {"indicator": "SMA", "params": {"period": 50}},
    {"indicator": "EMA", "params": {"period": 12}},
    {"indicator": "EMA", "params": {"period": 26}},
    # Overlap / trend
    {"indicator": "BBANDS", "params": {"period": 20}},
    {"indicator": "SAR", "params": {}},
    # Momentum / oscillator
    {"indicator": "RSI", "params": {"period": 14}},
    {"indicator": "MACD", "params": {"fast_period": 12, "slow_period": 26, "signal_period": 9}},
    {"indicator": "ADX", "params": {"timeperiod": 14}},
    {"indicator": "AROON", "params": {"timeperiod": 14}},
    {"indicator": "CCI", "params": {"timeperiod": 14}},
    {"indicator": "DX", "params": {"timeperiod": 14}},
    {"indicator": "MINUS_DI", "params": {"timeperiod": 14}},
    {"indicator": "PLUS_DI", "params": {"timeperiod": 14}},
    {"indicator": "TRIX", "params": {"timeperiod": 14}},
    {"indicator": "CMO", "params": {"timeperiod": 14}},
    {"indicator": "MFI", "params": {"timeperiod": 14}},
    {"indicator": "MOM", "params": {"timeperiod": 10}},
    {"indicator": "ROC", "params": {"timeperiod": 10}},
    {"indicator": "STOCH", "params": {}},
    {"indicator": "STOCHRSI", "params": {"timeperiod": 14}},
    {"indicator": "ULTOSC", "params": {}},
    {"indicator": "WILLR", "params": {"timeperiod": 14}},
    # Volatility
    {"indicator": "ATR", "params": {"period": 14}},
    {"indicator": "NATR", "params": {"timeperiod": 14}},
    {"indicator": "TRANGE", "params": {}},
    # Volume
    {"indicator": "OBV", "params": {}},
    {"indicator": "AD", "params": {}},
    {"indicator": "ADOSC", "params": {}},
]


def get_full_indicator_specs() -> list[dict[str, Any]]:
    """Return FeatureSpec-compatible dicts for the full TA-Lib indicator suite."""
    return list(FULL_INDICATOR_SPECS)
