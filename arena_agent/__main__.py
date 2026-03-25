"""CLI entrypoint for the Arena trading agent runtime."""

from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import json
import logging
from pathlib import Path
import signal
import sys
import time
from typing import Any

import yaml

from arena_agent.config_loader import load_runtime_config
from arena_agent.core.models import RuntimeConfig
from arena_agent.core.runtime_loop import MarketRuntime
from arena_agent.runtime_env import default_runtime_config_path, load_local_runtime_env, require_runtime_environment

# --agent values that map to the agent_exec policy and their backend.
_AGENT_EXEC_BACKENDS = {
    "claude": "claude",
    "gemini": "gemini",
    "openclaw": "openclaw",
    "codex": "codex",
    "auto": "auto",
}


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "monitor":
        from arena_agent.tui.__main__ import main as monitor_main

        monitor_main(argv[1:])
        return
    if argv and argv[0] == "auto":
        _run_auto(argv[1:])
        return
    if argv and argv[0] == "run":
        _run_runtime(argv[1:])
        return

    _run_runtime(argv)


def _run_runtime(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Run an Arena trading agent runtime.")
    parser.add_argument(
        "--agent",
        choices=["config", "rule", "tap"],
        default="config",
        help="Policy to run. 'config' keeps the YAML policy unchanged. "
        "'rule' uses the built-in rule policy. 'tap' uses an external HTTP endpoint. "
        "For LLM-backed trading, use 'arena_agent auto' instead.",
    )
    parser.add_argument(
        "--config",
        default=str(default_runtime_config_path("agent_config.yaml")),
        help="Path to the runtime YAML config.",
    )
    parser.add_argument(
        "--competition-id",
        type=int,
        default=None,
        help="Override competition ID from config.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Optional override for max iterations.",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional runtime env file to source before startup.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level.",
    )
    parser.add_argument(
        "--tap-endpoint",
        default="http://127.0.0.1:8080/decision",
        help="Decision endpoint when --agent tap is used.",
    )
    parser.add_argument(
        "--tap-timeout-seconds",
        type=float,
        default=60.0,
        help="Decision timeout when --agent tap is used.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    load_local_runtime_env(args.env_file)
    require_runtime_environment()
    config = load_runtime_config(args.config)
    if args.competition_id is not None:
        config = replace(config, competition_id=args.competition_id)
    if args.iterations is not None:
        config = replace(config, max_iterations=args.iterations)
    config = _apply_agent_override(config, args)

    report = MarketRuntime(config).run()
    logging.getLogger("arena_agent.runtime").info(
        "Runtime complete | iterations=%s executed_actions=%s transitions=%s realized_pnl=%.4f fees=%.4f final_equity=%s",
        report.iterations,
        report.executed_actions,
        report.transitions_recorded,
        report.total_realized_pnl,
        report.total_fees,
        report.final_equity,
    )


def _apply_agent_override(config, args: Any):
    agent = str(getattr(args, "agent", "config")).lower()
    if agent in {"config", "rule"}:
        return config
    if agent == "tap":
        policy = dict(config.policy)
        policy.update(
            {
                "type": "tap_http",
                "endpoint": args.tap_endpoint or policy.get("endpoint") or "http://127.0.0.1:8080/decision",
                "timeout_seconds": args.tap_timeout_seconds,
                "fail_open_to_hold": bool(policy.get("fail_open_to_hold", True)),
                "headers": dict(policy.get("headers", {"Content-Type": "application/json"})),
            }
        )
        return replace(config, policy=policy)
    return config


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge *overrides* into *base* (mutates base)."""
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _run_auto(argv: list[str]) -> None:
    """Setup → control → runtime loop.

    Each cycle:
      1. Run setup agent to get config overrides.
      2. Deep-merge overrides into the live config dict.
      3. Build RuntimeConfig and run the runtime for N iterations.
      4. Repeat until competition ends or SIGTERM.
    """
    parser = argparse.ArgumentParser(description="Autonomous setup + runtime loop.")
    parser.add_argument("--config", default=str(default_runtime_config_path("agent_config.yaml")))
    parser.add_argument("--competition-id", type=int, required=True)
    parser.add_argument("--agent", choices=list(_AGENT_EXEC_BACKENDS), default="claude")
    parser.add_argument("--model", default=None)
    parser.add_argument("--setup-model", default=None, help="Model for setup agent (defaults to --model).")
    parser.add_argument("--setup-interval", type=int, default=300, help="Default seconds between setup checks.")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("arena_agent.auto")

    load_local_runtime_env(args.env_file)
    require_runtime_environment()

    # Mutable config dict that persists across cycles
    config_path = Path(args.config)
    config_dict: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config_dict["competition_id"] = args.competition_id
    config_dict["dry_run"] = args.dry_run
    config_dict.setdefault("symbol", "BTCUSDT")

    # In auto mode, the --agent flag selects the setup agent's LLM backend,
    # NOT the runtime policy. The runtime policy comes from the YAML config
    # (or from setup agent overrides). The setup agent picks the strategy.
    policy = config_dict.setdefault("policy", {})
    # Ensure a valid default policy type if YAML doesn't specify one
    policy.setdefault("type", "expression")
    policy.setdefault("params", {})

    stop_requested = False

    def _on_sigterm(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, _on_sigterm)
    signal.signal(signal.SIGINT, _on_sigterm)

    from arena_agent.agents.setup_agent import SetupAgent
    from arena_agent.setup.context_builder import build_setup_context
    from arena_agent.setup.memory import SetupMemory

    arena_home = Path.cwd()
    memory = SetupMemory(arena_home / "setup_memory.json")

    # Resolve MCP config for the setup agent
    mcp_config = None
    for candidate in [arena_home / ".mcp.json", Path.cwd() / ".mcp.json"]:
        if candidate.exists():
            mcp_config = str(candidate)
            break

    # The setup agent always uses an LLM backend, even when the runtime
    # policy is rule-based. Use the agent backend or default to "auto".
    setup_backend = _AGENT_EXEC_BACKENDS.get(args.agent, "auto")
    # Let the user specify which openclaw agent to use via config YAML
    policy_cfg = config_dict.get("policy", {})
    openclaw_agent_id = policy_cfg.get("openclaw_agent_id")
    tool_proxy_enabled = bool(policy_cfg.get("tool_proxy_enabled", True))
    setup_agent = SetupAgent(
        backend=setup_backend,
        model=args.setup_model or args.model,
        timeout=args.timeout_seconds * 2,
        mcp_config_path=mcp_config,
        openclaw_agent_id=openclaw_agent_id,
        tool_proxy_enabled=tool_proxy_enabled,
    )

    # --- Liveness state ---
    inactive_cycles = 0          # consecutive cycles with 0 executed trades
    inactive_since: float | None = None  # wall-clock timestamp when inactivity started
    total_runtime_iterations = 0 # total iterations since last strategy change
    max_inactive_cycles = 4      # trigger inactivity alert after this many consecutive idle cycles
    consecutive_setup_failures = 0
    max_setup_failures = 5       # apply fallback strategy after this many
    consecutive_account_failures = 0  # stop after 3 consecutive "account not found"
    error_backoff = 5            # seconds, grows exponentially on crash
    max_error_backoff = 60

    # Fallback strategy used when ALL LLM backends are unavailable.
    _FALLBACK_STRATEGY: dict[str, Any] = {
        "policy": {
            "type": "ensemble",
            "members": [
                {"type": "expression", "params": {
                    "entry_long": "rsi_14 < 35 and close > sma_20",
                    "entry_short": "rsi_14 > 65 and close < sma_20",
                    "exit": "rsi_14 > 55 and rsi_14 < 45",
                }},
                {"type": "expression", "params": {
                    "entry_long": "close > sma_50 and close > sma_20",
                    "entry_short": "close < sma_50 and close < sma_20",
                    "exit": "close < sma_20 or close > sma_20",
                }},
            ],
        },
        "signal_indicators": [
            {"indicator": "RSI", "params": {"timeperiod": 14}},
            {"indicator": "SMA", "params": {"timeperiod": 20}},
            {"indicator": "SMA", "params": {"timeperiod": 50}},
        ],
        "strategy": {
            "sizing": {"type": "fixed_fraction", "fraction": 0.15},
            "tpsl": {"type": "fixed_pct", "tp_pct": 0.01, "sl_pct": 0.005},
        },
    }

    cycle = 0
    while not stop_requested:
        cycle += 1
        log.info("=== Auto cycle %d ===", cycle)

        # --- Pre-check: is the competition still active? ---
        try:
            import varsity_tools
            comp_detail = varsity_tools.get_competition_detail(str(args.competition_id))
            comp_status = comp_detail.get("status") if isinstance(comp_detail, dict) else None
            if comp_status in ("completed", "settled", "cancelled", "ended_early"):
                log.info("Competition %d is %s — stopping auto loop.", args.competition_id, comp_status)
                break
        except Exception as exc:
            log.warning("Competition status check failed: %s — continuing", exc)

        # --- Pre-check: is the engine account still available? ---
        try:
            acct_check = varsity_tools.get_live_account(args.competition_id)
            if isinstance(acct_check, dict) and acct_check.get("code") == 1001:
                consecutive_account_failures += 1
                if consecutive_account_failures >= 3:
                    log.error(
                        "Engine account not found for %d consecutive checks — agent is not a valid participant. Stopping.",
                        consecutive_account_failures,
                    )
                    break
                log.warning("Engine account not found (attempt %d/3) — retrying next cycle.", consecutive_account_failures)
                time.sleep(error_backoff)
                continue
            else:
                consecutive_account_failures = 0
        except Exception as exc:
            log.warning("Account pre-check failed: %s — continuing", exc)

        try:
            # --- Setup phase ---
            setup_failed = False
            try:
                actual_inactive_minutes = round((time.time() - inactive_since) / 60) if inactive_since else 0
                context = build_setup_context(
                    args.competition_id, config_dict, memory.recent(5),
                    inactivity_alert=inactive_cycles >= max_inactive_cycles,
                    inactive_minutes=actual_inactive_minutes,
                    consecutive_hold_cycles=inactive_cycles,
                    total_runtime_iterations=total_runtime_iterations,
                )
                # Skip LLM call if account context is broken (API error)
                acct_ctx = context.get("account_state", {})
                if isinstance(acct_ctx, dict) and "error" in acct_ctx:
                    log.warning("Account context unavailable (%s) — skipping setup agent call.", acct_ctx["error"][:100])
                    raise RuntimeError(f"broken context: {acct_ctx['error'][:100]}")
                # Propagate symbol from competition detail (asset-agnostic)
                comp = context.get("competition", {})
                if isinstance(comp, dict) and comp.get("symbol"):
                    if config_dict.get("symbol") != comp["symbol"]:
                        log.info("Symbol updated from competition: %s -> %s", config_dict.get("symbol"), comp["symbol"])
                    config_dict["symbol"] = comp["symbol"]
                memory_text = memory.format_for_prompt(5)
                decision = setup_agent.decide(context, memory_text)
                log.info(
                    "Setup decision: action=%s reason=%s restart=%s next_check=%s",
                    decision.action, decision.reason, decision.restart_runtime, decision.next_check_seconds,
                )

                # Track setup failures for fallback logic
                if decision.reason and decision.reason.startswith("setup_error"):
                    consecutive_setup_failures += 1
                    setup_failed = True
                    log.warning("Setup failure %d/%d", consecutive_setup_failures, max_setup_failures)
                else:
                    consecutive_setup_failures = 0

                if decision.action == "update" and decision.overrides:
                    log.info("Applying overrides: %s", json.dumps(decision.overrides, default=str)[:2000])
                    new_policy = decision.overrides.get("policy", {})
                    old_policy_type = config_dict.get("policy", {}).get("type")
                    new_policy_type = new_policy.get("type") if isinstance(new_policy, dict) else None
                    if new_policy_type and new_policy_type != old_policy_type:
                        log.info("Policy type changed: %s -> %s — replacing policy dict", old_policy_type, new_policy_type)
                        config_dict["policy"] = decision.overrides.pop("policy")
                        acct = context.get("account_state", {})
                        config_dict["_strategy_start_trade_count"] = acct.get("trade_count", 0) if isinstance(acct, dict) else 0
                        config_dict["_strategy_start_time"] = time.time()
                        inactive_cycles = 0
                        inactive_since = None
                        total_runtime_iterations = 0
                    _deep_merge(config_dict, decision.overrides)
                    # Apply agent-requested cooldown override
                    if "_cooldown_seconds" in decision.overrides:
                        setup_agent._cooldown_seconds = float(decision.overrides["_cooldown_seconds"])
                        log.info("Agent adjusted cooldown period to %ds", setup_agent._cooldown_seconds)
                    eff_policy = config_dict.get("policy", {})
                    log.info(
                        "Effective config after merge | policy.type=%s policy.params=%s strategy=%s",
                        eff_policy.get("type", "unknown"),
                        eff_policy.get("params", {}),
                        json.dumps(config_dict.get("strategy", {}), default=str)[:500],
                    )
                if decision.chat_message:
                    try:
                        varsity_tools.send_chat(args.competition_id, decision.chat_message)
                        log.info("Chat sent: %s", decision.chat_message[:100])
                    except Exception as exc:
                        log.warning("Failed to send chat: %s", exc)
                min_next_check = 600  # 10 min floor — prevent rapid-fire LLM calls
                next_check = max(decision.next_check_seconds or args.setup_interval, min_next_check)
                config_dict["_last_next_check_seconds"] = next_check
            except Exception as exc:
                log.warning("Setup agent failed: %s — using defaults", exc)
                consecutive_setup_failures += 1
                setup_failed = True
                next_check = args.setup_interval

            # --- Fallback strategy: apply if LLM is consistently unavailable ---
            if consecutive_setup_failures >= max_setup_failures:
                log.warning(
                    "LLM setup agent failed %d consecutive times — applying fallback strategy (ensemble)",
                    consecutive_setup_failures,
                )
                config_dict["policy"] = dict(_FALLBACK_STRATEGY["policy"])
                config_dict["strategy"] = dict(_FALLBACK_STRATEGY["strategy"])
                config_dict["signal_indicators"] = list(_FALLBACK_STRATEGY.get("signal_indicators", []))
                config_dict["_strategy_start_time"] = time.time()
                consecutive_setup_failures = 0
                inactive_cycles = 0
                inactive_since = None
                total_runtime_iterations = 0

            if stop_requested:
                break

            # --- Runtime phase ---
            tick = float(config_dict.get("tick_interval_seconds", 30))
            iterations = max(1, int(next_check / tick))
            config_dict["max_iterations"] = iterations
            log.info("Starting runtime: %d iterations (%.0fs tick, next setup in ~%ds)", iterations, tick, next_check)

            try:
                runtime_config = RuntimeConfig.from_mapping(config_dict)
                runtime = MarketRuntime(runtime_config)
                report = runtime.run()
                log.info(
                    "Runtime cycle %d done | iters=%s executed=%s pnl=%.4f equity=%s",
                    cycle, report.iterations, report.executed_actions,
                    report.total_realized_pnl, report.final_equity,
                )
            except (ValueError, TypeError) as exc:
                log.warning("Runtime config error: %s — dropping strategy overrides", exc)
                config_dict.pop("strategy", None)
                try:
                    runtime_config = RuntimeConfig.from_mapping(config_dict)
                    runtime = MarketRuntime(runtime_config)
                    report = runtime.run()
                    log.info(
                        "Runtime cycle %d done (fallback) | iters=%s executed=%s pnl=%.4f equity=%s",
                        cycle, report.iterations, report.executed_actions,
                        report.total_realized_pnl, report.final_equity,
                    )
                except Exception as inner_exc:
                    log.error("Runtime crashed even after fallback: %s", inner_exc, exc_info=True)
                    report = None
            except Exception as exc:
                log.error("Runtime crashed: %s", exc, exc_info=True)
                report = None

            # --- Feed runtime state back to config for next setup cycle ---
            config_dict.pop("_expression_errors", None)
            config_dict.pop("_last_indicator_values", None)
            if runtime is not None:
                # Expression validation errors → LLM can fix them next cycle
                policy = getattr(runtime, "policy", None)
                expr_errors = getattr(policy, "_validation_errors", None)
                if expr_errors:
                    config_dict["_expression_errors"] = [
                        {"expression": k, "error": v} for k, v in expr_errors.items()
                    ]
                # Last indicator values → LLM can calibrate thresholds
                sb = getattr(runtime, "state_builder", None)
                last_signal = getattr(sb, "_last_signal_values", None)
                if isinstance(last_signal, dict) and last_signal:
                    config_dict["_last_indicator_values"] = last_signal

            # --- Inactivity watchdog ---
            if report is not None:
                total_runtime_iterations += report.iterations
                if report.executed_actions == 0:
                    inactive_cycles += 1
                    if inactive_since is None:
                        inactive_since = time.time()
                else:
                    inactive_cycles = 0
                    inactive_since = None

            if inactive_cycles >= max_inactive_cycles:
                inactive_minutes = round((time.time() - inactive_since) / 60) if inactive_since else 0
                log.warning(
                    "Inactivity watchdog: %d cycles (%d min) with no trades — forcing strategy rotation next cycle",
                    inactive_cycles,
                    inactive_minutes,
                )
                # Don't reset here — reset happens after the next setup cycle
                # successfully produces an "update" decision

            if stop_requested:
                break

            # Reset error backoff on successful cycle
            error_backoff = 5
            # If runtime finished too quickly (e.g. crashed on first iteration),
            # wait at least setup_interval before the next cycle to avoid
            # rapid-fire LLM calls.
            if report is None or report.iterations <= 1:
                wait = min(args.setup_interval, 60)
                log.warning("Runtime finished in ≤1 iteration — waiting %ds before next cycle.", wait)
                time.sleep(wait)
            else:
                time.sleep(2)

        except Exception as exc:
            # --- Self-healing: never exit during a live competition ---
            log.error("Auto cycle %d crashed: %s — retrying in %ds", cycle, exc, error_backoff, exc_info=True)
            time.sleep(error_backoff)
            error_backoff = min(error_backoff * 2, max_error_backoff)
            continue

    log.info("Auto loop stopped after %d cycles.", cycle)


if __name__ == "__main__":
    main()
