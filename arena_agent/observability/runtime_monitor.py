"""Direct runtime observability stream for terminal monitors."""

from __future__ import annotations

from collections import deque
import json
import logging
import socket
import threading
import time
from typing import Any

from arena_agent.core.serialization import to_jsonable


def build_empty_snapshot() -> dict[str, Any]:
    return {
        "schema_version": "arena.monitor.v1",
        "stream": {"host": None, "port": None},
        "runtime": {
            "status": "idle",
            "policy_name": None,
            "competition_id": None,
            "symbol": None,
            "iteration": 0,
            "decisions": 0,
            "executed_actions": 0,
            "started_at": None,
            "updated_at": None,
            "stopped_at": None,
        },
        "health": {
            "status": "unknown",
            "decision_latency_seconds": None,
            "decision_timeout_seconds": None,
            "max_decision_latency_seconds": None,
            "max_consecutive_runtime_errors": None,
            "last_decision_timestamp": None,
            "last_decision_age_seconds": None,
            "last_transition_timestamp": None,
            "last_transition_age_seconds": None,
            "last_error_timestamp": None,
            "last_error_age_seconds": None,
            "last_error_message": None,
            "last_error_category": None,
            "consecutive_runtime_error_count": 0,
            "runtime_error_count": 0,
            "agent_error_count": 0,
            "tap_error_count": 0,
            "cli_error_count": 0,
            "rejected_action_count": 0,
            "state_guard_failure_count": 0,
            "position_drift_count": 0,
            "last_position_drift_timestamp": None,
            "last_position_drift_age_seconds": None,
            "last_position_drift_message": None,
            "no_transition_threshold_seconds": None,
            "no_transition_error_threshold_seconds": None,
        },
        "decision_state": None,
        "current_state": None,
        "last_decision": None,
        "last_execution": None,
        "last_transition": None,
        "transitions": [],
        "logs": [],
    }


