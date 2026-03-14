"""CLI entrypoint for the Arena trading agent runtime."""

from __future__ import annotations

import argparse
from dataclasses import replace
import logging
import os

from arena_agent.config_loader import load_runtime_config
from arena_agent.core.runtime_loop import MarketRuntime


def _require_runtime_environment() -> None:
    if not os.environ.get("VARSITY_API_KEY", "").strip():
        raise SystemExit("VARSITY_API_KEY must be injected via the runtime environment.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an Arena trading agent runtime.")
    parser.add_argument(
        "--config",
        default="arena_agent/config/agent_config.yaml",
        help="Path to the runtime YAML config.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Optional override for max iterations.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    _require_runtime_environment()
    config = load_runtime_config(args.config)
    if args.iterations is not None:
        config = replace(config, max_iterations=args.iterations)

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


if __name__ == "__main__":
    main()
