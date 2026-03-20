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

# Common param aliases that agents use (maps wrong name → correct name).
_PARAM_ALIASES: dict[str, str] = {
    # ATRBasedTPSL aliases
    "tp_multiple": "atr_tp_mult",
    "sl_multiple": "atr_sl_mult",
    "tp_mult": "atr_tp_mult",
    "sl_mult": "atr_sl_mult",
    "atr_take_profit_multiple": "atr_tp_mult",
    "atr_stop_loss_multiple": "atr_sl_mult",
    "atr_multiplier_tp": "atr_tp_mult",
    "atr_multiplier_sl": "atr_sl_mult",
    "take_profit_multiple": "atr_tp_mult",
    "stop_loss_multiple": "atr_sl_mult",
    "tp_multiplier": "atr_tp_mult",
    "sl_multiplier": "atr_sl_mult",
    "atr_tp_multiple": "atr_tp_mult",
    "atr_sl_multiple": "atr_sl_mult",
    # TrailingStop aliases
    "activation_r": "atr_multiplier",
    "trail_multiplier": "atr_multiplier",
    "trailing_multiplier": "atr_multiplier",
    "trailing_atr_multiplier": "atr_multiplier",
    "trail_atr": "atr_multiplier",
    # RMultipleTPSL aliases (prevent cross-type confusion)
    "reward_risk": "reward_risk_ratio",
    "rr_ratio": "reward_risk_ratio",
    "risk_reward_ratio": "reward_risk_ratio",
    "sl_mult": "sl_atr_mult",
    # min_sl_pct aliases
    "min_stop_loss_pct": "min_sl_pct",
    "min_stoploss_pct": "min_sl_pct",
    "min_sl_distance_pct": "min_sl_pct",
}


def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Apply alias normalization so agents don't need exact param names."""
    return {_PARAM_ALIASES.get(k, k): v for k, v in params.items()}


_log = __import__("logging").getLogger(__name__)


def _build_component(registry: dict[str, type], config: dict[str, Any] | str | None) -> Any:
    if not config:
        return None
    if isinstance(config, str):
        # Agent passed a string like "none" or a type name directly
        if config.lower() == "none":
            return None
        config = {"type": config}
    type_name = str(config.get("type", "")).lower()
    cls = registry.get(type_name)
    if cls is None:
        raise ValueError(
            f"Unknown strategy component type {type_name!r}. "
            f"Available: {', '.join(sorted(registry.keys()))}"
        )
    params = _normalize_params({k: v for k, v in config.items() if k != "type"})

    # Strip params that don't belong to this class (cross-type contamination).
    import dataclasses

    if dataclasses.is_dataclass(cls):
        valid_names = {f.name for f in dataclasses.fields(cls) if f.name != "name"}
        unknown = {k: v for k, v in params.items() if k not in valid_names}
        if unknown:
            kept = {k: v for k, v in params.items() if k in valid_names}
            _log.warning(
                "Strategy component %s: stripping unknown params %s "
                "(valid: %s). Keeping: %s.",
                type_name, unknown, sorted(valid_names), kept,
            )
            params = kept

    try:
        component = cls(**params)
        component._builder_used_defaults = False
        return component
    except TypeError as exc:
        # Remaining init failures — fall back to defaults
        valid = [f.name for f in dataclasses.fields(cls) if f.name != "name"] if dataclasses.is_dataclass(cls) else []
        _log.warning(
            "Strategy component %s(%s) failed: %s. Valid params: %s. Using defaults.",
            type_name, params, exc, valid,
        )
        component = cls()
        component._builder_used_defaults = True
        component._builder_rejected_params = params
        return component


def build_sizer(config: dict[str, Any] | None) -> PositionSizer | None:
    """Build a single sizer from config. Public for runtime override use."""
    return _build_component(_SIZERS, config)


def build_tpsl(config: dict[str, Any] | None) -> TPSLPlacer | None:
    """Build a single TP/SL placer from config. Public for runtime override use."""
    return _build_component(_TPSL, config)


def build_exit_rule(config: dict[str, Any] | None) -> ExitRule | None:
    """Build a single exit rule from config. Public for runtime override use."""
    return _build_component(_EXITS, config)


def available_components() -> dict[str, Any]:
    """Return a catalog of all available strategy components with their param names."""
    import dataclasses

    def _params_for(cls: type) -> dict[str, str]:
        if dataclasses.is_dataclass(cls):
            return {
                f.name: type(f.default).__name__ if f.default is not dataclasses.MISSING else f.type.__name__ if isinstance(f.type, type) else str(f.type)
                for f in dataclasses.fields(cls)
                if f.name != "name"
            }
        return {}

    def _registry_with_params(registry: dict[str, type]) -> dict[str, dict[str, str]]:
        return {name: _params_for(cls) for name, cls in sorted(registry.items())}

    return {
        "sizing": _registry_with_params(_SIZERS),
        "tpsl": _registry_with_params(_TPSL),
        "entry_filters": _registry_with_params(_FILTERS),
        "exit_rules": _registry_with_params(_EXITS),
    }


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
