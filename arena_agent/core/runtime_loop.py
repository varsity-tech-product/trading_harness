"""Runtime loop that coordinates state, policy, execution, transitions, and memory."""

from __future__ import annotations

import logging
import signal
import time

from arena_agent.agents.policy_factory import build_policy
from arena_agent.interfaces.action_schema import Action
from arena_agent.core.environment_adapter import EnvironmentAdapter
from arena_agent.core.models import RuntimeConfig, RuntimeReport, TransitionEvent, TransitionMetrics
from arena_agent.core.runtime_safety import detect_position_drift, evaluate_state_guard
from arena_agent.core.serialization import to_jsonable
from arena_agent.core.state_builder import StateBuilder
from arena_agent.execution.order_executor import OrderExecutor
from arena_agent.memory.transition_store import TransitionStore
from arena_agent.memory.trade_journal import TradeJournal
from arena_agent.strategy.builder import build_strategy_layer


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
        strategy=None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("arena_agent.runtime")
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
        self.policy = policy or build_policy(config.policy, runtime_config=config)
        self.strategy = strategy or build_strategy_layer(config.strategy, risk_limits=config.risk_limits)

    def run(self) -> RuntimeReport:
        self.policy.reset()
        start_timestamp = time.time()
        iterations = 0
        decisions = 0
        executed_actions = 0
        total_realized_pnl = 0.0
        total_fees = 0.0
        last_state = None
        previous_live_state = None
        stop_reason = "stopped"
        self._stop_requested = False

        def _on_sigterm(signum, frame):
            self._stop_requested = True

        prev_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _on_sigterm)

        try:
            return self._run_loop(
                start_timestamp, iterations, decisions, executed_actions,
                total_realized_pnl, total_fees, last_state, previous_live_state,
                stop_reason,
            )
        finally:
            signal.signal(signal.SIGTERM, prev_handler)

    def _run_loop(
        self, start_timestamp, iterations, decisions, executed_actions,
        total_realized_pnl, total_fees, last_state, previous_live_state,
        stop_reason,
    ) -> RuntimeReport:
        while True:
            # Check for graceful shutdown request (SIGTERM)
            if self._stop_requested:
                self.logger.info("SIGTERM received — shutting down gracefully.")
                self._close_position_on_exit()
                stop_reason = "sigterm"
                break
            if self.config.max_iterations is not None and iterations >= self.config.max_iterations:
                stop_reason = "max_iterations_reached"
                break

            iterations += 1
            try:
                state = self.state_builder.build()
                last_state = state
                drift_message = detect_position_drift(previous_live_state, state)
                if drift_message is not None:
                    self.logger.warning(drift_message)
                    self.journal.record(
                        "position_drift",
                        {"iteration": iterations, "timestamp": time.time(), "message": drift_message},
                    )
                if self.config.stop_when_competition_inactive and not state.competition.is_live:
                    self.logger.info("Competition %s is not live; stopping runtime.", self.config.competition_id)
                    self.journal.record(
                        "runtime_stopped",
                        {"reason": "competition_inactive", "timestamp": time.time()},
                    )
                    stop_reason = "competition_inactive"
                    break

                guard = evaluate_state_guard(
                    state,
                    max_feature_age_seconds=_feature_age_threshold_seconds(self.config),
                    require_feature_timestamp_match=True,
                )
                if not guard.ok:
                    self.logger.warning("State guard forced HOLD: %s", guard.reason)
                    self.journal.record(
                        "state_guard_failure",
                        {
                            "iteration": iterations,
                            "timestamp": time.time(),
                            "reason": guard.reason,
                            "details": guard.details,
                        },
                    )
                    action = self._build_guard_hold_action(guard)
                    decision_latency = 0.0
                else:
                    decision_started_at = time.time()
                    action = self.policy.decide(state)
                    decision_latency = time.time() - decision_started_at
                if self.strategy is not None:
                    try:
                        action = self.strategy.refine(action, state)
                    except (TypeError, ValueError) as strat_exc:
                        self.logger.warning(
                            "Strategy refine failed: %s", strat_exc
                        )
                        # Demote to HOLD — never send an order without TP/SL protection
                        if not action.is_hold:
                            self.logger.warning(
                                "Demoting %s to HOLD — strategy refine failed, no TP/SL on order",
                                action.type,
                            )
                            action = Action.hold(reason=f"strategy_refine_failed: {strat_exc}")
                decisions += 1
                execution_result = self.executor.execute(action, state)
                if execution_result.executed:
                    executed_actions += 1

                next_state = self.state_builder.build()
                last_state = next_state
                previous_live_state = next_state
                transition = self._build_transition(state, action, execution_result, next_state)
                total_realized_pnl += transition.metrics.realized_pnl_delta
                total_fees += transition.metrics.fee

                self.transition_store.append(transition)
                self.policy.update(self.transition_store.recent())

                # Dynamic indicator requests from agent (available next tick)
                requested_indicators = action.metadata.get("indicators")
                if requested_indicators and isinstance(requested_indicators, list):
                    added = self.state_builder.add_indicators(requested_indicators)
                    if added:
                        self.logger.info("Agent requested %d new indicator(s) for next tick.", added)
                self.journal.record(
                    "transition",
                    {
                        "iteration": iterations,
                        "timestamp": transition.timestamp,
                        "action": to_jsonable(action),
                        "execution_result": to_jsonable(execution_result),
                        "metrics": to_jsonable(transition.metrics),
                        "equity_after": next_state.account.equity,
                        "llm_usage": action.metadata.get("llm_usage"),
                    },
                )

                fee = transition.metrics.fee
                self.logger.info(
                    "Iteration %s | action=%s accepted=%s executed=%s pnl_delta=%.4f fee=%.4f equity_delta=%.4f equity=%.2f",
                    iterations,
                    action.type.value,
                    execution_result.accepted,
                    execution_result.executed,
                    transition.metrics.realized_pnl_delta,
                    fee,
                    transition.metrics.equity_delta,
                    next_state.account.equity,
                )

                llm_usage = action.metadata.get("llm_usage")
                if llm_usage and isinstance(llm_usage, dict):
                    parts = []
                    if llm_usage.get("input_tokens") is not None:
                        parts.append(f"in={llm_usage['input_tokens']}")
                    if llm_usage.get("output_tokens") is not None:
                        parts.append(f"out={llm_usage['output_tokens']}")
                    if llm_usage.get("cost_usd") is not None:
                        parts.append(f"cost=${llm_usage['cost_usd']}")
                    if llm_usage.get("duration_ms") is not None:
                        parts.append(f"duration={llm_usage['duration_ms']}ms")
                    if parts:
                        self.logger.info("LLM usage | %s", " ".join(parts))

                if next_state.competition.time_remaining_seconds is not None and next_state.competition.time_remaining_seconds <= 0:
                    self.logger.info("Competition time exhausted; stopping runtime.")
                    stop_reason = "competition_exhausted"
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
            # Sleep in small increments so SIGTERM is responsive
            sleep_remaining = self.config.tick_interval_seconds
            while sleep_remaining > 0 and not self._stop_requested:
                nap = min(sleep_remaining, 2.0)
                time.sleep(nap)
                sleep_remaining -= nap

        # Close position when competition ends naturally
        if stop_reason in ("competition_inactive", "competition_exhausted"):
            self._close_position_on_exit()

        end_timestamp = time.time()
        final_equity = None if last_state is None else last_state.account.equity
        final_balance = None if last_state is None else last_state.account.balance
        report = RuntimeReport(
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
        return report


    def _close_position_on_exit(self) -> None:
        """Attempt to close any open position before shutdown."""
        try:
            position = self.executor.adapter.get_live_position(self.config.competition_id)
            if position and isinstance(position, dict) and position.get("direction"):
                self.logger.info(
                    "Closing open %s position (size=%s) before exit...",
                    position.get("direction"), position.get("size"),
                )
                self.executor.adapter.trade_close(self.config.competition_id)
                self.logger.info("Position closed successfully.")
        except Exception as exc:
            self.logger.warning("Failed to close position on exit: %s", exc)

    def _build_transition(self, state, action, execution_result, next_state) -> TransitionEvent:
        return build_transition_event(state, action, execution_result, next_state)

    def _build_guard_hold_action(self, guard) -> Any:
        from arena_agent.interfaces.action_schema import Action

        return Action.hold(
            reason=f"state_guard:{guard.reason or 'unknown'}",
            guard_details=guard.details,
        )


def _feature_age_threshold_seconds(config: RuntimeConfig) -> float:
    return max(60.0, float(config.tick_interval_seconds) * 2.0)
