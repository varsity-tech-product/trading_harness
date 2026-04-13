"""Builds the JSON context that the setup agent LLM receives."""

from __future__ import annotations

import logging
import time
from typing import Any

import varsity_tools

from arena_agent.setup.memory import CompetitionRecord

logger = logging.getLogger("arena_agent.setup.context_builder")


def build_setup_context(
    competition_id: int,
    config: dict[str, Any],
    memory: list[CompetitionRecord],
    *,
    inactivity_alert: bool = False,
    inactive_minutes: int = 0,
    tight_exit_alert: bool = False,
    tight_exit_avg_hold: float = 0,
    consecutive_hold_cycles: int = 0,
    total_runtime_iterations: int = 0,
    competition_ending_soon: bool = False,
    competition_remaining_minutes: float = 0,
) -> dict[str, Any]:
    """Assemble everything the setup agent needs to make a decision."""
    context: dict[str, Any] = {}

    # Cooldown lock is injected later (after trade count is known) as STRATEGY_LOCKED.

    if inactivity_alert:
        context["inactivity_alert"] = {
            "active": True,
            "inactive_minutes": inactive_minutes,
            "message": (
                f"NOTE: Your current strategy has produced NO trades for {inactive_minutes} minutes. "
                "Consider whether the current policy is suitable for this market, or if different "
                "parameters or a different strategy type would generate more signals."
            ),
        }

    if tight_exit_alert:
        context["tight_exit_alert"] = {
            "active": True,
            "avg_hold_seconds": tight_exit_avg_hold,
            "message": (
                f"WARNING: Your recent trades are closing in {tight_exit_avg_hold:.0f}s on average — "
                "TP/SL or exit expression is too tight. "
                "Widen tp_pct to at least 1.5% and sl_pct to at least 1.0%, "
                "or relax exit expression thresholds to give trades room to breathe."
            ),
        }

    if competition_ending_soon:
        mins = round(competition_remaining_minutes, 1)
        context["competition_ending_soon"] = {
            "active": True,
            "remaining_minutes": mins,
            "message": (
                f"ALERT: Competition ends in {mins} minutes. "
                "Close any open positions and stop opening new trades. "
                "Switch to defensive mode — protect your current PnL. "
                "Do NOT open new positions unless you can close them before time runs out."
            ),
        }

    # Trading mode: rule_based (default) or discretionary
    context["mode"] = config.get("mode", "rule_based")

    symbol = config.get("symbol", "BTCUSDT")
    interval = config.get("interval", "1m")

    # Account state
    try:
        account = varsity_tools.get_live_account(competition_id)
        if isinstance(account, dict) and account.get("code") is None:
            # API fields: capital (equity), walletBalance, availableBalance,
            # unrealizedPnl, initialBalance, tradesCount, maxTrades
            equity = float(account.get("capital") or account.get("equity") or 5000)
            initial = float(account.get("initialBalance") or 5000)
            wallet = float(account.get("walletBalance") or account.get("balance") or equity)
            context["account_state"] = {
                "balance": wallet,
                "equity": equity,
                "unrealized_pnl": float(account.get("unrealizedPnl") or 0),
                "realized_pnl": round(wallet - initial, 4),
                "trade_count": int(account.get("tradesCount") or 0),
                "initial_balance": initial,
            }
        else:
            context["account_state"] = {"error": str(account)}
    except Exception as exc:
        context["account_state"] = {"error": str(exc)}

    # Position
    try:
        position = varsity_tools.get_live_position(competition_id)
        context["position"] = position
    except Exception as exc:
        context["position"] = {"error": str(exc)}

    # Competition info
    try:
        detail = varsity_tools.get_competition_detail(str(competition_id))
        if isinstance(detail, dict):
            context["competition"] = {
                "id": competition_id,
                "title": detail.get("title"),
                "status": detail.get("status"),
                "symbol": detail.get("symbol") or symbol,
                "start_time": detail.get("startTime"),
                "end_time": detail.get("endTime"),
                "max_trades": detail.get("maxTradesPerMatch") or detail.get("maxTrades"),
                "starting_capital": detail.get("startingCapital"),
                "fee_rate": detail.get("feeRate") or detail.get("fee_rate"),
            }
            # Use competition symbol if available (asset-agnostic)
            comp_symbol = detail.get("symbol")
            if comp_symbol:
                symbol = comp_symbol
                context["competition"]["symbol"] = comp_symbol
            # Compute trades remaining
            trade_count = 0
            acct = context.get("account_state", {})
            if isinstance(acct, dict) and "trade_count" in acct:
                trade_count = acct["trade_count"]
            max_trades = detail.get("maxTradesPerMatch") or detail.get("maxTrades")
            if max_trades is not None:
                context["competition"]["trades_remaining"] = max(0, max_trades - trade_count)
    except Exception as exc:
        context["competition"] = {"id": competition_id, "error": str(exc)}

    # --- Compact header: symbol, price, equity, position (Layer 1) ---
    # Use the competition symbol when available so setup decisions and runtime
    # always reason about the actual contest asset.
    try:
        market = _compute_market_summary(symbol, interval)
        context["market_summary"] = market
    except Exception as exc:
        market = {"available": False, "error": str(exc)}
        context["market_summary"] = market

    # Current config snapshot — include policy type for cooldown awareness
    policy_config = config.get("policy", {})
    strategy_start_time = config.get("_strategy_start_time")
    strategy_start_trades = config.get("_strategy_start_trade_count", 0)
    strategy_age_seconds = round(time.time() - strategy_start_time) if strategy_start_time else None

    # Cooldown status
    cooldown_seconds = config.get("_cooldown_seconds", 1200)
    cooldown_min_trades = config.get("_cooldown_min_trades", 5)
    cooldown_remaining = max(0, cooldown_seconds - strategy_age_seconds) if strategy_age_seconds else 0
    strategy_trades = 0
    perf = context.get("performance", {})
    if isinstance(perf, dict) and perf.get("current_strategy_performance"):
        strategy_trades = perf["current_strategy_performance"].get("trade_count", 0)
    elif isinstance(perf, dict):
        strategy_trades = perf.get("trade_count", 0)
    cooldown_trades_needed = max(0, cooldown_min_trades - strategy_trades)
    cooldown_active = cooldown_remaining > 0 and cooldown_trades_needed > 0

    # Inject STRATEGY_LOCKED as first key so the LLM can't miss it
    if cooldown_active:
        mins = round(cooldown_remaining / 60, 1)
        context["STRATEGY_LOCKED"] = (
            f"Strategy change is LOCKED ({mins} min / {cooldown_trades_needed} trades remaining). "
            "You MUST return action=hold. Analyze the market and chat, but do NOT propose strategy changes."
        )

    context["current_strategy"] = {
        "policy": policy_config.get("type", "unknown"),
        "params": policy_config.get("params", {}),
        "age_seconds": strategy_age_seconds,
        "age_minutes": round(strategy_age_seconds / 60, 1) if strategy_age_seconds else None,
        "last_check_interval": config.get("_last_next_check_seconds"),
        "consecutive_hold_cycles": consecutive_hold_cycles,
        "total_runtime_iterations_since_change": total_runtime_iterations,
        "cooldown": {
            "active": cooldown_active,
            "seconds_remaining": cooldown_remaining,
            "minutes_remaining": round(cooldown_remaining / 60, 1),
            "trades_needed": cooldown_trades_needed,
            "cooldown_period_seconds": cooldown_seconds,
        },
    }
    context["current_config"] = {
        "strategy": config.get("strategy", {}),
        "risk_limits": config.get("risk_limits", {}),
        "signal_indicators": config.get("signal_indicators", []),
        "interval": interval,
        "tick_interval_seconds": config.get("tick_interval_seconds", 60),
    }

    # Current indicator values with observed min/max ranges — so the LLM can
    # calibrate expression thresholds to actual market conditions, not textbook levels.
    indicator_ranges = config.get("_indicator_ranges")
    last_indicator_values = config.get("_last_indicator_values")
    if isinstance(indicator_ranges, dict) and indicator_ranges:
        context["current_indicator_values"] = indicator_ranges
    elif isinstance(last_indicator_values, dict) and last_indicator_values:
        context["current_indicator_values"] = last_indicator_values

    # Expression validation errors from previous cycle — so the LLM can fix them
    expr_errors = config.get("_expression_errors")
    if isinstance(expr_errors, list) and expr_errors:
        context["expression_errors"] = expr_errors

    # Recent trade performance and a compact trade tape for live analysis.
    try:
        trades = varsity_tools.get_trade_history(competition_id)
        context["performance"] = _compute_performance_from_trades(
            trades,
            strategy_start_trades=strategy_start_trades,
        )
        context["recent_trades"] = _compact_recent_trades(
            trades,
            strategy_start_trades=strategy_start_trades,
        )
    except Exception as exc:
        context["performance"] = {"error": str(exc)}
        context["recent_trades"] = []

    # Leaderboard position
    try:
        lb = varsity_tools.get_competition_leaderboard_me(competition_id)
        if isinstance(lb, dict) and lb.get("list"):
            entries = lb["list"]
            context["leaderboard"] = {
                "my_rank": entries[0].get("rank") if entries else None,
                "my_entry": entries[0] if len(entries) == 1 else entries,
                "total_participants": lb.get("total"),
            }
        else:
            context["leaderboard"] = lb
    except Exception as exc:
        context["leaderboard"] = {"error": str(exc)}

    # Recent chat messages (for social intelligence)
    try:
        chat = varsity_tools.get_chat_history(competition_id, 30)
        if isinstance(chat, dict) and chat.get("list"):
            context["chat_recent"] = [
                {
                    "username": msg.get("username"),
                    "message": msg.get("message", "")[:200],
                    "timestamp": msg.get("createdAt"),
                }
                for msg in chat["list"][-30:]
            ]
        elif isinstance(chat, list):
            context["chat_recent"] = [
                {
                    "username": msg.get("username"),
                    "message": msg.get("message", "")[:200],
                    "timestamp": msg.get("createdAt"),
                }
                for msg in chat[-30:]
            ]
        else:
            context["chat_recent"] = []
    except Exception:
        context["chat_recent"] = []

    # Multi-timeframe market view (5m and 15m in addition to the default)
    for tf in ["5m", "15m"]:
        if tf == interval:
            continue
        try:
            tf_summary = _compute_market_summary(symbol, tf)
            context[f"market_{tf}"] = tf_summary
        except Exception:
            pass

    # Memory from past competitions — excluded from setup context
    # to reduce prompt size. Memory is available via tools if needed.

    # Audit log: summarize what the setup agent will see
    acct = context.get("account_state", {})
    perf = context.get("performance", {})
    mkt = context.get("market_summary", {})
    logger.info(
        "setup_context built | symbol=%s price=%s equity=%s pnl=%s trades=%s/%s win_rate=%s fees=%s trend=%s",
        symbol,
        mkt.get("current_price"),
        acct.get("equity") if isinstance(acct, dict) else "?",
        acct.get("realized_pnl") if isinstance(acct, dict) else "?",
        acct.get("trade_count") if isinstance(acct, dict) else "?",
        context.get("competition", {}).get("max_trades"),
        perf.get("win_rate") if isinstance(perf, dict) else "?",
        perf.get("total_fees") if isinstance(perf, dict) else "?",
        mkt.get("trend"),
    )

    return context


