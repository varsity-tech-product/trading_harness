"""LLM-powered setup agent — configures the runtime agent's strategy."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from string import Template
import tempfile
import time
from typing import Any

from arena_agent.agents.cli_backends import (
    _extract_usage,
    _strip_markdown_fences,
    resolve_backend,
)

logger = logging.getLogger("arena_agent.setup_agent")

_PROMPT_TEMPLATE_PATH = Path(__file__).with_name("setup_prompt_template.md")
_SCHEMA_PATH = Path(__file__).with_name("setup_action_schema.json")

# Strategy change cooldown settings
_COOLDOWN_SECONDS = 1200  # 20 minutes
_COOLDOWN_MIN_TRADES = 5
_CATASTROPHIC_DRAWDOWN_PCT = 0.03  # 3%


def _normalize_sizing(value: float) -> float:
    """Normalize sizing_fraction that may be in 0-1 range to 1-100 range.

    LLMs sometimes output 0.9 meaning 90% or 0.8 meaning 80%.
    If the value is below 1.0, assume it's a decimal fraction and rescale.
    Clamped to 10-100 (minimum 10% to prevent micro-positions that lose to fees).
    """
    if value < 1.0:
        value = value * 100.0
    return max(10, min(100, value))


def _parse_codex_jsonl(raw: str) -> str | None:
    """Parse Codex ``--json`` JSONL output, log events for auditing.

    Returns the text from the last ``item.completed`` agent_message,
    or ``None`` if no message was found.
    """
    final_text: str | None = None
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = event.get("type", "")

        if etype == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                final_text = item.get("text", "")
                logger.info("codex agent_message: %s", (final_text or "")[:1000])
            elif item.get("type") == "mcp_tool_call":
                logger.info(
                    "codex mcp_tool_call | server=%s tool=%s status=%s error=%s",
                    item.get("server", "?"),
                    item.get("tool", "?"),
                    item.get("status", "?"),
                    item.get("error"),
                )
            elif item.get("type") == "reasoning":
                summary = item.get("summary") or item.get("text") or ""
                if summary:
                    logger.info("codex reasoning: %s", summary[:2000])

        elif etype == "item.started":
            item = event.get("item", {})
            if item.get("type") == "mcp_tool_call":
                logger.info(
                    "codex mcp_tool_call start | server=%s tool=%s",
                    item.get("server", "?"),
                    item.get("tool", "?"),
                )

        elif etype == "turn.completed":
            usage = event.get("usage", {})
            parts = []
            if usage.get("input_tokens"):
                parts.append(f"in={usage['input_tokens']}")
            if usage.get("cached_input_tokens"):
                parts.append(f"cached={usage['cached_input_tokens']}")
            if usage.get("output_tokens"):
                parts.append(f"out={usage['output_tokens']}")
            if parts:
                logger.info("codex usage | %s", " ".join(parts))

        elif etype == "thread.started":
            logger.info("codex thread: %s", event.get("thread_id", "?"))

    return final_text


def _find_mcp_config() -> str | None:
    """Locate the .mcp.json config for arena MCP tools."""
    import os
    candidates = [
        os.environ.get("ARENA_ROOT"),
        os.environ.get("ARENA_HOME"),
        str(Path.cwd()),
        str(Path(__file__).resolve().parent.parent.parent),  # arena repo root
    ]
    for base in candidates:
        if base:
            path = Path(base) / ".mcp.json"
            if path.exists():
                return str(path)

    # Check alongside the arena-mcp/arena-agent CLI binary (npm global install)
    for cmd in ("arena-mcp", "arena-agent"):
        bin_path = shutil.which(cmd)
        if bin_path:
            pkg_dir = Path(bin_path).resolve().parent.parent / "lib" / "node_modules" / "@varsity-arena" / "agent"
            mcp_json = pkg_dir / ".mcp.json"
            if mcp_json.exists():
                return str(mcp_json)

    return None


def _load_mcp_server_entry(config_path: str | None, name: str = "arena") -> dict[str, Any] | None:
    """Load a named MCP server entry from a Claude-style ``.mcp.json`` file."""
    if not config_path:
        return None
    try:
        payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    servers = payload.get("mcpServers") or payload.get("servers") or {}
    if not isinstance(servers, dict):
        return None
    entry = servers.get(name)
    return entry if isinstance(entry, dict) else None


def _default_arena_mcp_entry() -> dict[str, Any] | None:
    """Build a default stdio MCP entry for the bundled arena server."""
    arena_root = (
        os.environ.get("ARENA_ROOT")
        or os.environ.get("ARENA_HOME")
        or str(Path(__file__).resolve().parent.parent.parent)
    )
    command = shutil.which("arena-mcp") or "arena-mcp"
    return {
        "command": command,
        "args": ["serve"],
        "env": {"ARENA_ROOT": arena_root},
    }


def _build_codex_mcp_overrides(config_path: str | None) -> list[str]:
    """Translate Arena MCP config into ``codex exec -c`` overrides.

    Codex does not expose a dedicated ``--mcp-config`` flag like Claude Code,
    but it does accept per-run config overrides. That lets the setup agent use
    native MCP without touching ``~/.codex/config.toml``.
    """
    entry = _load_mcp_server_entry(config_path, "arena") or _default_arena_mcp_entry()
    if not isinstance(entry, dict):
        return []

    url = entry.get("url")
    transport = str(entry.get("transport") or entry.get("type") or "stdio").lower()
    command = entry.get("command")
    args = entry.get("args") or []
    env = entry.get("env") or {}

    overrides: list[str] = []
    if isinstance(url, str) and url:
        overrides.extend(["-c", f"mcp_servers.arena.url={json.dumps(url)}"])
    elif transport == "stdio" and isinstance(command, str) and command:
        overrides.extend(["-c", f"mcp_servers.arena.command={json.dumps(command)}"])
        overrides.extend(["-c", f"mcp_servers.arena.args={json.dumps([str(a) for a in args])}"])
    else:
        return []

    if isinstance(env, dict):
        for key, value in env.items():
            if not isinstance(key, str):
                continue
            overrides.extend(["-c", f"mcp_servers.arena.env.{key}={json.dumps(str(value))}"])
    return overrides


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first top-level JSON object from mixed text/markdown output."""
    # Try to find a fenced block first
    fence_match = re.search(r"```(?:json)?\s*\n(\{.*?\})\s*\n```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass
    # Scan for first { and match braces
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


@dataclass
class TradeDecision:
    """A discretionary trade action from the setup agent."""
    type: str          # OPEN_LONG, OPEN_SHORT, CLOSE_POSITION, UPDATE_TPSL, HOLD
    tp_pct: float | None = None       # take profit %
    sl_pct: float | None = None       # stop loss %
    sizing_fraction: float | None = None  # % of equity

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type}
        if self.tp_pct is not None:
            d["tp_pct"] = self.tp_pct
        if self.sl_pct is not None:
            d["sl_pct"] = self.sl_pct
        if self.sizing_fraction is not None:
            d["sizing_fraction"] = self.sizing_fraction
        return d


