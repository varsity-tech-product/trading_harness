"""Risk-aware action executor for Arena runtime actions."""

from __future__ import annotations

import math
import time
from typing import Any

from arena_agent.core.environment_adapter import EnvironmentAdapter
from arena_agent.core.models import AgentState, ExecutionResult, RiskLimits
from arena_agent.interfaces.action_schema import Action, ActionType
from arena_agent.interfaces.action_validator import validate_action


class OrderExecutor:
    def __init__(
        self,
        adapter: EnvironmentAdapter,
        competition_id: int,
        risk_limits: RiskLimits,
        dry_run: bool = False,
    ) -> None:
        self.adapter = adapter
        self.competition_id = competition_id
        self.risk_limits = risk_limits
        self.dry_run = dry_run
        self._last_trade_time = 0.0

    def execute(self, action: Action, state: AgentState) -> ExecutionResult:
        validation_error = self._validate(action, state)
        if validation_error is not None:
            return self._result(action, False, False, validation_error)

        if action.type == ActionType.HOLD:
            return self._result(action, True, False, "hold")

        if action.type in {ActionType.OPEN_LONG, ActionType.OPEN_SHORT}:
            size = self._resolve_size(action, state)
            take_profit = self._rounded_price(action.take_profit)
            stop_loss = self._rounded_price(action.stop_loss)
            payload = {
                "direction": action.direction,
                "size": size,
                "take_profit": take_profit,
                "stop_loss": stop_loss,
            }
            if self.dry_run:
                self._last_trade_time = time.time()
                return self._result(action, True, False, "dry-run open", payload=payload, order_size=size)

            try:
                response = self.adapter.trade_open(
                    self.competition_id,
                    action.direction or "",
                    size,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                )
            except Exception as exc:
                return self._result(action, False, False, f"trade_open failed: {exc}", order_size=size, take_profit=take_profit, stop_loss=stop_loss)
            self._last_trade_time = time.time()
            return self._result(
                action,
                True,
                True,
                "opened position",
                payload=response,
                realized_pnl=_extract_float(response, "pnl", "realizedPnl", "realized_pnl", "totalRealizedPnl"),
                fee=_extract_float(response, "fee", "totalFee", "totalCommission", default=0.0),
                order_size=size,
                take_profit=take_profit,
                stop_loss=stop_loss,
            )

        if action.type == ActionType.CLOSE_POSITION:
            if self.dry_run:
                self._last_trade_time = time.time()
                return self._result(action, True, False, "dry-run close")

            try:
                response = self.adapter.trade_close(self.competition_id)
            except Exception as exc:
                return self._result(action, False, False, f"trade_close failed: {exc}")
            self._last_trade_time = time.time()
            return self._result(
                action,
                True,
                True,
                "closed position",
                payload=response,
                realized_pnl=_extract_float(response, "pnl", "realizedPnl", "realized_pnl", "totalRealizedPnl"),
                fee=_extract_float(response, "fee", "totalFee", "totalCommission", default=0.0),
            )

        if action.type == ActionType.UPDATE_TPSL:
            take_profit = self._rounded_price(action.take_profit)
            stop_loss = self._rounded_price(action.stop_loss)
            if self.dry_run:
                return self._result(
                    action,
                    True,
                    False,
                    "dry-run update tpsl",
                    order_size=state.position.size if state.position else None,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                )

            try:
                response = self.adapter.trade_update_tpsl(
                    self.competition_id,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                )
            except Exception as exc:
                return self._result(
                    action,
                    False,
                    False,
                    f"trade_update_tpsl failed: {exc}",
                    order_size=state.position.size if state.position else None,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                )
            return self._result(
                action,
                True,
                True,
                "updated tpsl",
                payload=response,
                order_size=state.position.size if state.position else None,
                take_profit=take_profit,
                stop_loss=stop_loss,
            )

        return self._result(action, False, False, f"unsupported action type: {action.type}")

    def _validate(self, action: Action, state: AgentState) -> str | None:
        try:
            validate_action(action)
        except ValueError as exc:
            return f"invalid action: {exc}"
        if action.type == ActionType.OPEN_LONG and not self.risk_limits.allow_long:
            return "long positions are disabled"
        if action.type == ActionType.OPEN_SHORT and not self.risk_limits.allow_short:
            return "short positions are disabled"
        if action.type in {ActionType.OPEN_LONG, ActionType.OPEN_SHORT} and state.position is not None:
            return "cannot open a new position while another is active"
        if action.type == ActionType.CLOSE_POSITION and state.position is None:
            return "no open position to close"
        if action.type == ActionType.UPDATE_TPSL and state.position is None:
            return "cannot update TP/SL without an open position"
        # Rate-limit ALL trade actions (open AND close) to prevent rapid-fire
        # trade loops (e.g. close→open→close burning through the trade budget).
        if action.type in {ActionType.OPEN_LONG, ActionType.OPEN_SHORT, ActionType.CLOSE_POSITION}:
            if self.risk_limits.min_seconds_between_trades > 0:
                elapsed = time.time() - self._last_trade_time
                if elapsed < self.risk_limits.min_seconds_between_trades:
                    return "trade cooldown active"
        if action.type in {ActionType.OPEN_LONG, ActionType.OPEN_SHORT}:
            if action.size is None and not self._can_auto_size(state):
                return "market price unavailable for sizing"
            if state.competition.is_close_only:
                return "competition is in close-only mode"
            if state.competition.max_trades_remaining is not None and state.competition.max_trades_remaining <= 0:
                return "trade limit reached"
        return None

    def _resolve_size(self, action: Action, state: AgentState) -> float:
        if action.size is not None:
            size = float(action.size)
        else:
            buying_power = max(state.account.balance, state.account.equity)
            raw_size = buying_power * self.risk_limits.max_position_size_pct / state.market.last_price
            size = raw_size

        if self.risk_limits.max_absolute_size is not None:
            size = min(size, self.risk_limits.max_absolute_size)

        # Cap size so notional value never exceeds available balance * max_position_size_pct.
        # This prevents oversized orders regardless of what the LLM or strategy layer produces.
        if state.market.last_price > 0:
            buying_power = max(state.account.balance, state.account.equity)
            max_notional = buying_power * self.risk_limits.max_position_size_pct
            max_size = max_notional / state.market.last_price
            size = min(size, max_size)

        precision = 10 ** self.risk_limits.quantity_precision
        rounded = math.floor(size * precision) / precision
        return max(self.risk_limits.min_size, rounded)

    def _rounded_price(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), self.risk_limits.price_precision)

    def _can_auto_size(self, state: AgentState) -> bool:
        price = state.market.last_price
        return math.isfinite(price) and price > 0

    def _result(
        self,
        action: Action,
        accepted: bool,
        executed: bool,
        message: str,
        payload: dict[str, Any] | None = None,
        realized_pnl: float = 0.0,
        fee: float = 0.0,
        order_size: float | None = None,
        take_profit: float | None = None,
        stop_loss: float | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            action_type=action.type.value,
            accepted=accepted,
            executed=executed,
            message=message,
            timestamp=time.time(),
            realized_pnl=realized_pnl,
            fee=fee,
            order_size=order_size,
            take_profit=take_profit,
            stop_loss=stop_loss,
            venue_response=payload or {},
        )


def _extract_float(data: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in data and data[key] is not None:
            try:
                return float(data[key])
            except (TypeError, ValueError):
                return default
    # Check nested fills for commission aggregation (common venue response format)
    fills = data.get("fills") or data.get("orderFills")
    if isinstance(fills, list):
        total = 0.0
        found = False
        for fill in fills:
            if isinstance(fill, dict):
                for key in ("commission", "fee"):
                    val = fill.get(key)
                    if val is not None:
                        try:
                            total += abs(float(val))
                            found = True
                        except (TypeError, ValueError):
                            pass
        if found:
            return total
    return default
