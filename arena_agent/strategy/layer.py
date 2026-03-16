"""StrategyLayer — composable pipeline between policy decision and executor."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from arena_agent.core.models import AgentState, RiskLimits
from arena_agent.interfaces.action_schema import Action, ActionType


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

@runtime_checkable
class PositionSizer(Protocol):
    name: str

    def compute(self, action: Action, state: AgentState) -> float | None:
        """Return a position size, or None to keep the action's original size."""
        ...


@runtime_checkable
class TPSLPlacer(Protocol):
    name: str

    def compute(self, action: Action, state: AgentState) -> tuple[float | None, float | None]:
        """Return (take_profit, stop_loss). None means keep the action's original value."""
        ...


@runtime_checkable
class EntryFilter(Protocol):
    name: str

    def allow(self, action: Action, state: AgentState) -> tuple[bool, str]:
        """Return (allowed, reason). If not allowed, the action becomes HOLD."""
        ...


@runtime_checkable
class ExitRule(Protocol):
    name: str

    def check(self, state: AgentState) -> Action | None:
        """Return an action (CLOSE_POSITION or UPDATE_TPSL) to override HOLD, or None."""
        ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_indicator(state: AgentState, indicator: str, period: int | None = None) -> float | None:
    """Look up a scalar indicator value from signal_state.values.

    Tries exact key (e.g. ``atr_14``), then prefix match.
    Returns None if not found or not a number.
    """
    values = state.signal_state.values

    if period is not None:
        key = f"{indicator.lower()}_{period}"
        val = values.get(key)
        if isinstance(val, (int, float)):
            return float(val)

    prefix = indicator.lower()
    for key, val in values.items():
        if key.startswith(prefix) and isinstance(val, (int, float)):
            return float(val)

    return None


# ---------------------------------------------------------------------------
# StrategyLayer
# ---------------------------------------------------------------------------

class StrategyLayer:
    """Composable strategy pipeline that refines raw policy actions.

    Runs between ``policy.decide(state)`` and ``executor.execute(action, state)``.
    """

    def __init__(
        self,
        sizer: PositionSizer | None = None,
        tpsl_placer: TPSLPlacer | None = None,
        entry_filters: list[EntryFilter] | None = None,
        exit_rules: list[ExitRule] | None = None,
        risk_limits: RiskLimits | None = None,
    ) -> None:
        self.sizer = sizer
        self.tpsl_placer = tpsl_placer
        self.entry_filters = list(entry_filters or [])
        self.exit_rules = list(exit_rules or [])
        self.risk_limits = risk_limits

    def refine(self, action: Action, state: AgentState) -> Action:
        """Transform a raw policy action into a fully-specified executable action.

        Pipeline:
          1. If position is open and agent says HOLD → check exit rules
          2. If opening a position → apply entry filters, sizing, TP/SL

        The agent can include a ``"strategy"`` key in ``action.metadata`` to
        override the YAML defaults for this specific action::

            {
                "strategy": {
                    "sizing": {"type": "risk_per_trade", "max_risk_pct": 0.015},
                    "tpsl": {"type": "r_multiple", "reward_risk_ratio": 3.0},
                    "exit_rules": [{"type": "trailing_stop", "atr_multiplier": 3.0}]
                }
            }

        If a field is absent the YAML default is used.  If ``"strategy": "none"``
        the strategy layer is bypassed entirely for this action.
        """
        meta = dict(action.metadata)
        agent_overrides = meta.pop("strategy", None)

        # Agent can disable strategy for this action
        if agent_overrides == "none":
            meta["strategy_override"] = "none"
            return Action(
                type=action.type,
                size=action.size,
                take_profit=action.take_profit,
                stop_loss=action.stop_loss,
                metadata=meta,
            )

        # Resolve per-action components (agent overrides > YAML defaults)
        sizer, tpsl_placer, exit_rules = self._resolve_components(agent_overrides)

        # --- Exit rules (fire when agent HOLDs with an open position) ---
        if state.position is not None and action.is_hold:
            for rule in exit_rules:
                exit_action = rule.check(state)
                if exit_action is not None:
                    exit_meta = dict(exit_action.metadata)
                    exit_meta["strategy_exit_rule"] = rule.name
                    return Action(
                        type=exit_action.type,
                        size=exit_action.size,
                        take_profit=exit_action.take_profit,
                        stop_loss=exit_action.stop_loss,
                        metadata=exit_meta,
                    )

        # --- Only refine OPEN actions ---
        if action.type not in (ActionType.OPEN_LONG, ActionType.OPEN_SHORT):
            return action

        # --- Entry filters ---
        for entry_filter in self.entry_filters:
            allowed, reason = entry_filter.allow(action, state)
            if not allowed:
                return Action.hold(reason=f"strategy_filter:{reason}")

        # --- Position sizing ---
        size = action.size
        if sizer is not None:
            computed_size = sizer.compute(action, state)
            if computed_size is not None:
                meta["strategy_sizing"] = sizer.name
                meta["strategy_original_size"] = size
                size = computed_size

        # Apply risk limits cap
        if self.risk_limits is not None and size is not None:
            if self.risk_limits.max_absolute_size is not None:
                size = min(size, self.risk_limits.max_absolute_size)
            size = max(self.risk_limits.min_size, size)

        # --- TP/SL placement ---
        tp = action.take_profit
        sl = action.stop_loss
        if tpsl_placer is not None:
            computed_tp, computed_sl = tpsl_placer.compute(action, state)
            if computed_tp is not None:
                tp = computed_tp
            if computed_sl is not None:
                sl = computed_sl
            meta["strategy_tpsl"] = tpsl_placer.name

        return Action(
            type=action.type,
            size=size,
            take_profit=tp,
            stop_loss=sl,
            metadata=meta,
        )

    def _resolve_components(
        self,
        overrides: dict[str, Any] | None,
    ) -> tuple[PositionSizer | None, TPSLPlacer | None, list[ExitRule]]:
        """Merge agent per-action overrides with YAML defaults.

        Imports the builder lazily to avoid circular dependency.
        """
        if not overrides or not isinstance(overrides, dict):
            return self.sizer, self.tpsl_placer, self.exit_rules

        from arena_agent.strategy.builder import build_sizer, build_tpsl, build_exit_rule

        sizer = self.sizer
        if "sizing" in overrides:
            built = build_sizer(overrides["sizing"])
            if built is not None:
                sizer = built

        tpsl = self.tpsl_placer
        if "tpsl" in overrides:
            built = build_tpsl(overrides["tpsl"])
            if built is not None:
                tpsl = built

        exits = list(self.exit_rules)
        if "exit_rules" in overrides:
            override_exits = [
                build_exit_rule(e) for e in overrides["exit_rules"]
            ]
            override_exits = [e for e in override_exits if e is not None]
            if override_exits:
                exits = override_exits  # replace, not merge

        return sizer, tpsl, exits
