from __future__ import annotations

import unittest

from arena_agent.sdk.agent import ArenaAgent


class FakeClient:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments=None):
        arguments = arguments or {}
        self.calls.append((name, arguments))
        if name == "varsity.competition_info":
            return {
                "competition_id": 4,
                "symbol": "BTCUSDT",
                "status": "live",
                "is_live": True,
                "is_close_only": False,
                "current_trades": 1,
                "max_trades": 40,
                "max_trades_remaining": 39,
                "time_remaining_seconds": 60.0,
            }
        if name == "varsity.market_state":
            return {
                "market": {"last_price": 100.0, "orderbook_imbalance": 0.3},
                "position": None,
            }
        if name == "varsity.trade_action":
            return {
                "action": {"type": arguments["type"], "size": arguments.get("size")},
                "execution_result": {"accepted": True, "executed": arguments.get("execute", False)},
            }
        if name == "varsity.last_transition":
            return {"transition": {"action": {"type": "HOLD"}}}
        raise AssertionError(name)


class SDKTest(unittest.TestCase):
    def test_state_and_competition_info_return_attribute_views(self) -> None:
        agent = ArenaAgent(client=FakeClient(), config_path="cfg.yaml")

        info = agent.competition_info()
        state = agent.state()

        self.assertEqual(info.symbol, "BTCUSDT")
        self.assertEqual(state.market.last_price, 100.0)

    def test_action_helpers_delegate_to_trade_tool(self) -> None:
        client = FakeClient()
        agent = ArenaAgent(client=client)

        result = agent.long(0.001)

        self.assertEqual(result.action.type, "OPEN_LONG")
        self.assertEqual(client.calls[-1][0], "varsity.trade_action")
        self.assertEqual(client.calls[-1][1]["size"], 0.001)

    def test_run_executes_policy(self) -> None:
        client = FakeClient()
        agent = ArenaAgent(client=client)

        results = agent.run(lambda state: {"type": "OPEN_LONG", "size": 0.001}, max_steps=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].action.type, "OPEN_LONG")


if __name__ == "__main__":
    unittest.main()
