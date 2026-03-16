"""Position sizing strategies."""

from __future__ import annotations

import math
from dataclasses import dataclass

from arena_agent.core.models import AgentState
from arena_agent.interfaces.action_schema import Action
from arena_agent.strategy.layer import get_indicator


@dataclass
class FixedFractionSizer:
    """Size as a fixed fraction of equity divided by price.

    ``size = equity * fraction / last_price``
    """

    fraction: float = 0.05
    name: str = "fixed_fraction"

    def compute(self, action: Action, state: AgentState) -> float | None:
        if state.market.last_price <= 0:
            return None
        equity = max(state.account.balance, state.account.equity)
        return equity * self.fraction / state.market.last_price


@dataclass
class VolatilityScaledSizer:
    """Scale position size inversely with volatility (ATR).

    ``size = (equity * target_risk_pct) / (ATR * atr_multiplier)``

    In high-volatility markets the position shrinks; in low-volatility markets it grows.
    Requires ATR in the indicator set.
    """

    target_risk_pct: float = 0.02
    atr_multiplier: float = 2.0
    atr_period: int | None = None
    name: str = "volatility_scaled"

    def compute(self, action: Action, state: AgentState) -> float | None:
        atr = get_indicator(state, "atr", self.atr_period)
        if atr is None or atr <= 0:
            return None
        equity = max(state.account.balance, state.account.equity)
        risk_amount = equity * self.target_risk_pct
        size = risk_amount / (atr * self.atr_multiplier)
        return size if size > 0 else None


@dataclass
class RiskPerTradeSizer:
    """Size so that max loss (at stop-loss) equals a fixed % of equity.

    ``size = (equity * max_risk_pct) / |entry_price - stop_loss|``

    If the action has no stop-loss, falls back to ATR-based SL estimate.
    Requires the action to have a stop_loss or ATR in the indicator set.
    """

    max_risk_pct: float = 0.01
    fallback_atr_multiplier: float = 1.5
    atr_period: int | None = None
    name: str = "risk_per_trade"

    def compute(self, action: Action, state: AgentState) -> float | None:
        price = state.market.last_price
        if price <= 0:
            return None

        equity = max(state.account.balance, state.account.equity)
        risk_amount = equity * self.max_risk_pct

        # Determine SL distance
        sl_distance: float | None = None
        if action.stop_loss is not None:
            sl_distance = abs(price - action.stop_loss)

        if sl_distance is None or sl_distance <= 0:
            atr = get_indicator(state, "atr", self.atr_period)
            if atr is not None and atr > 0:
                sl_distance = atr * self.fallback_atr_multiplier

        if sl_distance is None or sl_distance <= 0:
            return None

        size = risk_amount / sl_distance
        return size if size > 0 else None
