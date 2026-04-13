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


def _extract_variables(expr: str) -> set[str]:
    """Extract all variable names referenced in an expression."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return set()
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


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
    exit_long_expr: str = ""
    exit_short_expr: str = ""
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
            ("exit_long", self.exit_long_expr),
            ("exit_short", self.exit_short_expr),
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

        # On first call, validate expression variables against actual namespace
        if not hasattr(self, "_ns_validated"):
            self._ns_validated = True
            self._logger.info(
                "Expression namespace keys: %s",
                sorted(ns.keys()),
            )
            ns_keys = set(ns.keys())
            for label, expr in [
                ("entry_long", self.entry_long),
                ("entry_short", self.entry_short),
                ("exit", self.exit_expr),
                ("exit_long", self.exit_long_expr),
                ("exit_short", self.exit_short_expr),
            ]:
                vars_used = _extract_variables(expr)
                undefined = vars_used - ns_keys
                if undefined:
                    available = sorted(ns_keys)
                    error = (
                        f"undefined variables: {sorted(undefined)}. "
                        f"Available: {available}. "
                        f"Fix: use the correct indicator key from the available list."
                    )
                    self._validation_errors[label] = error
                    self._logger.warning(
                        "Expression '%s' references undefined variables %s — will HOLD. Available: %s",
                        label, sorted(undefined), available,
                    )
            # Check exit/entry overlap — if entry and exit both fire on the SAME
            # namespace values, positions will close immediately after opening.
            if not self._validation_errors:
                long_exit = self.exit_long_expr if self.exit_long_expr.strip() else self.exit_expr
                short_exit = self.exit_short_expr if self.exit_short_expr.strip() else self.exit_expr
                if _safe_eval(self.entry_short, ns) and _safe_eval(short_exit, ns):
                    self._validation_errors["exit_overlap_short"] = (
                        f"exit_short '{short_exit}' is TRUE right now while entry_short '{self.entry_short}' is also TRUE. "
                        f"Short positions will close immediately after opening. "
                        f"Fix: exit threshold must be between entry_long and entry_short thresholds "
                        f"(e.g. if entry_short is rsi > 60, exit should be rsi < 50, not rsi > 50)."
                    )
                    self._logger.warning("Exit/entry_short overlap — both true at current values, shorts will close immediately")
                if _safe_eval(self.entry_long, ns) and _safe_eval(long_exit, ns):
                    self._validation_errors["exit_overlap_long"] = (
                        f"exit_long '{long_exit}' is TRUE right now while entry_long '{self.entry_long}' is also TRUE. "
                        f"Long positions will close immediately after opening. "
                        f"Fix: exit threshold must be between entry_long and entry_short thresholds."
                    )
                    self._logger.warning("Exit/entry_long overlap — both true at current values, longs will close immediately")

            if self._validation_errors:
                return Action.hold(
                    reason=f"expression_errors: {self._validation_errors}",
                    error=str(self._validation_errors),
                )

        if has_position:
            # Check exit condition
            active_exit_expr = self.exit_expr
            if state.position.direction == "long" and self.exit_long_expr.strip():
                active_exit_expr = self.exit_long_expr
            elif state.position.direction == "short" and self.exit_short_expr.strip():
                active_exit_expr = self.exit_short_expr
            if _safe_eval(active_exit_expr, ns):
                self._last_close_time = time.time()
                return Action(
                    type=ActionType.CLOSE_POSITION,
                    metadata={"reason": f"exit expression: {active_exit_expr}"},
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
