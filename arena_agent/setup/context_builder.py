"""Builds the JSON context that the setup agent LLM receives."""

from __future__ import annotations

import logging
from typing import Any

import varsity_tools

from arena_agent.setup.memory import CompetitionRecord

logger = logging.getLogger("arena_agent.setup.context_builder")


def build_setup_context(
    competition_id: int,
    config: dict[str, Any],
    memory: list[CompetitionRecord],
) -> dict[str, Any]:
    """Assemble everything the setup agent needs to make a decision."""
    context: dict[str, Any] = {}

    # Current config snapshot
    context["current_config"] = {
        "policy": {
            k: v
            for k, v in config.get("policy", {}).items()
            if k in (
                "indicator_mode", "timeout_seconds", "extra_instructions",
                "strategy_context", "fail_open_to_hold", "sandbox_mode",
            )
        },
        "strategy": config.get("strategy", {}),
        "risk_limits": config.get("risk_limits", {}),
        "signal_indicators": config.get("signal_indicators", []),
        "interval": config.get("interval", "1m"),
        "tick_interval_seconds": config.get("tick_interval_seconds", 30),
    }

    # Account state
    try:
        account = varsity_tools.get_live_account(competition_id)
        if isinstance(account, dict) and account.get("code") is None:
            context["account_state"] = {
                "balance": account.get("balance") or account.get("initialBalance", 5000),
                "equity": account.get("capital") or account.get("equity", 5000),
                "unrealized_pnl": account.get("unrealizedPnl", 0),
                "realized_pnl": account.get("realizedPnl", 0),
                "trade_count": account.get("tradesCount", 0),
                "initial_balance": account.get("initialBalance", 5000),
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
                "symbol": detail.get("symbol"),
                "start_time": detail.get("startTime"),
                "end_time": detail.get("endTime"),
                "max_trades": detail.get("maxTrades"),
                "starting_capital": detail.get("startingCapital"),
            }
            # Compute trades remaining
            trade_count = 0
            acct = context.get("account_state", {})
            if isinstance(acct, dict) and "trade_count" in acct:
                trade_count = acct["trade_count"]
            max_trades = detail.get("maxTrades")
            if max_trades is not None:
                context["competition"]["trades_remaining"] = max(0, max_trades - trade_count)
    except Exception as exc:
        context["competition"] = {"id": competition_id, "error": str(exc)}

    # Market summary from recent klines
    symbol = config.get("symbol", "BTCUSDT")
    interval = config.get("interval", "1m")
    try:
        context["market_summary"] = _compute_market_summary(symbol, interval)
    except Exception as exc:
        context["market_summary"] = {"error": str(exc)}

    # Recent trade performance
    try:
        context["performance"] = _compute_performance(competition_id)
    except Exception as exc:
        context["performance"] = {"error": str(exc)}

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
        chat = varsity_tools.get_chat_history(competition_id, 20)
        if isinstance(chat, dict) and chat.get("list"):
            context["chat_recent"] = [
                {
                    "username": msg.get("username"),
                    "message": msg.get("message", "")[:200],
                    "timestamp": msg.get("createdAt"),
                }
                for msg in chat["list"][-10:]
            ]
        elif isinstance(chat, list):
            context["chat_recent"] = [
                {
                    "username": msg.get("username"),
                    "message": msg.get("message", "")[:200],
                    "timestamp": msg.get("createdAt"),
                }
                for msg in chat[-10:]
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

    # Memory from past competitions
    context["memory"] = [r.to_dict() for r in memory]

    return context


def _compute_market_summary(symbol: str, interval: str) -> dict[str, Any]:
    """Compute a market summary from recent klines."""
    klines = varsity_tools.get_klines(symbol, interval, 50)
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


def _compute_performance(competition_id: int) -> dict[str, Any]:
    """Compute performance metrics from recent trades."""
    try:
        trades = varsity_tools.get_live_trades(competition_id)
    except Exception:
        return {"available": False}

    if not isinstance(trades, list) or not trades:
        return {"available": False, "trade_count": 0}

    wins = 0
    losses = 0
    total_pnl = 0.0
    pnls: list[float] = []

    for trade in trades:
        pnl = float(trade.get("realizedPnl", 0) if isinstance(trade, dict) else 0)
        pnls.append(pnl)
        total_pnl += pnl
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

    avg_pnl = total_pnl / len(pnls) if pnls else 0
    win_rate = wins / len(pnls) if pnls else 0

    return {
        "available": True,
        "trade_count": len(pnls),
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 3),
        "total_pnl": round(total_pnl, 4),
        "avg_pnl": round(avg_pnl, 4),
        "recent_pnls": [round(p, 4) for p in pnls[-10:]],
    }