def derive_health(snapshot: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    runtime = dict(snapshot.get("runtime") or {})
    health = dict(snapshot.get("health") or {})
    no_transition_threshold = _optional_float(health.get("no_transition_threshold_seconds"))
    no_transition_error_threshold = _optional_float(health.get("no_transition_error_threshold_seconds"))
    max_decision_latency_seconds = _optional_float(health.get("max_decision_latency_seconds"))
    max_consecutive_runtime_errors = _optional_float(health.get("max_consecutive_runtime_errors"))
    last_transition_timestamp = _optional_float(health.get("last_transition_timestamp"))
    last_decision_timestamp = _optional_float(health.get("last_decision_timestamp"))
    last_error_timestamp = _optional_float(health.get("last_error_timestamp"))
    last_position_drift_timestamp = _optional_float(health.get("last_position_drift_timestamp"))

    health["last_transition_age_seconds"] = (
        None if last_transition_timestamp is None else max(0.0, now - last_transition_timestamp)
    )
    health["last_decision_age_seconds"] = (
        None if last_decision_timestamp is None else max(0.0, now - last_decision_timestamp)
    )
    health["last_error_age_seconds"] = (
        None if last_error_timestamp is None else max(0.0, now - last_error_timestamp)
    )
    health["last_position_drift_age_seconds"] = (
        None if last_position_drift_timestamp is None else max(0.0, now - last_position_drift_timestamp)
    )

    recent_issue_window = no_transition_threshold if no_transition_threshold is not None else 60.0
    last_error_category = str(health.get("last_error_category") or "")
    last_error_age = health.get("last_error_age_seconds")

    if (
        runtime.get("status") == "degraded"
        or (
            max_consecutive_runtime_errors is not None
            and int(health.get("consecutive_runtime_error_count") or 0) >= int(max_consecutive_runtime_errors)
        )
        or (
            max_decision_latency_seconds is not None
            and _optional_float(health.get("decision_latency_seconds")) is not None
            and float(health["decision_latency_seconds"]) > max_decision_latency_seconds
        )
        or (
            no_transition_error_threshold is not None
            and runtime.get("decisions", 0) > 0
            and health.get("last_transition_age_seconds") is not None
            and float(health["last_transition_age_seconds"]) > no_transition_error_threshold
        )
    ):
        health["status"] = "error"
    elif (
        runtime.get("status") == "running"
        and no_transition_threshold is not None
        and health.get("last_transition_age_seconds") is not None
        and runtime.get("decisions", 0) > 0
        and float(health["last_transition_age_seconds"]) > no_transition_threshold
    ):
        health["status"] = "warning"
    elif last_error_age is not None and float(last_error_age) <= recent_issue_window:
        health["status"] = "error" if last_error_category == "runtime_error" else "warning"
    elif (
        health.get("last_position_drift_age_seconds") is not None
        and float(health["last_position_drift_age_seconds"]) <= recent_issue_window
    ):
        health["status"] = "warning"
    else:
        health["status"] = "ok"

    return health


class RuntimeMonitor:
    """Publishes runtime snapshots to local clients over a TCP socket."""

    def __init__(self, config: dict[str, Any] | None = None, *, logger: logging.Logger | None = None) -> None:
        self.config = dict(config or {})
        self.enabled = bool(self.config.get("enabled", False))
        self.host = str(self.config.get("host", "127.0.0.1"))
        self.port = int(self.config.get("port", 8765))
        self.max_transitions = max(1, int(self.config.get("max_transitions", 20)))
        self.max_logs = max(1, int(self.config.get("max_logs", 50)))
        self.attach_loggers = list(self.config.get("attach_loggers", ["arena_agent.runtime", "arena_agent.tap"]))
        self.logger = logger or logging.getLogger("arena_agent.runtime")
        self._snapshot = build_empty_snapshot()
        self._recent_transitions: deque[dict[str, Any]] = deque(maxlen=self.max_transitions)
        self._recent_logs: deque[dict[str, Any]] = deque(maxlen=self.max_logs)
        self._lock = threading.Lock()
        self._server_socket: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._clients: set[socket.socket] = set()
        self._running = threading.Event()
        self._latest_payload: bytes | None = None
        self._log_handler: _MonitorLogHandler | None = None
        self._started = False
        self.stream_active = False

    def start(self, *, runtime_config: Any, policy_name: str) -> None:
        if not self.enabled or self._started:
            return
        try:
            self._start_server()
        except OSError as exc:
            self.logger.warning("Observability stream unavailable: %s", exc)
            self.stream_active = False

        self._log_handler = _MonitorLogHandler(self)
        for logger_name in self.attach_loggers:
            logging.getLogger(logger_name).addHandler(self._log_handler)

        with self._lock:
            runtime = self._snapshot["runtime"]
            health = self._snapshot["health"]
            runtime.update(
                {
                    "status": "starting",
                    "policy_name": policy_name,
                    "competition_id": runtime_config.competition_id,
                    "symbol": runtime_config.symbol,
                    "started_at": time.time(),
                    "updated_at": time.time(),
                }
            )
            # Expose runtime config for the policy panel
            self._snapshot["runtime_config"] = _safe_config_dict(runtime_config)
            health["no_transition_threshold_seconds"] = float(
                self.config.get(
                    "no_transition_threshold_seconds",
                    max(30.0, float(getattr(runtime_config, "tick_interval_seconds", 30.0)) * 2.0),
                )
            )
            health["no_transition_error_threshold_seconds"] = _optional_float(
                self.config.get("no_transition_error_threshold_seconds")
            )
            timeout_seconds = getattr(runtime_config, "policy", {}).get("timeout_seconds")
            health["decision_timeout_seconds"] = _optional_float(timeout_seconds)
            health["max_decision_latency_seconds"] = _optional_float(
                self.config.get("max_decision_latency_seconds")
            )
            health["max_consecutive_runtime_errors"] = _optional_float(
                self.config.get("max_consecutive_runtime_errors")
            )
            self._snapshot["stream"] = {"host": self.host, "port": self.port, "active": self.stream_active}
        self._started = True
        self._publish_snapshot()

    def stop(self, *, report: Any | None = None, final_state: Any | None = None, reason: str = "stopped") -> None:
        if not self._started:
            return

        with self._lock:
            runtime = self._snapshot["runtime"]
            runtime["status"] = reason
            runtime["updated_at"] = time.time()
            runtime["stopped_at"] = time.time()
            if report is not None:
                runtime["report"] = to_jsonable(report)
            if final_state is not None:
                self._snapshot["current_state"] = _serialize_state(final_state)
        self._publish_snapshot()
        self._detach_log_handler()
        self._stop_server()
        self._started = False

    def record_state(
        self,
        *,
        iteration: int,
        decisions: int,
        executed_actions: int,
        policy_name: str,
        state: Any,
    ) -> None:
        if not self.enabled:
            return
        with self._lock:
            runtime = self._snapshot["runtime"]
            runtime.update(
                {
                    "status": "running",
                    "policy_name": policy_name,
                    "iteration": iteration,
                    "decisions": decisions,
                    "executed_actions": executed_actions,
                    "updated_at": time.time(),
                }
            )
            state_payload = _serialize_state(state)
            self._snapshot["decision_state"] = state_payload
            if self._snapshot["current_state"] is None:
                self._snapshot["current_state"] = state_payload
        self._publish_snapshot()

    def record_decision(
        self,
        *,
        iteration: int,
        action: Any,
        policy_name: str,
        latency_seconds: float | None = None,
        llm_usage: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        action_payload = to_jsonable(action)
        with self._lock:
            runtime = self._snapshot["runtime"]
            health = self._snapshot["health"]
            runtime.update({"iteration": iteration, "policy_name": policy_name, "updated_at": time.time()})
            self._snapshot["last_decision"] = {
                "timestamp": time.time(),
                "policy_name": policy_name,
                "action": action_payload,
                "reason": action_payload.get("metadata", {}).get("reason"),
                "confidence": action_payload.get("metadata", {}).get("confidence"),
                "llm_usage": llm_usage,
            }
            health["last_decision_timestamp"] = time.time()
            health["decision_latency_seconds"] = _optional_float(latency_seconds)

            # Accumulate LLM usage totals
            if llm_usage and isinstance(llm_usage, dict):
                totals = self._snapshot.setdefault("llm_usage_totals", {
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_cost_usd": 0.0,
                    "decisions_with_usage": 0,
                })
                totals["decisions_with_usage"] += 1
                if llm_usage.get("input_tokens") is not None:
                    totals["total_input_tokens"] += int(llm_usage["input_tokens"])
                if llm_usage.get("output_tokens") is not None:
                    totals["total_output_tokens"] += int(llm_usage["output_tokens"])
                if llm_usage.get("cost_usd") is not None:
                    totals["total_cost_usd"] += float(llm_usage["cost_usd"])
        self._publish_snapshot()

    def record_transition(
        self,
        *,
        iteration: int,
        decisions: int,
        executed_actions: int,
        next_state: Any,
        action: Any,
        execution_result: Any,
        transition: Any,
    ) -> None:
        if not self.enabled:
            return
        transition_payload = _serialize_transition(transition)
        with self._lock:
            runtime = self._snapshot["runtime"]
            health = self._snapshot["health"]
            runtime.update(
                {
                    "status": "running",
                    "iteration": iteration,
                    "decisions": decisions,
                    "executed_actions": executed_actions,
                    "updated_at": time.time(),
                }
            )
            self._snapshot["current_state"] = _serialize_state(next_state)
            self._snapshot["last_execution"] = to_jsonable(execution_result)
            self._snapshot["last_transition"] = transition_payload
            self._recent_transitions.append(transition_payload)
            self._snapshot["transitions"] = list(self._recent_transitions)
            health["last_transition_timestamp"] = _optional_float(transition_payload.get("timestamp"))
            health["consecutive_runtime_error_count"] = 0

            action_payload = to_jsonable(action)
            reason = action_payload.get("metadata", {}).get("reason")
            if reason and str(reason).startswith("tap_error:"):
                self._register_agent_issue_locked("tap_error", str(reason))
                self._append_log_locked("WARNING", "arena_agent.tap", str(reason))
            elif reason and str(reason).startswith("cli_error:"):
                self._register_agent_issue_locked("cli_error", str(reason))
                self._append_log_locked("WARNING", "arena_agent.cli", str(reason))
            if not bool(getattr(execution_result, "accepted", False)):
                message = getattr(execution_result, "message", "execution rejected")
                health["rejected_action_count"] = int(health.get("rejected_action_count") or 0) + 1
                health["last_error_category"] = "rejected_action"
                health["last_error_message"] = str(message)
                health["last_error_timestamp"] = time.time()
                self._append_log_locked("WARNING", "arena_agent.runtime", str(message))
        self._publish_snapshot()

    def record_error(self, *, iteration: int, decisions: int, executed_actions: int, error: Exception) -> None:
        if not self.enabled:
            return
        with self._lock:
            runtime = self._snapshot["runtime"]
            health = self._snapshot["health"]
            runtime.update(
                {
                    "status": "degraded",
                    "iteration": iteration,
                    "decisions": decisions,
                    "executed_actions": executed_actions,
                    "updated_at": time.time(),
                }
            )
            health["consecutive_runtime_error_count"] = int(health.get("consecutive_runtime_error_count") or 0) + 1
            health["runtime_error_count"] = int(health.get("runtime_error_count") or 0) + 1
            health["last_error_category"] = "runtime_error"
            health["last_error_message"] = str(error)
            health["last_error_timestamp"] = time.time()
            self._append_log_locked("ERROR", "arena_agent.runtime", str(error))
        self._publish_snapshot()

    def record_state_guard_failure(self, *, reason: str, details: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock:
            health = self._snapshot["health"]
            health["state_guard_failure_count"] = int(health.get("state_guard_failure_count") or 0) + 1
            health["last_error_category"] = "state_guard"
            health["last_error_message"] = f"{reason}: {details}"
            health["last_error_timestamp"] = time.time()
            self._append_log_locked("WARNING", "arena_agent.runtime", f"state_guard:{reason}")
        self._publish_snapshot()

    def record_position_drift(self, *, message: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            health = self._snapshot["health"]
            health["position_drift_count"] = int(health.get("position_drift_count") or 0) + 1
            health["last_position_drift_timestamp"] = time.time()
            health["last_position_drift_message"] = message
            self._append_log_locked("WARNING", "arena_agent.runtime", message)
        self._publish_snapshot()

    def record_log(self, level: str, logger_name: str, message: str, *, timestamp: float | None = None) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._append_log_locked(level, logger_name, message, timestamp=timestamp)
        self._publish_snapshot()

    def endpoint(self) -> tuple[str, int]:
        return self.host, self.port

    def current_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._snapshot))

    def _append_log_locked(
        self,
        level: str,
        logger_name: str,
        message: str,
        *,
        timestamp: float | None = None,
    ) -> None:
        self._recent_logs.append(
            {
                "timestamp": time.time() if timestamp is None else timestamp,
                "level": level,
                "logger": logger_name,
                "message": message,
            }
        )
        self._snapshot["logs"] = list(self._recent_logs)

    def _register_agent_issue_locked(self, category: str, message: str) -> None:
        health = self._snapshot["health"]
        health["agent_error_count"] = int(health.get("agent_error_count") or 0) + 1
        if category == "tap_error":
            health["tap_error_count"] = int(health.get("tap_error_count") or 0) + 1
        if category == "cli_error":
            health["cli_error_count"] = int(health.get("cli_error_count") or 0) + 1
        health["last_error_category"] = category
        health["last_error_message"] = message
        health["last_error_timestamp"] = time.time()

    def _start_server(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen()
        server.settimeout(0.5)
        self._server_socket = server
        self.host, self.port = server.getsockname()[0], server.getsockname()[1]
        self.stream_active = True
        self._running.set()
        self._accept_thread = threading.Thread(target=self._accept_loop, name="arena-monitor-stream", daemon=True)
        self._accept_thread.start()

    def _stop_server(self) -> None:
        self._running.clear()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None
        self.stream_active = False
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=1.0)
            self._accept_thread = None
        for client in list(self._clients):
            self._close_client(client)
        self._clients.clear()

    def _detach_log_handler(self) -> None:
        if self._log_handler is None:
            return
        for logger_name in self.attach_loggers:
            logging.getLogger(logger_name).removeHandler(self._log_handler)
        self._log_handler = None

    def _accept_loop(self) -> None:
        assert self._server_socket is not None
        while self._running.is_set():
            try:
                client, _ = self._server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client.setblocking(True)
            with self._lock:
                latest = self._latest_payload
                self._clients.add(client)
            if latest is not None:
                try:
                    client.sendall(latest)
                except OSError:
                    self._close_client(client)

    def _publish_snapshot(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._snapshot["stream"] = {
                "host": self.host,
                "port": self.port,
                "active": self.stream_active,
            }
            self._snapshot["health"] = derive_health(self._snapshot)
            payload = json.dumps(self._snapshot, sort_keys=True).encode("utf-8") + b"\n"
            self._latest_payload = payload
            clients = list(self._clients)
        if not self.stream_active:
            return
        stale_clients: list[socket.socket] = []
        for client in clients:
            try:
                client.sendall(payload)
            except OSError:
                stale_clients.append(client)
        for client in stale_clients:
            self._close_client(client)

    def _close_client(self, client: socket.socket) -> None:
        with self._lock:
            self._clients.discard(client)
        try:
            client.close()
        except OSError:
            pass


class _MonitorLogHandler(logging.Handler):
    def __init__(self, monitor: RuntimeMonitor) -> None:
        super().__init__(level=logging.INFO)
        self.monitor = monitor

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = record.msg if isinstance(record.msg, str) else repr(record.msg)
        self.monitor.record_log(
            record.levelname,
            record.name,
            message,
            timestamp=record.created,
        )


def _serialize_state(state: Any) -> dict[str, Any]:
    market = state.market
    recent_candles = list(market.recent_candles[-20:])
    return {
        "timestamp": state.timestamp,
        "market": {
            "symbol": market.symbol,
            "interval": market.interval,
            "last_price": market.last_price,
            "mark_price": market.mark_price,
            "volatility": market.volatility,
            "orderbook_imbalance": market.orderbook_imbalance,
            "funding_rate": market.funding_rate,
            "recent_candles": to_jsonable(recent_candles),
            "candle_count": len(market.recent_candles),
        },
        "account": to_jsonable(state.account),
        "position": to_jsonable(state.position),
        "competition": to_jsonable(state.competition),
        "signal_state": to_jsonable(state.signal_state),
    }


def _serialize_transition(transition: Any) -> dict[str, Any]:
    return {
        "timestamp": transition.timestamp,
        "action": to_jsonable(transition.action),
        "execution_result": to_jsonable(transition.execution_result),
        "metrics": to_jsonable(transition.metrics),
        "equity_after": transition.state_after.account.equity,
        "balance_after": transition.state_after.account.balance,
        "price_after": transition.state_after.market.last_price,
        "position_after": to_jsonable(transition.state_after.position),
    }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_config_dict(runtime_config: Any) -> dict[str, Any]:
    """Convert a RuntimeConfig dataclass to a plain dict for the snapshot."""
    import dataclasses

    if dataclasses.is_dataclass(runtime_config):
        return dataclasses.asdict(runtime_config)
    if hasattr(runtime_config, "__dict__"):
        return dict(runtime_config.__dict__)
    return {}
