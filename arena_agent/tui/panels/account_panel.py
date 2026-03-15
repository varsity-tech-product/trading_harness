"""Account and position panel."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from textual.widgets import Static


class AccountPanel(Static):
    def refresh_view(self, controller) -> None:
        account = controller.account_state()
        position = account.get("position") or {}
        table = Table.grid(padding=(0, 1))
        table.add_column(style="cyan")
        table.add_column()
        table.add_row("equity", _fmt(account.get("equity")))
        table.add_row("balance", _fmt(account.get("balance")))
        table.add_row("unrealized", _fmt(account.get("unrealized_pnl")))
        table.add_row("realized", _fmt(account.get("realized_pnl")))
        table.add_row("trade_count", _fmt(account.get("trade_count")))
        table.add_row("remaining", _fmt(account.get("remaining_trades")))
        table.add_row("position", str(position.get("direction") or "flat"))
        table.add_row("size", _fmt(position.get("size")))
        table.add_row("entry", _fmt(position.get("entry_price")))
        self.update(Panel(table, title="Account / Position", border_style="green"))


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
