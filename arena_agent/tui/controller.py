"""View-model controller for the Arena terminal monitor."""

from __future__ import annotations

import time
from typing import Any

from arena_agent.observability.runtime_monitor import build_empty_snapshot, derive_health
from arena_agent.tui.datasource import RuntimeStreamDataSource


class ArenaMonitorController:
    def __init__(self, datasource: RuntimeStreamDataSource) -> None:
        self.datasource = datasource
        self._snapshot = build_empty_snapshot()
        self._snapshot["connection"] = {"status": "disconnected", "host": None, "port": None, "error": None}

    def start(self) -> None:
        self.datasource.start()

    def stop(self) -> None:
        self.datasource.stop()

    def poll(self) -> bool:
        latest = self.datasource.poll_latest()
        if latest is None:
            return False
        self._snapshot = latest
        return True

    @property
    def snapshot(self) -> dict[str, Any]:
        return self._snapshot

    def status_line(self) -> str:
        runtime = self._snapshot.get("runtime", {})
        connection = self._snapshot.get("connection", {})
        auto_loop = self._snapshot.get("auto_loop", {})
        health = self.health_state()
        connection_status = connection.get("status", "unknown")
        runtime_status = runtime.get("status", "idle")
        policy_name = runtime.get("policy_name") or "unknown"
        iteration = runtime.get("iteration", 0)
        decisions = runtime.get("decisions", 0)
        executed = runtime.get("executed_actions", 0)
        error = connection.get("error")
        parts = []
        if auto_loop.get("active"):
            phase = (auto_loop.get("phase") or "unknown").upper()
            cycle = auto_loop.get("cycle", 0)
            parts.append(f"cycle={cycle}")
            parts.append(f"phase={phase}")
        parts.extend([
            f"connection={connection_status}",
            f"health={health.get('status', 'unknown')}",
            f"runtime={runtime_status}",
            f"policy={policy_name}",
            f"iteration={iteration}",
            f"decisions={decisions}",
            f"executed={executed}",
        ])
        if error:
            parts.append(f"error={error}")
        return " | ".join(parts)

    def health_state(self) -> dict[str, Any]:
        return derive_health(self._snapshot, now=time.time())

    def auto_loop_state(self) -> dict[str, Any]:
        return dict(self._snapshot.get("auto_loop", {}))

    def market_state(self) -> dict[str, Any]:
        state = self._decision_state()
        market = dict(state.get("market", {}))
        competition = dict(state.get("competition", {}))
        candles = list(market.get("recent_candles", []))
        market["last_candle"] = candles[-1] if candles else None
        market["time_remaining_seconds"] = competition.get("time_remaining_seconds")
        market["competition_status"] = competition.get("status")
        return market

    def account_state(self) -> dict[str, Any]:
        state = self._current_state()
        account = dict(state.get("account", {}))
        competition = dict(state.get("competition", {}))
        position = state.get("position")
        return {
            "equity": account.get("equity"),
            "balance": account.get("balance"),
            "unrealized_pnl": account.get("unrealized_pnl"),
            "realized_pnl": account.get("realized_pnl"),
            "trade_count": account.get("trade_count"),
            "remaining_trades": competition.get("max_trades_remaining"),
            "position": position,
        }

    def feature_state(self) -> dict[str, Any]:
        signal_state = dict(self._decision_state().get("signal_state", {}))
        values = dict(signal_state.get("values", {}))
        return {
            "backend": signal_state.get("backend"),
            "warmup_complete": signal_state.get("warmup_complete"),
            "values": values,
            "indicator_metadata": signal_state.get("metadata", {}).get("indicator_metadata", []),
        }

    def decision_state(self) -> dict[str, Any]:
        decision = dict(self._snapshot.get("last_decision") or {})
        execution = dict(self._snapshot.get("last_execution") or {})
        action = dict(decision.get("action") or {})
        return {
            "policy_name": decision.get("policy_name") or self._snapshot.get("runtime", {}).get("policy_name"),
            "action_type": action.get("type"),
            "size": action.get("size"),
            "take_profit": action.get("take_profit"),
            "stop_loss": action.get("stop_loss"),
            "reason": decision.get("reason") or action.get("metadata", {}).get("reason"),
            "confidence": decision.get("confidence") or action.get("metadata", {}).get("confidence"),
            "accepted": execution.get("accepted"),
            "executed": execution.get("executed"),
            "message": execution.get("message"),
        }

    def transition_rows(self, limit: int = 20) -> list[dict[str, Any]]:
        transitions = list(self._snapshot.get("transitions", []))
        rows = list(reversed(transitions[-limit:]))
        return rows

    def log_rows(self, limit: int = 50) -> list[dict[str, Any]]:
        logs = list(self._snapshot.get("logs", []))
        return list(reversed(logs[-limit:]))

    def expression_rules(self) -> dict[str, str]:
        """Return the active entry/exit expressions from runtime config."""
        config = self._snapshot.get("runtime_config", {})
        policy = config.get("policy", {}) if isinstance(config.get("policy"), dict) else {}
        params = policy.get("params", {}) if isinstance(policy.get("params"), dict) else {}
        rules: dict[str, str] = {}
        for key in ("entry_long", "entry_short", "exit"):
            if key in params and params[key]:
                rules[key] = str(params[key])
        return rules

    def trade_params(self) -> dict[str, Any]:
        """Return sizing, TP/SL, and risk config from runtime config."""
        config = self._snapshot.get("runtime_config", {})
        strategy = config.get("strategy", {}) if isinstance(config.get("strategy"), dict) else {}
        sizing = strategy.get("sizing", {}) if isinstance(strategy.get("sizing"), dict) else {}
        tpsl = strategy.get("tpsl", {}) if isinstance(strategy.get("tpsl"), dict) else {}
        risk = config.get("risk_limits", {}) if isinstance(config.get("risk_limits"), dict) else {}
        return {
            "sizing_type": sizing.get("type"),
            "fraction": sizing.get("fraction"),
            "tp_pct": tpsl.get("tp_pct"),
            "sl_pct": tpsl.get("sl_pct"),
            "tpsl_type": tpsl.get("type"),
            "max_position_size_pct": risk.get("max_position_size_pct"),
        }

    def policy_info(self) -> dict[str, Any]:
        runtime = self._snapshot.get("runtime", {})
        config = self._snapshot.get("runtime_config", {})
        policy = config.get("policy", {}) if isinstance(config.get("policy"), dict) else {}
        strategy = config.get("strategy", {}) if isinstance(config.get("strategy"), dict) else {}
        return {
            "policy_name": runtime.get("policy_name") or policy.get("type", "unknown"),
            "backend": policy.get("backend", "-"),
            "indicator_mode": policy.get("indicator_mode") or ("full" if config.get("signal_indicators") == [] else "-"),
            "timeout_seconds": policy.get("timeout_seconds", "-"),
            "tick_interval_seconds": config.get("tick_interval_seconds", "-"),
            "strategy_context": policy.get("strategy_context", "-"),
            "sizing_type": strategy.get("sizing", {}).get("type", "-") if isinstance(strategy.get("sizing"), dict) else "-",
            "tpsl_type": strategy.get("tpsl", {}).get("type", "-") if isinstance(strategy.get("tpsl"), dict) else "-",
            "competition_id": config.get("competition_id") or runtime.get("competition_id", "-"),
            "dry_run": config.get("dry_run", "-"),
        }

    def _decision_state(self) -> dict[str, Any]:
        return dict(self._snapshot.get("decision_state") or self._snapshot.get("current_state") or {})

    def _current_state(self) -> dict[str, Any]:
        return dict(self._snapshot.get("current_state") or self._snapshot.get("decision_state") or {})
