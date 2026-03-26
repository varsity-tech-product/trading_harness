from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arena_agent.agents.setup_agent import SetupAgent, _build_codex_mcp_overrides


class SetupAgentCodexMcpTest(unittest.TestCase):
    def test_build_codex_mcp_overrides_from_mcp_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".mcp.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "arena": {
                                "type": "stdio",
                                "command": "arena-mcp",
                                "args": ["serve"],
                                "env": {"ARENA_ROOT": "/tmp/arena-home"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            overrides = _build_codex_mcp_overrides(str(config_path))

        self.assertIn("-c", overrides)
        self.assertIn('mcp_servers.arena.command="arena-mcp"', overrides)
        self.assertIn('mcp_servers.arena.args=["serve"]', overrides)
        self.assertIn('mcp_servers.arena.env.ARENA_ROOT="/tmp/arena-home"', overrides)

    def test_setup_agent_disables_tool_proxy_for_codex_when_native_mcp_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".mcp.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "arena": {
                                "type": "stdio",
                                "command": "arena-mcp",
                                "args": ["serve"],
                                "env": {"ARENA_ROOT": "/tmp/arena-home"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            agent = SetupAgent(
                backend="codex",
                mcp_config_path=str(config_path),
                tool_proxy_enabled=True,
            )

        self.assertFalse(agent.tool_proxy_enabled)
        self.assertTrue(agent._codex_mcp_overrides)


if __name__ == "__main__":
    unittest.main()
