"""Universal MCP server exposing Arena platform tools."""

from __future__ import annotations

import argparse
from typing import Optional

from arena_agent.mcp import tools
from arena_agent.core.serialization import to_jsonable


def create_server(host: str = "127.0.0.1", port: int = 8000):
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:  # pragma: no cover - runtime dependency
        raise SystemExit(
            "The MCP SDK is not installed. Create a local venv and install `mcp`, "
            "or use `./run_mcp_server.sh`."
        ) from exc

    mcp = FastMCP(
        "varsity-arena",
        instructions=(
            "Varsity Arena agent toolkit — full platform access. "
            "Market data, competitions, registration, live trading, leaderboards, "
            "profiles, chat, predictions, notifications, seasons, and system health. "
            "Use arena.* tools for the autonomous runtime, varsity.* tools for "
            "direct API access."
        ),
        host=host,
        port=port,
        json_response=True,
    )

    # ── Runtime tools (local agent runtime) ──────────────────────────────

    @mcp.tool(name="varsity.market_state", description="Get the current Arena market and account state.")
    def market_state(config_path: str | None = None, signal_indicators: list[dict] | None = None) -> dict:
        return to_jsonable(tools.market_state(config_path, signal_indicators=signal_indicators))

    @mcp.tool(name="varsity.competition_info", description="Get compact Arena competition metadata.")
    def competition_info(config_path: str | None = None, signal_indicators: list[dict] | None = None) -> dict:
        return to_jsonable(tools.competition_info(config_path, signal_indicators=signal_indicators))

    @mcp.tool(name="varsity.trade_action", description="Submit a trading action to Arena.")
    def trade_action(
        type: str,
        size: float | None = None,
        tp: float | None = None,
        sl: float | None = None,
        execute: bool = False,
        config_path: str | None = None,
        signal_indicators: list[dict] | None = None,
    ) -> dict:
        return to_jsonable(
            tools.trade_action(
                type=type,
                size=size,
                tp=tp,
                sl=sl,
                execute=execute,
                config_path=config_path,
                signal_indicators=signal_indicators,
            )
        )

    @mcp.tool(name="varsity.last_transition", description="Get the last stored transition.")
    def last_transition(config_path: str | None = None) -> dict:
        return to_jsonable(tools.last_transition(config_path))

    # ── System ───────────────────────────────────────────────────────────

    @mcp.tool(name="varsity.health", description="Get system health status including database, redis, and matching engine connectivity.")
    def health() -> dict:
        return tools.health()

    @mcp.tool(name="varsity.version", description="Get API version and build hash.")
    def version() -> dict:
        return tools.version()

    @mcp.tool(name="varsity.arena_health", description="Get arena module health status.")
    def arena_health() -> dict:
        return tools.arena_health()

    # ── Market Data ──────────────────────────────────────────────────────

    @mcp.tool(name="varsity.symbols", description="List all available trading symbols (BTCUSDT, ETHUSDT, etc.) with precision and min quantity config.")
    def symbols() -> dict:
        return tools.symbols()

    @mcp.tool(name="varsity.orderbook", description="Get order book snapshot (bids & asks) for a trading symbol.")
    def orderbook(symbol: str, depth: int = 20) -> dict:
        return tools.orderbook(symbol, depth)

    @mcp.tool(name="varsity.klines", description="Get OHLCV candlestick data for a symbol. Use for price charts and technical analysis.")
    def klines(
        symbol: str,
        interval: str,
        size: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> dict:
        return tools.klines(symbol, interval, size, start_time, end_time)

    @mcp.tool(name="varsity.market_info", description="Get full market info for a symbol: last price, mark price, index price, funding rate, 24h volume.")
    def market_info(symbol: str) -> dict:
        return tools.market_info(symbol)

    # ── Competitions ─────────────────────────────────────────────────────

    @mcp.tool(name="varsity.competitions", description="List competitions with optional filters (season, status, type). Returns paginated results.")
    def competitions(
        season_id: Optional[int] = None,
        status: Optional[str] = None,
        competition_type: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        return tools.competitions(season_id, status, competition_type, page, size)

    @mcp.tool(name="varsity.competition_detail", description="Get full competition detail including rules, prize tables, and registration windows.")
    def competition_detail(identifier: str) -> dict:
        return tools.competition_detail(identifier)

    @mcp.tool(name="varsity.participants", description="List accepted participants for a competition (public, paginated).")
    def participants(identifier: str, page: int = 1, size: int = 50) -> dict:
        return tools.participants(identifier, page, size)

    # ── Registration ─────────────────────────────────────────────────────

    @mcp.tool(name="varsity.register", description="Register for a competition. Must be in 'registration_open' state.")
    def register(competition_id: int) -> dict:
        return tools.register(competition_id)

    @mcp.tool(name="varsity.withdraw", description="Withdraw registration from a competition (before it goes live).")
    def withdraw(competition_id: int) -> dict:
        return tools.withdraw(competition_id)

    @mcp.tool(name="varsity.my_registration", description="Get my registration status for a specific competition.")
    def my_registration(competition_id: int) -> dict:
        return tools.my_registration(competition_id)

    # ── Leaderboards ─────────────────────────────────────────────────────

    @mcp.tool(name="varsity.leaderboard", description="Get competition leaderboard with rankings, PnL, trades, and prizes.")
    def leaderboard(identifier: str, page: int = 1, size: int = 50) -> dict:
        return tools.leaderboard(identifier, page, size)

    @mcp.tool(name="varsity.my_leaderboard_position", description="Get my position on competition leaderboard with surrounding entries.")
    def my_leaderboard_position(identifier: str) -> dict:
        return tools.my_leaderboard_position(identifier)

    @mcp.tool(name="varsity.season_leaderboard", description="Get season leaderboard ranked by cumulative points. Omit season_id for current active season.")
    def season_leaderboard(
        season_id: Optional[int] = None,
        page: int = 1,
        size: int = 50,
    ) -> dict:
        return tools.season_leaderboard(season_id, page, size)

    # ── Profile & History ────────────────────────────────────────────────

    @mcp.tool(name="varsity.my_profile", description="Get the authenticated user's full profile (username, email, role, etc.).")
    def my_profile() -> dict:
        return tools.my_profile()

    @mcp.tool(name="varsity.my_history", description="Get my competition history with rankings, PnL, and points earned (paginated).")
    def my_history(page: int = 1, size: int = 10) -> dict:
        return tools.my_history(page, size)

    @mcp.tool(name="varsity.my_history_detail", description="Get detailed result for a specific past competition including trade-level breakdown.")
    def my_history_detail(competition_id: int) -> dict:
        return tools.my_history_detail(competition_id)

    @mcp.tool(name="varsity.achievements", description="Get the full achievement catalog with my unlock status for each badge.")
    def achievements() -> dict:
        return tools.achievements()

    @mcp.tool(name="varsity.public_profile", description="Get a user's public arena profile by username.")
    def public_profile(username: str) -> dict:
        return tools.public_profile(username)

    @mcp.tool(name="varsity.public_history", description="Get a user's public competition history by username.")
    def public_history(username: str, page: int = 1, size: int = 10) -> dict:
        return tools.public_history(username, page, size)

    @mcp.tool(name="varsity.update_profile", description="Update the authenticated user's profile fields.")
    def update_profile(
        username: Optional[str] = None,
        display_name: Optional[str] = None,
        bio: Optional[str] = None,
        country: Optional[str] = None,
        participant_type: Optional[str] = None,
    ) -> dict:
        return tools.update_profile(
            username=username, display_name=display_name,
            bio=bio, country=country, participant_type=participant_type,
        )

    # ── Hub & Dashboard ──────────────────────────────────────────────────

    @mcp.tool(name="varsity.hub", description="Get arena hub dashboard: active competition, registrations, upcoming events, season progress, recent results, quick stats.")
    def hub() -> dict:
        return tools.hub()

    @mcp.tool(name="varsity.arena_profile", description="Get my arena profile (tier, season points, arena capital, etc.).")
    def arena_profile() -> dict:
        return tools.arena_profile()

    @mcp.tool(name="varsity.my_registrations", description="Get all my active registrations (pending/accepted/waitlisted).")
    def my_registrations() -> dict:
        return tools.my_registrations()

    # ── Seasons & Tiers ──────────────────────────────────────────────────

    @mcp.tool(name="varsity.tiers", description="List all tier definitions (iron to diamond) with point thresholds and leverage multipliers.")
    def tiers() -> dict:
        return tools.tiers()

    @mcp.tool(name="varsity.seasons", description="List all non-archived seasons, sorted by start date descending.")
    def seasons() -> dict:
        return tools.seasons()

    @mcp.tool(name="varsity.season_detail", description="Get a single season's details including competition counts.")
    def season_detail(season_id: int) -> dict:
        return tools.season_detail(season_id)

    # ── Live Trading (Direct API) ────────────────────────────────────────

    @mcp.tool(name="varsity.live_trades", description="List my completed trades in a live competition.")
    def live_trades(competition_id: int) -> dict:
        return tools.live_trades(competition_id)

    @mcp.tool(name="varsity.live_position", description="Get my current open position in a live competition (null if no position).")
    def live_position(competition_id: int) -> dict:
        return tools.live_position(competition_id)

    @mcp.tool(name="varsity.live_account", description="Get my engine account state in a live competition: balance, equity, unrealized PnL, trade count.")
    def live_account(competition_id: int) -> dict:
        return tools.live_account(competition_id)

    # ── Predictions & Polls ──────────────────────────────────────────────

    @mcp.tool(name="varsity.predictions", description="Get current-hour prediction summary (up/down counts, my prediction, last result).")
    def predictions(competition_id: int) -> dict:
        return tools.predictions(competition_id)

    @mcp.tool(name="varsity.submit_prediction", description="Submit a direction prediction for the current hour.")
    def submit_prediction(competition_id: int, direction: str, confidence: int) -> dict:
        return tools.submit_prediction(competition_id, direction, confidence)

    @mcp.tool(name="varsity.polls", description="List active polls in a live competition.")
    def polls(competition_id: int) -> dict:
        return tools.polls(competition_id)

    @mcp.tool(name="varsity.vote_poll", description="Vote on an active poll.")
    def vote_poll(competition_id: int, poll_id: int, option_index: int) -> dict:
        return tools.vote_poll(competition_id, poll_id, option_index)

    # ── Social ───────────────────────────────────────────────────────────

    @mcp.tool(name="varsity.chat_send", description="Send a chat message in a live competition.")
    def chat_send(competition_id: int, message: str) -> dict:
        return tools.chat_send(competition_id, message)

    @mcp.tool(name="varsity.chat_history", description="Get chat history for a live competition with cursor-based pagination.")
    def chat_history(
        competition_id: int,
        size: int = 50,
        before: Optional[int] = None,
        before_id: Optional[int] = None,
    ) -> dict:
        return tools.chat_history(competition_id, size, before, before_id)

    # ── Notifications ────────────────────────────────────────────────────

    @mcp.tool(name="varsity.notifications", description="Get paginated notifications.")
    def notifications(page: int = 1, size: int = 20) -> dict:
        return tools.notifications(page, size)

    @mcp.tool(name="varsity.unread_count", description="Get count of unread notifications (lightweight, good for polling).")
    def unread_count() -> dict:
        return tools.unread_count()

    @mcp.tool(name="varsity.mark_read", description="Mark a single notification as read.")
    def mark_read(notification_id: int) -> dict:
        return tools.mark_read(notification_id)

    @mcp.tool(name="varsity.mark_all_read", description="Mark all notifications as read.")
    def mark_all_read() -> dict:
        return tools.mark_all_read()

    # ── Behaviour Events ─────────────────────────────────────────────────

    @mcp.tool(name="varsity.track_event", description="Track a user behaviour event.")
    def track_event(competition_id: int, event_type: str, payload: Optional[dict] = None) -> dict:
        return tools.track_event(competition_id, event_type, payload)

    # ── Composite tools (higher-level, combine multiple API calls) ────────

    @mcp.tool(name="varsity.my_status", description="Full agent dashboard in one call: account, position, PnL, rank, competition, season, notifications. Pass competition_id or auto-detects from active registrations.")
    def my_status(competition_id: Optional[int] = None) -> dict:
        return tools.my_status(competition_id)

    @mcp.tool(name="varsity.best_competition", description="Find the best competition to join. Returns top pick with entry requirements, reward, participants, schedule, and alternatives.")
    def best_competition() -> dict:
        return tools.best_competition()

    @mcp.tool(name="varsity.auto_join", description="Find the best competition and register for it automatically. Returns registration result or reason for failure.")
    def auto_join() -> dict:
        return tools.auto_join()

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Varsity Arena MCP server.")
    parser.add_argument("--transport", choices=["stdio", "streamable-http", "sse"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = create_server(host=args.host, port=args.port)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
