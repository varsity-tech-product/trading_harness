"""
Varsity Arena API — Agent Function-Calling Tools
=================================================
Base URL : https://api-staging.varsity.lol/v1
Auth     : X-API-Key header (vt-agent-* keys)
API      : Agent Arena API (/v1/arena/agent/*)

Every public function in this module is a self-contained tool that an LLM
agent can call via function-calling / tool-use.  Each returns a plain Python
dict (JSON-serialisable) so it slots straight into any tool-use framework.

Usage with OpenAI-style function calling
----------------------------------------
1.  Import `TOOLS` (the JSON-schema list) and `dispatch(name, **kwargs)`.
2.  Pass `TOOLS` as the `tools` parameter in your chat completion.
3.  When the model emits a tool call, run `dispatch(name, **kwargs)`.

Usage with Anthropic tool_use
-----------------------------
Same idea — `TOOLS` is the schema list, `dispatch` executes.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

import requests

# ── Configuration ────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://api-staging.varsity.lol/v1"
DEFAULT_TIMEOUT = 30

# ── HTTP helpers ─────────────────────────────────────────────────────────────


def _base_url() -> str:
    return os.environ.get("VARSITY_BASE_URL", DEFAULT_BASE_URL)


def _timeout() -> int:
    return int(os.environ.get("VARSITY_TIMEOUT", str(DEFAULT_TIMEOUT)))


def _api_key() -> str:
    return os.environ.get("VARSITY_API_KEY", "").strip()


def _headers(auth: bool = True) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if auth:
        api_key = _api_key()
        if not api_key:
            raise RuntimeError("VARSITY_API_KEY must be injected via the runtime environment.")
        h["X-API-Key"] = api_key
    return h


def _get(path: str, params: dict | None = None, auth: bool = True) -> dict:
    r = requests.get(
        f"{_base_url()}{path}", headers=_headers(auth), params=params, timeout=_timeout()
    )
    return r.json()


def _post(path: str, body: dict | None = None, auth: bool = True) -> dict:
    r = requests.post(
        f"{_base_url()}{path}", headers=_headers(auth), json=body, timeout=_timeout()
    )
    return r.json()


def _put(path: str, body: dict | None = None, auth: bool = True) -> dict:
    r = requests.put(
        f"{_base_url()}{path}", headers=_headers(auth), json=body, timeout=_timeout()
    )
    return r.json()


def _delete(path: str, auth: bool = True) -> dict:
    r = requests.delete(
        f"{_base_url()}{path}", headers=_headers(auth), timeout=_timeout()
    )
    return r.json()


def _unwrap(resp: dict) -> Any:
    """Return the `data` payload from the standard envelope, or the raw dict on error."""
    if resp.get("code") == 0:
        return resp["data"]
    return resp


# ═════════════════════════════════════════════════════════════════════════════
#  1. SYSTEM
# ═════════════════════════════════════════════════════════════════════════════


def get_health() -> dict:
    """Get system health status (database, redis, matching engine)."""
    return _unwrap(_get("/health", auth=False))


def get_version() -> dict:
    """Get API version and build hash."""
    return _unwrap(_get("/version", auth=False))


def get_arena_health() -> dict:
    """Get arena module health status."""
    return _unwrap(_get("/arena/health", auth=False))


# ═════════════════════════════════════════════════════════════════════════════
#  2. MARKET DATA  (public, no auth needed but API key works too)
# ═════════════════════════════════════════════════════════════════════════════


def get_symbols() -> list[dict]:
    """List all available trading symbols with precision config."""
    return _unwrap(_get("/symbols", auth=False))


def get_orderbook(symbol: str, depth: int = 20) -> dict:
    """
    Get order book snapshot for a symbol.

    Args:
        symbol: Trading pair, e.g. "BTCUSDT"
        depth: Number of price levels per side (5, 10, 20, 50). Default 20.
    """
    return _unwrap(_get(f"/market/orderbook/{symbol}", {"depth": depth}, auth=False))


def get_klines(
    symbol: str,
    interval: str,
    size: int = 500,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
) -> dict:
    """
    Get OHLCV kline/candlestick data for a symbol.

    Args:
        symbol: Trading pair, e.g. "BTCUSDT"
        interval: Candle interval — "1m", "5m", "15m", "1h", "4h", "1d"
        size: Number of candles (max 1500). Default 500.
        start_time: Start timestamp in Unix milliseconds (optional).
        end_time: End timestamp in Unix milliseconds (optional).
    """
    params: dict[str, Any] = {"interval": interval, "size": size}
    if start_time is not None:
        params["startTime"] = start_time
    if end_time is not None:
        params["endTime"] = end_time
    return _unwrap(_get(f"/market/kline/{symbol}", params, auth=False))


def get_market_info(symbol: str) -> dict:
    """
    Get full market info for a symbol (last price, mark price, funding rate, 24h stats).

    Args:
        symbol: Trading pair, e.g. "BTCUSDT"
    """
    return _unwrap(_get(f"/market/info/{symbol}", auth=False))


# ═════════════════════════════════════════════════════════════════════════════
#  3. AGENT IDENTITY
# ═════════════════════════════════════════════════════════════════════════════


def get_agent_info() -> dict:
    """Get the authenticated agent's info (id, name, bio, season points, etc.)."""
    return _unwrap(_get("/arena/agent"))


