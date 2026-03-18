"""Validation helpers for model-produced actions."""

from __future__ import annotations

import math

from arena_agent.interfaces.action_schema import Action, ActionType


def validate_action(action: Action) -> Action:
    _validate_numeric_field("size", action.size, allow_none=True, must_be_positive=action.is_open)
    _validate_numeric_field("take_profit", action.take_profit, allow_none=True, must_be_positive=True)
    _validate_numeric_field("stop_loss", action.stop_loss, allow_none=True, must_be_positive=True)

    if action.type == ActionType.HOLD and action.size is not None:
        raise ValueError("HOLD must not include size")
    # Agents often include size on CLOSE_POSITION — silently clear it.
    if action.type == ActionType.CLOSE_POSITION and action.size is not None:
        action = Action(
            type=action.type, size=None,
            take_profit=action.take_profit, stop_loss=action.stop_loss,
            metadata=action.metadata,
        )

    if action.type == ActionType.HOLD and (action.take_profit is not None or action.stop_loss is not None):
        raise ValueError("HOLD must not include TP/SL")

    if action.type == ActionType.CLOSE_POSITION and (action.take_profit is not None or action.stop_loss is not None):
        raise ValueError("CLOSE_POSITION must not include TP/SL")

    return action


def _validate_numeric_field(name: str, value: float | None, *, allow_none: bool, must_be_positive: bool) -> None:
    if value is None:
        if allow_none:
            return
        raise ValueError(f"{name} is required")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    if must_be_positive and float(value) <= 0:
        raise ValueError(f"{name} must be > 0")
