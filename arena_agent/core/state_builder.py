"""Build agent state from raw Arena API responses."""

from __future__ import annotations

import logging
import math
import statistics
import time
from typing import Any

from arena_agent.core.environment_adapter import EnvironmentAdapter
from arena_agent.core.models import (
    AccountSnapshot,
    AgentState,
    Candle,
    CompetitionSnapshot,
    MarketSnapshot,
    PositionSnapshot,
    RuntimeConfig,
)
from arena_agent.features.engine import FeatureEngine, compute_kline_limit, resolve_indicator_specs
from arena_agent.features.registry import feature_key

logger = logging.getLogger("arena_agent.state_builder")


class StateBuilder:
    def __init__(self, adapter: EnvironmentAdapter, config: RuntimeConfig) -> None:
        self.adapter = adapter
        self.config = config
        resolved_specs = resolve_indicator_specs(config.policy, config.signal_indicators)
        self.feature_engine = FeatureEngine(resolved_specs)
        self._kline_limit = compute_kline_limit(
            resolved_specs,
            minimum=config.kline_limit,
        )
        # Rolling window of recent indicator values (last 30 iterations ≈ 30 min at 1m ticks)
        self._indicator_history: dict[str, list[float]] = {}
        self._INDICATOR_WINDOW = 30

    def add_indicators(self, raw_specs: list[dict]) -> int:
        """Merge dynamic indicator specs into the feature engine.

        Called by the runtime loop when the agent requests new indicators
        via ``action.metadata["indicators"]``.  Deduplicates by feature key.
        Automatically recalculates ``kline_limit`` so new indicators have
        enough history to avoid warmup.
        Returns the number of new indicators actually added.
        """
        from arena_agent.core.models import FeatureSpec as FS

        existing_keys = {
            feature_key(s.indicator, s.params, s.key)
            for s in self.feature_engine.feature_specs
        }
        added = 0
        for raw in raw_specs:
            if not isinstance(raw, dict) or "indicator" not in raw:
                continue
            spec = FS.from_mapping(raw)
            key = feature_key(spec.indicator, spec.params, spec.key)
            if key not in existing_keys:
                self.feature_engine.feature_specs.append(spec)
                existing_keys.add(key)
                added += 1
        if added:
            self._kline_limit = compute_kline_limit(
                self.feature_engine.feature_specs,
                minimum=self.config.kline_limit,
            )
        return added

    def build(self) -> AgentState:
        competition = self.adapter.get_competition_detail(self.config.competition_id)
        competition_symbol = _normalize_symbol(
            competition.get("symbol") or competition.get("matchInfo", {}).get("symbol")
        )
        active_symbol = competition_symbol or self.config.symbol
        if competition_symbol and competition_symbol != _normalize_symbol(self.config.symbol):
            logger.warning(
                "Competition symbol %s overrides runtime config symbol %s for competition %s",
                competition_symbol,
                self.config.symbol,
                self.config.competition_id,
            )

        market_info = self.adapter.get_market_info(active_symbol)
        klines_payload = self.adapter.get_klines(
            active_symbol,
            self.config.interval,
            self._kline_limit,
        )
        orderbook = self.adapter.get_orderbook(active_symbol, self.config.orderbook_depth)
        account = self.adapter.get_live_account(self.config.competition_id)
        position = self.adapter.get_live_position(self.config.competition_id)
        trades = self.adapter.get_trade_history(self.config.competition_id)

        candles = self._parse_candles(klines_payload)
        market_snapshot = self._build_market_snapshot(active_symbol, market_info, orderbook, candles)
        signal_state = self.feature_engine.compute(candles)
        # Cache latest indicator values and track rolling min/max for setup agent
        if hasattr(signal_state, "values") and isinstance(signal_state.values, dict):
            self._last_signal_values = {}
            for k, v in signal_state.values.items():
                if isinstance(v, (int, float)):
                    val = round(float(v), 4)
                    self._last_signal_values[k] = val
                    # Append to rolling window
                    hist = self._indicator_history.setdefault(k, [])
                    hist.append(val)
                    if len(hist) > self._INDICATOR_WINDOW:
                        hist.pop(0)
                else:
                    self._last_signal_values[k] = v
            # Build ranges from rolling window
            self._indicator_ranges = {}
            for k, hist in self._indicator_history.items():
                if hist:
                    self._indicator_ranges[k] = {
                        "current": hist[-1],
                        "min": round(min(hist), 4),
                        "max": round(max(hist), 4),
                    }
        account_snapshot = self._build_account_snapshot(account, trades)
        position_snapshot = self._build_position_snapshot(position, trades, account_snapshot)
        competition_snapshot = self._build_competition_snapshot(competition, account_snapshot, trades)

        return AgentState(
            timestamp=time.time(),
            market=market_snapshot,
            signal_state=signal_state,
            account=account_snapshot,
            position=position_snapshot,
            competition=competition_snapshot,
            raw={
                "config_symbol": self.config.symbol,
                "active_symbol": active_symbol,
                "market_info": market_info,
                "orderbook": orderbook,
                "account": account,
                "position": position,
                "trades": trades,
                "competition": competition,
            },
        )

    def _build_market_snapshot(
        self,
        symbol: str,
        market_info: dict[str, Any],
        orderbook: dict[str, Any],
        candles: list[Candle],
    ) -> MarketSnapshot:
        closes = [candle.close for candle in candles]
        last_price = _float(market_info.get("lastPrice"), default=closes[-1] if closes else 0.0)
        mark_price = _optional_float(market_info.get("markPrice"))
        return MarketSnapshot(
            symbol=symbol,
            interval=self.config.interval,
            last_price=last_price,
            mark_price=mark_price,
            volatility=self._estimate_volatility(closes),
            orderbook_imbalance=self._compute_orderbook_imbalance(orderbook),
            recent_candles=candles,
            funding_rate=_optional_float(market_info.get("fundingRate")),
            metadata=market_info,
        )

    def _build_account_snapshot(
        self,
        account: dict[str, Any],
        trades: list[dict[str, Any]],
    ) -> AccountSnapshot:
        balance = _first_float(account, "walletBalance", "availableBalance", "balance", "capital")
        equity = _first_float(account, "totalEquity", "equity", "capital", default=balance)
        unrealized_pnl = _first_float(account, "unrealizedPnl", "unrealized_pnl", default=0.0)
        realized_pnl = _first_float(account, "realizedPnl", "realized_pnl", default=0.0)
        trade_count = int(
            account.get("tradeCount")
            or account.get("tradesCount")
            or account.get("currentTrades")
            or account.get("trades")
            or len(trades)
        )
        return AccountSnapshot(
            balance=balance,
            equity=equity,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            trade_count=trade_count,
            metadata=account,
        )

    def _build_position_snapshot(
        self,
        position: dict[str, Any] | None,
        trades: list[dict[str, Any]],
        account_snapshot: AccountSnapshot,
    ) -> PositionSnapshot | None:
        if not position:
            return self._infer_position_from_trades(trades, account_snapshot)

        direction = str(position.get("direction") or position.get("positionSide") or "").lower()
        if direction == "long":
            normalized_direction = "long"
        elif direction == "short":
            normalized_direction = "short"
        else:
            normalized_direction = direction

        return PositionSnapshot(
            direction=normalized_direction,
            size=_first_float(position, "size"),
            entry_price=_first_float(position, "entryPrice", "entry_price"),
            unrealized_pnl=_first_float(position, "unrealizedPnl", "unrealized_pnl", default=account_snapshot.unrealized_pnl),
            leverage=_optional_float(position.get("leverage")),
            take_profit=_optional_float(position.get("takeProfit")),
            stop_loss=_optional_float(position.get("stopLoss")),
            metadata=position,
        )

    def _infer_position_from_trades(
        self,
        trades: list[dict[str, Any]],
        account_snapshot: AccountSnapshot,
    ) -> PositionSnapshot | None:
        unresolved = [trade for trade in trades if _trade_is_unresolved(trade)]
        if not unresolved:
            return None

        has_unrealized_signal = not math.isclose(account_snapshot.unrealized_pnl, 0.0, abs_tol=1e-9)
        has_recent_unresolved_trade = any(_trade_is_recent(trade) for trade in unresolved)
        if not has_unrealized_signal and not has_recent_unresolved_trade:
            return None

        net_size = 0.0
        weighted_entry = 0.0
        total_size = 0.0
        unresolved_pnl = 0.0

        for trade in unresolved:
            size = _first_float(trade, "size")
            if size <= 0:
                continue
            direction = str(trade.get("direction", "")).lower()
            sign = 1.0 if direction == "long" else -1.0 if direction == "short" else 0.0
            if sign == 0.0:
                continue
            entry_price = _first_float(trade, "entryPrice", "entry_price")
            net_size += sign * size
            total_size += size
            weighted_entry += entry_price * size
            unresolved_pnl += _optional_float(trade.get("pnl")) or 0.0

        if math.isclose(net_size, 0.0) or math.isclose(total_size, 0.0):
            return None

        return PositionSnapshot(
            direction="long" if net_size > 0 else "short",
            size=abs(net_size),
            entry_price=weighted_entry / total_size,
            unrealized_pnl=unresolved_pnl if not math.isclose(unresolved_pnl, 0.0) else account_snapshot.unrealized_pnl,
            metadata={
                "inferred": True,
                "source": "trade_history",
                "unresolved_trade_count": len(unresolved),
                "trades": unresolved,
            },
        )

    def _build_competition_snapshot(
        self,
        competition: dict[str, Any],
        account_snapshot: AccountSnapshot,
        trades: list[dict[str, Any]],
    ) -> CompetitionSnapshot:
        source = competition.get("matchInfo", competition)
        current_trades = int(next(
            (v for v in (
                source.get("currentTrades"),
                source.get("tradeCount"),
                competition.get("currentTrades"),
                competition.get("tradeCount"),
                account_snapshot.trade_count,
            ) if v is not None),
            len(trades),
        ))
        max_trades_value = next(
            (v for v in (
                source.get("maxTrades"),
                source.get("maxTradesPerMatch"),
                competition.get("maxTrades"),
                competition.get("maxTradesPerMatch"),
                self.config.risk_limits.max_trades,
            ) if v is not None),
            None,
        )
        max_trades = None if max_trades_value is None else int(max_trades_value)

        close_only_at_seconds = _milliseconds_to_seconds(source.get("closeOnlyAt") or competition.get("closeOnlyAt"))
        close_only_mode = bool(
            source.get("closeOnlyMode")
            or source.get("close_only_mode")
            or source.get("closeOnly")
            or competition.get("closeOnlyMode")
            or competition.get("close_only_mode")
            or competition.get("closeOnly")
        )
        end_time_seconds = _milliseconds_to_seconds(source.get("endTime") or competition.get("endTime"))
        close_only_seconds = _optional_float(source.get("closeOnlySeconds") or competition.get("closeOnlySeconds"))
        if close_only_at_seconds is None and end_time_seconds is not None and close_only_seconds is not None:
            close_only_at_seconds = end_time_seconds - close_only_seconds
        now = time.time()
        time_remaining = None if end_time_seconds is None else max(0.0, end_time_seconds - now)
        if close_only_at_seconds is not None and now >= close_only_at_seconds:
            close_only_mode = True
        status = str(source.get("status") or competition.get("status") or "unknown")
        status_lower = status.lower()
        is_live = (
            status_lower in {"live", "active", "running", "ongoing"}
            or bool(source.get("isLive"))
            or bool(competition.get("isLive"))
            or (status_lower == "unknown" and time_remaining is not None and time_remaining > 0)
        )

        return CompetitionSnapshot(
            competition_id=self.config.competition_id,
            symbol=str(source.get("symbol") or competition.get("symbol") or self.config.symbol),
            status=status,
            is_live=is_live,
            is_close_only=close_only_mode,
            current_trades=current_trades,
            max_trades=max_trades,
            max_trades_remaining=None if max_trades is None else max(0, max_trades - current_trades),
            time_remaining_seconds=time_remaining,
            metadata=competition,
        )

    def _parse_candles(self, payload: dict[str, Any] | list[dict[str, Any]]) -> list[Candle]:
        rows = payload.get("klines", payload) if isinstance(payload, dict) else payload
        candles: list[Candle] = []
        for row in rows:
            candles.append(
                Candle(
                    open_time=int(row.get("openTime", row.get("open_time", 0))),
                    close_time=int(row.get("closeTime", row.get("close_time", row.get("openTime", 0)))),
                    open=_first_float(row, "open"),
                    high=_first_float(row, "high"),
                    low=_first_float(row, "low"),
                    close=_first_float(row, "close"),
                    volume=_first_float(row, "volume", default=0.0),
                    is_final=bool(row.get("isFinal", True)),
                )
            )
        return candles

    def _estimate_volatility(self, closes: list[float]) -> float:
        if len(closes) < 3:
            return 0.0
        returns = []
        for previous, current in zip(closes, closes[1:]):
            if previous <= 0:
                continue
            returns.append((current - previous) / previous)
        if len(returns) < 2:
            return 0.0
        return float(statistics.pstdev(returns))

    def _compute_orderbook_imbalance(self, orderbook: dict[str, Any]) -> float | None:
        bids = orderbook.get("bids") or []
        asks = orderbook.get("asks") or []
        bid_volume = sum(_float(level[1] if isinstance(level, list) else level.get("size"), default=0.0) for level in bids)
        ask_volume = sum(_float(level[1] if isinstance(level, list) else level.get("size"), default=0.0) for level in asks)
        total = bid_volume + ask_volume
        if math.isclose(total, 0.0):
            return None
        return (bid_volume - ask_volume) / total


def _first_float(data: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in data and data[key] is not None:
            return _float(data[key], default=default)
    return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _milliseconds_to_seconds(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric / 1000.0


def _trade_is_unresolved(trade: dict[str, Any]) -> bool:
    return trade.get("closeTime") is None or trade.get("exitPrice") is None


def _trade_is_recent(trade: dict[str, Any], *, recent_seconds: int = 900) -> bool:
    open_time = trade.get("openTime")
    if open_time is None:
        return False
    try:
        return (time.time() - (float(open_time) / 1000.0)) <= recent_seconds
    except (TypeError, ValueError):
        return False


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()