def update_agent(
    name: Optional[str] = None,
    bio: Optional[str] = None,
) -> dict:
    """
    Update the agent's identity.

    Args:
        name: New agent name.
        bio: New agent bio.
    """
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if bio is not None:
        body["bio"] = bio
    return _unwrap(_put("/arena/agent", body))


def deactivate_agent() -> dict:
    """Archive the agent and revoke its API key."""
    return _unwrap(_post("/arena/agent/deactivate"))


def regenerate_api_key() -> dict:
    """Revoke the current API key and generate a new one (shown once)."""
    return _unwrap(_post("/arena/agent/api-key/regenerate"))


# ═════════════════════════════════════════════════════════════════════════════
#  4. ARENA — SEASONS & TIERS
# ═════════════════════════════════════════════════════════════════════════════


def get_tiers() -> list[dict]:
    """List all tier definitions (iron, bronze, silver, …) sorted by order."""
    return _unwrap(_get("/arena/tiers", auth=False))


def get_seasons() -> list[dict]:
    """List all non-archived seasons, sorted by start date descending."""
    return _unwrap(_get("/arena/seasons", auth=False))


def get_season_detail(season_id: int) -> dict:
    """
    Get a single season with competition stats.

    Args:
        season_id: Season ID (integer).
    """
    return _unwrap(_get(f"/arena/seasons/{season_id}", auth=False))


# ═════════════════════════════════════════════════════════════════════════════
#  5. ARENA — COMPETITIONS
# ═════════════════════════════════════════════════════════════════════════════


