"""Typed models used by the trading agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Candle:
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_final: bool = True


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    symbol: str
    interval: str
    last_price: float
    mark_price: float | None
    volatility: float
    orderbook_imbalance: float | None
    recent_candles: list[Candle]
    funding_rate: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    balance: float
    equity: float
    unrealized_pnl: float
    realized_pnl: float
    trade_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    direction: str
    size: float
    entry_price: float
    unrealized_pnl: float
    leverage: float | None = None
    take_profit: float | None = None
    stop_loss: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompetitionSnapshot:
    competition_id: int
    symbol: str
    status: str
    is_live: bool
    is_close_only: bool
    current_trades: int
    max_trades: int | None
    max_trades_remaining: int | None
    time_remaining_seconds: float | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    indicator: str
    params: dict[str, Any] = field(default_factory=dict)
    key: str | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "FeatureSpec":
        return cls(
            indicator=str(data["indicator"]),
            params=dict(data.get("params", {})),
            key=data.get("key"),
        )


@dataclass(frozen=True, slots=True)
class SignalState:
    version: str
    backend: str
    requested: list[FeatureSpec]
    values: dict[str, Any]
    warmup_complete: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def empty(cls, requested: list[FeatureSpec] | None = None) -> "SignalState":
        return cls(
            version="signal_state.v1",
            backend="none",
            requested=list(requested or []),
            values={},
            warmup_complete=True,
            metadata={},
        )


@dataclass(frozen=True, slots=True)
class AgentState:
    timestamp: float
    market: MarketSnapshot
    account: AccountSnapshot
    position: PositionSnapshot | None
    competition: CompetitionSnapshot
    signal_state: SignalState = field(default_factory=SignalState.empty)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StorageConfig:
    transition_path: str | None = None
    journal_path: str | None = None
    max_in_memory_transitions: int = 1000

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "StorageConfig":
        data = data or {}
        return cls(
            transition_path=data.get("transition_path", data.get("experience_path")),
            journal_path=data.get("journal_path"),
            max_in_memory_transitions=int(
                data.get("max_in_memory_transitions", data.get("max_in_memory_experiences", 1000))
            ),
        )


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_position_size_pct: float = 0.1
    max_absolute_size: float | None = None
    min_size: float = 0.001
    quantity_precision: int = 3
    price_precision: int = 2
    max_trades: int | None = None
    min_seconds_between_trades: float = 0.0
    allow_long: bool = True
    allow_short: bool = True

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "RiskLimits":
        data = data or {}
        max_absolute_size = data.get("max_absolute_size")
        return cls(
            max_position_size_pct=float(data.get("max_position_size_pct", 0.1)),
            max_absolute_size=None if max_absolute_size is None else float(max_absolute_size),
            min_size=float(data.get("min_size", 0.001)),
            quantity_precision=int(data.get("quantity_precision", 3)),
            price_precision=int(data.get("price_precision", 2)),
            max_trades=None if data.get("max_trades") is None else int(data["max_trades"]),
            min_seconds_between_trades=float(data.get("min_seconds_between_trades", 0.0)),
            allow_long=bool(data.get("allow_long", True)),
            allow_short=bool(data.get("allow_short", True)),
        )


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    competition_id: int
    symbol: str
    interval: str = "1m"
    tick_interval_seconds: float = 30.0
    kline_limit: int = 120
    orderbook_depth: int = 20
    max_iterations: int | None = None
    stop_when_competition_inactive: bool = True
    error_backoff_seconds: float = 5.0
    dry_run: bool = False
    adapter_retry_attempts: int = 3
    adapter_retry_backoff_seconds: float = 0.5
    adapter_min_call_spacing_seconds: float = 0.0
    signal_indicators: list[FeatureSpec] = field(default_factory=list)
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    storage: StorageConfig = field(default_factory=StorageConfig)
    policy: dict[str, Any] = field(default_factory=dict)
    observability: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "RuntimeConfig":
        return cls(
            competition_id=int(data["competition_id"]),
            symbol=str(data["symbol"]),
            interval=str(data.get("interval", "1m")),
            tick_interval_seconds=float(data.get("tick_interval_seconds", 30.0)),
            kline_limit=int(data.get("kline_limit", 120)),
            orderbook_depth=int(data.get("orderbook_depth", 20)),
            max_iterations=None if data.get("max_iterations") is None else int(data["max_iterations"]),
            stop_when_competition_inactive=bool(data.get("stop_when_competition_inactive", True)),
            error_backoff_seconds=float(data.get("error_backoff_seconds", 5.0)),
            dry_run=bool(data.get("dry_run", False)),
            adapter_retry_attempts=int(data.get("adapter_retry_attempts", 3)),
            adapter_retry_backoff_seconds=float(data.get("adapter_retry_backoff_seconds", 0.5)),
            adapter_min_call_spacing_seconds=float(data.get("adapter_min_call_spacing_seconds", 0.0)),
            signal_indicators=[
                FeatureSpec.from_mapping(item)
                for item in data.get("signal_indicators", data.get("features", []))
            ],
            risk_limits=RiskLimits.from_mapping(data.get("risk_limits")),
            storage=StorageConfig.from_mapping(data.get("storage")),
            policy=dict(data.get("policy", {})),
            observability=dict(data.get("observability", {})),
        )


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    action_type: str
    accepted: bool
    executed: bool
    message: str
    timestamp: float
    realized_pnl: float = 0.0
    fee: float = 0.0
    order_size: float | None = None
    take_profit: float | None = None
    stop_loss: float | None = None
    venue_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransitionMetrics:
    market_price_before: float
    market_price_after: float
    price_delta: float
    balance_before: float
    balance_after: float
    balance_delta: float
    equity_before: float
    equity_after: float
    equity_delta: float
    unrealized_pnl_before: float
    unrealized_pnl_after: float
    unrealized_pnl_delta: float
    realized_pnl_delta: float
    fee: float
    trade_count_before: int
    trade_count_after: int
    trade_count_delta: int
    position_changed: bool


@dataclass(frozen=True, slots=True)
class TransitionEvent:
    timestamp: float
    state_before: AgentState
    action: Any
    execution_result: ExecutionResult
    state_after: AgentState
    metrics: TransitionMetrics
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeReport:
    iterations: int
    final_equity: float | None
    final_balance: float | None
    decisions: int
    executed_actions: int
    transitions_recorded: int
    total_realized_pnl: float
    total_fees: float
    start_timestamp: float
    end_timestamp: float
