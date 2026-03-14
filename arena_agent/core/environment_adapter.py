"""Arena API adapter with validation, retries, and light rate limiting."""

from __future__ import annotations

import time
from typing import Any, Callable

import varsity_tools


Validator = Callable[[Any], bool]


class EnvironmentAdapter:
    def __init__(
        self,
        client: Any | None = None,
        retry_attempts: int = 3,
        retry_backoff_seconds: float = 0.5,
        min_call_spacing_seconds: float = 0.0,
    ) -> None:
        self.client = client or varsity_tools
        self.retry_attempts = max(1, retry_attempts)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.min_call_spacing_seconds = max(0.0, min_call_spacing_seconds)
        self._last_call_started_at: dict[str, float] = {}

    def get_symbols(self) -> list[dict[str, Any]]:
        return self._invoke("get_symbols", validator=lambda value: isinstance(value, list))

    def get_market_info(self, symbol: str) -> dict[str, Any]:
        return self._invoke("get_market_info", symbol, validator=_is_dict)

    def get_klines(self, symbol: str, interval: str, size: int) -> dict[str, Any]:
        return self._invoke("get_klines", symbol, interval, size=size, validator=_is_dict_or_list)

    def get_orderbook(self, symbol: str, depth: int) -> dict[str, Any]:
        return self._invoke("get_orderbook", symbol, depth=depth, validator=_is_dict)

    def get_live_account(self, competition_id: int) -> dict[str, Any]:
        return self._invoke("get_live_account", competition_id, validator=_is_dict)

    def get_live_position(self, competition_id: int) -> dict[str, Any] | None:
        return self._invoke(
            "get_live_position",
            competition_id,
            validator=lambda value: value is None or isinstance(value, dict),
        )

    def get_live_trades(self, competition_id: int) -> list[dict[str, Any]]:
        return self._invoke("get_live_trades", competition_id, validator=lambda value: isinstance(value, list))

    def get_competition_detail(self, competition_id: int) -> dict[str, Any]:
        return self._invoke("get_competition_detail", competition_id, validator=_is_dict)

    def trade_open(
        self,
        competition_id: int,
        direction: str,
        size: float,
        take_profit: float | None = None,
        stop_loss: float | None = None,
    ) -> dict[str, Any]:
        return self._invoke(
            "trade_open",
            competition_id,
            direction,
            size,
            take_profit=take_profit,
            stop_loss=stop_loss,
            validator=_is_dict,
        )

    def trade_close(self, competition_id: int) -> dict[str, Any]:
        return self._invoke("trade_close", competition_id, validator=_is_dict)

    def trade_update_tpsl(
        self,
        competition_id: int,
        take_profit: float | None = None,
        stop_loss: float | None = None,
    ) -> dict[str, Any]:
        return self._invoke(
            "trade_update_tpsl",
            competition_id,
            take_profit=take_profit,
            stop_loss=stop_loss,
            validator=_is_dict,
        )

    def _invoke(self, method_name: str, *args: Any, validator: Validator | None = None, **kwargs: Any) -> Any:
        method = getattr(self.client, method_name)
        last_error: Exception | None = None

        for attempt in range(1, self.retry_attempts + 1):
            self._throttle(method_name)
            try:
                response = method(*args, **kwargs)
                _raise_if_api_error(response, method_name)
                if validator and not validator(response):
                    raise ValueError(f"{method_name} returned invalid payload: {response!r}")
                return response
            except Exception as exc:  # pragma: no cover - exercised via fake clients
                last_error = exc
                if attempt == self.retry_attempts:
                    break
                time.sleep(self.retry_backoff_seconds * attempt)

        assert last_error is not None
        raise last_error

    def _throttle(self, method_name: str) -> None:
        if self.min_call_spacing_seconds <= 0:
            self._last_call_started_at[method_name] = time.time()
            return

        now = time.time()
        previous = self._last_call_started_at.get(method_name)
        if previous is not None:
            elapsed = now - previous
            if elapsed < self.min_call_spacing_seconds:
                time.sleep(self.min_call_spacing_seconds - elapsed)
        self._last_call_started_at[method_name] = time.time()


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _is_dict_or_list(value: Any) -> bool:
    return isinstance(value, (dict, list))


def _raise_if_api_error(value: Any, method_name: str) -> None:
    if not isinstance(value, dict):
        return
    if "code" not in value:
        return
    code = value.get("code")
    if code in (0, None):
        return
    message = value.get("message") or value.get("detail") or "unknown Arena API error"
    raise RuntimeError(f"{method_name} failed with code={code}: {message}")
