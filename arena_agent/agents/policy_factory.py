"""Policy factory and ensemble composition.

All signal logic is defined by the agent via expression strings.
No hardcoded indicator logic — the agent subscribes to TA-Lib
indicators and writes entry/exit conditions as expressions.
"""

from __future__ import annotations

from typing import Sequence

from arena_agent.core.models import AgentState, TransitionEvent
from arena_agent.interfaces.action_schema import Action
from arena_agent.interfaces.policy_interface import Policy
from arena_agent.tap.http_policy import HttpTapPolicy


class HoldPolicy(Policy):
    name = "hold"

    def decide(self, state: AgentState) -> Action:
        return Action.hold(reason="hold policy")


class EnsemblePolicy(Policy):
    """Evaluate multiple expression policies — first non-HOLD signal wins."""

    def __init__(self, policies: Sequence[Policy]) -> None:
        self.policies = list(policies)
        self.name = "ensemble"

    def decide(self, state: AgentState) -> Action:
        for policy in self.policies:
            action = policy.decide(state)
            if not action.is_hold:
                return action
        return Action.hold(reason="ensemble no-op")

    def update(self, memory: Sequence[TransitionEvent]) -> None:
        for policy in self.policies:
            policy.update(memory)


def build_policy(config: dict, *, runtime_config=None) -> Policy:
    """Build a policy from a config dict.

    Supported types:
    - ``expression``: agent-defined signal expressions (default)
    - ``ensemble``: list of expression policies, first non-HOLD wins
    - ``tap_http``: external HTTP decision endpoint
    - ``hold``: always HOLD
    """
    from arena_agent.agents.expression_policy import ExpressionPolicy

    policy_type = str(config.get("type", "expression")).lower()
    params = dict(config.get("params", {}))

    if policy_type == "expression":
        return ExpressionPolicy(
            entry_long=str(params.get("entry_long", "False")),
            entry_short=str(params.get("entry_short", "False")),
            exit_expr=str(params.get("exit", "False")),
            exit_long_expr=str(params.get("exit_long", "False")),
            exit_short_expr=str(params.get("exit_short", "False")),
            reentry_cooldown_seconds=float(params.get("reentry_cooldown_seconds", 300.0)),
        )
    if policy_type == "ensemble":
        members = [
            build_policy(member, runtime_config=runtime_config)
            for member in config.get("members", [])
        ]
        return EnsemblePolicy(members or [HoldPolicy()])
    if policy_type == "tap_http":
        endpoint = config.get("endpoint") or params.pop("endpoint", None)
        if not endpoint:
            raise ValueError("tap_http policy requires an 'endpoint'")
        timeout_seconds = float(config.get("timeout_seconds", params.pop("timeout_seconds", 10.0)))
        headers = dict(config.get("headers", params.pop("headers", {})))
        fail_open_to_hold = bool(config.get("fail_open_to_hold", params.pop("fail_open_to_hold", True)))
        return HttpTapPolicy(
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            headers=headers,
            fail_open_to_hold=fail_open_to_hold,
            **params,
        )
    if policy_type == "hold":
        return HoldPolicy()

    # Unknown type → treat as expression (agent may have used old policy names)
    return ExpressionPolicy(
        entry_long=str(params.get("entry_long", "False")),
        entry_short=str(params.get("entry_short", "False")),
        exit_expr=str(params.get("exit", "False")),
        exit_long_expr=str(params.get("exit_long", "False")),
        exit_short_expr=str(params.get("exit_short", "False")),
        reentry_cooldown_seconds=float(params.get("reentry_cooldown_seconds", 300.0)),
    )
