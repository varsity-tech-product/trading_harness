"""Minimal SDK example."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena_agent.sdk import ArenaAgent


def simple_policy(state):
    if state.position is None and state.market.orderbook_imbalance is not None and state.market.orderbook_imbalance > 0.25:
        return {"type": "OPEN_LONG", "size": 0.001}
    if state.position is not None:
        return "HOLD"
    return "HOLD"


if __name__ == "__main__":
    agent = ArenaAgent()
    print(agent.competition_info().to_dict())
    print(agent.run(simple_policy, max_steps=1))
