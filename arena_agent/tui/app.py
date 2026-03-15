"""Textual app for the Arena agent monitor."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from arena_agent.tui.controller import ArenaMonitorController
from arena_agent.tui.datasource import RuntimeStreamDataSource
from arena_agent.tui.panels.account_panel import AccountPanel
from arena_agent.tui.panels.decision_panel import DecisionPanel
from arena_agent.tui.panels.features_panel import FeaturesPanel
from arena_agent.tui.panels.logs_panel import LogsPanel
from arena_agent.tui.panels.market_panel import MarketPanel
from arena_agent.tui.panels.transition_panel import TransitionPanel


class ArenaMonitorApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }

    #status-line {
        height: 3;
        padding: 0 1;
        content-align: left middle;
    }

    #body {
        height: 1fr;
    }

    #top-row {
        height: 11;
    }

    #top-row > * {
        width: 1fr;
    }

    .full-row {
        height: 1fr;
    }
    """

    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh_now", "Refresh")]

    def __init__(
        self,
        *,
        host: str,
        port: int,
        refresh_interval_seconds: float = 0.5,
        reconnect_seconds: float = 1.0,
    ) -> None:
        super().__init__()
        datasource = RuntimeStreamDataSource(host=host, port=port, reconnect_seconds=reconnect_seconds)
        self.controller = ArenaMonitorController(datasource)
        self.refresh_interval_seconds = refresh_interval_seconds

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="status-line")
        with Vertical(id="body"):
            with Horizontal(id="top-row"):
                yield MarketPanel(id="market-panel")
                yield AccountPanel(id="account-panel")
            yield FeaturesPanel(id="features-panel", classes="full-row")
            yield DecisionPanel(id="decision-panel", classes="full-row")
            yield TransitionPanel(id="transition-panel", classes="full-row")
            yield LogsPanel(id="logs-panel", classes="full-row")
        yield Footer()

    def on_mount(self) -> None:
        self.controller.start()
        self.set_interval(self.refresh_interval_seconds, self._refresh_views)
        self._refresh_views()

    def on_unmount(self) -> None:
        self.controller.stop()

    def action_refresh_now(self) -> None:
        self._refresh_views()

    def _refresh_views(self) -> None:
        self.controller.poll()
        self.query_one("#status-line", Static).update(self.controller.status_line())
        self.query_one(MarketPanel).refresh_view(self.controller)
        self.query_one(AccountPanel).refresh_view(self.controller)
        self.query_one(FeaturesPanel).refresh_view(self.controller)
        self.query_one(DecisionPanel).refresh_view(self.controller)
        self.query_one(TransitionPanel).refresh_view(self.controller)
        self.query_one(LogsPanel).refresh_view(self.controller)
