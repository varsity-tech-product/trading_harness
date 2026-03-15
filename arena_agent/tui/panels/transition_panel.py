"""Transition-history panel."""

from __future__ import annotations

from datetime import datetime

from rich.panel import Panel
from rich.table import Table
from textual.widgets import Static


class TransitionPanel(Static):
    def refresh_view(self, controller) -> None:
        rows = controller.transition_rows()
        table = Table(expand=True)
        table.add_column("Time", style="cyan")
        table.add_column("Action")
        table.add_column("PnL")
        table.add_column("Equity")
        table.add_column("Price")
        if rows:
            for row in rows:
                metrics = row.get("metrics", {})
                action = row.get("action", {})
                table.add_row(
                    _ts(row.get("timestamp")),
                    str(action.get("type") or "-"),
                    _fmt(metrics.get("realized_pnl_delta")),
                    _fmt(row.get("equity_after")),
                    _fmt(row.get("price_after")),
                )
        else:
            table.add_row("-", "No transitions", "-", "-", "-")
        self.update(Panel(table, title="Transition History", border_style="white"))


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _ts(value) -> str:
    if value is None:
        return "-"
    return datetime.fromtimestamp(float(value)).strftime("%H:%M:%S")