def _compute_market_summary(symbol: str, interval: str) -> dict[str, Any]:
    """Compute a market summary from recent klines."""
    klines = varsity_tools.get_klines(symbol, interval, 50)
    # get_klines may return {"symbol": ..., "klines": [...]} or a bare list
    if isinstance(klines, dict):
        klines = klines.get("klines", [])
    if not isinstance(klines, list) or len(klines) < 5:
        return {"available": False}

    closes = [float(k[4]) if isinstance(k, list) else float(k.get("close", 0)) for k in klines]
    highs = [float(k[2]) if isinstance(k, list) else float(k.get("high", 0)) for k in klines]
    lows = [float(k[3]) if isinstance(k, list) else float(k.get("low", 0)) for k in klines]

    current = closes[-1]
    sma_20 = sum(closes[-20:]) / min(20, len(closes[-20:])) if len(closes) >= 5 else current

    # Volatility: average true range approximation
    ranges = [h - l for h, l in zip(highs[-14:], lows[-14:])]
    avg_range = sum(ranges) / len(ranges) if ranges else 0
    volatility_pct = (avg_range / current * 100) if current else 0

    # Trend: price vs 20-period SMA
    trend = "neutral"
    if current > sma_20 * 1.002:
        trend = "bullish"
    elif current < sma_20 * 0.998:
        trend = "bearish"

    # Price change over last 10 candles
    if len(closes) >= 10:
        change_pct = (closes[-1] / closes[-10] - 1) * 100
    else:
        change_pct = 0

    return {
        "available": True,
        "current_price": current,
        "sma_20": round(sma_20, 2),
        "trend": trend,
        "volatility_pct": round(volatility_pct, 3),
        "recent_change_pct": round(change_pct, 3),
        "candle_count": len(klines),
    }


