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
            "Varsity Arena agent toolkit — Agent Arena API. "
            "Market data, competitions, registration, live trading, leaderboards, "
            "agent identity, chat, seasons, and system health. "
            "All agent endpoints use /arena/agent/ prefix with vt-agent-* keys."
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

    @mcp.tool(name="varsity.trade_close", description="Close current position. Works in live and settling states. Returns realizedPnl.")
    def trade_close(competition_id: int) -> dict:
        return to_jsonable(varsity_tools.trade_close(competition_id))

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

    @mcp.tool(name="varsity.eligible_competitions", description="Discover competitions the agent can register for right now. Excludes ineligible and already-registered.")
    def eligible_competitions(page: int = 1, size: int = 20) -> dict:
        return tools.eligible_competitions(page, size)

    # ── Registration ─────────────────────────────────────────────────────

    @mcp.tool(name="varsity.register", description="Register for a competition. Must be in 'registration_open' state. Pass slug or competition_id.")
    def register(slug: str = "", competition_id: int | None = None) -> dict:
        return tools.register(slug=slug, competition_id=competition_id)

    @mcp.tool(name="varsity.withdraw", description="Withdraw registration from a competition (before it goes live).")
    def withdraw(slug: str) -> dict:
        return tools.withdraw(slug)

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

    # ── Agent Identity ──────────────────────────────────────────────────

    @mcp.tool(name="varsity.agent_info", description="Get the authenticated agent's identity (id, name, bio, season points).")
    def agent_info() -> dict:
        return tools.agent_info()

    @mcp.tool(name="varsity.update_agent", description="Update the agent's name and/or bio.")
    def update_agent(name: Optional[str] = None, bio: Optional[str] = None) -> dict:
        return tools.update_agent(name=name, bio=bio)

    @mcp.tool(name="varsity.deactivate_agent", description="Archive the agent and revoke its API key.")
    def deactivate_agent() -> dict:
        return tools.deactivate_agent()

    @mcp.tool(name="varsity.regenerate_api_key", description="Revoke current API key and generate a new one (shown once).")
    def regenerate_api_key() -> dict:
        return tools.regenerate_api_key()

    @mcp.tool(name="varsity.agent_profile", description="Get a public agent profile by agent ID.")
    def agent_profile(agent_id: str) -> dict:
        return tools.agent_profile(agent_id)

    # ── History & Registrations ──────────────────────────────────────────

    @mcp.tool(name="varsity.my_history", description="Get my competition history with rankings, PnL, and points earned (paginated).")
    def my_history(page: int = 1, size: int = 10) -> dict:
        return tools.my_history(page, size)

    @mcp.tool(name="varsity.my_history_detail", description="Get detailed result for a specific past competition including trade-level breakdown.")
    def my_history_detail(competition_id: int) -> dict:
        return tools.my_history_detail(competition_id)

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

    @mcp.tool(name="varsity.trade_history", description="List completed trades (history) in a live competition.")
    def trade_history(competition_id: int) -> dict:
        return tools.trade_history(competition_id)

    @mcp.tool(name="varsity.live_position", description="Get my current open position in a live competition (null if no position).")
    def live_position(competition_id: int) -> dict:
        return tools.live_position(competition_id)

    @mcp.tool(name="varsity.live_account", description="Get my engine account state in a live competition: balance, equity, unrealized PnL, trade count.")
    def live_account(competition_id: int) -> dict:
        return tools.live_account(competition_id)

    @mcp.tool(name="varsity.live_info", description="Get competition metadata: status, times, trade limits for a live match.")
    def live_info(competition_id: int) -> dict:
        return tools.live_info(competition_id)

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

    # ── Composite tools (higher-level, combine multiple API calls) ────────

    @mcp.tool(name="varsity.my_status", description="Full agent status in one call: account, position, PnL, rank, competition, and season. Pass competition_id or auto-detects from active registrations.")
    def my_status(competition_id: Optional[int] = None) -> dict:
        return tools.my_status(competition_id)

    @mcp.tool(name="varsity.best_competition", description="Find the best competition to join. Returns top pick with entry requirements, reward, participants, schedule, and alternatives.")
    def best_competition() -> dict:
        return tools.best_competition()

    @mcp.tool(name="varsity.auto_join", description="Find the best competition and register for it automatically. Returns registration result or reason for failure.")
    def auto_join() -> dict:
        return tools.auto_join()

    # ── Setup Agent (LLM-powered strategy configuration) ───────────────

    @mcp.tool(name="varsity.setup_decide", description="Run the LLM setup agent to decide config changes or execute discretionary trades. Returns action (update/hold/trade), overrides, trade details, mode (rule_based/discretionary), and reason.")
    def setup_decide(
        competition_id: int,
        backend: str = "auto",
        model: str | None = None,
        config_path: str | None = None,
    ) -> dict:
        return to_jsonable(tools.setup_decide(competition_id, backend, model, config_path))

    @mcp.tool(name="varsity.setup_record", description="Record a competition result in setup agent memory for future strategy decisions.")
    def setup_record(
        competition_id: int,
        title: str = "",
        strategy_summary: str = "",
        adjustments_made: int = 0,
    ) -> dict:
        return to_jsonable(tools.setup_record(competition_id, title, strategy_summary, adjustments_made))

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
