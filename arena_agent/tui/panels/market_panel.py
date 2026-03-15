"""Market-state panel."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from textual.widgets import Static


class MarketPanel(Static):
    def refresh_view(self, controller) -> None:
        market = controller.market_state()
        table = Table.grid(padding=(0, 1))
        table.add_column(style="cyan")
        table.add_column()
        table.add_row("symbol", str(market.get("symbol") or "-"))
        table.add_row("price", _fmt(market.get("last_price")))
        table.add_row("mark", _fmt(market.get("mark_price")))
        table.add_row("interval", str(market.get("interval") or "-"))
        table.add_row("imbalance", _fmt(market.get("orderbook_imbalance")))
        table.add_row("volatility", _fmt(market.get("volatility")))
        table.add_row("time_left", _fmt(market.get("time_remaining_seconds")))
        candle = market.get("last_candle") or {}
        table.add_row("last_candle", f"o={_fmt(candle.get('open'))} c={_fmt(candle.get('close'))}")
        self.update(Panel(table, title="Market State", border_style="blue"))


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