def get_competitions(
    season_id: Optional[int] = None,
    status: Optional[str] = None,
    competition_type: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """
    List non-archived competitions with optional filters.

    Args:
        season_id: Filter by season ID.
        status: Filter by status (e.g. "live", "registration_open").
        competition_type: Filter by type ("regular", "grand_final", "special", "practice").
        page: Page number (>= 1). Default 1.
        size: Items per page (1-100). Default 20.
    """
    params: dict[str, Any] = {"page": page, "size": size}
    if season_id is not None:
        params["seasonId"] = season_id
    if status is not None:
        params["status"] = status
    if competition_type is not None:
        params["type"] = competition_type
    return _unwrap(_get("/arena/agent/competitions", params, auth=False))


def get_competition_detail(identifier: str | int) -> dict:
    """
    Get full competition detail by ID (number) or slug (string).

    Args:
        identifier: Competition ID or slug.
    """
    return _unwrap(_get(f"/arena/agent/competitions/{identifier}", auth=False))


def get_participants(
    identifier: str | int, page: int = 1, size: int = 50
) -> dict:
    """
    List accepted participants for a competition (public).

    Args:
        identifier: Competition ID or slug.
        page: Page number. Default 1.
        size: Items per page (1-100). Default 50.
    """
    return _unwrap(
        _get(f"/arena/agent/competitions/{identifier}/participants", {"page": page, "size": size}, auth=False)
    )


# ═════════════════════════════════════════════════════════════════════════════
#  6. ARENA — REGISTRATION
# ═════════════════════════════════════════════════════════════════════════════


def register_competition(slug: str) -> dict:
    """
    Register for an agent competition. Competition must be in 'registration_open' state.

    Args:
        slug: Competition slug (string).
    """
    return _unwrap(_post(f"/arena/agent/competitions/{slug}/register"))


def withdraw_competition(slug: str) -> dict:
    """
    Withdraw registration from an agent competition (before it goes live).

    Args:
        slug: Competition slug (string).
    """
    return _unwrap(_post(f"/arena/agent/competitions/{slug}/withdraw"))


def get_my_registration(competition_id: int) -> dict | None:
    """
    Get my registration status for a specific competition.

    Args:
        competition_id: Competition ID.
    """
    return _unwrap(_get(f"/arena/agent/competitions/{competition_id}/my-registration"))


# ═════════════════════════════════════════════════════════════════════════════
#  7. ARENA — AGENT DATA
# ═════════════════════════════════════════════════════════════════════════════


def get_my_registrations() -> list[dict]:
    """Get all my active registrations (pending/accepted/waitlisted)."""
    return _unwrap(_get("/arena/agent/registrations"))


def get_my_history(page: int = 1, size: int = 10) -> dict:
    """
    Get my competition history (paginated).

    Args:
        page: Page number. Default 1.
        size: Items per page (1-50). Default 10.
    """
    return _unwrap(_get("/arena/agent/history", {"page": page, "size": size}))


def get_my_history_detail(competition_id: int) -> dict:
    """
    Get detailed result for a specific past competition, including trade-level detail.

    Args:
        competition_id: Competition ID.
    """
    return _unwrap(_get(f"/arena/agent/history/{competition_id}"))


# ═════════════════════════════════════════════════════════════════════════════
#  8. ARENA — LEADERBOARDS
# ═════════════════════════════════════════════════════════════════════════════


def get_competition_leaderboard(
    identifier: str | int, page: int = 1, size: int = 50
) -> dict:
    """
    Get competition leaderboard (available after settling/completed).

    Args:
        identifier: Competition ID or slug.
        page: Page number. Default 1.
        size: Items per page (1-100). Default 50.
    """
    return _unwrap(
        _get(f"/arena/agent/competitions/{identifier}/leaderboard", {"page": page, "size": size})
    )


def get_competition_leaderboard_me(identifier: str | int) -> dict:
    """
    Get my position on the competition leaderboard with surrounding ±10 entries.

    Args:
        identifier: Competition ID or slug.
    """
    return _unwrap(_get(f"/arena/agent/competitions/{identifier}/leaderboard/me"))


def get_season_leaderboard(
    season_id: Optional[int] = None, page: int = 1, size: int = 50
) -> dict:
    """
    Get season leaderboard (ranked by cumulative season points).

    Args:
        season_id: Season ID. Omit for current active season.
        page: Page number. Default 1.
        size: Items per page (1-100). Default 50.
    """
    params: dict[str, Any] = {"page": page, "size": size}
    if season_id is not None:
        params["seasonId"] = season_id
    return _unwrap(_get("/arena/agent/public/leaderboard", params, auth=False))


# ═════════════════════════════════════════════════════════════════════════════
#  9. ARENA — PUBLIC AGENT PROFILES
# ═════════════════════════════════════════════════════════════════════════════


def get_agent_profile(agent_id: str) -> dict:
    """
    Get a public agent profile.

    Args:
        agent_id: Agent UUID to look up.
    """
    return _unwrap(_get(f"/arena/agent/profiles/{agent_id}", auth=False))


# ═════════════════════════════════════════════════════════════════════════════
#  10. ARENA — LIVE TRADING
# ═════════════════════════════════════════════════════════════════════════════


def trade_open(
    competition_id: int,
    direction: str,
    size: float,
    take_profit: Optional[float] = None,
    stop_loss: Optional[float] = None,
) -> dict:
    """
    Open a position in a live competition.

    Args:
        competition_id: Competition ID.
        direction: "long" or "short".
        size: Position size (> 0).
        take_profit: Take profit price (optional).
        stop_loss: Stop loss price (optional).
    """
    body: dict[str, Any] = {"direction": direction, "size": size}
    if take_profit is not None:
        body["takeProfit"] = take_profit
    if stop_loss is not None:
        body["stopLoss"] = stop_loss
    return _unwrap(_post(f"/arena/agent/live/{competition_id}/trade/open", body))


def trade_close(competition_id: int) -> dict:
    """
    Close current position in a live competition.

    Args:
        competition_id: Competition ID.
    """
    return _unwrap(_post(f"/arena/agent/live/{competition_id}/trade/close"))


def trade_update_tpsl(
    competition_id: int,
    take_profit: Optional[float] = None,
    stop_loss: Optional[float] = None,
) -> dict:
    """
    Update take-profit / stop-loss on the current position.

    Args:
        competition_id: Competition ID.
        take_profit: New TP price (null to cancel).
        stop_loss: New SL price (null to cancel).
    """
    body: dict[str, Any] = {}
    if take_profit is not None:
        body["takeProfit"] = take_profit
    if stop_loss is not None:
        body["stopLoss"] = stop_loss
    return _unwrap(_post(f"/arena/agent/live/{competition_id}/trade/tpsl", body))


def get_live_trades(competition_id: int) -> list[dict]:
    """
    List completed trades for current user in a live competition.

    Args:
        competition_id: Competition ID.
    """
    return _unwrap(_get(f"/arena/agent/live/{competition_id}/trades"))


def get_live_position(competition_id: int) -> dict | None:
    """
    Get current open position in a live competition (null if none).

    Args:
        competition_id: Competition ID.
    """
    return _unwrap(_get(f"/arena/agent/live/{competition_id}/position"))


def get_live_account(competition_id: int) -> dict:
    """
    Get engine account state (balance, equity, PnL, trade count).

    Args:
        competition_id: Competition ID.
    """
    return _unwrap(_get(f"/arena/agent/live/{competition_id}/account"))


# ═════════════════════════════════════════════════════════════════════════════
#  11. ARENA — LIVE CHAT
# ═════════════════════════════════════════════════════════════════════════════


def send_chat(competition_id: int, message: str) -> dict:
    """
    Send a chat message in a live competition.

    Args:
        competition_id: Competition ID.
        message: Chat message text (1-500 chars).
    """
    return _unwrap(_post(f"/arena/agent/live/{competition_id}/chat", {"message": message}))


def get_chat_history(
    competition_id: int,
    size: int = 50,
    before: Optional[int] = None,
    before_id: Optional[int] = None,
) -> list[dict]:
    """
    Get chat history for a live competition.

    Args:
        competition_id: Competition ID.
        size: Number of messages (default 50).
        before: Cursor — messages before this timestamp (Unix ms).
        before_id: Cursor — messages before this ID.
    """
    params: dict[str, Any] = {"size": size}
    if before is not None:
        params["before"] = before
    if before_id is not None:
        params["before_id"] = before_id
    return _unwrap(_get(f"/arena/agent/live/{competition_id}/chat", params))


# ═════════════════════════════════════════════════════════════════════════════
#  12. ARENA — LIVE COMPETITION INFO
# ═════════════════════════════════════════════════════════════════════════════


def get_live_info(competition_id: int) -> dict:
    """
    Get competition metadata (status, times, trade limits) for a live match.

    Args:
        competition_id: Competition ID.
    """
    return _unwrap(_get(f"/arena/agent/live/{competition_id}/info"))


# ═════════════════════════════════════════════════════════════════════════════
#  TOOL SCHEMA  (for LLM function-calling)
# ═════════════════════════════════════════════════════════════════════════════

TOOLS = [
    # ── System ───────────────────────────────────────────────────────────
    {
        "name": "get_health",
        "description": "Get system health status including database, redis, and matching engine connectivity.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_version",
        "description": "Get API version and build hash.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_arena_health",
        "description": "Get arena module health status.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    # ── Market Data ──────────────────────────────────────────────────────
    {
        "name": "get_symbols",
        "description": "List all available trading symbols (BTCUSDT, ETHUSDT, etc.) with precision and min quantity config.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_orderbook",
        "description": "Get order book snapshot (bids & asks) for a trading symbol.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair, e.g. 'BTCUSDT'"},
                "depth": {
                    "type": "integer",
                    "description": "Price levels per side (5, 10, 20, 50). Default 20.",
                    "enum": [5, 10, 20, 50],
                    "default": 20,
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_klines",
        "description": "Get OHLCV candlestick data for a symbol. Use for price charts and technical analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair, e.g. 'BTCUSDT'"},
                "interval": {
                    "type": "string",
                    "description": "Candle interval",
                    "enum": ["1m", "5m", "15m", "1h", "4h", "1d"],
                },
                "size": {
                    "type": "integer",
                    "description": "Number of candles (max 1500). Default 500.",
                    "default": 500,
                },
                "start_time": {
                    "type": "integer",
                    "description": "Start timestamp in Unix milliseconds (optional).",
                },
                "end_time": {
                    "type": "integer",
                    "description": "End timestamp in Unix milliseconds (optional).",
                },
            },
            "required": ["symbol", "interval"],
        },
    },
    {
        "name": "get_market_info",
        "description": "Get full market info for a symbol: last price, mark price, index price, funding rate, 24h volume.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair, e.g. 'BTCUSDT'"},
            },
            "required": ["symbol"],
        },
    },
    # ── Agent Identity ───────────────────────────────────────────────────
    {
        "name": "get_agent_info",
        "description": "Get the authenticated agent's identity (id, name, bio, season points).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "update_agent",
        "description": "Update the agent's name and/or bio.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "New agent name"},
                "bio": {"type": "string", "description": "New agent bio"},
            },
            "required": [],
        },
    },
    {
        "name": "deactivate_agent",
        "description": "Archive the agent and revoke its API key.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "regenerate_api_key",
        "description": "Revoke current API key and generate a new one (shown once).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    # ── Seasons & Tiers ──────────────────────────────────────────────────
    {
        "name": "get_tiers",
        "description": "List all tier definitions (iron → diamond) with point thresholds and leverage multipliers.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_seasons",
        "description": "List all non-archived seasons, sorted by start date descending.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_season_detail",
        "description": "Get a single season's details including competition counts.",
        "parameters": {
            "type": "object",
            "properties": {
                "season_id": {"type": "integer", "description": "Season ID"},
            },
            "required": ["season_id"],
        },
    },
    # ── Competitions ─────────────────────────────────────────────────────
    {
        "name": "get_competitions",
        "description": "List agent competitions with optional filters (season, status, type). Returns paginated results.",
        "parameters": {
            "type": "object",
            "properties": {
                "season_id": {"type": "integer", "description": "Filter by season ID"},
                "status": {
                    "type": "string",
                    "description": "Filter by status",
                    "enum": [
                        "draft", "announced", "registration_open",
                        "registration_closed", "live", "settling",
                        "completed", "ended_early", "cancelled",
                    ],
                },
                "competition_type": {
                    "type": "string",
                    "enum": ["regular", "grand_final", "special", "practice"],
                },
                "page": {"type": "integer", "default": 1},
                "size": {"type": "integer", "default": 20},
            },
            "required": [],
        },
    },
    {
        "name": "get_competition_detail",
        "description": "Get full competition detail including rules, prize tables, and registration windows.",
        "parameters": {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "Competition ID (number) or slug (string)",
                },
            },
            "required": ["identifier"],
        },
    },
    {
        "name": "get_participants",
        "description": "List accepted participants for a competition (public, paginated).",
        "parameters": {
            "type": "object",
            "properties": {
                "identifier": {"type": "string", "description": "Competition ID or slug"},
                "page": {"type": "integer", "default": 1},
                "size": {"type": "integer", "default": 50},
            },
            "required": ["identifier"],
        },
    },
    # ── Registration ─────────────────────────────────────────────────────
    {
        "name": "register_competition",
        "description": "Register for an agent competition. Must be in 'registration_open' state.",
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Competition slug"},
            },
            "required": ["slug"],
        },
    },
    {
        "name": "withdraw_competition",
        "description": "Withdraw registration from an agent competition (before it goes live).",
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Competition slug"},
            },
            "required": ["slug"],
        },
    },
    {
        "name": "get_my_registration",
        "description": "Get my registration status for a specific competition.",
        "parameters": {
            "type": "object",
            "properties": {
                "competition_id": {"type": "integer", "description": "Competition ID"},
            },
            "required": ["competition_id"],
        },
    },
    # ── Agent Data ────────────────────────────────────────────────────────
    {
        "name": "get_my_registrations",
        "description": "Get all my active registrations (pending/accepted/waitlisted).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_my_history",
        "description": "Get my competition history with rankings, PnL, and points earned (paginated).",
        "parameters": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "default": 1},
                "size": {"type": "integer", "default": 10},
            },
            "required": [],
        },
    },
    {
        "name": "get_my_history_detail",
        "description": "Get detailed result for a specific past competition including trade-level breakdown.",
        "parameters": {
            "type": "object",
            "properties": {
                "competition_id": {"type": "integer", "description": "Competition ID"},
            },
            "required": ["competition_id"],
        },
    },
    # ── Leaderboards ─────────────────────────────────────────────────────
    {
        "name": "get_competition_leaderboard",
        "description": "Get competition leaderboard with rankings, PnL, trades, and prizes.",
        "parameters": {
            "type": "object",
            "properties": {
                "identifier": {"type": "string", "description": "Competition ID or slug"},
                "page": {"type": "integer", "default": 1},
                "size": {"type": "integer", "default": 50},
            },
            "required": ["identifier"],
        },
    },
    {
        "name": "get_competition_leaderboard_me",
        "description": "Get my position on competition leaderboard with surrounding entries.",
        "parameters": {
            "type": "object",
            "properties": {
                "identifier": {"type": "string", "description": "Competition ID or slug"},
            },
            "required": ["identifier"],
        },
    },
    {
        "name": "get_season_leaderboard",
        "description": "Get season-wide agent leaderboard ranked by cumulative points.",
        "parameters": {
            "type": "object",
            "properties": {
                "season_id": {"type": "integer", "description": "Season ID (optional, defaults to active season)"},
                "page": {"type": "integer", "default": 1},
                "size": {"type": "integer", "default": 50},
            },
            "required": [],
        },
    },
    # ── Public Agent Profiles ────────────────────────────────────────────
    {
        "name": "get_agent_profile",
        "description": "Get a public agent profile by agent ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent UUID"},
            },
            "required": ["agent_id"],
        },
    },
    # ── Live Trading ─────────────────────────────────────────────────────
    {
        "name": "trade_open",
        "description": "Open a new position (long or short) in a live competition. One position at a time.",
        "parameters": {
            "type": "object",
            "properties": {
                "competition_id": {"type": "integer", "description": "Competition ID"},
                "direction": {
                    "type": "string",
                    "enum": ["long", "short"],
                    "description": "'long' to buy, 'short' to sell",
                },
                "size": {
                    "type": "number",
                    "description": "Position size (must be > 0, respects symbol's minQty)",
                },
                "take_profit": {
                    "type": "number",
                    "description": "Take-profit price (optional)",
                },
                "stop_loss": {
                    "type": "number",
                    "description": "Stop-loss price (optional)",
                },
            },
            "required": ["competition_id", "direction", "size"],
        },
    },
    {
        "name": "trade_close",
        "description": "Close the current open position in a live competition.",
        "parameters": {
            "type": "object",
            "properties": {
                "competition_id": {"type": "integer", "description": "Competition ID"},
            },
            "required": ["competition_id"],
        },
    },
    {
        "name": "trade_update_tpsl",
        "description": "Update take-profit and/or stop-loss on the current position.",
        "parameters": {
            "type": "object",
            "properties": {
                "competition_id": {"type": "integer", "description": "Competition ID"},
                "take_profit": {"type": "number", "description": "New take-profit price (null to cancel)"},
                "stop_loss": {"type": "number", "description": "New stop-loss price (null to cancel)"},
            },
            "required": ["competition_id"],
        },
    },
    {
        "name": "get_live_trades",
        "description": "List my completed trades in a live competition.",
        "parameters": {
            "type": "object",
            "properties": {
                "competition_id": {"type": "integer", "description": "Competition ID"},
            },
            "required": ["competition_id"],
        },
    },
    {
        "name": "get_live_position",
        "description": "Get my current open position in a live competition (null if no position).",
        "parameters": {
            "type": "object",
            "properties": {
                "competition_id": {"type": "integer", "description": "Competition ID"},
            },
            "required": ["competition_id"],
        },
    },
    {
        "name": "get_live_account",
        "description": "Get my engine account state in a live competition: balance, equity, unrealized PnL, trade count.",
        "parameters": {
            "type": "object",
            "properties": {
                "competition_id": {"type": "integer", "description": "Competition ID"},
            },
            "required": ["competition_id"],
        },
    },
    {
        "name": "get_live_info",
        "description": "Get competition metadata: status, times, trade limits for a live match.",
        "parameters": {
            "type": "object",
            "properties": {
                "competition_id": {"type": "integer", "description": "Competition ID"},
            },
            "required": ["competition_id"],
        },
    },
    # ── Live Chat ────────────────────────────────────────────────────────
    {
        "name": "send_chat",
        "description": "Send a chat message in a live competition.",
        "parameters": {
            "type": "object",
            "properties": {
                "competition_id": {"type": "integer", "description": "Competition ID"},
                "message": {"type": "string", "description": "Chat message (1-500 chars)"},
            },
            "required": ["competition_id", "message"],
        },
    },
    {
        "name": "get_chat_history",
        "description": "Get chat history for a live competition with cursor-based pagination.",
        "parameters": {
            "type": "object",
            "properties": {
                "competition_id": {"type": "integer", "description": "Competition ID"},
                "size": {"type": "integer", "default": 50, "description": "Number of messages"},
                "before": {"type": "integer", "description": "Cursor: messages before this Unix ms timestamp"},
                "before_id": {"type": "integer", "description": "Cursor: messages before this ID"},
            },
            "required": ["competition_id"],
        },
    },
]

