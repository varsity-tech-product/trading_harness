"""Signal features panel."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from textual.widgets import Static


class FeaturesPanel(Static):
    def refresh_view(self, controller) -> None:
        feature_state = controller.feature_state()
        table = Table(expand=True)
        table.add_column("Indicator", style="cyan")
        table.add_column("Value")
        values = feature_state.get("values", {})
        if values:
            for key, value in values.items():
                table.add_row(str(key), _fmt(value))
        else:
            table.add_row("-", "No features yet")
        title = f"Indicators / Features | backend={feature_state.get('backend') or '-'} | warmup={feature_state.get('warmup_complete')}"
        self.update(Panel(table, title=title, border_style="magenta"))


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)
