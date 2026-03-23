"""Tool proxy — lets agents call arena tools without MCP configuration.

Instead of requiring the user to configure MCP servers in their agent's
global config, we describe available tools in the prompt and execute
tool-call requests locally via ``varsity_tools.dispatch()``.

The agent signals a tool-call request by including a ``"tool_calls"`` key
in its JSON response.  The proxy executes the calls, appends results to
the prompt, and re-invokes the CLI.  When the agent omits ``tool_calls``
the response is treated as the final answer and returned to the caller.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import varsity_tools

logger = logging.getLogger("arena_agent.tool_proxy")

# ---------------------------------------------------------------------------
# Tool catalog — generated from varsity_tools.TOOLS at runtime
# ---------------------------------------------------------------------------

TOOL_GROUPS: dict[str, list[str]] = {
    "market_data": [
        "get_klines", "get_orderbook", "get_market_info", "get_symbols",
    ],
    "trading": [
        "trade_open", "trade_close", "trade_update_tpsl",
        "get_live_trades", "get_live_position", "get_live_account",
    ],
    "competitions": [
        "get_competitions", "get_competition_detail", "get_participants",
        "register_competition", "withdraw_competition",
        "get_my_registration", "get_my_registrations",
    ],
    "leaderboard": [
        "get_competition_leaderboard", "get_competition_leaderboard_me",
        "get_season_leaderboard",
    ],
    "social": [
        "send_chat", "get_chat_history",
    ],
    "profile": [
        "get_my_profile", "get_arena_profile", "get_my_history",
        "get_my_history_detail", "get_achievements",
        "get_public_profile", "get_public_history",
    ],
    "hub": [
        "get_hub", "get_my_registrations",
    ],
    "predictions": [
        "get_predictions", "submit_prediction", "get_polls", "vote_poll",
    ],
    "notifications": [
        "get_notifications", "get_unread_notification_count",
        "mark_notification_read", "mark_all_notifications_read",
    ],
    "system": [
        "get_health", "get_version", "get_arena_health",
    ],
}

# Pre-select relevant groups for different agent contexts.
SETUP_GROUPS = [
    "market_data", "trading", "competitions", "leaderboard", "social",
    "profile", "hub", "predictions",
]
RUNTIME_GROUPS = [
    "market_data", "trading", "leaderboard",
]

# Index of tool definitions keyed by name (built lazily).
_TOOL_INDEX: dict[str, dict[str, Any]] | None = None


def _get_tool_index() -> dict[str, dict[str, Any]]:
    global _TOOL_INDEX
    if _TOOL_INDEX is None:
        _TOOL_INDEX = {t["name"]: t for t in varsity_tools.TOOLS}
    return _TOOL_INDEX


def _format_tool_signature(tool_def: dict[str, Any]) -> str:
    """Return a compact one-line signature like ``get_klines(symbol, interval, size?) — description``."""
    params = tool_def.get("parameters", {}).get("properties", {})
    required = set(tool_def.get("parameters", {}).get("required", []))
    parts: list[str] = []
    for pname, pschema in params.items():
        ptype = pschema.get("type", "any")
        if pname in required:
            parts.append(f"{pname}: {ptype}")
        else:
            parts.append(f"{pname}?: {ptype}")
    sig = ", ".join(parts)
    desc = tool_def.get("description", "")
    # Truncate long descriptions.
    if len(desc) > 100:
        desc = desc[:97] + "..."
    return f"{tool_def['name']}({sig}) — {desc}"


def build_tool_catalog(groups: list[str] | None = None) -> str:
    """Generate a compact tool catalog string grouped by category.

    Parameters
    ----------
    groups:
        Category names from :data:`TOOL_GROUPS`.  ``None`` means all groups.
    """
    index = _get_tool_index()
    selected_groups = groups or list(TOOL_GROUPS.keys())
    sections: list[str] = []
    seen: set[str] = set()
    for group_name in selected_groups:
        tool_names = TOOL_GROUPS.get(group_name, [])
        lines: list[str] = []
        for tname in tool_names:
            if tname in seen:
                continue
            seen.add(tname)
            tdef = index.get(tname)
            if tdef:
                lines.append("  " + _format_tool_signature(tdef))
        if lines:
            label = group_name.replace("_", " ").title()
            sections.append(f"[{label}]\n" + "\n".join(lines))
    return "\n\n".join(sections)


def build_tool_prompt_section(
    context_type: str = "setup",
    competition_id: int | None = None,
    symbol: str | None = None,
) -> str:
    """Build the prompt section that describes available tools.

    This is appended to the main prompt so the agent knows what tools
    it can request.
    """
    groups = SETUP_GROUPS if context_type == "setup" else RUNTIME_GROUPS
    catalog = build_tool_catalog(groups)

    hints: list[str] = []
    if competition_id is not None:
        hints.append(f"  competition_id = {competition_id}")
    if symbol:
        hints.append(f"  symbol = \"{symbol}\"")
    hint_block = ""
    if hints:
        hint_block = "\nCommon parameter values for this session:\n" + "\n".join(hints) + "\n"

    return f"""

