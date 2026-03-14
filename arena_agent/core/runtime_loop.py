"""Runtime loop that coordinates state, policy, execution, transitions, and memory."""

from __future__ import annotations

import logging
import time

from arena_agent.agents.rule_agent import build_policy
from arena_agent.core.environment_adapter import EnvironmentAdapter
from arena_agent.core.models import RuntimeConfig, RuntimeReport, TransitionEvent, TransitionMetrics
from arena_agent.core.serialization import to_jsonable
from arena_agent.core.state_builder import StateBuilder
from arena_agent.execution.order_executor import OrderExecutor
from arena_agent.memory.transition_store import TransitionStore
from arena_agent.memory.trade_journal import TradeJournal


def build_transition_event(state, action, execution_result, next_state) -> TransitionEvent:
    realized_pnl_delta = execution_result.realized_pnl
    if realized_pnl_delta == 0.0:
        realized_pnl_delta = next_state.account.realized_pnl - state.account.realized_pnl

    metrics = TransitionMetrics(
        market_price_before=state.market.last_price,
        market_price_after=next_state.market.last_price,
        price_delta=next_state.market.last_price - state.market.last_price,
        balance_before=state.account.balance,
        balance_after=next_state.account.balance,
        balance_delta=next_state.account.balance - state.account.balance,
        equity_before=state.account.equity,
        equity_after=next_state.account.equity,
        equity_delta=next_state.account.equity - state.account.equity,
        unrealized_pnl_before=state.account.unrealized_pnl,
        unrealized_pnl_after=next_state.account.unrealized_pnl,
        unrealized_pnl_delta=next_state.account.unrealized_pnl - state.account.unrealized_pnl,
        realized_pnl_delta=realized_pnl_delta,
        fee=execution_result.fee,
        trade_count_before=state.account.trade_count,
        trade_count_after=next_state.account.trade_count,
        trade_count_delta=next_state.account.trade_count - state.account.trade_count,
        position_changed=(state.position != next_state.position),
    )
    return TransitionEvent(
        timestamp=time.time(),
        state_before=state,
        action=action,
        execution_result=execution_result,
        state_after=next_state,
        metrics=metrics,
        metadata={},
    )


class MarketRuntime:
    def __init__(
        self,
        config: RuntimeConfig,
        adapter: EnvironmentAdapter | None = None,
        state_builder: StateBuilder | None = None,
        executor: OrderExecutor | None = None,
        transition_store: TransitionStore | None = None,
        experience_store: TransitionStore | None = None,
        journal: TradeJournal | None = None,
        policy=None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.adapter = adapter or EnvironmentAdapter(
            retry_attempts=config.adapter_retry_attempts,
            retry_backoff_seconds=config.adapter_retry_backoff_seconds,
            min_call_spacing_seconds=config.adapter_min_call_spacing_seconds,
        )
        self.state_builder = state_builder or StateBuilder(self.adapter, config)
        self.executor = executor or OrderExecutor(
            self.adapter,
            competition_id=config.competition_id,
            risk_limits=config.risk_limits,
            dry_run=config.dry_run,
        )
        if transition_store is not None:
            self.transition_store = transition_store
        elif experience_store is not None:
            self.transition_store = experience_store
        else:
            self.transition_store = TransitionStore(
                maxlen=config.storage.max_in_memory_transitions,
                output_path=config.storage.transition_path,
            )
        self.journal = journal or TradeJournal(config.storage.journal_path)
        self.policy = policy or build_policy(config.policy)
        self.logger = logger or logging.getLogger("arena_agent.runtime")

    def run(self) -> RuntimeReport:
        self.policy.reset()
        start_timestamp = time.time()
        iterations = 0
        decisions = 0
        executed_actions = 0
        total_realized_pnl = 0.0
        total_fees = 0.0
        last_state = None

        while True:
            if self.config.max_iterations is not None and iterations >= self.config.max_iterations:
                break

            iterations += 1
            try:
                state = self.state_builder.build()
                last_state = state
                if self.config.stop_when_competition_inactive and not state.competition.is_live:
                    self.logger.info("Competition %s is not live; stopping runtime.", self.config.competition_id)
                    self.journal.record(
                        "runtime_stopped",
                        {"reason": "competition_inactive", "timestamp": time.time()},
                    )
                    break

                action = self.policy.decide(state)
                decisions += 1
                execution_result = self.executor.execute(action, state)
                if execution_result.executed:
                    executed_actions += 1

                next_state = self.state_builder.build()
                last_state = next_state
                transition = self._build_transition(state, action, execution_result, next_state)
                total_realized_pnl += transition.metrics.realized_pnl_delta
                total_fees += transition.metrics.fee

                self.transition_store.append(transition)
                self.policy.update(self.transition_store.recent())
                self.journal.record(
                    "transition",
                    {
                        "iteration": iterations,
                        "timestamp": transition.timestamp,
                        "action": to_jsonable(action),
                        "execution_result": to_jsonable(execution_result),
                        "metrics": to_jsonable(transition.metrics),
                        "equity_after": next_state.account.equity,
                    },
                )

                self.logger.info(
                    "Iteration %s | action=%s accepted=%s executed=%s pnl_delta=%.4f equity_delta=%.4f equity=%.2f",
                    iterations,
                    action.type.value,
                    execution_result.accepted,
                    execution_result.executed,
                    transition.metrics.realized_pnl_delta,
                    transition.metrics.equity_delta,
                    next_state.account.equity,
                )

                if next_state.competition.time_remaining_seconds is not None and next_state.competition.time_remaining_seconds <= 0:
                    self.logger.info("Competition time exhausted; stopping runtime.")
                    break

            except Exception as exc:
                self.logger.exception("Runtime iteration %s failed: %s", iterations, exc)
                self.journal.record(
                    "error",
                    {"iteration": iterations, "timestamp": time.time(), "error": str(exc)},
                )
                time.sleep(self.config.error_backoff_seconds)
                continue

            if self.config.max_iterations is not None and iterations >= self.config.max_iterations:
                break
            time.sleep(self.config.tick_interval_seconds)

        end_timestamp = time.time()
        final_equity = None if last_state is None else last_state.account.equity
        final_balance = None if last_state is None else last_state.account.balance
        return RuntimeReport(
            iterations=iterations,
            final_equity=final_equity,
            final_balance=final_balance,
            decisions=decisions,
            executed_actions=executed_actions,
            transitions_recorded=len(self.transition_store),
            total_realized_pnl=total_realized_pnl,
            total_fees=total_fees,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

    def _build_transition(self, state, action, execution_result, next_state) -> TransitionEvent:
        return build_transition_event(state, action, execution_result, next_state)
