"""Runtime logs panel."""

from __future__ import annotations

from datetime import datetime

from rich.panel import Panel
from rich.table import Table
from textual.widgets import Static


class LogsPanel(Static):
    def refresh_view(self, controller) -> None:
        rows = controller.log_rows(limit=12)
        table = Table(expand=True)
        table.add_column("Time", style="cyan")
        table.add_column("Level")
        table.add_column("Logger")
        table.add_column("Message")
        if rows:
            for row in rows:
                level = str(row.get("level") or "-")
                style = "red" if level in {"ERROR", "CRITICAL"} else "yellow" if level == "WARNING" else "white"
                table.add_row(
                    _ts(row.get("timestamp")),
                    f"[{style}]{level}[/{style}]",
                    str(row.get("logger") or "-"),
                    str(row.get("message") or "-"),
                )
        else:
            table.add_row("-", "-", "-", "No runtime logs yet")
        self.update(Panel(table, title="Runtime Logs / Errors", border_style="red"))


def _ts(value) -> str:
    if value is None:
        return "-"
    return datetime.fromtimestamp(float(value)).strftime("%H:%M:%S")