def _summarize_trades(trades: list[dict]) -> dict[str, Any]:
    """Compute summary stats for a list of trade dicts."""
    wins = 0
    losses = 0
    total_pnl = 0.0
    total_fees = 0.0
    pnls: list[float] = []
    hold_times: list[float] = []
    trades_stopped_out = 0
    trades_exited_fast = 0  # any trade closing < 60s regardless of pnl

    for trade in trades:
        if not isinstance(trade, dict):
            continue
        # API returns "pnl" (not "realizedPnl") and "fee" (not "commission")
        pnl = float(trade.get("pnl") or trade.get("realizedPnl") or 0)
        pnls.append(pnl)
        total_pnl += pnl
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

        fee = float(trade.get("fee") or trade.get("commission") or 0)
        total_fees += fee

        # Hold time — API provides holdDuration in milliseconds
        hold_sec = trade.get("holdDuration")
        if hold_sec is not None:
            try:
                hold_sec = float(hold_sec) / 1000
                hold_times.append(hold_sec)
                if pnl < 0 and hold_sec < 120:
                    trades_stopped_out += 1
                if hold_sec < 60:
                    trades_exited_fast += 1
            except (TypeError, ValueError):
                pass
        else:
            open_time = trade.get("openTime") or trade.get("entryTime")
            close_time = trade.get("closeTime") or trade.get("exitTime")
            if open_time is not None and close_time is not None:
                try:
                    ot = float(open_time) / 1000 if float(open_time) > 1e12 else float(open_time)
                    ct = float(close_time) / 1000 if float(close_time) > 1e12 else float(close_time)
                    hs = ct - ot
                    if hs >= 0:
                        hold_times.append(hs)
                        if pnl < 0 and hs < 120:
                            trades_stopped_out += 1
                        if hs < 60:
                            trades_exited_fast += 1
                except (TypeError, ValueError):
                    pass

    avg_pnl = total_pnl / len(pnls) if pnls else 0
    win_rate = wins / len(pnls) if pnls else 0
    avg_hold_seconds = sum(hold_times) / len(hold_times) if hold_times else 0

    # Per-direction consecutive loss tracking (most recent trades first)
    def _consecutive_losses_for(direction: str) -> int:
        count = 0
        for t in reversed(trades):
            if not isinstance(t, dict):
                continue
            if str(t.get("direction", "")).lower() != direction:
                continue
            if t.get("closeTime") is None:
                continue  # skip open positions
            pnl_val = float(t.get("pnl") or 0)
            if pnl_val < 0:
                count += 1
            else:
                break
        return count

    return {
        "trade_count": len(pnls),
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 3),
        "total_pnl": round(total_pnl, 4),
        "avg_pnl": round(avg_pnl, 4),
        "total_fees": round(total_fees, 4),
        "avg_hold_seconds": round(avg_hold_seconds, 1),
        "trades_stopped_out": trades_stopped_out,
        "trades_exited_fast": trades_exited_fast,
        "recent_pnls": [round(p, 4) for p in pnls[-10:]],
        "consecutive_long_losses": _consecutive_losses_for("long"),
        "consecutive_short_losses": _consecutive_losses_for("short"),
    }


