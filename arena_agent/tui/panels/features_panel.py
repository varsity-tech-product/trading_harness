"""Strategy panel — expression rules and trade parameters."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import Static


_EXPR_LABELS = {
    "entry_long": ("LONG", "green"),
    "entry_short": ("SHORT", "red"),
    "exit": ("EXIT", "yellow"),
}


class FeaturesPanel(Static):
    """Shows signal expressions and trade params (sizing, TP/SL)."""

    def refresh_view(self, controller) -> None:
        expressions = controller.expression_rules()
        trade = controller.trade_params()

        table = Table(expand=True)
        table.add_column("Key", style="cyan", width=14)
        table.add_column("Value")

        # Expression rules
        if expressions:
            for key, expr in expressions.items():
                label, style = _EXPR_LABELS.get(key, (key.upper(), ""))
                table.add_row(
                    Text(label, style=f"bold {style}"),
                    Text(expr, style="dim"),
                )
        else:
            table.add_row("-", "No expressions configured")

        # Trade parameters
        table.add_row("", "")
        fraction = trade.get("fraction")
        if fraction is not None:
            table.add_row("sizing", f"{float(fraction) * 100:.0f}% of equity")
        else:
            max_pct = trade.get("max_position_size_pct")
            if max_pct is not None:
                table.add_row("sizing", f"max {float(max_pct) * 100:.0f}% (risk limit)")
        tp = trade.get("tp_pct")
        sl = trade.get("sl_pct")
        if tp is not None or sl is not None:
            tp_str = f"{float(tp) * 100:.2f}%" if tp is not None else "-"
            sl_str = f"{float(sl) * 100:.2f}%" if sl is not None else "-"
            table.add_row("tp / sl", f"{tp_str} / {sl_str}")
        else:
            table.add_row("tp / sl", "not configured")

        self.update(Panel(table, title="Strategy", border_style="magenta"))
