"""Recursive attribute views for SDK responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArenaView:
    _data: dict[str, Any]

    def __getattr__(self, item: str) -> Any:
        try:
            return _to_view(self._data[item])
        except KeyError as exc:
            alias_value = _lookup_alias(self._data, item)
            if alias_value is not _MISSING:
                return _to_view(alias_value)
            raise AttributeError(item) from exc

    def to_dict(self) -> dict[str, Any]:
        return self._data


def _to_view(value: Any) -> Any:
    if isinstance(value, dict):
        return ArenaView(value)
    if isinstance(value, list):
        return [_to_view(item) for item in value]
    return value


def as_view(value: Any) -> Any:
    return _to_view(value)


_MISSING = object()


def _lookup_alias(data: dict[str, Any], item: str) -> Any:
    alias_map = {
        "price": ("market", "last_price"),
        "candles": ("market", "recent_candles"),
        "symbol": ("market", "symbol"),
        "features": ("signal_state", "values"),
        "pnl": ("account", "unrealized_pnl"),
        "equity": ("account", "equity"),
        "balance": ("account", "balance"),
        "remaining_trades": ("competition", "max_trades_remaining"),
        "trade_count": ("account", "trade_count"),
        "time_remaining": ("competition", "time_remaining_seconds"),
    }
    path = alias_map.get(item)
    if path is None:
        return _MISSING
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return _MISSING
        current = current[key]
    return current
