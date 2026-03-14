"""Minimal TAP request/response translation helpers."""

from __future__ import annotations

from typing import Any

from arena_agent.core.models import AgentState
from arena_agent.core.serialization import to_jsonable
from arena_agent.interfaces.action_schema import Action, ActionType


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
    action_type = ActionType(str(raw_type))

    take_profit = _optional_float(action_payload.get("tp", action_payload.get("take_profit")))
    stop_loss = _optional_float(action_payload.get("sl", action_payload.get("stop_loss")))
    size = _optional_float(action_payload.get("size"))

    metadata = dict(action_payload.get("metadata", {}))
    if "reason" in action_payload and "reason" not in metadata:
        metadata["reason"] = str(action_payload["reason"])
    if "reason" in payload and "reason" not in metadata:
        metadata["reason"] = str(payload["reason"])
    if "analysis" in payload and "reason" not in metadata:
        metadata["reason"] = str(payload["analysis"])

    return Action(
        type=action_type,
        size=size,
        take_profit=take_profit,
        stop_loss=stop_loss,
        metadata=metadata,
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
