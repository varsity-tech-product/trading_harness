"""Universal MCP server exposing Arena trading tools."""

from __future__ import annotations

import argparse

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
            "Arena trading environment. Use small composable tools only: "
            "market state, competition info, trade action, and last transition."
        ),
        host=host,
        port=port,
        json_response=True,
    )

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
