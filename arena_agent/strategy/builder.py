"""Build a StrategyLayer from a YAML config dict."""

from __future__ import annotations

from typing import Any

from arena_agent.core.models import RiskLimits
from arena_agent.strategy.layer import (
    EntryFilter,
    ExitRule,
    PositionSizer,
    StrategyLayer,
    TPSLPlacer,
)
from arena_agent.strategy.sizing import (
    FixedFractionSizer,
    RiskPerTradeSizer,
    VolatilityScaledSizer,
)
from arena_agent.strategy.tpsl import ATRBasedTPSL, FixedTPSL, RMultipleTPSL
from arena_agent.strategy.rules import (
    DrawdownExit,
    TimeExit,
    TrailingStop,
    TradeBudgetFilter,
    VolatilityGate,
)


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

_SIZERS: dict[str, type] = {
    "fixed_fraction": FixedFractionSizer,
    "volatility_scaled": VolatilityScaledSizer,
    "risk_per_trade": RiskPerTradeSizer,
}

_TPSL: dict[str, type] = {
    "fixed_pct": FixedTPSL,
    "atr_multiple": ATRBasedTPSL,
    "r_multiple": RMultipleTPSL,
}

_FILTERS: dict[str, type] = {
    "volatility_gate": VolatilityGate,
    "trade_budget": TradeBudgetFilter,
}

_EXITS: dict[str, type] = {
    "trailing_stop": TrailingStop,
    "time_exit": TimeExit,
    "drawdown_exit": DrawdownExit,
}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _build_component(registry: dict[str, type], config: dict[str, Any] | None) -> Any:
    if not config:
        return None
    type_name = str(config.get("type", "")).lower()
    cls = registry.get(type_name)
    if cls is None:
        raise ValueError(
            f"Unknown strategy component type {type_name!r}. "
            f"Available: {', '.join(sorted(registry.keys()))}"
        )
    params = {k: v for k, v in config.items() if k != "type"}
    return cls(**params)


def build_strategy_layer(
    config: dict[str, Any] | None,
    risk_limits: RiskLimits | None = None,
) -> StrategyLayer | None:
    """Build a StrategyLayer from a config dict.

    Returns None if the config is empty or absent (no strategy).

    Example config::

        {
            "sizing": {"type": "volatility_scaled", "target_risk_pct": 0.02},
            "tpsl": {"type": "atr_multiple", "atr_tp_mult": 2.0, "atr_sl_mult": 1.5},
            "entry_filters": [
                {"type": "volatility_gate", "max_volatility": 0.05},
                {"type": "trade_budget", "min_remaining_trades": 5},
            ],
            "exit_rules": [
                {"type": "trailing_stop", "atr_multiplier": 2.0},
                {"type": "time_exit", "max_hold_seconds": 600},
            ],
        }
    """
    if not config:
        return None

    sizer: PositionSizer | None = _build_component(_SIZERS, config.get("sizing"))
    tpsl: TPSLPlacer | None = _build_component(_TPSL, config.get("tpsl"))
    entry_filters: list[EntryFilter] = [
        _build_component(_FILTERS, f) for f in config.get("entry_filters", [])
    ]
    exit_rules: list[ExitRule] = [
        _build_component(_EXITS, e) for e in config.get("exit_rules", [])
    ]
    entry_filters = [f for f in entry_filters if f is not None]
    exit_rules = [e for e in exit_rules if e is not None]

    if not any([sizer, tpsl, entry_filters, exit_rules]):
        return None

    return StrategyLayer(
        sizer=sizer,
        tpsl_placer=tpsl,
        entry_filters=entry_filters,
        exit_rules=exit_rules,
        risk_limits=risk_limits,
    )
