"""Setup agent activity panel — shows auto daemon logs, LLM decisions, and memory."""

from __future__ import annotations

import json
import os
from pathlib import Path

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import Static


class SetupPanel(Static):
    """Reads the auto daemon log file and setup memory, displays setup agent activity."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._log_path: str | None = None
        self._last_size: int = 0
        self._lines: list[str] = []

    def set_log_path(self, path: str) -> None:
        self._log_path = path

    def refresh_view(self, controller) -> None:
        # Auto-detect log path from arena home
        if self._log_path is None:
            self._log_path = _find_auto_log(controller)

        lines = self._read_recent_lines(30)
        memory_records = _load_memory_summary()

        table = Table(expand=True)
        table.add_column("Time", style="dim", width=8)
        table.add_column("Event")

        # Show setup agent log lines with highlighted decisions
        if lines:
            for line in lines[-12:]:
                time_str, event = _parse_line(line)
                style = ""
                if "Setup agent" in event or "setup agent" in event:
                    style = "bold cyan"
                elif "adjustment" in event.lower():
                    style = "yellow"
                elif "Restarting runtime" in event:
                    style = "bold yellow"
                elif "memory" in event.lower():
                    style = "green"
                table.add_row(time_str, Text(event, style=style) if style else event)
        else:
            table.add_row("-", "No setup agent activity (start with: arena-agent auto)")

        # Show memory summary if available
        if memory_records:
            table.add_row("", "")
            table.add_row("", Text("Past Competitions:", style="bold"))
            for rec in memory_records[-3:]:
                pnl_style = "green" if rec.get("pnl", 0) >= 0 else "red"
                pnl_str = f"{rec.get('pnl', 0):+.2f} ({rec.get('pnl_pct', 0):+.1f}%)"
                table.add_row(
                    "",
                    Text(
                        f"  #{rec.get('competition_id', '?')} | PnL: {pnl_str} | adj: {rec.get('adjustments_made', 0)}",
                        style=pnl_style,
                    ),
                )

        title = "Setup Agent"
        if self._log_path:
            title += f" | {os.path.basename(self._log_path)}"
        self.update(Panel(table, title=title, border_style="green"))

    def _read_recent_lines(self, n: int) -> list[str]:
        if not self._log_path or not os.path.exists(self._log_path):
            return []
        try:
            with open(self._log_path, "r") as f:
                f.seek(0, 2)
                size = f.tell()
                # Only re-read if file grew
                if size == self._last_size and self._lines:
                    return self._lines
                self._last_size = size
                # Read last ~4KB
                start = max(0, size - 4096)
                f.seek(start)
                if start > 0:
                    f.readline()  # skip partial line
                self._lines = f.readlines()[-n:]
                return self._lines
        except Exception:
            return []


def _find_auto_log(controller) -> str | None:
    """Try to find the auto daemon log from runtime state."""
    snapshot = controller.snapshot
    # Try common arena home locations
    homes = [
        os.path.expanduser("~/.arena-agent"),
        os.path.expanduser("~/.arena-trader-6cff"),
    ]
    # Also check ARENA_HOME env
    env_home = os.environ.get("ARENA_HOME") or os.environ.get("ARENA_ROOT")
    if env_home and env_home not in homes:
        homes.insert(0, env_home)

    for home in homes:
        logs_dir = os.path.join(home, "logs")
        if os.path.isdir(logs_dir):
            # Match any auto daemon log pattern
            candidates = sorted(
                list(Path(logs_dir).glob("auto-daemon*.log")) +
                list(Path(logs_dir).glob("auto-*.log")),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            # Prefer daemon logs over runtime logs
            for c in candidates:
                if "daemon" in c.name:
                    return str(c)
            if candidates:
                return str(candidates[0])
    return None


def _load_memory_summary() -> list[dict]:
    """Load recent records from setup_memory.json."""
    homes = [
        os.path.expanduser("~/.arena-agent"),
        os.path.expanduser("~/.arena-trader-6cff"),
    ]
    env_home = os.environ.get("ARENA_HOME") or os.environ.get("ARENA_ROOT")
    if env_home and env_home not in homes:
        homes.insert(0, env_home)

    for home in homes:
        memory_path = os.path.join(home, "setup_memory.json")
        if os.path.exists(memory_path):
            try:
                with open(memory_path, "r") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return data[-5:]
            except Exception:
                pass
    return []


def _parse_line(line: str) -> tuple[str, str]:
    """Extract time and event from a log line."""
    line = line.strip()
    if not line:
        return ("-", "")
    # Lines from daemon: "Arena auto-trade daemon starting."
    # Lines from Python bridge: "[03/18/26 14:56:08] INFO ..."
    # Lines from our daemon log: "Trading competition #9..."
    parts = line.split(None, 1)
    if len(parts) >= 2 and ":" in parts[0]:
        return parts[0][-8:], parts[1][:80]
    return ("", line[:80])
