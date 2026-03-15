"""CLI entrypoint for the Arena Textual monitor."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Arena terminal observability monitor.")
    parser.add_argument("--host", default="127.0.0.1", help="Runtime observability host.")
    parser.add_argument("--port", type=int, default=8765, help="Runtime observability port.")
    parser.add_argument("--refresh-ms", type=int, default=500, help="UI refresh interval in milliseconds.")
    parser.add_argument("--reconnect-ms", type=int, default=1000, help="Reconnect delay in milliseconds.")
    args = parser.parse_args(argv)

    try:
        from arena_agent.tui.app import ArenaMonitorApp
    except ModuleNotFoundError as exc:
        if exc.name in {"textual", "rich"}:
            raise SystemExit(
                "The terminal monitor requires `textual` and `rich`. "
                "Install them in the local environment, for example: `.venv/bin/pip install textual rich`."
            ) from exc
        raise

    app = ArenaMonitorApp(
        host=args.host,
        port=args.port,
        refresh_interval_seconds=max(0.1, args.refresh_ms / 1000.0),
        reconnect_seconds=max(0.1, args.reconnect_ms / 1000.0),
    )
    app.run()


if __name__ == "__main__":
    main()
