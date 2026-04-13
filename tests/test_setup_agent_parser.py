from __future__ import annotations

import unittest

from arena_agent.agents.setup_agent import SetupAgent


class SetupAgentParserTest(unittest.TestCase):
    def test_parse_decision_canonicalizes_flat_updates_and_requires_restart(self) -> None:
        decision = SetupAgent._parse_decision(
            {
                "action": "update",
                "policy": "expression",
                "policy_params": {
                    "entry_long": "close > ema_21",
                    "entry_short": "close < ema_21",
                    "exit_long": "close < ema_9",
                    "exit_short": "close > ema_9",
                },
                "tp_pct": 1.8,
                "sl_pct": 0.9,
                "sizing_fraction": 20,
                "reason": "test",
            }
        )

        assert decision.overrides is not None
        self.assertTrue(decision.restart_runtime)
        self.assertEqual(decision.overrides["policy"]["params"]["exit_long"], "close < ema_9")
        self.assertEqual(decision.overrides["policy"]["params"]["exit_short"], "close > ema_9")
        self.assertEqual(decision.overrides["strategy"]["sizing"]["type"], "fixed_fraction")
        self.assertEqual(decision.overrides["strategy"]["tpsl"]["type"], "fixed_pct")

    def test_parse_decision_rejects_invalid_legacy_strategy_params(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown params"):
            SetupAgent._parse_decision(
                {
                    "action": "update",
                    "reason": "bad legacy payload",
                    "overrides": {
                        "strategy": {
                            "sizing": {
                                "type": "fixed_fraction",
                                "fraction": 0.2,
                                "target_risk_pct": 0.02,
                            }
                        }
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
