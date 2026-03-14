from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arena_agent.skills.shared import parse_action_payload, read_last_transition
from arena_agent.interfaces.action_schema import ActionType


class SkillsTest(unittest.TestCase):
    def test_parse_action_payload_accepts_json_and_normalizes_type(self) -> None:
        action = parse_action_payload(
            json.dumps(
                {
                    "action": "open_long",
                    "size": 0.25,
                    "tp": 110.0,
                    "sl": 98.0,
                    "metadata": {"source": "tool"},
                }
            ),
            action=None,
            size=None,
            tp=None,
            sl=None,
        )

        self.assertEqual(action.type, ActionType.OPEN_LONG)
        self.assertAlmostEqual(action.size or 0.0, 0.25)
        self.assertAlmostEqual(action.take_profit or 0.0, 110.0)
        self.assertAlmostEqual(action.stop_loss or 0.0, 98.0)
        self.assertEqual(action.metadata["source"], "tool")

    def test_read_last_transition_returns_last_jsonl_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "transitions.jsonl"
            path.write_text(
                json.dumps({"transition": 1}) + "\n" + json.dumps({"transition": 2}) + "\n",
                encoding="utf-8",
            )

            transition = read_last_transition(str(path))

        self.assertEqual(transition, {"transition": 2})


if __name__ == "__main__":
    unittest.main()