def _compact_recent_trades(
    trades: list[dict] | Any,
    *,
    limit: int = 8,
    strategy_start_trades: int = 0,
) -> list[dict[str, Any]]:
    """Return a compact recent trade tape for the setup agent.

    Includes enough per-trade detail for fee and exit analysis without dumping
    the full raw API payload into the prompt.
    """
    if not isinstance(trades, list) or not trades:
        return []

    entries: list[dict[str, Any]] = []
    total = len(trades)
    strategy_cutoff = max(0, int(strategy_start_trades))
    for idx, trade in enumerate(trades[:limit]):
        if not isinstance(trade, dict):
            continue

        hold_seconds = None
        raw_hold = trade.get("holdDuration")
        if raw_hold is not None:
            try:
                hold_seconds = round(float(raw_hold) / 1000, 1)
            except (TypeError, ValueError):
                hold_seconds = None
        elif trade.get("openTime") is not None and trade.get("closeTime") is not None:
            try:
                hold_seconds = round((float(trade["closeTime"]) - float(trade["openTime"])) / 1000, 1)
            except (TypeError, ValueError):
                hold_seconds = None

        entries.append(
            {
                "direction": str(trade.get("direction") or "").lower() or None,
                "size": _round_optional(trade.get("size")),
                "entry_price": _round_optional(trade.get("entryPrice") or trade.get("entry_price")),
                "exit_price": _round_optional(trade.get("exitPrice") or trade.get("exit_price")),
                "pnl": _round_optional(trade.get("pnl") or trade.get("realizedPnl")),
                "pnl_pct": _round_optional(trade.get("pnlPct")),
                "fee": _round_optional(trade.get("fee") or trade.get("commission")),
                "hold_seconds": hold_seconds,
                "close_reason": trade.get("closeReason"),
                "opened_at": trade.get("openTime") or trade.get("entryTime"),
                "closed_at": trade.get("closeTime") or trade.get("exitTime"),
                "is_open": trade.get("closeTime") is None or trade.get("exitPrice") is None,
                "under_current_strategy": idx >= strategy_cutoff if strategy_cutoff > 0 else True,
            }
        )
    return entries


