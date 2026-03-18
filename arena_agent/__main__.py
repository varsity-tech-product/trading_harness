"""CLI entrypoint for the Arena trading agent runtime."""

from __future__ import annotations

import argparse
from dataclasses import replace
import logging
from pathlib import Path
import sys
from typing import Any

from arena_agent.config_loader import load_runtime_config
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
        # Resolve timeout: CLI flag > YAML config > 120s default
        yaml_timeout = config.policy.get("timeout_seconds") if isinstance(config.policy, dict) else None
        timeout = args.timeout_seconds or yaml_timeout or 120.0
        policy = {
            "type": "agent_exec",
            "backend": backend,
            "model": args.model,
            "timeout_seconds": timeout,
            "recent_transition_limit": args.recent_transitions,
            "fail_open_to_hold": True,
            "sandbox_mode": "read-only",
            "cwd": str(Path.cwd()),
            "extra_instructions": args.extra_instructions,
            "strategy_context": args.strategy_context,
            "bootstrap_from_transition_log": True,
        }
        if backend == "openclaw":
            policy["openclaw_agent_id"] = "arena-trader"
        return replace(config, policy=policy)
    return config


if __name__ == "__main__":
    main()
