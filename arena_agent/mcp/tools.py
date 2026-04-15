"""Plain Python tool functions exposed through MCP."""

from __future__ import annotations

from typing import Optional

from arena_agent.core.runtime_loop import build_transition_event
from arena_agent.interfaces.action_schema import Action, ActionType
from arena_agent.interfaces.action_validator import validate_action
from arena_agent.skills.shared import build_runtime_components, read_last_transition

import varsity_tools


def market_state(config_path: str | None = None, signal_indicators: list[dict] | None = None):
    _, _, state_builder, _, _, _ = build_runtime_components(config_path, signal_indicators=signal_indicators)
    return state_builder.build()


def competition_info(config_path: str | None = None, signal_indicators: list[dict] | None = None):
    state = market_state(config_path, signal_indicators=signal_indicators)
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
    signal_indicators: list[dict] | None = None,
):
    action = validate_action(
        Action(
            type=ActionType(str(type).upper()),
            size=size,
            take_profit=tp,
            stop_loss=sl,
        )
    )
    config, _, state_builder, executor, transition_store, _ = build_runtime_components(
        config_path,
        signal_indicators=signal_indicators,
    )
    executor.dry_run = config.dry_run if not execute else False

    state_before = state_builder.build()
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


# ═══════════════════════════════════════════════════════════════════════════
#  Platform API tools — thin wrappers around varsity_tools
# ═══════════════════════════════════════════════════════════════════════════


# ── System ────────────────────────────────────────────────────────────────


def health():
    return varsity_tools.get_health()


def version():
    return varsity_tools.get_version()


def arena_health():
    return varsity_tools.get_arena_health()


# ── Market Data ───────────────────────────────────────────────────────────


def symbols():
    return varsity_tools.get_symbols()


def orderbook(symbol: str, depth: int = 20):
    return varsity_tools.get_orderbook(symbol, depth)


def klines(
    symbol: str,
    interval: str,
    size: int = 500,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
):
    return varsity_tools.get_klines(symbol, interval, size, start_time, end_time)


def market_info(symbol: str):
    return varsity_tools.get_market_info(symbol)


# ── Competitions ──────────────────────────────────────────────────────────


def competitions(
    season_id: Optional[int] = None,
    status: Optional[str] = None,
    competition_type: Optional[str] = None,
    page: int = 1,
    size: int = 20,
):
    return varsity_tools.get_competitions(season_id, status, competition_type, page, size)


def competition_detail(identifier: str):
    return varsity_tools.get_competition_detail(identifier)


def eligible_competitions(page: int = 1, size: int = 20):
    return varsity_tools.get_eligible_competitions(page, size)


# ── Registration ──────────────────────────────────────────────────────────


def register(slug: str = "", competition_id: int | None = None):
    if not slug and competition_id is not None:
        detail = varsity_tools.get_competition_detail(competition_id)
        slug = detail.get("slug", str(competition_id)) if isinstance(detail, dict) else str(competition_id)
    return varsity_tools.register_competition(slug)




# ── Leaderboards ──────────────────────────────────────────────────────────


def leaderboard(identifier: str, page: int = 1, size: int = 50):
    return varsity_tools.get_competition_leaderboard(identifier, page, size)


def my_leaderboard_position(identifier: str):
    return varsity_tools.get_competition_leaderboard_me(identifier)


def season_leaderboard(
    season_id: Optional[int] = None,
    page: int = 1,
    size: int = 50,
):
    return varsity_tools.get_season_leaderboard(season_id, page, size)


# ── Agent Identity ────────────────────────────────────────────────────────


def agent_info():
    return varsity_tools.get_agent_info()


def agent_profile(agent_id: str):
    return varsity_tools.get_agent_profile(agent_id)


def agent_profile_history(agent_id: str, page: int = 1, size: int = 10):
    return varsity_tools.get_agent_profile_history(agent_id, page, size)


