"""Live indicator values panel."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from textual.widgets import Static


class IndicatorsPanel(Static):
    """Shows live indicator values, filtered to those used in expressions."""

    def refresh_view(self, controller) -> None:
        feature_state = controller.feature_state()
        expressions = controller.expression_rules()
        values = feature_state.get("values", {})

        table = Table(expand=True)
        table.add_column("Indicator", style="cyan", width=14)
        table.add_column("Value")

        if values:
            expr_text = " ".join(expressions.values()).lower() if expressions else ""
            shown = 0
            for key, value in values.items():
                if not expr_text or key.lower() in expr_text:
                    table.add_row(str(key), _fmt(value))
                    shown += 1
            if shown == 0:
                table.add_row("-", "No matching indicators")
        else:
            table.add_row("-", "Waiting for data...")

        warmup = feature_state.get("warmup_complete")
        backend = feature_state.get("backend") or "-"
        title = f"Indicators | backend={backend} | warmup={warmup}"
        self.update(Panel(table, title=title, border_style="blue"))


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)
