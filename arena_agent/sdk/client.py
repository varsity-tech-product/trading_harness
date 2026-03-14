"""Minimal synchronous MCP client for Arena SDK calls."""

from __future__ import annotations

import json
import os
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ArenaMCPClient:
    command: str = "./run_mcp_server.sh"
    args: list[str] = field(default_factory=lambda: ["--transport", "stdio"])
    cwd: str | None = None
    env: dict[str, str] | None = None
    _portal_cm: Any | None = field(init=False, default=None, repr=False)
    _portal: Any | None = field(init=False, default=None, repr=False)
    _runner_future: Any | None = field(init=False, default=None, repr=False)
    _requests: queue.Queue | None = field(init=False, default=None, repr=False)
    _ready: threading.Event | None = field(init=False, default=None, repr=False)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        arguments = arguments or {}
        self._ensure_session()
        response_queue: queue.Queue = queue.Queue(maxsize=1)
        self._requests.put((name, arguments, response_queue))
        status, payload = response_queue.get()
        if status == "error":
            raise payload
        result = payload
        return _extract_payload(result)

    def close(self) -> None:
        if self._portal is None:
            return
        try:
            if self._requests is not None:
                self._requests.put(None)
            if self._runner_future is not None:
                self._runner_future.result(timeout=5)
        finally:
            self._portal_cm.__exit__(None, None, None)
            self._portal_cm = None
            self._portal = None
            self._runner_future = None
            self._requests = None
            self._ready = None

    def __enter__(self) -> "ArenaMCPClient":
        self._ensure_session()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        try:
            self.close()
        except Exception:
            pass

    def _ensure_session(self) -> None:
        if self._portal is not None:
            return
        try:
            from anyio.from_thread import start_blocking_portal
        except ModuleNotFoundError as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError(
                "MCP client dependencies are unavailable. Use the local .venv or install `mcp`."
            ) from exc

        self._portal_cm = start_blocking_portal()
        self._portal = self._portal_cm.__enter__()
        self._requests = queue.Queue()
        self._ready = threading.Event()
        self._runner_future = self._portal.start_task_soon(self._session_worker)
        if not self._ready.wait(timeout=10):
            if self._runner_future.done():
                raise self._runner_future.exception()  # pragma: no cover - startup failure
            raise RuntimeError("Timed out starting the MCP client session.")

    async def _session_worker(self) -> None:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            import anyio
        except ModuleNotFoundError as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError(
                "MCP client dependencies are unavailable. Use the local .venv or install `mcp`."
            ) from exc

        server = StdioServerParameters(
            command=self.command,
            args=self.args,
            cwd=self.cwd or str(Path.cwd()),
            env=(os.environ.copy() | (self.env or {})),
        )
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                self._ready.set()
                while True:
                    request = await anyio.to_thread.run_sync(self._requests.get)
                    if request is None:
                        return
                    name, arguments, response_queue = request
                    try:
                        result = await session.call_tool(name, arguments)
                    except Exception as exc:
                        response_queue.put(("error", exc))
                    else:
                        response_queue.put(("ok", result))


def _extract_payload(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured

    content = getattr(result, "content", None) or []
    text = "".join(getattr(block, "text", "") for block in content)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
