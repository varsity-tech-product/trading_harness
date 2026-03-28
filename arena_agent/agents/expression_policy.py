"""Expression-based policy — agent-defined signal logic using TA-Lib indicators.

The setup agent defines entry/exit conditions as Python expressions:

    entry_long  = "rsi_14 < 30 and close > sma_50"
    entry_short = "rsi_14 > 70 and close < sma_50"
    exit        = "rsi_14 > 50"

Each tick, expressions are evaluated against a namespace built from
``signal_state.values`` (pre-computed TA-Lib indicators) plus market
data (close, high, low, open, volume).

Safety: expressions are validated via ``ast.parse`` — only comparisons,
boolean ops, arithmetic, numbers, and variable names are allowed.
No function calls, imports, attribute access, or assignments.
"""

from __future__ import annotations

import ast
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from arena_agent.core.models import AgentState, TransitionEvent
from arena_agent.interfaces.action_schema import Action, ActionType
from arena_agent.interfaces.policy_interface import Policy

logger = logging.getLogger("arena_agent.expression_policy")

# AST node types that are safe in expressions.
_SAFE_NODES = (
    ast.Expression,
    ast.BoolOp, ast.And, ast.Or,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.FloorDiv,
    ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Constant,
    ast.Name, ast.Load,
    # Python 3.12+ uses ast.NameConstant for True/False/None in some cases
)


def _validate_expression(expr: str) -> str | None:
    """Validate an expression string is safe to eval.

    Returns None if safe, or an error message if unsafe.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        return f"syntax error: {exc}"

    for node in ast.walk(tree):
        if not isinstance(node, _SAFE_NODES):
            return f"unsafe node: {type(node).__name__} (only comparisons, boolean ops, arithmetic, numbers, and variable names are allowed)"
    return None


def _build_namespace(state: AgentState) -> dict[str, Any]:
    """Build the expression evaluation namespace from state.

    Includes all indicator values from signal_state plus market data.
    Multi-output indicators (e.g. MACD, BBANDS) are flattened:
      macd_12_26_9 = {"macd": 1.5, "signal": 1.2, "hist": 0.3}
      → macd_12_26_9_macd = 1.5, macd_12_26_9_signal = 1.2, macd_12_26_9_hist = 0.3
      → also: macd_macd = 1.5, macd_signal = 1.2, macd_hist = 0.3 (short aliases)
    """
    ns: dict[str, Any] = {}

    # Indicator values
    for key, value in state.signal_state.values.items():
        if isinstance(value, (int, float)):
            ns[key] = float(value)
        elif isinstance(value, dict):
            # Multi-output indicator — flatten with full key and short alias
            indicator_base = key.split("_")[0]  # e.g. "macd" from "macd_12_26_9"
            for subkey, subval in value.items():
                if isinstance(subval, (int, float)):
                    ns[f"{key}_{subkey}"] = float(subval)  # macd_12_26_9_hist
                    ns[f"{indicator_base}_{subkey}"] = float(subval)  # macd_hist

    # Market data
    market = state.market
    ns["close"] = market.last_price
    if hasattr(market, "recent_candles") and market.recent_candles:
        last_candle = market.recent_candles[-1]
        ns["high"] = getattr(last_candle, "high", market.last_price)
        ns["low"] = getattr(last_candle, "low", market.last_price)
        ns["open"] = getattr(last_candle, "open", market.last_price)
        ns["volume"] = getattr(last_candle, "volume", 0)
    else:
        ns["high"] = market.last_price
        ns["low"] = market.last_price
        ns["open"] = market.last_price
        ns["volume"] = 0

    return ns


def _safe_eval(expr: str, namespace: dict[str, Any]) -> bool:
    """Evaluate a validated expression string in a restricted namespace.

    Returns False on any error.
    """
    try:
        result = eval(expr, {"__builtins__": {}}, namespace)  # noqa: S307
        return bool(result)
    except Exception:
        return False


@dataclass
class ExpressionPolicy(Policy):
    """Policy that evaluates agent-defined expressions against indicator values."""

    entry_long: str = "False"
    entry_short: str = "False"
    exit_expr: str = "False"
    reentry_cooldown_seconds: float = 300.0
    name: str = "expression"

    _validation_errors: dict[str, str] = field(init=False, default_factory=dict)
    _logger: logging.Logger = field(init=False, repr=False)
    _last_close_time: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self._logger = logging.getLogger("arena_agent.expression_policy")
        self._validation_errors = {}
        self._last_close_time = 0.0

        # Validate all expressions at construction time
        for label, expr in [
            ("entry_long", self.entry_long),
            ("entry_short", self.entry_short),
            ("exit", self.exit_expr),
        ]:
            error = _validate_expression(expr)
            if error:
                self._validation_errors[label] = error
                self._logger.warning("Expression '%s' invalid: %s — will HOLD", label, error)
            else:
                self._logger.info("Expression '%s' validated: %s", label, expr)

    def reset(self) -> None:
        pass

    def update(self, memory: Sequence[TransitionEvent]) -> None:
        pass

    def decide(self, state: AgentState) -> Action:
        # If warmup not complete, hold
        if not state.signal_state.warmup_complete:
            return Action.hold(reason="indicator_warmup")

        # If any expression is invalid, hold
        if self._validation_errors:
            return Action.hold(
                reason=f"expression_errors: {self._validation_errors}",
                error=str(self._validation_errors),
            )

        ns = _build_namespace(state)
        has_position = state.position is not None

        # Log namespace keys on first call for debugging
        if not hasattr(self, "_ns_logged"):
            self._logger.info(
                "Expression namespace keys: %s",
                sorted(ns.keys()),
            )
            self._ns_logged = True

        if has_position:
            # Check exit condition
            if _safe_eval(self.exit_expr, ns):
                self._last_close_time = time.time()
                return Action(
                    type=ActionType.CLOSE_POSITION,
                    metadata={"reason": f"exit expression: {self.exit_expr}"},
                )
            return Action.hold(reason="expression_no_exit_signal")
        else:
            # Reentry cooldown — suppress entry signals after a close
            if self.reentry_cooldown_seconds > 0 and self._last_close_time > 0:
                elapsed = time.time() - self._last_close_time
                if elapsed < self.reentry_cooldown_seconds:
                    remaining = self.reentry_cooldown_seconds - elapsed
                    return Action.hold(
                        reason=f"reentry_cooldown: {remaining:.0f}s remaining",
                    )

            # Check entry conditions
            if _safe_eval(self.entry_long, ns):
                return Action(
                    type=ActionType.OPEN_LONG,
                    metadata={"reason": f"entry_long expression: {self.entry_long}"},
                )
            if _safe_eval(self.entry_short, ns):
                return Action(
                    type=ActionType.OPEN_SHORT,
                    metadata={"reason": f"entry_short expression: {self.entry_short}"},
                )
            return Action.hold(reason="expression_no_entry_signal")
