"""Codex-backed stateless execution policy."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import subprocess
from string import Template
import tempfile
from typing import Any, Sequence

from arena_agent.core.models import AgentState, RiskLimits, TransitionEvent
from arena_agent.core.serialization import to_jsonable
from arena_agent.interfaces.action_schema import Action
from arena_agent.interfaces.policy_interface import Policy
from arena_agent.tap.protocol import parse_decision_response


DEFAULT_SCHEMA_PATH = Path(__file__).with_name("codex_action_schema.json")
DEFAULT_PROMPT_TEMPLATE_PATH = Path(__file__).with_name("codex_prompt_template.md")


@dataclass
class CodexExecPolicy(Policy):
    model: str | None = None
    command: str = "codex"
    timeout_seconds: float = 45.0
    recent_transition_limit: int = 5
    fail_open_to_hold: bool = True
    sandbox_mode: str = "read-only"
    cwd: str | None = None
    extra_instructions: str = ""
    prompt_template_path: str | None = None
    transition_path: str | None = None
    bootstrap_from_transition_log: bool = True
    risk_limits: RiskLimits | None = None
    name: str = "codex_exec"
    subprocess_runner: Any | None = None
    _recent_transition_summaries: list[dict[str, Any]] = field(init=False, default_factory=list, repr=False)
    _logger: logging.Logger = field(init=False, repr=False)
    _prompt_template: Template = field(init=False, repr=False)
    _action_schema_text: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._logger = logging.getLogger("arena_agent.codex")
        if self.subprocess_runner is None:
            self.subprocess_runner = subprocess.run
        template_path = Path(self.prompt_template_path) if self.prompt_template_path else DEFAULT_PROMPT_TEMPLATE_PATH
        self._prompt_template = Template(template_path.read_text(encoding="utf-8"))
        self._action_schema_text = DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8").strip()

    def reset(self) -> None:
        self._recent_transition_summaries = []
        if self.bootstrap_from_transition_log and self.transition_path:
            self._recent_transition_summaries = self._load_recent_transition_summaries()

    def update(self, memory: Sequence[TransitionEvent]) -> None:
        self._recent_transition_summaries = [
            _summarize_transition(transition)
            for transition in list(memory)[-self.recent_transition_limit :]
        ]

    def decide(self, state: AgentState) -> Action:
        prompt = self._build_prompt(state)
        try:
            payload = self._run_codex(prompt)
            parsed = parse_decision_response(payload)
            metadata = dict(parsed.metadata)
            metadata.setdefault("source", "codex_exec")
            metadata.setdefault("codex_model", self.model or "default")
            return Action(
                type=parsed.type,
                size=parsed.size,
                take_profit=parsed.take_profit,
                stop_loss=parsed.stop_loss,
                metadata=metadata,
            )
        except Exception as exc:
            if self.fail_open_to_hold:
                self._logger.warning("Codex decision failed: %s", exc)
                return Action.hold(
                    reason=f"codex_error:{type(exc).__name__}",
                    error=str(exc),
                )
            raise

    def _build_prompt(self, state: AgentState) -> str:
        context = {
            "market_state": _build_market_context(state),
            "features": {
                "backend": state.signal_state.backend,
                "warmup_complete": state.signal_state.warmup_complete,
                "values": to_jsonable(state.signal_state.values),
            },
            "account_state": {
                "balance": state.account.balance,
                "equity": state.account.equity,
                "unrealized_pnl": state.account.unrealized_pnl,
                "realized_pnl": state.account.realized_pnl,
                "trade_count": state.account.trade_count,
            },
            "position": to_jsonable(state.position),
            "competition": {
                "status": state.competition.status,
                "is_live": state.competition.is_live,
                "is_close_only": state.competition.is_close_only,
                "remaining_trades": state.competition.max_trades_remaining,
                "time_remaining_seconds": state.competition.time_remaining_seconds,
            },
            "recent_transitions": list(self._recent_transition_summaries),
            "risk_limits": to_jsonable(self.risk_limits) if self.risk_limits is not None else None,
            "agent_summary": _build_agent_summary(state, self._recent_transition_summaries),
        }
        extra_instructions_block = (
            "Additional policy instructions:\n" + self.extra_instructions.strip()
            if self.extra_instructions.strip()
            else "Additional policy instructions:\nNone."
        )
        return self._prompt_template.substitute(
            extra_instructions_block=extra_instructions_block,
            decision_context_json=json.dumps(context, ensure_ascii=False, sort_keys=True),
            action_schema_json=self._action_schema_text,
        )

    def _run_codex(self, prompt: str) -> dict[str, Any]:
        command = [
            self.command,
            "exec",
            "--skip-git-repo-check",
            "--color",
            "never",
            "-s",
            self.sandbox_mode,
            "--output-schema",
            str(DEFAULT_SCHEMA_PATH),
        ]
        if self.model:
            command.extend(["-m", self.model])

        decision_cwd = self.cwd or tempfile.gettempdir()
        with tempfile.TemporaryDirectory(prefix="arena_codex_policy_") as temp_dir:
            output_path = Path(temp_dir) / "decision.json"
            command.extend(["-o", str(output_path), "-"])
            result = self.subprocess_runner(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                cwd=decision_cwd,
                timeout=self.timeout_seconds,
                check=False,
            )
            if result.returncode != 0:
                stderr = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(f"codex exec failed with code={result.returncode}: {stderr[:500]}")
            if not output_path.exists():
                raise RuntimeError("codex exec produced no output file")
            raw_output = output_path.read_text(encoding="utf-8").strip()
            if not raw_output:
                raise RuntimeError("codex exec returned empty output")
            try:
                payload = json.loads(raw_output)
            except json.JSONDecodeError as exc:
                raise ValueError(f"codex exec returned invalid JSON: {raw_output[:500]}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"codex exec payload must be an object, got: {payload!r}")
        return payload

    def _load_recent_transition_summaries(self) -> list[dict[str, Any]]:
        path = Path(self.transition_path or "")
        if not path.exists():
            return []
        items: deque[dict[str, Any]] = deque(maxlen=self.recent_transition_limit)
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                items.append(_summarize_transition(payload))
        return list(items)


def _build_market_context(state: AgentState) -> dict[str, Any]:
    recent_candles = state.market.recent_candles[-8:]
    return {
        "symbol": state.market.symbol,
        "interval": state.market.interval,
        "last_price": state.market.last_price,
        "mark_price": state.market.mark_price,
        "volatility": state.market.volatility,
        "orderbook_imbalance": state.market.orderbook_imbalance,
        "funding_rate": state.market.funding_rate,
        "recent_candles": [
            {
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "close_time": candle.close_time,
            }
            for candle in recent_candles
        ],
    }


def _build_agent_summary(state: AgentState, recent_transitions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    last_transition = recent_transitions[-1] if recent_transitions else None
    consecutive_holds = 0
    for transition in reversed(recent_transitions):
        if transition.get("action") == "HOLD":
            consecutive_holds += 1
            continue
        break

    position_age_seconds = None
    if state.position is not None:
        open_time = state.position.metadata.get("openTime") if state.position.metadata else None
        if open_time is not None:
            try:
                position_age_seconds = max(0.0, state.timestamp - (float(open_time) / 1000.0))
            except (TypeError, ValueError):
                position_age_seconds = None

    return {
        "position_status": "flat" if state.position is None else state.position.direction,
        "position_size": None if state.position is None else state.position.size,
        "entry_price": None if state.position is None else state.position.entry_price,
        "position_age_seconds": position_age_seconds,
        "last_action": None if last_transition is None else last_transition.get("action"),
        "last_action_reason": None if last_transition is None else last_transition.get("reason"),
        "consecutive_holds": consecutive_holds,
        "signal_backend": state.signal_state.backend,
        "warmup_complete": state.signal_state.warmup_complete,
    }


def _summarize_transition(transition: TransitionEvent | dict[str, Any]) -> dict[str, Any]:
    if isinstance(transition, dict):
        action_payload = dict(transition.get("action", {}))
        execution_payload = dict(transition.get("execution_result", {}))
        metrics_payload = dict(transition.get("metrics", {}))
        return {
            "timestamp": transition.get("timestamp"),
            "action": action_payload.get("type"),
            "reason": action_payload.get("metadata", {}).get("reason"),
            "accepted": execution_payload.get("accepted"),
            "executed": execution_payload.get("executed"),
            "message": execution_payload.get("message"),
            "realized_pnl_delta": metrics_payload.get("realized_pnl_delta"),
            "equity_delta": metrics_payload.get("equity_delta"),
            "price_delta": metrics_payload.get("price_delta"),
            "position_changed": metrics_payload.get("position_changed"),
        }

    return {
        "timestamp": transition.timestamp,
        "action": transition.action.type.value,
        "reason": transition.action.metadata.get("reason"),
        "accepted": transition.execution_result.accepted,
        "executed": transition.execution_result.executed,
        "message": transition.execution_result.message,
        "realized_pnl_delta": transition.metrics.realized_pnl_delta,
        "equity_delta": transition.metrics.equity_delta,
        "price_delta": transition.metrics.price_delta,
        "position_changed": transition.metrics.position_changed,
    }
