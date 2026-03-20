"""Runtime safety checks for state consistency and drift detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arena_agent.core.models import AgentState


@dataclass(frozen=True, slots=True)
class StateGuardResult:
    ok: bool
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def evaluate_state_guard(
    state: AgentState,
    *,
    max_feature_age_seconds: float | None = None,
    require_feature_timestamp_match: bool = True,
) -> StateGuardResult:
    signal_state = state.signal_state
    if not signal_state.requested:
        return StateGuardResult(ok=True)

    # Block trading decisions during indicator warmup to prevent
    # the LLM from acting on incomplete/garbage indicator values.
    if not signal_state.warmup_complete:
        return StateGuardResult(
            ok=False,
            reason="warmup_incomplete",
            details={
                "requested_features": len(signal_state.requested),
                "warmup_complete": False,
            },
        )

    metadata = signal_state.metadata or {}
    raw_feature_timestamp = metadata.get("timestamp")
    if raw_feature_timestamp is None:
        return StateGuardResult(
            ok=False,
            reason="missing_feature_timestamp",
            details={"requested_features": len(signal_state.requested)},
        )

    feature_timestamp_seconds = _normalize_timestamp_seconds(raw_feature_timestamp)
    latest_candle_close_seconds = None
    if state.market.recent_candles:
        latest_candle_close_seconds = state.market.recent_candles[-1].close_time / 1000.0

    if require_feature_timestamp_match and latest_candle_close_seconds is not None:
        if abs(feature_timestamp_seconds - latest_candle_close_seconds) > 1e-6:
            return StateGuardResult(
                ok=False,
                reason="feature_timestamp_mismatch",
                details={
                    "feature_timestamp_seconds": feature_timestamp_seconds,
                    "latest_candle_close_seconds": latest_candle_close_seconds,
                },
            )

    feature_age_seconds = max(0.0, state.timestamp - feature_timestamp_seconds)
    if max_feature_age_seconds is not None and feature_age_seconds > max_feature_age_seconds:
        return StateGuardResult(
            ok=False,
            reason="feature_timestamp_stale",
            details={
                "feature_age_seconds": feature_age_seconds,
                "max_feature_age_seconds": max_feature_age_seconds,
            },
        )

    return StateGuardResult(
        ok=True,
        details={
            "feature_timestamp_seconds": feature_timestamp_seconds,
            "feature_age_seconds": feature_age_seconds,
        },
    )


def detect_position_drift(previous_state: AgentState | None, current_state: AgentState) -> str | None:
    if previous_state is None:
        return None

    previous_position = _position_signature(previous_state.position)
    current_position = _position_signature(current_state.position)
    previous_trade_count = previous_state.account.trade_count
    current_trade_count = current_state.account.trade_count

    if previous_position == current_position and previous_trade_count == current_trade_count:
        return None

    return (
        "exchange state drift detected: "
        f"position {previous_position} -> {current_position}, "
        f"trade_count {previous_trade_count} -> {current_trade_count}"
    )


def _position_signature(position: Any) -> tuple[Any, Any, Any]:
    if position is None:
        return ("flat", None, None)
    return (
        getattr(position, "direction", None),
        getattr(position, "size", None),
        getattr(position, "entry_price", None),
    )


def _normalize_timestamp_seconds(value: Any) -> float:
    numeric = float(value)
    return numeric / 1000.0 if numeric > 10_000_000_000 else numeric
