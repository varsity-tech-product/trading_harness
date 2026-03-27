"""Decision trace panel."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from textual.widgets import Static


class DecisionPanel(Static):
    def refresh_view(self, controller) -> None:
        decision = controller.decision_state()
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="cyan", width=14)
        table.add_column()
        action_type = decision.get("action_type") or "-"
        table.add_row("action", str(action_type))
        # Only show size/tp/sl for trade actions (not HOLD)
        if action_type not in ("-", "HOLD", "None"):
            table.add_row("size", _fmt(decision.get("size")))
            table.add_row("tp/sl", f"{_fmt(decision.get('take_profit'))} / {_fmt(decision.get('stop_loss'))}")
        table.add_row("accepted", str(decision.get("accepted")))
        table.add_row("executed", str(decision.get("executed")))
        reason = decision.get("reason") or decision.get("message") or "-"
        table.add_row("reason", str(reason))
        self.update(Panel(table, title="Runtime Decision (per-tick)", border_style="yellow"))


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
