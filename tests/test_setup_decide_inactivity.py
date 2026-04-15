from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from arena_agent.mcp import tools


class SetupDecideInactivityTest(unittest.TestCase):
    def test_setup_decide_passes_inactivity_context_to_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "rule.yaml"
            config_path.write_text("competition_id: 6\nsymbol: SOLUSDT\n", encoding="utf-8")

            decision = Mock()
            decision.to_dict.return_value = {"action": "hold", "reason": "ok"}

            with patch("arena_agent.setup.context_builder.build_setup_context") as build_context:
                build_context.return_value = {"competition": {"id": 6}}
                with patch("arena_agent.setup.memory.SetupMemory") as setup_memory_cls:
                    setup_memory = setup_memory_cls.return_value
                    setup_memory.recent.return_value = []
                    setup_memory.format_for_prompt.return_value = ""
                    with patch("arena_agent.agents.setup_agent.SetupAgent") as setup_agent_cls:
                        setup_agent_cls.return_value.decide.return_value = decision

                        result = tools.setup_decide(
                            competition_id=6,
                            backend="codex",
                            model="gpt-test",
                            config_path=str(config_path),
                            inactivity_alert=True,
                            inactive_minutes=25,
                            consecutive_hold_cycles=4,
                            total_runtime_iterations=80,
                        )

            self.assertEqual(result["action"], "hold")
            build_context.assert_called_once_with(
                6,
                {"competition_id": 6, "symbol": "SOLUSDT"},
                [],
                inactivity_alert=True,
                inactive_minutes=25,
                consecutive_hold_cycles=4,
                total_runtime_iterations=80,
            )


if __name__ == "__main__":
    unittest.main()
