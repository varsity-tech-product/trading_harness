"""Compact loop status banner — always-visible condition of the loop."""

from __future__ import annotations

import time

from rich.text import Text
from textual.widgets import Static


_PHASE_BADGES = {
    "runtime": ("bold white on green", " RUNTIME "),
    "setup": ("bold white on blue", " SETUP "),
    "waiting": ("bold white on dark_goldenrod", " WAITING "),
    "pre_check": ("bold white on dark_goldenrod", " PRE-CHECK "),
    "registering": ("bold white on dark_goldenrod", " REGISTER "),
    "account_check": ("bold white on dark_goldenrod", " ACCT CHECK "),
    "error_backoff": ("bold white on red", " ERROR "),
    "stopped": ("bold white on grey50", " STOPPED "),
}


def _format_elapsed(started_at: float | None) -> str:
    if started_at is None:
        return ""
    elapsed = max(0, time.time() - started_at)
    minutes, seconds = divmod(int(elapsed), 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{seconds:02d}s"


class LoopStatusPanel(Static):
    """One-line loop condition banner at the top of the TUI."""

    def refresh_view(self, controller) -> None:
        auto = controller.auto_loop_state()

        if not auto.get("active"):
            # Standalone runtime mode (arena_agent run)
            runtime = controller.snapshot.get("runtime", {})
            status = runtime.get("status", "idle")
            line = Text()
            line.append(" STANDALONE ", style="bold white on grey50")
            line.append(f"  runtime={status}", style="dim")
            self.update(line)
            return

        phase = auto.get("phase") or "unknown"
        cycle = auto.get("cycle", 0)
        elapsed = _format_elapsed(auto.get("phase_started_at"))

        line = Text()

        # Phase badge
        style, label = _PHASE_BADGES.get(phase, ("bold white on grey50", f" {phase.upper()} "))
        line.append(label, style=style)

        # Backend + cycle + elapsed
        backend = auto.get("setup_backend") or "unknown"
        line.append(f"  {backend}", style="bold")
        line.append(f" | cycle {cycle}")
        if elapsed:
            line.append(f" | {elapsed}")

        # Next setup countdown (during runtime phase)
        next_check = auto.get("next_setup_check_seconds")
        if next_check is not None and phase == "runtime":
            phase_started = auto.get("phase_started_at") or time.time()
            remaining = max(0, next_check - (time.time() - phase_started))
            mins, secs = divmod(int(remaining), 60)
            line.append(f" | next setup ~{mins}m{secs:02d}s", style="dim")

        # Inactive warning
        inactive = auto.get("inactive_cycles", 0)
        if inactive > 0:
            line.append(f" | {inactive} idle", style="yellow")

        # Setup failures warning
        failures = auto.get("consecutive_setup_failures", 0)
        if failures > 0:
            line.append(f" | {failures} fail", style="red")

        # Competition status
        comp = auto.get("competition_status")
        if comp:
            line.append(f" | comp: {comp}", style="dim")

        self.update(line)
