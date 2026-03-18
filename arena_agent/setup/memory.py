"""Persistent memory for the setup agent — tracks past competition results."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("arena_agent.setup.memory")


@dataclass
class CompetitionRecord:
    competition_id: int
    title: str
    final_equity: float
    pnl: float
    pnl_pct: float
    trades_used: int
    strategy_summary: str
    adjustments_made: int
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SetupMemory:
    """JSON-file backed memory for past competition results."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._records: list[CompetitionRecord] | None = None

    def load(self) -> list[CompetitionRecord]:
        """Load all past competition records."""
        if self._records is not None:
            return self._records
        if not self.path.exists():
            self._records = []
            return self._records
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._records = [
                CompetitionRecord(**record) for record in data
            ]
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Failed to load setup memory from %s: %s", self.path, exc)
            self._records = []
        return self._records

    def append(self, record: CompetitionRecord) -> None:
        """Add a competition result and persist."""
        records = self.load()
        # Deduplicate by competition_id — keep latest
        records = [r for r in records if r.competition_id != record.competition_id]
        records.append(record)
        self._records = records
        self._save()

    def recent(self, n: int = 5) -> list[CompetitionRecord]:
        """Last N competition results for context."""
        records = self.load()
        return records[-n:]

    def format_for_prompt(self, n: int = 5) -> str:
        """Format recent memory as text for the LLM prompt."""
        records = self.recent(n)
        if not records:
            return "No past competition data available."
        lines = []
        for r in records:
            lines.append(
                f"- Competition #{r.competition_id} ({r.title}): "
                f"PnL={r.pnl:+.2f} ({r.pnl_pct:+.1f}%), "
                f"trades={r.trades_used}, adjustments={r.adjustments_made}, "
                f"strategy: {r.strategy_summary}"
            )
        return "\n".join(lines)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [r.to_dict() for r in (self._records or [])]
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Setup memory saved to %s (%d records)", self.path, len(data))
