"""Minimal TAP request/response translation helpers."""

from __future__ import annotations

from typing import Any

from arena_agent.core.models import AgentState
from arena_agent.core.serialization import to_jsonable
from arena_agent.interfaces.action_schema import Action, ActionType
from arena_agent.interfaces.action_validator import validate_action


def build_decision_request(state: AgentState) -> dict[str, Any]:
    return {
        "timestamp": state.timestamp,
        "state": to_jsonable(state),
    }


def parse_decision_response(payload: dict[str, Any]) -> Action:
    if not isinstance(payload, dict):
        raise ValueError(f"TAP response must be an object, got: {payload!r}")

    action_payload = payload.get("action", payload)
    if not isinstance(action_payload, dict):
        raise ValueError(f"TAP action payload must be an object, got: {action_payload!r}")

    raw_type = action_payload.get("type", ActionType.HOLD.value)
    action_type = ActionType(str(raw_type).upper())

    take_profit = _parse_optional_float_field(action_payload, "tp", "take_profit")
    stop_loss = _parse_optional_float_field(action_payload, "sl", "stop_loss")
    size = _parse_optional_float_field(action_payload, "size")

    metadata = dict(action_payload.get("metadata", {}))
    if "reason" in action_payload and "reason" not in metadata:
        metadata["reason"] = str(action_payload["reason"])
    if "reason" in payload and "reason" not in metadata:
        metadata["reason"] = str(payload["reason"])
    if "analysis" in payload and "reason" not in metadata:
        metadata["reason"] = str(payload["analysis"])
    if "confidence" in action_payload and "confidence" not in metadata:
        metadata["confidence"] = _parse_optional_float_value(action_payload["confidence"], field_name="confidence")
    if "confidence" in payload and "confidence" not in metadata:
        metadata["confidence"] = _parse_optional_float_value(payload["confidence"], field_name="confidence")

    # Strategy overrides from agent (passed through to StrategyLayer)
    if "strategy" in action_payload and "strategy" not in metadata:
        metadata["strategy"] = action_payload["strategy"]

    action = Action(
        type=action_type,
        size=size,
        take_profit=take_profit,
        stop_loss=stop_loss,
        metadata=metadata,
    )
    return validate_action(action)


def _parse_optional_float_field(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in payload:
            return _parse_optional_float_value(payload[key], field_name=key)
    return None


def _parse_optional_float_value(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be numeric, got: {value!r}")
