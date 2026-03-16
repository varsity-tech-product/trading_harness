"""Entry filters and exit rules."""

from __future__ import annotations

from dataclasses import dataclass

from arena_agent.core.models import AgentState
from arena_agent.interfaces.action_schema import Action, ActionType
from arena_agent.strategy.layer import get_indicator


# ---------------------------------------------------------------------------
# Entry filters — gate whether an open action should proceed
# ---------------------------------------------------------------------------

@dataclass
class VolatilityGate:
    """Only allow entries when volatility is within a target range.

    Requires a volatility indicator in the signal state.
    """

    min_volatility: float = 0.0
    max_volatility: float = 1.0
    name: str = "volatility_gate"

    def allow(self, action: Action, state: AgentState) -> tuple[bool, str]:
        vol = get_indicator(state, "volatility")
        if vol is None:
            return True, ""  # Pass through if no data
        if vol < self.min_volatility:
            return False, f"volatility {vol:.6f} below min {self.min_volatility}"
        if vol > self.max_volatility:
            return False, f"volatility {vol:.6f} above max {self.max_volatility}"
        return True, ""


@dataclass
class TradeBudgetFilter:
    """Block entries if remaining trade count is too low (save trades for later).

    Uses ``state.competition.max_trades_remaining``.
    """

    min_remaining_trades: int = 5
    name: str = "trade_budget"

    def allow(self, action: Action, state: AgentState) -> tuple[bool, str]:
        remaining = state.competition.max_trades_remaining
        if remaining is not None and remaining <= self.min_remaining_trades:
            return False, f"only {remaining} trades remaining, budget requires {self.min_remaining_trades}"
        return True, ""


# ---------------------------------------------------------------------------
# Exit rules — override HOLD when the position should be managed
# ---------------------------------------------------------------------------

@dataclass
class TrailingStop:
    """Trail the stop-loss upward (long) or downward (short) as price moves favorably.

    Each tick computes ``new_sl = price ∓ ATR * atr_multiplier``.
    Only moves the stop in the favorable direction; never widens it.

    Returns UPDATE_TPSL when the SL should move, None otherwise.
    Requires ATR in the indicator set.
    """

    atr_multiplier: float = 2.0
    atr_period: int | None = None
    price_precision: int = 2
    name: str = "trailing_stop"

    def check(self, state: AgentState) -> Action | None:
        pos = state.position
        if pos is None:
            return None

        atr = get_indicator(state, "atr", self.atr_period)
        if atr is None or atr <= 0:
            return None

        price = state.market.last_price
        trail = atr * self.atr_multiplier

        if pos.direction == "long":
            new_sl = round(price - trail, self.price_precision)
            # Only move SL up, never down
            if pos.stop_loss is not None and new_sl <= pos.stop_loss:
                return None
            return Action(
                type=ActionType.UPDATE_TPSL,
                take_profit=pos.take_profit,
                stop_loss=new_sl,
                metadata={
                    "strategy_exit": "trailing_stop",
                    "previous_sl": pos.stop_loss,
                    "new_sl": new_sl,
                    "atr": atr,
                },
            )

        if pos.direction == "short":
            new_sl = round(price + trail, self.price_precision)
            # Only move SL down, never up
            if pos.stop_loss is not None and new_sl >= pos.stop_loss:
                return None
            return Action(
                type=ActionType.UPDATE_TPSL,
                take_profit=pos.take_profit,
                stop_loss=new_sl,
                metadata={
                    "strategy_exit": "trailing_stop",
                    "previous_sl": pos.stop_loss,
                    "new_sl": new_sl,
                    "atr": atr,
                },
            )

        return None


@dataclass
class TimeExit:
    """Force close after holding for longer than ``max_hold_seconds``.

    Uses ``state.position.metadata["openTime"]`` (milliseconds) to compute age.
    """

    max_hold_seconds: float = 600.0
    name: str = "time_exit"

    def check(self, state: AgentState) -> Action | None:
        pos = state.position
        if pos is None or pos.metadata is None:
            return None

        open_time = pos.metadata.get("openTime")
        if open_time is None:
            return None

        try:
            age = state.timestamp - (float(open_time) / 1000.0)
        except (TypeError, ValueError):
            return None

        if age < self.max_hold_seconds:
            return None

        return Action(
            type=ActionType.CLOSE_POSITION,
            metadata={
                "strategy_exit": "time_exit",
                "hold_seconds": round(age, 1),
                "max_hold_seconds": self.max_hold_seconds,
            },
        )


@dataclass
class DrawdownExit:
    """Force close if unrealized loss exceeds a fraction of equity.

    ``loss_pct = |unrealized_pnl| / equity``
    """

    max_drawdown_pct: float = 0.02
    name: str = "drawdown_exit"

    def check(self, state: AgentState) -> Action | None:
        pos = state.position
        if pos is None:
            return None

        if pos.unrealized_pnl >= 0:
            return None

        equity = state.account.equity
        if equity <= 0:
            return None

        loss_pct = abs(pos.unrealized_pnl) / equity
        if loss_pct < self.max_drawdown_pct:
            return None

        return Action(
            type=ActionType.CLOSE_POSITION,
            metadata={
                "strategy_exit": "drawdown_exit",
                "loss_pct": round(loss_pct, 6),
                "max_drawdown_pct": self.max_drawdown_pct,
                "unrealized_pnl": pos.unrealized_pnl,
            },
        )