@dataclass
class SetupDecision:
    action: str  # "update", "hold", or "trade"
    overrides: dict[str, Any] | None
    reason: str
    restart_runtime: bool
    next_check_seconds: int | None = None  # LLM-controlled poll interval
    chat_message: str | None = None  # optional message to competition chat
    trade: TradeDecision | None = None  # discretionary trade action
    mode: str | None = None  # "rule_based" or "discretionary"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "action": self.action,
            "overrides": self.overrides,
            "reason": self.reason,
            "restart_runtime": self.restart_runtime,
            "next_check_seconds": self.next_check_seconds,
            "chat_message": self.chat_message,
        }
        if self.trade is not None:
            d["trade"] = self.trade.to_dict()
        if self.mode is not None:
            d["mode"] = self.mode
        return d


def _get_valid_talib_names() -> set[str]:
    """Return the set of valid TA-Lib function names."""
    try:
        import talib
        return set(talib.get_functions())
    except Exception:
        return set()


_VALID_TALIB_NAMES: set[str] | None = None


def _is_valid_talib_indicator(name: str) -> bool:
    global _VALID_TALIB_NAMES
    if _VALID_TALIB_NAMES is None:
        _VALID_TALIB_NAMES = _get_valid_talib_names()
    return name.upper() in _VALID_TALIB_NAMES


def _parse_indicator_spec(indicator_str: str) -> dict[str, Any] | None:
    """Parse 'NAME_PERIOD' format to FeatureSpec dict.

    Only accepts indicators that exist in TA-Lib.

    Examples:
        'SMA_20' -> {'indicator': 'SMA', 'params': {'timeperiod': 20}}
        'MACD'   -> {'indicator': 'MACD'}
        'RSI_14' -> {'indicator': 'RSI', 'params': {'timeperiod': 14}}
    """
    indicator_str = indicator_str.strip()
    if not indicator_str:
        return None
    # Try to split on last underscore to get NAME_PERIOD
    match = re.match(r"^([A-Z_]+?)_(\d+)$", indicator_str)
    if match:
        name = match.group(1)
        period = int(match.group(2))
        if not _is_valid_talib_indicator(name):
            logging.getLogger("arena_agent.setup_agent").warning(
                "Indicator '%s' not found in TA-Lib — skipping", name,
            )
            return None
        return {"indicator": name, "params": {"timeperiod": period}}
    # No period — just the indicator name
    if re.match(r"^[A-Z_]+$", indicator_str):
        if not _is_valid_talib_indicator(indicator_str):
            logging.getLogger("arena_agent.setup_agent").warning(
                "Indicator '%s' not found in TA-Lib — skipping", indicator_str,
            )
            return None
        return {"indicator": indicator_str}
    return None