# ── History & Registrations ──────────────────────────────────────────────


def my_history(page: int = 1, size: int = 10):
    return varsity_tools.get_my_history(page, size)


def my_registrations():
    return varsity_tools.get_my_registrations()


# ── Seasons & Tiers ──────────────────────────────────────────────────────


def tiers():
    return varsity_tools.get_tiers()


def seasons():
    return varsity_tools.get_seasons()


def season_detail(season_id: int):
    return varsity_tools.get_season_detail(season_id)


# ── Live Trading (Direct API) ────────────────────────────────────────────


def trade_close(competition_id: int):
    return varsity_tools.trade_close(competition_id)


def trade_history(competition_id: int):
    return varsity_tools.get_trade_history(competition_id)


def live_position(competition_id: int):
    return varsity_tools.get_live_position(competition_id)


def live_account(competition_id: int):
    return varsity_tools.get_live_account(competition_id)


def live_info(competition_id: int):
    return varsity_tools.get_live_info(competition_id)


# ── Social ────────────────────────────────────────────────────────────────


def chat_send(competition_id: int, message: str):
    return varsity_tools.send_chat(competition_id, message)


def chat_history(
    competition_id: int,
    size: int = 50,
    before: Optional[int] = None,
    before_id: Optional[int] = None,
):
    return varsity_tools.get_chat_history(competition_id, size, before, before_id)


def public_chat(
    competition_id: int,
    size: int = 50,
    before: Optional[int] = None,
    before_id: Optional[int] = None,
):
    return varsity_tools.get_public_chat(competition_id, size, before, before_id)


# ── Observer Analytics ───────────────────────────────────────────────────


def equity_curve(competition_id: int, agent_id: str, range: str = "all"):
    return varsity_tools.get_equity_curve(competition_id, agent_id, range)


def daily_returns(
    competition_id: int,
    agent_id: str,
    range: str = "all",
    page: int = 1,
    size: int = 20,
):
    return varsity_tools.get_daily_returns(competition_id, agent_id, range, page, size)


def performance(competition_id: int, agent_id: str):
    return varsity_tools.get_performance(competition_id, agent_id)


# ═══════════════════════════════════════════════════════════════════════════
#  Setup Agent — LLM-powered strategy configuration
# ═══════════════════════════════════════════════════════════════════════════


def setup_decide(
    competition_id: int,
    backend: str = "auto",
    model: Optional[str] = None,
    config_path: Optional[str] = None,
    inactivity_alert: bool = False,
    inactive_minutes: int = 0,
    consecutive_hold_cycles: int = 0,
    total_runtime_iterations: int = 0,
):
    """Run the setup agent to get a config decision."""
    import os
    from pathlib import Path
    from arena_agent.agents.setup_agent import SetupAgent
    from arena_agent.setup.context_builder import build_setup_context
    from arena_agent.setup.memory import SetupMemory

    # Load current config from YAML
    config: dict = {}
    if config_path:
        resolved = Path(config_path)
    else:
        from arena_agent.runtime_env import default_runtime_config_path
        resolved = default_runtime_config_path("codex_agent_config.yaml")
    if resolved.exists():
        import yaml
        config = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}

    # Load memory
    arena_home = os.environ.get("ARENA_HOME") or os.environ.get("ARENA_ROOT") or str(Path.cwd())
    memory_path = Path(arena_home) / "setup_memory.json"
    memory = SetupMemory(memory_path)
    recent = memory.recent(5)

    # Build context
    context = build_setup_context(
        competition_id,
        config,
        recent,
        inactivity_alert=inactivity_alert,
        inactive_minutes=inactive_minutes,
        consecutive_hold_cycles=consecutive_hold_cycles,
        total_runtime_iterations=total_runtime_iterations,
    )

    # Run setup agent
    agent = SetupAgent(backend=backend, model=model)
    memory_text = memory.format_for_prompt(5)
    decision = agent.decide(context, memory_text)

    return decision.to_dict()


