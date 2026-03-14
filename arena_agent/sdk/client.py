"""Minimal synchronous MCP client for Arena SDK calls."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ArenaMCPClient:
    command: str = "./run_mcp_server.sh"
    args: list[str] = field(default_factory=lambda: ["--transport", "stdio"])
    cwd: str | None = None
    env: dict[str, str] | None = None

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        arguments = arguments or {}
        return _run_call(
            command=self.command,
            args=self.args,
            cwd=self.cwd,
            env=self.env,
            tool_name=name,
            arguments=arguments,
        )


def _run_call(command: str, args: list[str], cwd: str | None, env: dict[str, str] | None, tool_name: str, arguments: dict[str, Any]) -> Any:
    try:
        import anyio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ModuleNotFoundError as exc:  # pragma: no cover - runtime dependency
        raise RuntimeError(
            "MCP client dependencies are unavailable. Use the local .venv or install `mcp`."
        ) from exc

    async def _call() -> Any:
        server = StdioServerParameters(
            command=command,
            args=args,
            cwd=cwd or str(Path.cwd()),
            env=(os.environ.copy() | (env or {})),
        )
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                return _extract_payload(result)

    return anyio.run(_call)


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