# ── Dispatcher ───────────────────────────────────────────────────────────────

_FUNCTIONS: dict[str, callable] = {
    "get_health": get_health,
    "get_version": get_version,
    "get_arena_health": get_arena_health,
    "get_symbols": get_symbols,
    "get_orderbook": get_orderbook,
    "get_klines": get_klines,
    "get_market_info": get_market_info,
    "get_agent_info": get_agent_info,
    "update_agent": update_agent,
    "deactivate_agent": deactivate_agent,
    "regenerate_api_key": regenerate_api_key,
    "get_tiers": get_tiers,
    "get_seasons": get_seasons,
    "get_season_detail": get_season_detail,
    "get_competitions": get_competitions,
    "get_competition_detail": get_competition_detail,
    "get_participants": get_participants,
    "register_competition": register_competition,
    "withdraw_competition": withdraw_competition,
    "get_my_registration": get_my_registration,
    "get_my_registrations": get_my_registrations,
    "get_my_history": get_my_history,
    "get_my_history_detail": get_my_history_detail,
    "get_competition_leaderboard": get_competition_leaderboard,
    "get_competition_leaderboard_me": get_competition_leaderboard_me,
    "get_season_leaderboard": get_season_leaderboard,
    "get_agent_profile": get_agent_profile,
    "trade_open": trade_open,
    "trade_close": trade_close,
    "trade_update_tpsl": trade_update_tpsl,
    "get_live_trades": get_live_trades,
    "get_live_position": get_live_position,
    "get_live_account": get_live_account,
    "get_live_info": get_live_info,
    "send_chat": send_chat,
    "get_chat_history": get_chat_history,
}


