"""Thin developer SDK on top of the Arena MCP server."""

from __future__ import annotations

import time
from typing import Any, Callable

from arena_agent.sdk.client import ArenaMCPClient
from arena_agent.sdk.views import as_view


class ArenaAgent:
    def __init__(self, client: ArenaMCPClient | None = None, config_path: str | None = None) -> None:
        self.client = client or ArenaMCPClient()
        self.config_path = config_path

    def state(self):
        return as_view(self._call("varsity.market_state"))

    def competition_info(self):
        return as_view(self._call("varsity.competition_info"))

    def last_transition(self):
        return as_view(self._call("varsity.last_transition"))

    def action(
        self,
        action_type: str,
        *,
        size: float | None = None,
        tp: float | None = None,
        sl: float | None = None,
        execute: bool = False,
    ):
        return as_view(
            self._call(
                "varsity.trade_action",
                {
                    "type": action_type,
                    "size": size,
                    "tp": tp,
                    "sl": sl,
                    "execute": execute,
                },
            )
        )

    def long(self, size: float | None = None, *, tp: float | None = None, sl: float | None = None, execute: bool = False):
        return self.action("OPEN_LONG", size=size, tp=tp, sl=sl, execute=execute)

    def short(self, size: float | None = None, *, tp: float | None = None, sl: float | None = None, execute: bool = False):
        return self.action("OPEN_SHORT", size=size, tp=tp, sl=sl, execute=execute)

    def close(self, *, execute: bool = False):
        return self.action("CLOSE_POSITION", execute=execute)

    def hold(self):
        return self.action("HOLD")

    def running(self) -> bool:
        info = self.competition_info()
        return bool(info.is_live and (info.time_remaining_seconds is None or info.time_remaining_seconds > 0))

    def run(self, policy: Callable[[Any], Any], *, max_steps: int | None = None, sleep_seconds: float = 0.0, execute: bool = False):
        steps = 0
        results = []
        while self.running():
            if max_steps is not None and steps >= max_steps:
                break
            state = self.state()
            decision = policy(state)
            result = self._dispatch_policy_decision(decision, execute=execute)
            results.append(result)
            steps += 1
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        return results

    def _dispatch_policy_decision(self, decision: Any, *, execute: bool):
        if isinstance(decision, str):
            return self.action(decision, execute=execute)
        if isinstance(decision, dict):
            payload = dict(decision)
            payload.setdefault("execute", execute)
            return as_view(self._call("varsity.trade_action", payload))
        action_type = getattr(decision, "type", None)
        if action_type is not None:
            return self.action(
                action_type,
                size=getattr(decision, "size", None),
                tp=getattr(decision, "take_profit", None),
                sl=getattr(decision, "stop_loss", None),
                execute=execute,
            )
        raise TypeError(f"Unsupported policy decision: {decision!r}")

    def _call(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        arguments = dict(arguments or {})
        if self.config_path is not None:
            arguments.setdefault("config_path", self.config_path)
        return self.client.call_tool(tool_name, arguments)
