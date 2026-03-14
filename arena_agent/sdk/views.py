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