def _translate_flat_decision(payload: dict[str, Any]) -> dict[str, Any]:
    """Map the flat setup decision schema to internal config overrides.

    Converts percentage-based, flat fields into the nested config dict
    that the runtime expects.
    """
    overrides: dict[str, Any] = {}

    # --- Policy ---
    policy_type = payload.get("policy")
    if policy_type:
        policy_params = payload.get("policy_params", {})

        if policy_type == "ensemble":
            members_raw = payload.get("ensemble_members", [])
            members = []
            for m in members_raw:
                if isinstance(m, dict):
                    member = {"type": m.get("type", "expression")}
                    if "params" in m and isinstance(m["params"], dict):
                        member["params"] = m["params"]
                    members.append(member)
            overrides["policy"] = {
                "type": "ensemble",
                "members": members or [{"type": "expression", "params": {}}],
            }
        else:
            # Expression policy (default) — params are string expressions
            expr_params = {}
            if isinstance(policy_params, dict):
                for k in ("entry_long", "entry_short", "exit"):
                    if k in policy_params:
                        expr_params[k] = str(policy_params[k])
            overrides["policy"] = {"type": "expression", "params": expr_params}

    # --- TP/SL (percentage-based -> fixed_pct) ---
    tp_pct = payload.get("tp_pct")
    sl_pct = payload.get("sl_pct")
    if tp_pct is not None or sl_pct is not None:
        tpsl: dict[str, Any] = {"type": "fixed_pct"}
        if tp_pct is not None:
            tp_pct = max(0.5, min(5.0, float(tp_pct)))
            tpsl["tp_pct"] = tp_pct / 100.0
        if sl_pct is not None:
            sl_pct = max(0.3, min(3.0, float(sl_pct)))
            tpsl["sl_pct"] = sl_pct / 100.0
        overrides.setdefault("strategy", {})["tpsl"] = tpsl

    # --- Sizing (percentage-based -> fixed_fraction) ---
    # LLM outputs e.g. sizing_fraction=80 meaning 80%, but may output 0.8 meaning the same.
    sizing_fraction = payload.get("sizing_fraction")
    if sizing_fraction is not None:
        sizing_fraction = _normalize_sizing(float(sizing_fraction))
        overrides.setdefault("strategy", {})["sizing"] = {
            "type": "fixed_fraction",
            "fraction": sizing_fraction / 100.0,
        }

    # --- Direction bias ---
    # Ignored: direction bias is NOT applied to risk_limits.
    # Rule-based strategies decide trade direction based on their own signals.
    # The setup agent should not override allow_long/allow_short.

    # --- Indicators (NAME_PERIOD -> signal_indicators FeatureSpec list) ---
    indicators = payload.get("indicators")
    if isinstance(indicators, list) and indicators:
        signal_indicators = []
        for ind_str in indicators:
            spec = _parse_indicator_spec(str(ind_str))
            if spec:
                signal_indicators.append(spec)
        if signal_indicators:
            overrides["signal_indicators"] = signal_indicators
            # Ensure custom indicator mode when specifying indicators
            overrides.setdefault("policy", {})["indicator_mode"] = "custom"

    # --- Clear max_absolute_size so runtime computes from fraction + equity ---
    overrides.setdefault("risk_limits", {})["max_absolute_size"] = None

    # --- Cooldown override (agent can adjust the cooldown period) ---
    cooldown_seconds = payload.get("cooldown_seconds")
    if cooldown_seconds is not None:
        try:
            cooldown_seconds = max(60, min(3600, int(cooldown_seconds)))
            overrides["_cooldown_seconds"] = cooldown_seconds
        except (TypeError, ValueError):
            pass

    # --- Always restart when policy changes ---
    if "policy" in overrides:
        pass  # restart_runtime handled by caller

    logger.info(
        "flat_decision translated | policy=%s tp_pct=%s sl_pct=%s sizing=%s bias=%s indicators=%d",
        payload.get("policy"),
        payload.get("tp_pct"),
        payload.get("sl_pct"),
        payload.get("sizing_fraction"),
        payload.get("direction_bias"),
        len(overrides.get("signal_indicators", [])),
    )
    return overrides


