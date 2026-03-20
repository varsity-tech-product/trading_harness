"""LLM-powered setup agent — configures the runtime agent's strategy."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
from string import Template
import tempfile
import time
from typing import Any

from arena_agent.agents.agent_exec_policy import (
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
class SetupDecision:
    action: str  # "update" or "hold"
    overrides: dict[str, Any] | None
    reason: str
    restart_runtime: bool
    next_check_seconds: int | None = None  # LLM-controlled poll interval
    chat_message: str | None = None  # optional message to competition chat

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "overrides": self.overrides,
            "reason": self.reason,
            "restart_runtime": self.restart_runtime,
            "next_check_seconds": self.next_check_seconds,
            "chat_message": self.chat_message,
        }


def _parse_indicator_spec(indicator_str: str) -> dict[str, Any] | None:
    """Parse 'NAME_PERIOD' format to FeatureSpec dict.

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
        return {"indicator": name, "params": {"timeperiod": period}}
    # No period — just the indicator name
    if re.match(r"^[A-Z_]+$", indicator_str):
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
        # Validate policy_params: all values must be numeric
        clean_params = {}
        if isinstance(policy_params, dict):
            for k, v in policy_params.items():
                try:
                    clean_params[k] = float(v) if isinstance(v, (int, float)) else float(v)
                    # Preserve int if it was int
                    if isinstance(v, int) or (isinstance(v, float) and v == int(v)):
                        clean_params[k] = int(clean_params[k])
                except (TypeError, ValueError):
                    logger.warning("Ignoring non-numeric policy_param %s=%r", k, v)

        if policy_type == "ensemble":
            members_raw = payload.get("ensemble_members", [])
            members = []
            for m in members_raw:
                if isinstance(m, dict) and "type" in m:
                    member = {"type": m["type"]}
                    if "params" in m and isinstance(m["params"], dict):
                        member["params"] = m["params"]
                    members.append(member)
            overrides["policy"] = {
                "type": "ensemble",
                "members": members or [{"type": "ma_crossover"}],
            }
        else:
            overrides["policy"] = {
                "type": policy_type,
                "params": clean_params,
            }

    # --- TP/SL (percentage-based -> fixed_pct) ---
    tp_pct = payload.get("tp_pct")
    sl_pct = payload.get("sl_pct")
    if tp_pct is not None or sl_pct is not None:
        tpsl: dict[str, Any] = {"type": "fixed_pct"}
        if tp_pct is not None:
            tp_pct = max(0.1, min(5.0, float(tp_pct)))
            tpsl["tp_pct"] = tp_pct / 100.0
        if sl_pct is not None:
            sl_pct = max(0.1, min(3.0, float(sl_pct)))
            tpsl["sl_pct"] = sl_pct / 100.0
        overrides.setdefault("strategy", {})["tpsl"] = tpsl

    # --- Sizing (percentage-based -> fixed_fraction) ---
    sizing_fraction = payload.get("sizing_fraction")
    if sizing_fraction is not None:
        sizing_fraction = max(1, min(20, float(sizing_fraction)))
        overrides.setdefault("strategy", {})["sizing"] = {
            "type": "fixed_fraction",
            "fraction": sizing_fraction / 100.0,
        }

    # --- Direction bias ---
    direction_bias = payload.get("direction_bias")
    if direction_bias in ("both", "long_only", "short_only"):
        overrides["risk_limits"] = {
            "allow_long": direction_bias != "short_only",
            "allow_short": direction_bias != "long_only",
        }

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

    # --- Always restart when policy changes ---
    if "policy" in overrides:
        pass  # restart_runtime handled by caller

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
    ):
        self.backend = backend
        self.model = model
        self.timeout = timeout
        self.mcp_config_path = mcp_config_path or _find_mcp_config()
        if not self.mcp_config_path:
            logger.warning(
                "No .mcp.json config found — setup agent will not have access to "
                "arena MCP tools (arena_klines, arena_leaderboard, etc). "
                "Set ARENA_ROOT or ARENA_HOME env var, or pass mcp_config_path explicitly."
            )
        self._resolved_backend = resolve_backend(backend, None)
        self._original_backend = self._resolved_backend
        self._consecutive_failures = 0
        self._max_consecutive_failures = max_consecutive_failures
        self._prompt_template = Template(
            _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
        )
        self._schema_text = _SCHEMA_PATH.read_text(encoding="utf-8").strip()

        # Strategy change cooldown state
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
        logger.info("Setup agent invoking %s (timeout=%ss)", self._resolved_backend, self.timeout)
        try:
            payload = self._run_cli(prompt)
            self._consecutive_failures = 0
            decision = self._parse_decision(payload)
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

            time_ok = elapsed >= _COOLDOWN_SECONDS
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
        return decision

    def _try_fallback(self) -> None:
        """Switch to an alternative backend after consecutive failures."""
        from arena_agent.agents.agent_exec_policy import _find_fallback_backend
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

    def _run_cli(self, prompt: str) -> dict[str, Any]:
        if self._resolved_backend == "claude":
            return self._run_claude(prompt)
        if self._resolved_backend == "gemini":
            return self._run_gemini(prompt)
        if self._resolved_backend == "openclaw":
            return self._run_openclaw(prompt)
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

    def _run_openclaw(self, prompt: str) -> dict[str, Any]:
        command = [
            "openclaw",
            "agent",
            "--local",
            "--json",
            "--agent", "arena-trader",
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
            if usage.get("cost_usd") is not None:
                parts.append(f"cost=${usage['cost_usd']}")
            if parts:
                logger.info("setup_agent LLM usage | %s", " ".join(parts))

        payloads = wrapper.get("payloads", [])
        if payloads and isinstance(payloads[0], dict):
            result_text = str(payloads[0].get("text", "")).strip()
        else:
            result_text = "\n".join(json_lines)
        result_text = _strip_markdown_fences(result_text)
        return json.loads(result_text)

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
        except json.JSONDecodeError as exc:
            raise ValueError(f"{backend_name} returned invalid JSON: {raw[:500]}") from exc

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
        if action not in ("update", "hold"):
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

        # Detect flat vs legacy format:
        # If the payload contains "policy" (a string), use the new flat path.
        # If the payload contains "overrides" (a dict), use the legacy path.
        uses_flat = isinstance(payload.get("policy"), str)
        uses_legacy = isinstance(payload.get("overrides"), dict)

        if action == "update" and uses_flat:
            overrides = _translate_flat_decision(payload)
            # Flat path always restarts when policy changes
            restart = "policy" in overrides
        elif action == "update" and uses_legacy:
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
        )


# Hard bounds on sizing params the setup agent can set.
_SIZING_BOUNDS: dict[str, tuple[float, float]] = {
    "fraction": (0.01, 0.20),
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
