"""Runtime health panel."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from textual.widgets import Static


class HealthPanel(Static):
    def refresh_view(self, controller) -> None:
        health = controller.health_state()
        status = str(health.get("status") or "unknown")
        border_style = "green" if status == "ok" else "yellow" if status == "warning" else "red"
        table = Table.grid(padding=(0, 1))
        table.add_column(style="cyan")
        table.add_column()
        table.add_row("status", status)
        table.add_row("decision_latency", _fmt(health.get("decision_latency_seconds")))
        table.add_row("decision_age", _fmt(health.get("last_decision_age_seconds")))
        table.add_row("transition_age", _fmt(health.get("last_transition_age_seconds")))
        table.add_row("runtime_errors", _fmt(health.get("runtime_error_count")))
        table.add_row("agent_errors", _fmt(health.get("agent_error_count")))
        table.add_row("tap_errors", _fmt(health.get("tap_error_count")))
        table.add_row("cli_errors", _fmt(health.get("cli_error_count")))
        table.add_row("rejected", _fmt(health.get("rejected_action_count")))
        table.add_row("guard_failures", _fmt(health.get("state_guard_failure_count")))
        table.add_row("position_drift", _fmt(health.get("position_drift_count")))
        table.add_row("last_error", str(health.get("last_error_message") or "-"))
        self.update(Panel(table, title="Health", border_style=border_style))


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}s" if abs(value) < 10000 else f"{value:.2f}"
    return str(value)