def setup_record(
    competition_id: int,
    title: str = "",
    strategy_summary: str = "",
    adjustments_made: int = 0,
):
    """Record a competition result in setup memory."""
    import os
    from pathlib import Path
    from datetime import datetime, timezone

    from arena_agent.setup.memory import SetupMemory, CompetitionRecord

    # Get final account state
    try:
        account = varsity_tools.get_live_account(competition_id)
        equity = float(account.get("capital", 0) if isinstance(account, dict) else 0)
        initial = float(account.get("initialBalance", 5000) if isinstance(account, dict) else 5000)
        trades = int(account.get("tradesCount", 0) if isinstance(account, dict) else 0)
        pnl = equity - initial
        pnl_pct = (pnl / initial * 100) if initial else 0
    except Exception:
        equity = 0
        pnl = 0
        pnl_pct = 0
        trades = 0
        initial = 5000

    arena_home = os.environ.get("ARENA_HOME") or os.environ.get("ARENA_ROOT") or str(Path.cwd())
    memory_path = Path(arena_home) / "setup_memory.json"
    memory = SetupMemory(memory_path)

    record = CompetitionRecord(
        competition_id=competition_id,
        title=title,
        final_equity=equity,
        pnl=pnl,
        pnl_pct=pnl_pct,
        trades_used=trades,
        strategy_summary=strategy_summary or "default config",
        adjustments_made=adjustments_made,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    memory.append(record)

    return {
        "recorded": True,
        "competition_id": competition_id,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "memory_path": str(memory_path),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Composite tools — higher-level actions combining multiple API calls
# ═══════════════════════════════════════════════════════════════════════════


def my_status(competition_id: Optional[int] = None):
    """Full agent status in one call: agent info, account, position, rank, registrations."""
    result: dict = {}

    # Agent identity
    try:
        agent = varsity_tools.get_agent_info()
        if isinstance(agent, dict) and agent.get("code") is None:
            result["agent"] = agent
    except Exception as e:
        result["agent_error"] = str(e)

    # Registrations — also used to auto-detect competition_id
    try:
        regs = varsity_tools.get_my_registrations()
        if isinstance(regs, list):
            result["registrations"] = regs
            if not competition_id:
                for reg in regs:
                    if reg.get("competitionStatus") in ("live", "registration_closed"):
                        competition_id = reg.get("competitionId")
                        break
    except Exception as e:
        result["registrations_error"] = str(e)

    # If we have a competition, get account + position + rank
    if competition_id:
        result["competition_id"] = competition_id

        try:
            account = varsity_tools.get_live_account(competition_id)
            result["account"] = account
        except Exception as e:
            result["account_error"] = str(e)

        try:
            position = varsity_tools.get_live_position(competition_id)
            result["position"] = position
        except Exception as e:
            result["position_error"] = str(e)

        try:
            lb = varsity_tools.get_competition_leaderboard_me(competition_id)
            if isinstance(lb, dict) and lb.get("list"):
                result["my_rank"] = lb["list"][0] if len(lb["list"]) == 1 else lb["list"]
            else:
                result["my_rank"] = lb
        except Exception as e:
            result["rank_error"] = str(e)

    return result


def best_competition():
    """Find the best competition to join. Returns top pick with entry requirements, reward, and participants."""
    candidates = []

    # Check registration_open competitions first
    for status in ("registration_open", "announced", "live"):
        try:
            comps = varsity_tools.get_competitions(status=status)
            items = comps.get("list", []) if isinstance(comps, dict) else []
            candidates.extend(items)
        except Exception:
            pass

    if not candidates:
        return {"found": False, "message": "No competitions available for registration or joining."}

    # Get my current registrations to avoid duplicates
    my_reg_ids = set()
    try:
        regs = varsity_tools.get_my_registrations()
        if isinstance(regs, list):
            my_reg_ids = {r.get("competitionId") for r in regs}
    except Exception:
        pass

    # Score and rank candidates
    scored = []
    for c in candidates:
        comp_id = c.get("id")
        if comp_id in my_reg_ids:
            continue  # Already registered

        score = 0
        # Prefer registration_open over live
        if c.get("status") == "registration_open":
            score += 100
        elif c.get("status") == "announced":
            score += 50
        # Higher prize pool = better
        score += (c.get("prizePool") or 0) / 10
        # Fewer participants = easier to rank
        registered = c.get("registeredCount", 0)
        max_p = c.get("maxParticipants", 50)
        if max_p > 0:
            score += (1 - registered / max_p) * 30

        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        return {
            "found": False,
            "message": "All available competitions are already registered.",
            "registered_competition_ids": list(my_reg_ids),
        }

    best = scored[0][1]
    comp_id = best.get("id")

    # Fetch full detail for the top pick
    detail = {}
    try:
        detail = varsity_tools.get_competition_detail(str(comp_id))
    except Exception:
        detail = best

    return {
        "found": True,
        "recommendation": {
            "id": comp_id,
            "slug": detail.get("slug") or best.get("slug"),
            "title": detail.get("title") or best.get("title"),
            "status": detail.get("status") or best.get("status"),
            "symbol": detail.get("symbol") or best.get("symbol"),
            "type": detail.get("competitionType") or best.get("competitionType"),
        },
        "entry_requirements": {
            "min_tier": detail.get("requireMinTier"),
            "min_season_points": detail.get("requireMinSeasonPoints"),
            "invite_only": detail.get("inviteOnly", False),
        },
        "reward": {
            "prize_pool": detail.get("prizePool") or best.get("prizePool"),
            "prize_table": detail.get("prizeTableJson"),
            "points_table": detail.get("pointsTableJson"),
            "starting_capital": detail.get("startingCapital"),
        },
        "participants": {
            "registered": detail.get("registeredCount") or best.get("registeredCount", 0),
            "max": detail.get("maxParticipants") or best.get("maxParticipants"),
        },
        "schedule": {
            "registration_open": detail.get("registrationOpenAt"),
            "registration_close": detail.get("registrationCloseAt"),
            "start": detail.get("startTime") or best.get("startTime"),
            "end": detail.get("endTime") or best.get("endTime"),
        },
        "other_options": [
            {"id": c.get("id"), "title": c.get("title"), "status": c.get("status"), "prize_pool": c.get("prizePool")}
            for _, c in scored[1:5]
        ],
        "already_registered": list(my_reg_ids),
    }


def auto_join():
    """Find the best competition and register for it automatically."""
    pick = best_competition()
    if not pick.get("found"):
        return pick

    comp_id = pick["recommendation"]["id"]
    slug = pick["recommendation"].get("slug") or str(comp_id)
    status = pick["recommendation"]["status"]

    if status not in ("registration_open",):
        return {
            "joined": False,
            "reason": f"Best competition '{slug}' is '{status}' — cannot register yet.",
            "recommendation": pick["recommendation"],
        }

    if pick["entry_requirements"].get("invite_only"):
        return {
            "joined": False,
            "reason": f"Competition '{slug}' is invite-only.",
            "recommendation": pick["recommendation"],
        }

    try:
        result = varsity_tools.register_competition(slug)
        if isinstance(result, dict) and result.get("code") is not None and result["code"] != 0:
            return {
                "joined": False,
                "reason": result.get("message", "Registration failed"),
                "recommendation": pick["recommendation"],
            }
        return {
            "joined": True,
            "competition_id": comp_id,
            "slug": slug,
            "title": pick["recommendation"]["title"],
            "registration": result,
            "reward": pick["reward"],
            "schedule": pick["schedule"],
        }
    except Exception as e:
        return {
            "joined": False,
            "reason": str(e),
            "recommendation": pick["recommendation"],
        }
