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
        choices=["config", "tap"],
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
    if agent == "config":
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


_REPLACE_DICT_PATHS = {
    ("strategy", "sizing"),
    ("strategy", "tpsl"),
}


def _deep_merge(base: dict, overrides: dict, path: tuple[str, ...] = ()) -> dict:
    """Recursively merge *overrides* into *base* (mutates base).

    Strategy subcomponents such as ``strategy.sizing`` and ``strategy.tpsl``
    are typeful config blocks. When the setup agent switches one of these
    components, the new block must replace the old one wholesale; otherwise
    stale keys from the previous type leak through and get stripped by the
    strategy builder every cycle.
    """
    for key, value in overrides.items():
        child_path = path + (str(key),)
        if child_path in _REPLACE_DICT_PATHS and isinstance(value, dict):
            base[key] = copy.deepcopy(value)
        elif key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value, child_path)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _execute_discretionary_trade(
    trade,
    config_dict: dict[str, Any],
    dry_run: bool,
    log: logging.Logger,
) -> dict[str, Any] | None:
    """Execute a discretionary trade directly — no runtime loop.

    Builds executor and state from the live config_dict, computes TP/SL
    and sizing from percentages, then sends the order to the arena API.

    Returns the execution result dict, or None on failure.
    """
    from arena_agent.core.environment_adapter import EnvironmentAdapter
    from arena_agent.core.state_builder import StateBuilder
    from arena_agent.core.runtime_loop import build_transition_event
    from arena_agent.execution.order_executor import OrderExecutor
    from arena_agent.interfaces.action_schema import Action, ActionType
    from arena_agent.memory.transition_store import TransitionStore

    trade_type = trade.type
    if trade_type == "HOLD":
        log.info("Discretionary trade: HOLD — no action")
        return None

    try:
        # Build components from the live config_dict
        runtime_config = RuntimeConfig.from_mapping(config_dict)
        adapter = EnvironmentAdapter(
            retry_attempts=runtime_config.adapter_retry_attempts,
            retry_backoff_seconds=runtime_config.adapter_retry_backoff_seconds,
            min_call_spacing_seconds=runtime_config.adapter_min_call_spacing_seconds,
        )
        state_builder = StateBuilder(adapter, runtime_config)
        executor = OrderExecutor(
            adapter,
            competition_id=runtime_config.competition_id,
            risk_limits=runtime_config.risk_limits,
            dry_run=dry_run,
        )
        transition_store = TransitionStore(
            maxlen=runtime_config.storage.max_in_memory_transitions,
            output_path=runtime_config.storage.transition_path,
        )

        state_before = state_builder.build()
        current_price = state_before.market.last_price
        equity = state_before.account.equity

        # --- Determine direction for TP/SL computation ---
        if trade_type in ("OPEN_LONG", "OPEN_SHORT"):
            is_long = trade_type == "OPEN_LONG"
        elif trade_type == "UPDATE_TPSL" and state_before.position:
            is_long = state_before.position.direction == "long"
        else:
            is_long = True  # fallback

        # --- Compute TP/SL from percentages ---
        tp_price = None
        sl_price = None
        if trade.tp_pct is not None and current_price:
            pct = trade.tp_pct / 100.0
            tp_price = current_price * (1 + pct) if is_long else current_price * (1 - pct)

        if trade.sl_pct is not None and current_price:
            pct = trade.sl_pct / 100.0
            sl_price = current_price * (1 - pct) if is_long else current_price * (1 + pct)

        # --- Compute size from sizing_fraction ---
        size = None
        if trade.sizing_fraction is not None and equity and current_price:
            fraction = trade.sizing_fraction / 100.0
            size = (equity * fraction) / current_price

        action = Action(
            type=ActionType(trade_type),
            size=size,
            take_profit=tp_price,
            stop_loss=sl_price,
            metadata={"source": "discretionary"},
        )

        log.info(
            "Discretionary trade: %s size=%s tp=%s sl=%s (price=%.2f equity=%.2f)",
            trade_type, size, tp_price, sl_price, current_price or 0, equity or 0,
        )

        result = executor.execute(action, state_before)
        state_after = state_builder.build()
        transition = build_transition_event(state_before, action, result, state_after)
        transition_store.append(transition)

        log.info(
            "Discretionary trade result: accepted=%s executed=%s pnl=%.4f fee=%.4f msg=%s",
            result.accepted, result.executed, result.realized_pnl, result.fee,
            result.message,
        )
        return {
            "accepted": result.accepted,
            "executed": result.executed,
            "realized_pnl": result.realized_pnl,
            "fee": result.fee,
            "message": result.message,
        }
    except Exception as exc:
        log.error("Discretionary trade failed: %s", exc, exc_info=True)
        return None


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
    parser.add_argument("--no-auto-register", action="store_true", help="Disable auto-registration for new competitions.")
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
    # Trading mode: rule_based (default) or discretionary
    config_dict.setdefault("mode", "rule_based")

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

    # --- Persistent monitor for the entire auto loop ---
    from arena_agent.observability import RuntimeMonitor

    obs_config = dict(config_dict.get("observability", {}))
    obs_config["enabled"] = True  # always enable in auto mode
    # Also attach the auto logger so setup-phase logs appear in the TUI
    attach = list(obs_config.get("attach_loggers", ["arena_agent.runtime", "arena_agent.tap"]))
    if "arena_agent.auto" not in attach:
        attach.append("arena_agent.auto")
    obs_config["attach_loggers"] = attach
    monitor = RuntimeMonitor(obs_config, logger=log)
    try:
        monitor._start_server()
    except OSError as exc:
        log.warning("Observability stream unavailable: %s", exc)
    monitor._attach_log_handler()
    # Mark as started so MarketRuntime.start() resets runtime fields
    # instead of trying to bind the port again.
    monitor._started = True
    monitor.update_auto_loop({"active": True, "setup_backend": setup_backend})

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
        monitor.update_auto_loop({"cycle": cycle, "phase": "pre_check", "phase_started_at": time.time()})

        # --- Pre-check: is the competition still active? ---
        comp_status = None
        try:
            import varsity_tools
            comp_detail = varsity_tools.get_competition_detail(str(args.competition_id))
            comp_status = comp_detail.get("status") if isinstance(comp_detail, dict) else None
            monitor.update_auto_loop({"competition_status": comp_status})
            if comp_status in ("completed", "settled", "cancelled", "ended_early"):
                log.info("Competition %d is %s — stopping auto loop.", args.competition_id, comp_status)
                break
        except Exception as exc:
            log.warning("Competition status check failed: %s — continuing", exc)

        # --- Auto-register for any open competitions ---
        monitor.update_auto_loop({"phase": "registering", "phase_started_at": time.time()})
        if not args.no_auto_register:
            try:
                open_comps = varsity_tools.get_competitions(status="registration_open")
                open_list = open_comps.get("list", []) if isinstance(open_comps, dict) else []
                my_regs = varsity_tools.get_my_registrations()
                registered_ids = set()
                if isinstance(my_regs, list):
                    registered_ids = {r.get("competitionId") for r in my_regs}
                for comp in open_list:
                    comp_id = comp.get("id")
                    slug = comp.get("slug")
                    if comp_id and slug and comp_id not in registered_ids:
                        try:
                            result = varsity_tools.register_competition(slug)
                            log.info("Auto-registered for competition: %s (slug=%s) result=%s", comp.get("title"), slug, result)
                        except Exception as reg_exc:
                            log.warning("Auto-registration failed for %s: %s", slug, reg_exc)
            except Exception as exc:
                log.debug("Auto-registration check failed: %s", exc)

        # --- Pre-check: is the engine account still available? ---
        monitor.update_auto_loop({"phase": "account_check", "phase_started_at": time.time()})
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
            monitor.update_auto_loop({"phase": "setup", "phase_started_at": time.time()})
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
                overrides_summary = ""
                if decision.action == "update" and decision.overrides:
                    overrides_summary = json.dumps(decision.overrides, default=str)[:200]
                monitor.update_auto_loop({
                    "last_setup_decision": {
                        "action": decision.action,
                        "reason": decision.reason,
                        "overrides_summary": overrides_summary,
                        "timestamp": time.time(),
                    },
                })

                # Track setup failures for fallback logic
                if decision.reason and decision.reason.startswith("setup_error"):
                    consecutive_setup_failures += 1
                    setup_failed = True
                    log.warning("Setup failure %d/%d", consecutive_setup_failures, max_setup_failures)
                else:
                    consecutive_setup_failures = 0

                # --- Handle mode switching ---
                if decision.mode and decision.mode != config_dict.get("mode", "rule_based"):
                    log.info("Mode changed: %s -> %s", config_dict.get("mode", "rule_based"), decision.mode)
                    config_dict["mode"] = decision.mode
                    monitor.update_auto_loop({"mode": decision.mode})

                # --- Execute discretionary trade ---
                if decision.action == "trade" and decision.trade:
                    trade_result = _execute_discretionary_trade(
                        decision.trade, config_dict, args.dry_run, log,
                    )
                    monitor.update_auto_loop({
                        "last_discretionary_trade": {
                            "type": decision.trade.type,
                            "result": trade_result,
                            "timestamp": time.time(),
                        },
                    })
                    if trade_result and trade_result.get("executed"):
                        inactive_cycles = 0
                        inactive_since = None

                if decision.action == "update" and decision.overrides:
                    log.info("Applying overrides: %s", json.dumps(decision.overrides, default=str)[:2000])
                    new_policy = decision.overrides.get("policy", {})
                    old_policy_type = config_dict.get("policy", {}).get("type")
                    new_policy_type = new_policy.get("type") if isinstance(new_policy, dict) else None
                    if new_policy_type and new_policy_type != old_policy_type:
                        log.info("Policy type changed: %s -> %s — replacing policy dict", old_policy_type, new_policy_type)
                        config_dict["policy"] = decision.overrides.pop("policy")
                    # Reset cooldown tracking on ANY update (not just type changes)
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
                # In discretionary mode, allow shorter intervals (60s floor)
                current_mode = config_dict.get("mode", "rule_based")
                min_next_check = 60 if current_mode == "discretionary" else 600
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
            current_mode = config_dict.get("mode", "rule_based")
            runtime = None
            report = None

            if current_mode == "discretionary":
                # ── Discretionary mode: no runtime loop ──
                # The setup agent already executed the trade directly.
                # TP/SL is enforced server-side on the order.
                # Just wait for the next setup cycle.
                log.info("Discretionary mode: skipping runtime loop (next setup in ~%ds)", next_check)
                monitor.update_auto_loop({
                    "phase": "discretionary_wait",
                    "phase_started_at": time.time(),
                    "next_setup_check_seconds": next_check,
                    "mode": "discretionary",
                })
                time.sleep(next_check)

            else:
                # ── Rule-based mode: run the expression engine ──
                tick = float(config_dict.get("tick_interval_seconds", 60))
                iterations = max(1, int(next_check / tick))
                config_dict["max_iterations"] = iterations

                log.info("Starting runtime: %d iterations (%.0fs tick, next setup in ~%ds)", iterations, tick, next_check)
                monitor.update_auto_loop({
                    "phase": "runtime",
                    "phase_started_at": time.time(),
                    "next_setup_check_seconds": next_check,
                    "mode": "rule_based",
                })

                try:
                    runtime_config = RuntimeConfig.from_mapping(config_dict)
                    runtime = MarketRuntime(runtime_config, monitor=monitor)
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
                        runtime = MarketRuntime(runtime_config, monitor=monitor)
                        report = runtime.run()
                        log.info(
                            "Runtime cycle %d done (fallback) | iters=%s executed=%s pnl=%.4f equity=%s",
                            cycle, report.iterations, report.executed_actions,
                            report.total_realized_pnl, report.final_equity,
                        )
                    except Exception as inner_exc:
                        log.error("Runtime crashed even after fallback: %s", inner_exc, exc_info=True)
                except Exception as exc:
                    log.error("Runtime crashed: %s", exc, exc_info=True)

                # --- Feed runtime state back to config for next setup cycle ---
                config_dict.pop("_expression_errors", None)
                config_dict.pop("_last_indicator_values", None)
                if runtime is not None:
                    # Expression validation errors → LLM can fix them next cycle
                    policy_obj = getattr(runtime, "policy", None)
                    expr_errors = getattr(policy_obj, "_validation_errors", None)
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

            # --- Publish watchdog + runtime result to monitor ---
            if current_mode == "discretionary":
                stop_reason_label = "discretionary"
            elif report is not None:
                stop_reason_label = getattr(report, "stop_reason", None)
            else:
                stop_reason_label = "crashed"
            monitor.update_auto_loop({
                "inactive_cycles": inactive_cycles,
                "inactive_since": inactive_since,
                "inactive_minutes": round((time.time() - inactive_since) / 60) if inactive_since else 0,
                "total_runtime_iterations": total_runtime_iterations,
                "consecutive_setup_failures": consecutive_setup_failures,
                "consecutive_account_failures": consecutive_account_failures,
                "error_backoff_seconds": error_backoff,
                "last_runtime_stop_reason": stop_reason_label,
                "last_runtime_iterations": report.iterations if report else None,
                "last_runtime_executed": report.executed_actions if report else None,
                "mode": current_mode,
            })

            if stop_requested:
                break

            # Reset error backoff on successful cycle
            error_backoff = 5
            # In discretionary mode we already waited during the sleep above.
            # In rule-based mode, guard against rapid-fire LLM calls if
            # runtime finished too quickly (e.g. crashed on first iteration).
            if current_mode != "discretionary":
                if report is None or report.iterations <= 1:
                    wait = min(args.setup_interval, 60)
                    log.warning("Runtime finished in ≤1 iteration — waiting %ds before next cycle.", wait)
                    monitor.update_auto_loop({"phase": "waiting", "phase_started_at": time.time()})
                    time.sleep(wait)
                else:
                    monitor.update_auto_loop({"phase": "waiting", "phase_started_at": time.time()})
                    time.sleep(2)

        except Exception as exc:
            # --- Self-healing: never exit during a live competition ---
            log.error("Auto cycle %d crashed: %s — retrying in %ds", cycle, exc, error_backoff, exc_info=True)
            monitor.update_auto_loop({
                "phase": "error_backoff",
                "phase_started_at": time.time(),
                "error_backoff_seconds": error_backoff,
            })
            time.sleep(error_backoff)
            error_backoff = min(error_backoff * 2, max_error_backoff)
            continue

    monitor.update_auto_loop({"active": False, "phase": "stopped"})
    monitor.stop()
    log.info("Auto loop stopped after %d cycles.", cycle)


if __name__ == "__main__":
    main()