class SetupAgent:
    """Runs an LLM to decide config changes for the runtime agent."""

    def __init__(
        self,
        backend: str = "auto",
        model: str | None = None,
        timeout: float = 300.0,
        mcp_config_path: str | None = None,
        max_consecutive_failures: int = 2,
        openclaw_agent_id: str | None = None,
        tool_proxy_enabled: bool = True,
        tool_proxy_max_rounds: int = 5,
    ):
        self.backend = backend
        self.model = model
        self.timeout = timeout
        self.openclaw_agent_id = openclaw_agent_id
        self.mcp_config_path = mcp_config_path or _find_mcp_config()
        self._resolved_backend = resolve_backend(backend, None)
        self._codex_mcp_overrides = (
            _build_codex_mcp_overrides(self.mcp_config_path)
            if self._resolved_backend == "codex"
            else []
        )
        self.tool_proxy_enabled = tool_proxy_enabled
        self.tool_proxy_max_rounds = tool_proxy_max_rounds
        if self._resolved_backend == "codex" and self._codex_mcp_overrides:
            if self.tool_proxy_enabled:
                logger.info("Codex native MCP enabled — bypassing tool proxy.")
            self.tool_proxy_enabled = False
        native_mcp_enabled = (
            bool(self.mcp_config_path)
            if self._resolved_backend == "claude"
            else bool(self._codex_mcp_overrides)
            if self._resolved_backend == "codex"
            else False
        )
        if not native_mcp_enabled and not self.tool_proxy_enabled:
            logger.warning(
                "Native MCP unavailable and tool proxy disabled — setup agent "
                "will not have access to arena tools for deeper analysis."
            )
        self._original_backend = self._resolved_backend
        self._consecutive_failures = 0
        self._max_consecutive_failures = max_consecutive_failures
        self._prompt_template = Template(
            _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
        )
        self._schema_text = _SCHEMA_PATH.read_text(encoding="utf-8").strip()

        # Strategy change cooldown state (agent can override via cooldown_seconds)
        self._cooldown_seconds: float = _COOLDOWN_SECONDS
        self._last_strategy_change_time: float | None = None
        self._last_strategy_key: str | None = None  # "policy_type:params_hash"
        self._equity_at_last_change: float | None = None
        self._trades_since_last_change: int = 0

    def decide(self, context: dict[str, Any], memory_context: str = "") -> SetupDecision:
        """Send context to LLM, get config update decision."""
        # Track trade count for cooldown
        perf = context.get("performance", {})
        if isinstance(perf, dict):
            current_trade_count = perf.get("trade_count", 0)
        else:
            current_trade_count = 0

        prompt = self._render_prompt(context, memory_context)

        # Append tool catalog so the agent can request additional data.
        if self.tool_proxy_enabled:
            from arena_agent.agents.tool_proxy import build_tool_prompt_section
            comp = context.get("competition", {})
            prompt += build_tool_prompt_section(
                context_type="setup",
                competition_id=comp.get("id") if isinstance(comp, dict) else None,
                symbol=comp.get("symbol") if isinstance(comp, dict) else None,
            )

        logger.info("Setup agent invoking %s (timeout=%ss)", self._resolved_backend, self.timeout)
        try:
            try:
                payload = self._run_cli_with_tools(prompt)
            except (ValueError, json.JSONDecodeError) as json_exc:
                if "not valid JSON" in str(json_exc) or isinstance(json_exc, json.JSONDecodeError):
                    logger.warning("LLM returned invalid JSON — retrying with feedback: %s", json_exc)
                    retry_prompt = (
                        prompt
                        + "\n\n--- JSON Parse Error ---\n"
                        "Your previous response was NOT valid JSON and could not be parsed.\n"
                        f"Error: {json_exc}\n"
                        "You MUST return a single valid JSON object. "
                        "If using tool_calls, put ALL calls in ONE array: "
                        '{"tool_calls": [{"tool": "...", "args": {...}}, {"tool": "...", "args": {...}}]}\n'
                        "Return your corrected JSON now.\n"
                        "--- End Error ---"
                    )
                    payload = self._run_cli_with_tools(retry_prompt)
                else:
                    raise
            self._consecutive_failures = 0
            decision = self._parse_decision(payload)
            # Check for exit/entry overlap and let the LLM retry once
            overlap_error = self._check_expression_overlap(decision, context)
            if overlap_error:
                logger.warning("Expression overlap detected — re-invoking LLM: %s", overlap_error)
                retry_prompt = (
                    prompt
                    + f"\n\n--- Expression Overlap Error ---\n"
                    f"Your previous response was REJECTED because of exit/entry overlap:\n"
                    f"{overlap_error}\n"
                    f"The exit expression fires at the same time as the entry expression, "
                    f"causing immediate close after open (fee death). "
                    f"Fix the exit expression so it does NOT fire when the entry fires. "
                    f"Return your corrected decision JSON.\n"
                    f"--- End Error ---"
                )
                payload = self._run_cli_with_tools(retry_prompt)
                decision = self._parse_decision(payload)
                # Check again — if still overlapping, demote to hold
                retry_overlap = self._check_expression_overlap(decision, context)
                if retry_overlap:
                    logger.warning("Expression overlap persists after retry — demoting to hold")
                    return SetupDecision(
                        action="hold", overrides=None,
                        reason=f"expression_overlap_rejected: {retry_overlap}",
                        restart_runtime=False,
                        next_check_seconds=decision.next_check_seconds,
                        chat_message=decision.chat_message,
                    )
            # Apply cooldown enforcement
            decision = self._apply_cooldown(decision, context, current_trade_count)
            return decision
        except Exception as exc:
            self._consecutive_failures += 1
            logger.warning("Setup agent decision failed (%d consecutive): %s", self._consecutive_failures, exc)
            if self._consecutive_failures >= self._max_consecutive_failures:
                self._try_fallback()
            return SetupDecision(
                action="hold",
                overrides=None,
                reason=f"setup_error: {exc}",
                restart_runtime=False,
            )

    def _apply_cooldown(
        self,
        decision: SetupDecision,
        context: dict[str, Any],
        current_trade_count: int,
    ) -> SetupDecision:
        """Enforce strategy change cooldown to prevent rapid thrashing."""
        if decision.action != "update" or not decision.overrides:
            return decision

        # Determine if policy is actually changing
        new_policy = decision.overrides.get("policy", {})
        if not isinstance(new_policy, dict) or "type" not in new_policy:
            return decision  # Not a policy change, allow it

        new_key = f"{new_policy.get('type')}:{json.dumps(new_policy.get('params', {}), sort_keys=True)}"
        if self._last_strategy_key is not None and new_key == self._last_strategy_key:
            return decision  # Same strategy, no cooldown needed

        # Check cooldown conditions
        if self._last_strategy_change_time is not None:
            elapsed = time.time() - self._last_strategy_change_time
            trades_since = current_trade_count - self._trades_since_last_change

            time_ok = elapsed >= self._cooldown_seconds
            trades_ok = trades_since >= _COOLDOWN_MIN_TRADES

            if not time_ok and not trades_ok:
                # Check catastrophic exception
                acct = context.get("account_state", {})
                if isinstance(acct, dict):
                    current_equity = acct.get("equity", 0)
                    if (
                        self._equity_at_last_change is not None
                        and self._equity_at_last_change > 0
                        and current_equity > 0
                    ):
                        drawdown = (self._equity_at_last_change - current_equity) / self._equity_at_last_change
                        if drawdown > _CATASTROPHIC_DRAWDOWN_PCT:
                            logger.warning(
                                "Strategy cooldown bypassed: %.1f%% drawdown exceeds %.1f%% threshold",
                                drawdown * 100, _CATASTROPHIC_DRAWDOWN_PCT * 100,
                            )
                        else:
                            # Demote to hold
                            logger.info(
                                "Strategy cooldown: demoting update to hold (%.0fs / %d trades since last change)",
                                elapsed, trades_since,
                            )
                            return SetupDecision(
                                action="hold",
                                overrides=None,
                                reason=f"strategy_cooldown: {int(elapsed)}s / {trades_since} trades since last change",
                                restart_runtime=False,
                                next_check_seconds=decision.next_check_seconds,
                                chat_message=decision.chat_message,
                            )
                    else:
                        # Can't compute drawdown — enforce cooldown
                        logger.info(
                            "Strategy cooldown: demoting update to hold (%.0fs / %d trades since last change)",
                            elapsed, trades_since,
                        )
                        return SetupDecision(
                            action="hold",
                            overrides=None,
                            reason=f"strategy_cooldown: {int(elapsed)}s / {trades_since} trades since last change",
                            restart_runtime=False,
                            next_check_seconds=decision.next_check_seconds,
                            chat_message=decision.chat_message,
                        )

        # Record this strategy change
        self._last_strategy_change_time = time.time()
        self._last_strategy_key = new_key
        self._trades_since_last_change = current_trade_count
        acct = context.get("account_state", {})
        if isinstance(acct, dict):
            self._equity_at_last_change = acct.get("equity")
        logger.info(
            "Strategy change accepted | new_key=%s equity_snapshot=%s trade_count=%d",
            new_key, self._equity_at_last_change, current_trade_count,
        )
        return decision

    @staticmethod
    def _check_expression_overlap(
        decision: SetupDecision,
        context: dict[str, Any],
    ) -> str | None:
        """Check if exit expression overlaps with entry expressions at current values.

        Returns an error message if overlap detected, None otherwise.
        """
        if decision.action != "update" or not decision.overrides:
            return None
        policy = decision.overrides.get("policy", {})
        if not isinstance(policy, dict) or policy.get("type") != "expression":
            return None
        params = policy.get("params", {})
        entry_long = params.get("entry_long", "")
        entry_short = params.get("entry_short", "")
        exit_expr = params.get("exit", "")
        if not entry_long or not entry_short or not exit_expr:
            return None

        # Build namespace from current indicator values
        from arena_agent.agents.expression_policy import _safe_eval
        ind_vals = context.get("current_indicator_values", {})
        ns: dict = {}
        if isinstance(ind_vals, dict):
            for k, v in ind_vals.items():
                ns[k] = v.get("current", 0) if isinstance(v, dict) else v
        mkt = context.get("market_summary", {})
        if isinstance(mkt, dict) and mkt.get("current_price"):
            ns.setdefault("close", mkt["current_price"])

        overlaps = []
        if _safe_eval(entry_long, ns) and _safe_eval(exit_expr, ns):
            overlaps.append(
                f"entry_long '{entry_long}' and exit '{exit_expr}' both TRUE "
                f"at current values — longs will close immediately"
            )
        if _safe_eval(entry_short, ns) and _safe_eval(exit_expr, ns):
            overlaps.append(
                f"entry_short '{entry_short}' and exit '{exit_expr}' both TRUE "
                f"at current values — shorts will close immediately"
            )
        return "; ".join(overlaps) if overlaps else None

    def _try_fallback(self) -> None:
        """Switch to an alternative backend after consecutive failures."""
        from arena_agent.agents.cli_backends import _find_fallback_backend
        fallback = _find_fallback_backend(self._resolved_backend)
        if fallback is None:
            return
        logger.warning(
            "Setup agent: %s failed %d times — falling back to %s.",
            self._resolved_backend, self._consecutive_failures, fallback,
        )
        self._resolved_backend = fallback
        self._consecutive_failures = 0

    def _render_prompt(self, context: dict[str, Any], memory_context: str) -> str:
        memory_block = ""
        if memory_context:
            memory_block = (
                "Past competition memory (use this to avoid repeating bad strategies):\n"
                + memory_context
            )
        return self._prompt_template.substitute(
            memory_context=memory_block,
            setup_context_json=json.dumps(context, ensure_ascii=False, default=str),
        )

    def _run_cli_with_tools(self, prompt: str) -> dict[str, Any]:
        """Run CLI with optional tool proxy loop."""
        if not self.tool_proxy_enabled:
            return self._run_cli(prompt)

        from arena_agent.agents.tool_proxy import ToolProxyConfig, run_tool_proxy_loop
        proxy_config = ToolProxyConfig(
            enabled=True,
            max_rounds=self.tool_proxy_max_rounds,
            context_type="setup",
        )
        return run_tool_proxy_loop(self._run_cli, prompt, proxy_config)

    def _run_cli(self, prompt: str) -> dict[str, Any]:
        if self._resolved_backend == "claude":
            return self._run_claude(prompt)
        if self._resolved_backend == "gemini":
            return self._run_gemini(prompt)
        if self._resolved_backend == "openclaw":
            return self._run_openclaw(prompt)
        if self._resolved_backend == "codex":
            return self._run_codex(prompt)
        return self._run_claude(prompt)

    def _run_claude(self, prompt: str) -> dict[str, Any]:
        command = [
            "claude",
            "-p",
            "--no-session-persistence",
            "--output-format", "json",
        ]
        if self.model:
            command.extend(["--model", self.model])
        if self.mcp_config_path:
            command.extend(["--mcp-config", self.mcp_config_path])
            command.extend(["--allowedTools", "mcp__arena__*"])
        return self._exec_subprocess(command, prompt, "claude")

    def _run_gemini(self, prompt: str) -> dict[str, Any]:
        command = [
            "gemini",
            "-p", "",
            "--output-format", "json",
            "--sandbox",
        ]
        if self.model:
            command.extend(["-m", self.model])
        return self._exec_subprocess(command, prompt, "gemini", response_key="response")

    def _run_codex(self, prompt: str) -> dict[str, Any]:
        command = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--color", "never",
            "--json",
            "-c", 'model_reasoning_effort="medium"',
            "-c", 'model_reasoning_summaries="verbose"',
        ]
        if self._codex_mcp_overrides:
            command.extend(self._codex_mcp_overrides)
        if self.model:
            command.extend(["-m", self.model])
        command.append("-")
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=tempfile.gettempdir(),
            timeout=self.timeout,
            check=False,
        )
        stderr_text = (result.stderr or "").strip()
        if stderr_text:
            logger.info("setup_agent codex stderr:\n%s", stderr_text[:2000])
        # Parse JSONL events from stdout for audit logging
        raw = (result.stdout or "").strip()
        final_text = _parse_codex_jsonl(raw)
        if result.returncode != 0:
            raise RuntimeError(f"codex failed with code={result.returncode}: {(stderr_text or raw)[:500]}")
        if not final_text:
            raise RuntimeError("codex returned no assistant message")
        result_text = _strip_markdown_fences(final_text)
        try:
            payload = json.loads(result_text)
        except json.JSONDecodeError:
            payload = _extract_json_object(result_text)
            if payload is None:
                raise ValueError(f"codex result is not valid JSON: {result_text[:500]}")
        if not isinstance(payload, dict):
            raise ValueError(f"codex payload must be an object, got: {payload!r}")
        logger.info("setup_agent decision: %s", json.dumps(payload, default=str)[:1000])
        return payload

    @staticmethod
    def _detect_openclaw_agent() -> str:
        """Auto-detect the best openclaw agent from the user's existing config.

        Reads ``~/.openclaw/openclaw.json`` (never modifies it) and looks for
        arena-specific agents that already have a model configured.  Falls back
        to ``main`` if nothing better is found.
        """
        config_path = Path.home() / ".openclaw" / "openclaw.json"
        if not config_path.exists():
            return "main"
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "main"
        agents = cfg.get("agents", {}).get("list", [])
        # Prefer arena-specific agents that have a model configured
        for preferred in ("arena-setup", "arena-trader"):
            for agent in agents:
                if agent.get("id") == preferred and agent.get("model"):
                    logger.info("openclaw auto-detected agent '%s' (model=%s)", preferred, agent["model"])
                    return preferred
        return "main"

    def _run_openclaw(self, prompt: str) -> dict[str, Any]:
        # Use whichever openclaw agent the user configured.
        # Defaults to auto-detected arena agent, or "main".
        from arena_agent.agents.cli_backends import _clear_openclaw_sessions
        agent_id = self.openclaw_agent_id or self._detect_openclaw_agent()
        _clear_openclaw_sessions(agent_id)
        command = [
            "openclaw",
            "agent",
            "--local",
            "--json",
            "--agent", agent_id,
            "--message", prompt,
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=tempfile.gettempdir(),
            timeout=self.timeout,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"openclaw failed: {(result.stderr or result.stdout or '')[:500]}")
        raw = (result.stdout or "").strip()
        if not raw:
            raise RuntimeError("openclaw returned empty output")
        # Extract JSON from openclaw output
        json_lines: list[str] = []
        brace_depth = 0
        for line in raw.split("\n"):
            stripped = line.lstrip()
            if brace_depth == 0 and not stripped.startswith("{"):
                continue
            json_lines.append(line)
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                break
        wrapper = json.loads("\n".join(json_lines))

        # Log normalized LLM usage
        usage = _extract_usage(wrapper, "openclaw")
        if usage:
            parts = []
            if usage.get("input_tokens") is not None:
                parts.append(f"in={usage['input_tokens']}")
            if usage.get("output_tokens") is not None:
                parts.append(f"out={usage['output_tokens']}")
            if usage.get("cache_read_input_tokens") is not None:
                parts.append(f"cached={usage['cache_read_input_tokens']}")
            if usage.get("duration_ms") is not None:
                parts.append(f"duration={usage['duration_ms']}ms")
            if usage.get("model"):
                parts.append(f"model={usage['model']}")
            if parts:
                logger.info("setup_agent LLM usage | %s", " ".join(parts))

        payloads = wrapper.get("payloads", [])
        if payloads and isinstance(payloads[0], dict):
            result_text = str(payloads[0].get("text", "")).strip()
        else:
            result_text = "\n".join(json_lines)
        result_text = _strip_markdown_fences(result_text)
        try:
            return json.loads(result_text)
        except json.JSONDecodeError:
            payload = _extract_json_object(result_text)
            if payload is None:
                raise ValueError(f"openclaw result is not valid JSON: {result_text[:500]}")
            return payload

    def _exec_subprocess(
        self,
        command: list[str],
        prompt: str,
        backend_name: str,
        response_key: str = "result",
    ) -> dict[str, Any]:
        logger.debug("setup_agent cmd: %s", " ".join(command))
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=tempfile.gettempdir(),
            timeout=self.timeout,
            check=False,
        )
        stderr_text = (result.stderr or "").strip()
        if stderr_text:
            logger.info("setup_agent stderr:\n%s", stderr_text[:2000])
        if result.returncode != 0:
            raise RuntimeError(f"{backend_name} failed with code={result.returncode}: {(stderr_text or result.stdout or '')[:500]}")
        raw = (result.stdout or "").strip()
        if not raw:
            raise RuntimeError(f"{backend_name} returned empty output")
        logger.debug("setup_agent raw output (%d bytes): %s", len(raw), raw[:3000])

        try:
            wrapper = json.loads(raw)
        except json.JSONDecodeError:
            # Gemini and other CLIs may prefix output with warnings
            # (e.g. "MCP issues detected..."). Extract the first JSON object.
            wrapper = _extract_json_object(raw)
            if wrapper is None:
                raise ValueError(f"{backend_name} returned invalid JSON: {raw[:500]}")

        # Log tool use from the wrapper if present
        if isinstance(wrapper, dict):
            for key in ("tool_uses", "tool_use", "messages"):
                if key in wrapper:
                    logger.info("setup_agent %s: %s", key, json.dumps(wrapper[key], default=str)[:2000])
            # Log cost/usage stats if available
            for key in ("usage", "stats", "cost_usd", "duration_ms", "num_turns"):
                if key in wrapper:
                    logger.info("setup_agent %s: %s", key, wrapper[key])

        # Log normalized LLM usage
        usage = _extract_usage(wrapper, backend_name)
        if usage:
            parts = []
            if usage.get("input_tokens") is not None:
                parts.append(f"in={usage['input_tokens']}")
            if usage.get("output_tokens") is not None:
                parts.append(f"out={usage['output_tokens']}")
            if usage.get("cost_usd") is not None:
                parts.append(f"cost=${usage['cost_usd']}")
            if usage.get("duration_ms") is not None:
                parts.append(f"duration={usage['duration_ms']}ms")
            if parts:
                logger.info("setup_agent LLM usage | %s", " ".join(parts))

        if isinstance(wrapper, dict) and response_key in wrapper:
            result_text = str(wrapper[response_key]).strip()
        else:
            result_text = raw

        result_text = _strip_markdown_fences(result_text)

        try:
            payload = json.loads(result_text)
        except json.JSONDecodeError:
            # Claude may return reasoning text before/after JSON — extract it
            payload = _extract_json_object(result_text)
            if payload is None:
                raise ValueError(f"{backend_name} result is not valid JSON: {result_text[:500]}")
        if not isinstance(payload, dict):
            raise ValueError(f"{backend_name} payload must be an object, got: {payload!r}")
        logger.info("setup_agent decision: %s", json.dumps(payload, default=str)[:1000])
        return payload

    @staticmethod
    def _parse_decision(payload: dict[str, Any]) -> SetupDecision:
        action = str(payload.get("action", "hold")).lower()
        if action not in ("update", "hold", "trade"):
            action = "hold"
        # Parse next_check_seconds, clamp to 60-3600
        next_check = payload.get("next_check_seconds")
        if next_check is not None:
            try:
                next_check = max(60, min(3600, int(next_check)))
            except (TypeError, ValueError):
                next_check = None
        chat_msg = payload.get("chat_message")
        if chat_msg is not None:
            chat_msg = str(chat_msg).strip() or None

        # Parse mode switch
        mode = payload.get("mode")
        if mode is not None:
            mode = str(mode).lower()
            if mode not in ("rule_based", "discretionary"):
                mode = None

        # Parse discretionary trade
        trade = None
        trade_raw = payload.get("trade")
        if action == "trade" and isinstance(trade_raw, dict):
            trade_type = str(trade_raw.get("type", "HOLD")).upper()
            if trade_type not in ("OPEN_LONG", "OPEN_SHORT", "CLOSE_POSITION", "UPDATE_TPSL", "HOLD"):
                trade_type = "HOLD"
            tp_pct = trade_raw.get("tp_pct")
            sl_pct = trade_raw.get("sl_pct")
            sizing_fraction = trade_raw.get("sizing_fraction")
            if tp_pct is not None:
                tp_pct = max(0.5, min(5.0, float(tp_pct)))
            if sl_pct is not None:
                sl_pct = max(0.3, min(3.0, float(sl_pct)))
            if sizing_fraction is not None:
                sizing_fraction = _normalize_sizing(float(sizing_fraction))
            trade = TradeDecision(
                type=trade_type,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
                sizing_fraction=sizing_fraction,
            )
            logger.info("_parse_decision: discretionary trade type=%s tp=%.2s sl=%.2s size=%.2s",
                        trade_type, tp_pct, sl_pct, sizing_fraction)
        elif action == "trade" and trade_raw is None:
            # Agent said "trade" but didn't provide trade object — demote to hold
            logger.warning("_parse_decision: action=trade but no trade object — demoting to hold")
            action = "hold"

        # Detect flat vs legacy format:
        # If the payload contains "policy" (a string), use the new flat path.
        # If the payload contains "overrides" (a dict), use the legacy path.
        uses_flat = isinstance(payload.get("policy"), str)
        uses_legacy = isinstance(payload.get("overrides"), dict)

        if action == "update" and uses_flat:
            logger.info("_parse_decision: using FLAT schema path (policy=%s)", payload.get("policy"))
            overrides = _translate_flat_decision(payload)
            # Only flag restart when the policy TYPE is present in overrides.
            # TP/SL/sizing tweaks are applied via deep_merge without restarting.
            restart = isinstance(overrides.get("policy"), dict) and "type" in overrides.get("policy", {})
        elif action == "update" and uses_legacy:
            logger.info("_parse_decision: using LEGACY overrides path (keys=%s)", list(payload["overrides"].keys()))
            overrides = payload["overrides"]
            overrides = _clamp_sizing_params(overrides)
            restart = bool(payload.get("restart_runtime", False))
        else:
            overrides = None
            restart = bool(payload.get("restart_runtime", False))

        return SetupDecision(
            action=action,
            overrides=overrides,
            reason=str(payload.get("reason", "no reason")),
            restart_runtime=restart,
            next_check_seconds=next_check,
            chat_message=chat_msg,
            trade=trade,
            mode=mode,
        )


# Hard bounds on sizing params the setup agent can set.
_SIZING_BOUNDS: dict[str, tuple[float, float]] = {
    "fraction": (0.01, 0.50),
    "target_risk_pct": (0.005, 0.05),
    "max_risk_pct": (0.005, 0.03),
    "atr_multiplier": (0.5, 5.0),
    "fallback_atr_multiplier": (0.5, 5.0),
}


def _clamp_sizing_params(overrides: dict[str, Any]) -> dict[str, Any]:
    """Clamp strategy sizing params to safe bounds."""
    sizing = overrides.get("strategy", {}).get("sizing")
    if not isinstance(sizing, dict):
        return overrides
    changed = False
    for param, (lo, hi) in _SIZING_BOUNDS.items():
        if param in sizing:
            try:
                val = float(sizing[param])
                clamped = max(lo, min(hi, val))
                if clamped != val:
                    logger.warning(
                        "Setup agent clamped sizing.%s: %.4f → %.4f (bounds [%.4f, %.4f])",
                        param, val, clamped, lo, hi,
                    )
                    sizing[param] = clamped
                    changed = True
            except (TypeError, ValueError):
                pass
    return overrides