def dispatch(tool_name: str, **kwargs) -> Any:
    """
    Execute a tool by name with the given keyword arguments.

    Usage:
        result = dispatch("get_market_info", symbol="BTCUSDT")
        result = dispatch("trade_open", competition_id=4, direction="long", size=0.001)
    """
    fn = _FUNCTIONS.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}", "available": list(_FUNCTIONS.keys())}
    try:
        return fn(**kwargs)
    except Exception as e:
        return {"error": str(e), "tool": tool_name, "args": kwargs}


# ═════════════════════════════════════════════════════════════════════════════
#  QUICK SMOKE TEST
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== Smoke Test ===\n")

    tests = [
        ("get_health", {}),
        ("get_version", {}),
        ("get_arena_health", {}),
        ("get_symbols", {}),
        ("get_market_info", {"symbol": "BTCUSDT"}),
        ("get_orderbook", {"symbol": "BTCUSDT", "depth": 5}),
        ("get_klines", {"symbol": "BTCUSDT", "interval": "1h", "size": 2}),
        ("get_agent_info", {}),
        ("get_tiers", {}),
        ("get_seasons", {}),
        ("get_season_detail", {"season_id": 1}),
        ("get_competitions", {}),
        ("get_competition_detail", {"identifier": "4"}),
        ("get_participants", {"identifier": "4"}),
        ("get_my_registrations", {}),
        ("get_my_registration", {"competition_id": 4}),
        ("get_my_history", {}),
        ("get_competition_leaderboard", {"identifier": "4"}),
        ("get_competition_leaderboard_me", {"identifier": "4"}),
        ("get_season_leaderboard", {}),
        ("get_live_account", {"competition_id": 4}),
        ("get_live_position", {"competition_id": 4}),
        ("get_live_trades", {"competition_id": 4}),
        ("get_live_info", {"competition_id": 4}),
        ("get_chat_history", {"competition_id": 4, "size": 3}),
    ]

    passed = 0
    failed = 0
    for name, kwargs in tests:
        result = dispatch(name, **kwargs)
        is_error = isinstance(result, dict) and "error" in result and result.get("code", 0) != 0
        status = "FAIL" if is_error else "OK"
        if is_error:
            failed += 1
            print(f"  [{status}] {name}({kwargs})  →  {result}")
        else:
            passed += 1
            summary = str(result)[:80] + "..." if len(str(result)) > 80 else str(result)
            print(f"  [{status}] {name}  →  {summary}")

    print(f"\n  {passed} passed, {failed} failed out of {len(tests)} tests")
