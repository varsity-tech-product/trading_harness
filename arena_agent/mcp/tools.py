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


def participants(identifier: str, page: int = 1, size: int = 50):
    return varsity_tools.get_participants(identifier, page, size)


# ── Registration ──────────────────────────────────────────────────────────


def register(competition_id: int):
    return varsity_tools.register_competition(competition_id)


def withdraw(competition_id: int):
    return varsity_tools.withdraw_competition(competition_id)


def my_registration(competition_id: int):
    return varsity_tools.get_my_registration(competition_id)


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


# ── Profile & History ─────────────────────────────────────────────────────


def my_profile():
    return varsity_tools.get_my_profile()


def my_history(page: int = 1, size: int = 10):
    return varsity_tools.get_my_history(page, size)


def achievements():
    return varsity_tools.get_achievements()


def public_profile(username: str):
    return varsity_tools.get_public_profile(username)


def public_history(username: str, page: int = 1, size: int = 10):
    return varsity_tools.get_public_history(username, page, size)


def my_history_detail(competition_id: int):
    return varsity_tools.get_my_history_detail(competition_id)


def update_profile(
    username: Optional[str] = None,
    display_name: Optional[str] = None,
    bio: Optional[str] = None,
    country: Optional[str] = None,
    participant_type: Optional[str] = None,
):
    fields = {k: v for k, v in dict(
        username=username, display_name=display_name, bio=bio,
        country=country, participant_type=participant_type,
    ).items() if v is not None}
    return varsity_tools.update_my_profile(**fields)


# ── Hub & Dashboard ──────────────────────────────────────────────────────


def hub():
    return varsity_tools.get_hub()


def arena_profile():
    return varsity_tools.get_arena_profile()


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


def live_trades(competition_id: int):
    return varsity_tools.get_live_trades(competition_id)


def live_position(competition_id: int):
    return varsity_tools.get_live_position(competition_id)


def live_account(competition_id: int):
    return varsity_tools.get_live_account(competition_id)


# ── Predictions & Polls ──────────────────────────────────────────────────


def predictions(competition_id: int):
    return varsity_tools.get_predictions(competition_id)


def submit_prediction(competition_id: int, direction: str, confidence: int):
    return varsity_tools.submit_prediction(competition_id, direction, confidence)


def polls(competition_id: int):
    return varsity_tools.get_polls(competition_id)


def vote_poll(competition_id: int, poll_id: int, option_index: int):
    return varsity_tools.vote_poll(competition_id, poll_id, option_index)


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


# ── Notifications ─────────────────────────────────────────────────────────


def notifications(page: int = 1, size: int = 20):
    return varsity_tools.get_notifications(page, size)


def unread_count():
    return varsity_tools.get_unread_notification_count()


def mark_read(notification_id: int):
    return varsity_tools.mark_notification_read(notification_id)


def mark_all_read():
    return varsity_tools.mark_all_notifications_read()


# ── Behaviour Events ─────────────────────────────────────────────────────


def track_event(competition_id: int, event_type: str, payload: Optional[dict] = None):
    return varsity_tools.track_event(competition_id, event_type, payload)


# ═══════════════════════════════════════════════════════════════════════════
#  Composite tools — higher-level actions combining multiple API calls
# ═══════════════════════════════════════════════════════════════════════════


def my_status(competition_id: Optional[int] = None):
    """Full agent dashboard in one call: account, position, rank, competition, notifications."""
    result: dict = {}

    # Hub gives us active competition, registrations, season, stats, unread count
    try:
        hub_data = varsity_tools.get_hub()
        if isinstance(hub_data, dict) and hub_data.get("code") is None:
            result["season"] = hub_data.get("season")
            result["quick_stats"] = hub_data.get("quickStats")
            result["unread_notifications"] = hub_data.get("unreadNotificationCount", 0)
            result["recent_results"] = hub_data.get("recentResults", [])
            result["registrations"] = hub_data.get("myRegistrations", [])

            # Auto-detect competition_id from active competition or first registration
            if not competition_id:
                active = hub_data.get("activeCompetition")
                if active and isinstance(active, dict):
                    competition_id = active.get("competitionId") or active.get("id")
                elif hub_data.get("myRegistrations"):
                    for reg in hub_data["myRegistrations"]:
                        if reg.get("competitionStatus") in ("live", "registration_closed"):
                            competition_id = reg.get("competitionId")
                            break
        else:
            result["hub_error"] = hub_data
    except Exception as e:
        result["hub_error"] = str(e)

    # If we have a competition, get account + position + rank
    if competition_id:
        result["competition_id"] = competition_id

        try:
            account = varsity_tools.get_live_account(competition_id)
            if isinstance(account, dict) and account.get("code") is None:
                result["account"] = account
            else:
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
            for c in items:
                if not c.get("allowApiWrite", True) and status == "live":
                    continue  # Skip live comps that don't allow API trading
                candidates.append(c)
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
        # API-writable is essential for agents
        if c.get("allowApiWrite"):
            score += 200
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
            "title": detail.get("title") or best.get("title"),
            "status": detail.get("status") or best.get("status"),
            "symbol": detail.get("symbol") or best.get("symbol"),
            "type": detail.get("competitionType") or best.get("competitionType"),
        },
        "entry_requirements": {
            "min_tier": detail.get("requireMinTier"),
            "min_season_points": detail.get("requireMinSeasonPoints"),
            "invite_only": detail.get("inviteOnly", False),
            "api_write_allowed": detail.get("allowApiWrite", best.get("allowApiWrite")),
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
    status = pick["recommendation"]["status"]

    if status not in ("registration_open",):
        return {
            "joined": False,
            "reason": f"Best competition #{comp_id} is '{status}' — cannot register yet.",
            "recommendation": pick["recommendation"],
        }

    if pick["entry_requirements"].get("invite_only"):
        return {
            "joined": False,
            "reason": f"Competition #{comp_id} is invite-only.",
            "recommendation": pick["recommendation"],
        }

    try:
        result = varsity_tools.register_competition(comp_id)
        if isinstance(result, dict) and result.get("code") is not None and result["code"] != 0:
            return {
                "joined": False,
                "reason": result.get("message", "Registration failed"),
                "recommendation": pick["recommendation"],
            }
        return {
            "joined": True,
            "competition_id": comp_id,
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