def _compute_performance(
    competition_id: int,
    strategy_start_trades: int = 0,
) -> dict[str, Any]:
    """Compute performance metrics from recent trades, with per-strategy breakdown."""
    try:
        trades = varsity_tools.get_trade_history(competition_id)
    except Exception:
        return {"available": False}

    return _compute_performance_from_trades(
        trades,
        strategy_start_trades=strategy_start_trades,
    )


def _compute_performance_from_trades(
    trades: list[dict] | Any,
    strategy_start_trades: int = 0,
) -> dict[str, Any]:
    """Compute performance metrics from a trade list, with per-strategy breakdown."""

    if not isinstance(trades, list) or not trades:
        return {"available": False, "trade_count": 0}

    # Overall performance
    result = _summarize_trades(trades)
    result["available"] = True

    # Per-strategy performance (trades since last strategy change)
    if strategy_start_trades > 0 and strategy_start_trades < len(trades):
        strategy_trades = trades[strategy_start_trades:]
        result["current_strategy_performance"] = _summarize_trades(strategy_trades)
    elif strategy_start_trades == 0:
        # No strategy change recorded — all trades are under current strategy
        pass
    else:
        result["current_strategy_performance"] = {
            "trade_count": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "total_pnl": 0, "avg_pnl": 0, "total_fees": 0,
        }

    return result


def _round_optional(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None
