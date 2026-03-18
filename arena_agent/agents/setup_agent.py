"""LLM-powered setup agent — configures the runtime agent's strategy."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import shutil
import subprocess
from string import Template
import tempfile
from typing import Any

from arena_agent.agents.agent_exec_policy import (
    _strip_markdown_fences,
    resolve_backend,
)

logger = logging.getLogger("arena_agent.setup_agent")

_PROMPT_TEMPLATE_PATH = Path(__file__).with_name("setup_prompt_template.md")
_SCHEMA_PATH = Path(__file__).with_name("setup_action_schema.json")


@dataclass
class SetupDecision:
    action: str  # "update" or "hold"
    overrides: dict[str, Any] | None
    reason: str
    restart_runtime: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "overrides": self.overrides,
            "reason": self.reason,
            "restart_runtime": self.restart_runtime,
        }


class SetupAgent:
    """Runs an LLM to decide config changes for the runtime agent."""

    def __init__(
        self,
        backend: str = "auto",
        model: str | None = None,
        timeout: float = 120.0,
    ):
        self.backend = backend
        self.model = model
        self.timeout = timeout
        self._resolved_backend = resolve_backend(backend, None)
        self._prompt_template = Template(
            _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
        )
        self._schema_text = _SCHEMA_PATH.read_text(encoding="utf-8").strip()

    def decide(self, context: dict[str, Any], memory_context: str = "") -> SetupDecision:
        """Send context to LLM, get config update decision."""
        prompt = self._render_prompt(context, memory_context)
        logger.info("Setup agent invoking %s (timeout=%ss)", self._resolved_backend, self.timeout)
        try:
            payload = self._run_cli(prompt)
            return self._parse_decision(payload)
        except Exception as exc:
            logger.warning("Setup agent decision failed: %s", exc)
            return SetupDecision(
                action="hold",
                overrides=None,
                reason=f"setup_error: {exc}",
                restart_runtime=False,
            )

    def _render_prompt(self, context: dict[str, Any], memory_context: str) -> str:
        memory_block = ""
        if memory_context:
            memory_block = (
                "Past competition memory (use this to avoid repeating bad strategies):\n"
                + memory_context
            )
        return self._prompt_template.substitute(
            memory_context=memory_block,
            setup_context_json=json.dumps(context, ensure_ascii=False, default=str),
        )

    def _run_cli(self, prompt: str) -> dict[str, Any]:
        if self._resolved_backend == "claude":
            return self._run_claude(prompt)
        if self._resolved_backend == "gemini":
            return self._run_gemini(prompt)
        if self._resolved_backend == "openclaw":
            return self._run_openclaw(prompt)
        return self._run_claude(prompt)

    def _run_claude(self, prompt: str) -> dict[str, Any]:
        command = [
            "claude",
            "-p",
            "--no-session-persistence",
            "--output-format", "json",
            "--json-schema", self._schema_text,
        ]
        if self.model:
            command.extend(["--model", self.model])
        return self._exec_subprocess(command, prompt, "claude")

    def _run_gemini(self, prompt: str) -> dict[str, Any]:
        command = [
            "gemini",
            "-p", "",
            "--output-format", "json",
            "--sandbox",
        ]
        if self.model:
            command.extend(["-m", self.model])
        return self._exec_subprocess(command, prompt, "gemini", response_key="response")

    def _run_openclaw(self, prompt: str) -> dict[str, Any]:
        command = [
            "openclaw",
            "agent",
            "--local",
            "--json",
            "--agent", "arena-trader",
            "--message", prompt,
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=tempfile.gettempdir(),
            timeout=self.timeout,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"openclaw failed: {(result.stderr or result.stdout or '')[:500]}")
        raw = (result.stdout or "").strip()
        if not raw:
            raise RuntimeError("openclaw returned empty output")
        # Extract JSON from openclaw output
        json_lines: list[str] = []
        brace_depth = 0
        for line in raw.split("\n"):
            stripped = line.lstrip()
            if brace_depth == 0 and not stripped.startswith("{"):
                continue
            json_lines.append(line)
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                break
        wrapper = json.loads("\n".join(json_lines))
        payloads = wrapper.get("payloads", [])
        if payloads and isinstance(payloads[0], dict):
            result_text = str(payloads[0].get("text", "")).strip()
        else:
            result_text = "\n".join(json_lines)
        result_text = _strip_markdown_fences(result_text)
        return json.loads(result_text)

    def _exec_subprocess(
        self,
        command: list[str],
        prompt: str,
        backend_name: str,
        response_key: str = "result",
    ) -> dict[str, Any]:
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=tempfile.gettempdir(),
            timeout=self.timeout,
            check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"{backend_name} failed with code={result.returncode}: {stderr[:500]}")
        raw = (result.stdout or "").strip()
        if not raw:
            raise RuntimeError(f"{backend_name} returned empty output")

        try:
            wrapper = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{backend_name} returned invalid JSON: {raw[:500]}") from exc

        if isinstance(wrapper, dict) and response_key in wrapper:
            result_text = str(wrapper[response_key]).strip()
        else:
            result_text = raw

        result_text = _strip_markdown_fences(result_text)

        try:
            payload = json.loads(result_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{backend_name} result is not valid JSON: {result_text[:500]}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{backend_name} payload must be an object, got: {payload!r}")
        return payload

    @staticmethod
    def _parse_decision(payload: dict[str, Any]) -> SetupDecision:
        action = str(payload.get("action", "hold")).lower()
        if action not in ("update", "hold"):
            action = "hold"
        return SetupDecision(
            action=action,
            overrides=payload.get("overrides") if action == "update" else None,
            reason=str(payload.get("reason", "no reason")),
            restart_runtime=bool(payload.get("restart_runtime", False)),
        )
