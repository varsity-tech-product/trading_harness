"""Built-in rule-based policy implementations and factory helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena_agent.agents.agent_exec_policy import AgentExecPolicy
from arena_agent.agents.indicators import rolling_sma, rsi
from arena_agent.core.models import AgentState, TransitionEvent
from arena_agent.interfaces.action_schema import Action, ActionType
from arena_agent.interfaces.policy_interface import Policy
from arena_agent.tap.http_policy import HttpTapPolicy


class HoldPolicy(Policy):
    name = "hold"

    def decide(self, state: AgentState) -> Action:
        return Action.hold(reason="hold policy")


@dataclass
class MovingAverageCrossPolicy(Policy):
    fast_period: int = 20
    slow_period: int = 50
    name: str = "ma_crossover"

    def decide(self, state: AgentState) -> Action:
        closes = [candle.close for candle in state.market.recent_candles]
        if len(closes) < self.slow_period + 2:
            return Action.hold(reason="insufficient candles")

        fast = rolling_sma(closes, self.fast_period)
        slow = rolling_sma(closes, self.slow_period)
        prev_fast = fast[-3]
        curr_fast = fast[-2]
        prev_slow = slow[-3]
        curr_slow = slow[-2]

        if None in (prev_fast, curr_fast, prev_slow, curr_slow):
            return Action.hold(reason="indicator warmup")

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            if state.position and state.position.direction == "short":
                return Action(type=ActionType.CLOSE_POSITION, metadata={"reason": "bullish crossover vs short"})
            if state.position is None:
                return Action(type=ActionType.OPEN_LONG, metadata={"reason": "bullish crossover"})

        if prev_fast >= prev_slow and curr_fast < curr_slow:
            if state.position and state.position.direction == "long":
                return Action(type=ActionType.CLOSE_POSITION, metadata={"reason": "bearish crossover vs long"})
            if state.position is None:
                return Action(type=ActionType.OPEN_SHORT, metadata={"reason": "bearish crossover"})

        return Action.hold(reason="no crossover")


@dataclass
class RSIMeanReversionPolicy(Policy):
    rsi_period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0
    exit_level: float = 50.0
    name: str = "rsi_mean_reversion"

    def decide(self, state: AgentState) -> Action:
        closes = [candle.close for candle in state.market.recent_candles]
        values = rsi(closes, self.rsi_period)
        if len(values) < self.rsi_period + 3:
            return Action.hold(reason="insufficient candles")

        prev_rsi = values[-3]
        curr_rsi = values[-2]
        if prev_rsi is None or curr_rsi is None:
            return Action.hold(reason="indicator warmup")

        if state.position:
            if state.position.direction == "long" and prev_rsi < self.exit_level <= curr_rsi:
                return Action(type=ActionType.CLOSE_POSITION, metadata={"reason": "rsi mean reversion exit"})
            if state.position.direction == "short" and prev_rsi > self.exit_level >= curr_rsi:
                return Action(type=ActionType.CLOSE_POSITION, metadata={"reason": "rsi mean reversion exit"})

        if prev_rsi >= self.oversold and curr_rsi < self.oversold and state.position is None:
            return Action(type=ActionType.OPEN_LONG, metadata={"reason": "rsi oversold entry"})
        if prev_rsi <= self.overbought and curr_rsi > self.overbought and state.position is None:
            return Action(type=ActionType.OPEN_SHORT, metadata={"reason": "rsi overbought entry"})
        return Action.hold(reason="no rsi signal")


@dataclass
class ChannelBreakoutPolicy(Policy):
    lookback: int = 20
    name: str = "channel_breakout"

    def decide(self, state: AgentState) -> Action:
        candles = state.market.recent_candles
        if len(candles) < self.lookback + 2:
            return Action.hold(reason="insufficient candles")

        completed = candles[-(self.lookback + 1) : -1]
        channel_high = max(candle.high for candle in completed)
        channel_low = min(candle.low for candle in completed)
        price = state.market.last_price

        if state.position:
            if state.position.direction == "long" and price < channel_low:
                return Action(type=ActionType.CLOSE_POSITION, metadata={"reason": "breakdown against long"})
            if state.position.direction == "short" and price > channel_high:
                return Action(type=ActionType.CLOSE_POSITION, metadata={"reason": "breakout against short"})
            return Action.hold(reason="holding breakout position")

        if price > channel_high:
            return Action(type=ActionType.OPEN_LONG, metadata={"reason": "channel breakout"})
        if price < channel_low:
            return Action(type=ActionType.OPEN_SHORT, metadata={"reason": "channel breakdown"})
        return Action.hold(reason="inside channel")


class EnsemblePolicy(Policy):
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
    policy_type = str(config.get("type", "hold")).lower()
    params = dict(config.get("params", {}))

    if policy_type == "ma_crossover":
        return MovingAverageCrossPolicy(**params)
    if policy_type == "rsi_mean_reversion":
        return RSIMeanReversionPolicy(**params)
    if policy_type == "channel_breakout":
        return ChannelBreakoutPolicy(**params)
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
    if policy_type in ("agent_exec", "codex_exec"):
        backend = str(config.get("backend", params.pop("backend", "auto")))
        model = config.get("model") or params.pop("model", None)
        command = config.get("command") or params.pop("command", None)
        timeout_seconds = float(config.get("timeout_seconds", params.pop("timeout_seconds", 45.0)))
        recent_transition_limit = int(
            config.get("recent_transition_limit", params.pop("recent_transition_limit", 5))
        )
        fail_open_to_hold = bool(config.get("fail_open_to_hold", params.pop("fail_open_to_hold", True)))
        sandbox_mode = str(config.get("sandbox_mode", params.pop("sandbox_mode", "read-only")))
        cwd = config.get("cwd") or params.pop("cwd", None)
        extra_instructions = str(config.get("extra_instructions", params.pop("extra_instructions", "")))
        strategy_context = str(config.get("strategy_context", params.pop("strategy_context", "")))
        bootstrap_from_transition_log = bool(
            config.get("bootstrap_from_transition_log", params.pop("bootstrap_from_transition_log", True))
        )
        transition_path = None if runtime_config is None else runtime_config.storage.transition_path
        risk_limits = None if runtime_config is None else runtime_config.risk_limits
        return AgentExecPolicy(
            backend=backend,
            model=model,
            command=command,
            timeout_seconds=timeout_seconds,
            recent_transition_limit=recent_transition_limit,
            fail_open_to_hold=fail_open_to_hold,
            sandbox_mode=sandbox_mode,
            cwd=cwd,
            extra_instructions=extra_instructions,
            strategy_context=strategy_context,
            transition_path=transition_path,
            bootstrap_from_transition_log=bootstrap_from_transition_log,
            risk_limits=risk_limits,
            **params,
        )
    if policy_type == "ensemble":
        members = [build_policy(member, runtime_config=runtime_config) for member in config.get("members", [])]
        return EnsemblePolicy(members or [HoldPolicy()])
    return HoldPolicy()
