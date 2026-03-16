from __future__ import annotations

import unittest
from unittest.mock import patch

from arena_agent.__main__ import _apply_agent_override
from arena_agent.core.models import RuntimeConfig


class RunCLITest(unittest.TestCase):
    def test_agent_claude_sets_agent_exec_with_claude_backend(self) -> None:
        config = RuntimeConfig.from_mapping(
            {
                "competition_id": 4,
                "symbol": "BTCUSDT",
                "policy": {"type": "ensemble"},
            }
        )
        args = type(
            "Args",
            (),
            {
                "agent": "claude",
                "model": "sonnet",
                "timeout_seconds": 60.0,
                "recent_transitions": 5,
                "extra_instructions": "Stay conservative.",
                "strategy_context": "momentum",
            },
        )()

        updated = _apply_agent_override(config, args)

        self.assertEqual(updated.policy["type"], "agent_exec")
        self.assertEqual(updated.policy["backend"], "claude")
        self.assertEqual(updated.policy["model"], "sonnet")
        self.assertEqual(updated.policy["timeout_seconds"], 24.0)
        self.assertEqual(updated.policy["strategy_context"], "momentum")

    def test_agent_codex_sets_codex_backend(self) -> None:
        config = RuntimeConfig.from_mapping(
            {
                "competition_id": 4,
                "symbol": "BTCUSDT",
            }
        )
        args = type(
            "Args",
            (),
            {
                "agent": "codex",
                "model": "gpt-5",
                "timeout_seconds": 45.0,
                "recent_transitions": 5,
                "extra_instructions": "",
                "strategy_context": "",
            },
        )()

        updated = _apply_agent_override(config, args)
        self.assertEqual(updated.policy["type"], "agent_exec")
        self.assertEqual(updated.policy["backend"], "codex")

    def test_agent_auto_sets_auto_backend(self) -> None:
        config = RuntimeConfig.from_mapping(
            {
                "competition_id": 4,
                "symbol": "BTCUSDT",
            }
        )
        args = type(
            "Args",
            (),
            {
                "agent": "auto",
                "model": None,
                "timeout_seconds": 45.0,
                "recent_transitions": 5,
                "extra_instructions": "",
                "strategy_context": "",
            },
        )()

        updated = _apply_agent_override(config, args)
        self.assertEqual(updated.policy["type"], "agent_exec")
        self.assertEqual(updated.policy["backend"], "auto")

    def test_run_subcommand_invokes_runtime(self) -> None:
        config = RuntimeConfig.from_mapping({"competition_id": 4, "symbol": "BTCUSDT"})
        runtime_instance = type(
            "RuntimeStub",
            (),
            {
                "run": lambda self: type(
                    "Report",
                    (),
                    {
                        "iterations": 1,
                        "executed_actions": 0,
                        "transitions_recorded": 0,
                        "total_realized_pnl": 0.0,
                        "total_fees": 0.0,
                        "final_equity": 1000.0,
                    },
                )()
            },
        )()

        with patch("arena_agent.__main__.load_runtime_config", return_value=config), patch(
            "arena_agent.__main__.load_local_runtime_env"
        ), patch("arena_agent.__main__.require_runtime_environment"), patch(
            "arena_agent.__main__.MarketRuntime",
            return_value=runtime_instance,
        ) as runtime_cls:
            from arena_agent.__main__ import main

            main(["run", "--agent", "claude", "--config", "arena_agent/config/agent_config.yaml"])

        self.assertEqual(runtime_cls.call_args.args[0].policy["type"], "agent_exec")
        self.assertEqual(runtime_cls.call_args.args[0].policy["backend"], "claude")


if __name__ == "__main__":
    unittest.main()
