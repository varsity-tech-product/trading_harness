"""Plain Python tool functions exposed through MCP."""

from __future__ import annotations

from arena_agent.core.runtime_loop import build_transition_event
from arena_agent.interfaces.action_schema import Action, ActionType
from arena_agent.skills.shared import build_runtime_components, read_last_transition


def market_state(config_path: str | None = None):
    _, _, state_builder, _, _, _ = build_runtime_components(config_path)
    return state_builder.build()


def competition_info(config_path: str | None = None):
    state = market_state(config_path)
    return {
        "competition_id": state.competition.competition_id,
        "symbol": state.competition.symbol,
        "status": state.competition.status,
        "is_live": state.competition.is_live,
        "is_close_only": state.competition.is_close_only,
        "current_trades": state.competition.current_trades,
        "max_trades": state.competition.max_trades,
        "max_trades_remaining": state.competition.max_trades_remaining,
        "time_remaining_seconds": state.competition.time_remaining_seconds,
        "metadata": state.competition.metadata,
    }


def trade_action(
    type: str,
    size: float | None = None,
    tp: float | None = None,
    sl: float | None = None,
    execute: bool = False,
    config_path: str | None = None,
):
    config, _, state_builder, executor, transition_store, _ = build_runtime_components(config_path)
    executor.dry_run = config.dry_run if not execute else False

    state_before = state_builder.build()
    action = Action(
        type=ActionType(str(type).upper()),
        size=size,
        take_profit=tp,
        stop_loss=sl,
    )
    execution_result = executor.execute(action, state_before)
    state_after = state_builder.build()
    transition = build_transition_event(state_before, action, execution_result, state_after)
    transition_store.append(transition)

    return {
        "action": action,
        "execution_result": execution_result,
        "transition": transition,
    }


def last_transition(config_path: str | None = None):
    config, _, _, _, _, _ = build_runtime_components(config_path)
    return {"transition": read_last_transition(config.storage.transition_path)}
