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
        choices=["config", "rule", "tap", "claude", "gemini", "openclaw", "codex", "auto"],
        default="config",
        help="Policy to run. 'claude' uses Claude Code, 'gemini' uses Gemini CLI, "
        "'openclaw' uses OpenClaw, 'codex' uses Codex CLI, "
        "'auto' detects which is available. 'tap' uses an external HTTP endpoint. "
        "'config' keeps the YAML policy unchanged.",
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
        "--model",
        default=None,
        help="Model override (e.g. sonnet, opus, gpt-5).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=None,
        help="Decision timeout for the CLI agent. Defaults to config value or 120s.",
    )
    parser.add_argument(
        "--recent-transitions",
        type=int,
        default=5,
        help="How many recent transitions to include in decision memory.",
    )
    parser.add_argument(
        "--extra-instructions",
        default="",
        help="Optional extra prompt instructions for the policy.",
    )
    parser.add_argument(
        "--strategy-context",
        default="",
        help="Optional fixed strategy context for agent decisions.",
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
    if agent in _AGENT_EXEC_BACKENDS:
        backend = _AGENT_EXEC_BACKENDS[agent]
        yaml_policy = config.policy if isinstance(config.policy, dict) else {}
        # Start from the full YAML policy, then override specific fields.
        # This preserves indicator_mode, extra_instructions, strategy_context,
        # and any other policy fields the user set in the YAML config.
        policy = dict(yaml_policy)
        policy["type"] = "agent_exec"
        policy["backend"] = backend
        policy["cwd"] = str(Path.cwd())
        # CLI flag > YAML config > default for fields with CLI overrides
        if args.model is not None:
            policy["model"] = args.model
        elif "model" not in policy:
            policy["model"] = None
        policy["timeout_seconds"] = (
            args.timeout_seconds or yaml_policy.get("timeout_seconds") or 120.0
        )
        policy["recent_transition_limit"] = args.recent_transitions
        if args.extra_instructions:
            policy["extra_instructions"] = args.extra_instructions
        elif "extra_instructions" not in policy:
            policy["extra_instructions"] = ""
        if args.strategy_context:
            policy["strategy_context"] = args.strategy_context
        elif "strategy_context" not in policy:
            policy["strategy_context"] = ""
        # Defaults for fields that must exist
        policy.setdefault("indicator_mode", "full")
        policy.setdefault("fail_open_to_hold", True)
        policy.setdefault("sandbox_mode", "read-only")
        policy.setdefault("bootstrap_from_transition_log", True)
        if backend == "openclaw":
            policy.setdefault("openclaw_agent_id", "arena-trader")
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
    policy.setdefault("type", "ma_crossover")
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
    setup_agent = SetupAgent(
        backend=setup_backend,
        model=args.setup_model or args.model,
        timeout=args.timeout_seconds * 2,
        mcp_config_path=mcp_config,
    )

    cycle = 0
    while not stop_requested:
        cycle += 1
        log.info("=== Auto cycle %d ===", cycle)

        # --- Setup phase ---
        try:
            context = build_setup_context(args.competition_id, config_dict, memory.recent(5))
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
            if decision.action == "update" and decision.overrides:
                log.info("Applying overrides: %s", json.dumps(decision.overrides, default=str)[:2000])
                # When policy type changes, replace the entire policy dict
                # to avoid stale params from the old policy contaminating the new one.
                new_policy = decision.overrides.get("policy", {})
                old_policy_type = config_dict.get("policy", {}).get("type")
                new_policy_type = new_policy.get("type") if isinstance(new_policy, dict) else None
                if new_policy_type and new_policy_type != old_policy_type:
                    log.info("Policy type changed: %s -> %s — replacing policy dict", old_policy_type, new_policy_type)
                    config_dict["policy"] = decision.overrides.pop("policy")
                _deep_merge(config_dict, decision.overrides)
                # Log the effective policy type after merge
                eff_policy = config_dict.get("policy", {})
                log.info(
                    "Effective config after merge | policy.type=%s policy.params=%s strategy=%s",
                    eff_policy.get("type", "unknown"),
                    eff_policy.get("params", {}),
                    json.dumps(config_dict.get("strategy", {}), default=str)[:500],
                )
            if decision.chat_message:
                try:
                    import varsity_tools
                    varsity_tools.send_chat(args.competition_id, decision.chat_message)
                    log.info("Chat sent: %s", decision.chat_message[:100])
                except Exception as exc:
                    log.warning("Failed to send chat: %s", exc)
            next_check = decision.next_check_seconds or args.setup_interval
        except Exception as exc:
            log.warning("Setup agent failed: %s — using defaults", exc)
            next_check = args.setup_interval

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
            # Bad override from setup agent (e.g. invalid strategy type) — drop it and retry
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
                time.sleep(10)
                continue
        except Exception as exc:
            log.error("Runtime crashed: %s", exc, exc_info=True)
            time.sleep(10)
            continue

        if stop_requested:
            break

        # Brief pause before next setup cycle
        time.sleep(2)

    log.info("Auto loop stopped after %d cycles.", cycle)


if __name__ == "__main__":
    main()