## Available Tools

You can request additional data or perform actions by including a "tool_calls"
array in your JSON response.  Example:

{{"tool_calls": [{{"tool": "get_klines", "args": {{"symbol": "BTCUSDT", "interval": "5m", "size": 50}}}}]}}

The runtime will execute the tools and send you the results.  You will then
be re-invoked to continue your analysis or return your final decision.

When you have enough information, omit "tool_calls" and return your final
decision directly.

Rules:
- Max 3 tool calls per round.
- Return your final decision as soon as you can — do not call tools unnecessarily.
- If a tool returns an error, adapt or proceed with your decision.
{hint_block}
{catalog}
"""


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def extract_tool_calls(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Extract ``tool_calls`` from a parsed LLM response.

    Returns ``None`` when the response is a final answer (no tool calls).
    """
    calls = payload.get("tool_calls")
    if not isinstance(calls, list) or len(calls) == 0:
        return None
    valid: list[dict[str, Any]] = []
    for call in calls:
        if isinstance(call, dict) and "tool" in call:
            valid.append({
                "tool": str(call["tool"]),
                "args": dict(call.get("args") or {}),
            })
    return valid if valid else None


def execute_tool_calls(
    calls: list[dict[str, Any]],
    *,
    max_per_round: int = 3,
) -> list[dict[str, Any]]:
    """Execute tool calls via ``varsity_tools.dispatch()`` and return results.

    Each result dict has keys ``tool``, ``args``, ``result``.
    """
    results: list[dict[str, Any]] = []
    for call in calls[:max_per_round]:
        name = call["tool"]
        args = call["args"]
        logger.info("Executing tool: %s(%s)", name, json.dumps(args, default=str)[:200])
        try:
            result = varsity_tools.dispatch(name, **args)
        except Exception as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
        results.append({"tool": name, "args": args, "result": result})
    return results


def format_tool_results(
    results: list[dict[str, Any]],
    round_num: int,
    *,
    max_result_chars: int = 4000,
) -> str:
    """Format tool results as text to append to the prompt."""
    lines: list[str] = [f"\n--- Tool Results (round {round_num}) ---"]
    for r in results:
        args_str = ", ".join(f"{k}={json.dumps(v, default=str)}" for k, v in r["args"].items())
        result_json = json.dumps(r["result"], default=str, ensure_ascii=False)
        if len(result_json) > max_result_chars:
            result_json = result_json[:max_result_chars] + "... [truncated]"
        lines.append(f"{r['tool']}({args_str}):\n{result_json}")
    lines.append(
        "--- Continue your analysis.  Return your final decision "
        "(omit \"tool_calls\"), or request more tools. ---"
    )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Tool proxy loop
# ---------------------------------------------------------------------------

@dataclass
class ToolProxyConfig:
    """Configuration for the tool proxy loop."""
    enabled: bool = True
    max_rounds: int = 5
    max_tools_per_round: int = 3
    max_result_chars: int = 4000
    max_total_appended_chars: int = 40_000
    context_type: str = "setup"  # "setup" or "runtime"


def run_tool_proxy_loop(
    run_cli: Callable[[str], dict[str, Any]],
    prompt: str,
    config: ToolProxyConfig,
) -> dict[str, Any]:
    """Orchestrate the tool-call loop.

    Parameters
    ----------
    run_cli:
        A callable that takes a prompt string and returns a parsed dict
        (the LLM's JSON response).  This is the existing ``_run_cli()``
        method from ``SetupAgent`` or ``AgentExecPolicy``.
    prompt:
        The initial prompt (including tool catalog section).
    config:
        Loop configuration.

    Returns
    -------
    dict
        The final decision payload (without ``tool_calls``).
    """
    current_prompt = prompt
    total_appended = 0

    for round_num in range(1, config.max_rounds + 1):
        payload = run_cli(current_prompt)
        tool_calls = extract_tool_calls(payload)

        if tool_calls is None:
            # Final answer — return as-is.
            return payload

        logger.info(
            "Tool proxy round %d: %d call(s) requested",
            round_num, len(tool_calls),
        )
        results = execute_tool_calls(
            tool_calls, max_per_round=config.max_tools_per_round,
        )
        results_text = format_tool_results(
            results, round_num, max_result_chars=config.max_result_chars,
        )

        total_appended += len(results_text)
        if total_appended > config.max_total_appended_chars:
            logger.warning(
                "Tool proxy total appended chars (%d) exceeds budget (%d) — forcing final answer",
                total_appended, config.max_total_appended_chars,
            )
            break

        # Re-invoke with original prompt + all accumulated results.
        current_prompt = prompt + results_text

    # Max rounds or budget exceeded — treat last payload as final answer.
    payload.pop("tool_calls", None)
    if not payload:
        raise RuntimeError(
            f"Tool proxy exhausted {config.max_rounds} rounds without a final decision"
        )
    return payload
