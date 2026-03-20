"""Take-profit / stop-loss placement strategies."""

from __future__ import annotations

from dataclasses import dataclass

from arena_agent.core.models import AgentState
from arena_agent.interfaces.action_schema import Action, ActionType
from arena_agent.strategy.layer import get_indicator


@dataclass
class FixedTPSL:
    """Set TP/SL as a fixed percentage from entry price.

    Long:  TP = price * (1 + tp_pct),  SL = price * (1 - sl_pct)
    Short: TP = price * (1 - tp_pct),  SL = price * (1 + sl_pct)
    """

    tp_pct: float = 0.005
    sl_pct: float = 0.003
    name: str = "fixed_pct"

    def compute(self, action: Action, state: AgentState) -> tuple[float | None, float | None]:
        price = state.market.last_price
        if price <= 0:
            return None, None

        if action.type == ActionType.OPEN_LONG:
            return price * (1 + self.tp_pct), price * (1 - self.sl_pct)
        if action.type == ActionType.OPEN_SHORT:
            return price * (1 - self.tp_pct), price * (1 + self.sl_pct)
        return None, None


@dataclass
class ATRBasedTPSL:
    """Set TP/SL using ATR multiples from entry price.

    Long:  TP = price + ATR * tp_mult,  SL = price - ATR * sl_mult
    Short: TP = price - ATR * tp_mult,  SL = price + ATR * sl_mult

    Requires ATR in the indicator set.
    ``min_sl_pct`` enforces a minimum SL distance as a fraction of price
    to avoid noise-level stops on short timeframes.
    """

    atr_tp_mult: float = 2.0
    atr_sl_mult: float = 1.5
    atr_period: int | None = None
    min_sl_pct: float = 0.003
    name: str = "atr_multiple"

    def compute(self, action: Action, state: AgentState) -> tuple[float | None, float | None]:
        atr = get_indicator(state, "atr", self.atr_period)
        if atr is None or atr <= 0:
            return None, None

        price = state.market.last_price
        sl_offset = atr * self.atr_sl_mult
        tp_offset = atr * self.atr_tp_mult

        # Enforce minimum SL distance to avoid noise-level stops
        min_distance = price * self.min_sl_pct
        if sl_offset < min_distance:
            # Scale TP proportionally to maintain the TP/SL ratio
            ratio = min_distance / sl_offset if sl_offset > 0 else 1.0
            sl_offset = min_distance
            tp_offset = tp_offset * ratio

        if action.type == ActionType.OPEN_LONG:
            return price + tp_offset, price - sl_offset
        if action.type == ActionType.OPEN_SHORT:
            return price - tp_offset, price + sl_offset
        return None, None


@dataclass
class RMultipleTPSL:
    """Set SL based on ATR, then TP as a reward:risk multiple of SL distance.

    SL distance = ATR * sl_atr_mult
    TP distance = SL distance * reward_risk_ratio

    Requires ATR in the indicator set.
    ``min_sl_pct`` enforces a minimum SL distance as a fraction of price.
    """

    sl_atr_mult: float = 1.5
    reward_risk_ratio: float = 2.0
    atr_period: int | None = None
    min_sl_pct: float = 0.003
    name: str = "r_multiple"

    def compute(self, action: Action, state: AgentState) -> tuple[float | None, float | None]:
        atr = get_indicator(state, "atr", self.atr_period)
        if atr is None or atr <= 0:
            return None, None

        price = state.market.last_price
        sl_distance = atr * self.sl_atr_mult

        # Enforce minimum SL distance
        min_distance = price * self.min_sl_pct
        sl_distance = max(sl_distance, min_distance)

        tp_distance = sl_distance * self.reward_risk_ratio

        if action.type == ActionType.OPEN_LONG:
            return price + tp_distance, price - sl_distance
        if action.type == ActionType.OPEN_SHORT:
            return price - tp_distance, price + sl_distance
        return None, None
