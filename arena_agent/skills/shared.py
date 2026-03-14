"""Shared helpers for local Arena skill commands."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
from typing import Any

from arena_agent.config_loader import load_runtime_config
from arena_agent.core.environment_adapter import EnvironmentAdapter
from arena_agent.core.models import FeatureSpec, RuntimeConfig, TransitionEvent
from arena_agent.core.runtime_loop import MarketRuntime
from arena_agent.core.serialization import to_jsonable
from arena_agent.core.state_builder import StateBuilder
from arena_agent.execution.order_executor import OrderExecutor
from arena_agent.interfaces.action_schema import Action, ActionType
from arena_agent.memory.transition_store import TransitionStore


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = ROOT_DIR / ".env.runtime.local"
DEFAULT_CONFIG = ROOT_DIR / "arena_agent" / "config" / "tap_agent_config.yaml"


def load_local_runtime_env(env_file: str | None = None) -> Path | None:
    path = Path(env_file) if env_file else DEFAULT_ENV_FILE
    if not path.exists():
        return None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
    return path


def require_runtime_environment() -> None:
    if not os.environ.get("VARSITY_API_KEY", "").strip():
        raise SystemExit("VARSITY_API_KEY must be injected via the runtime environment.")


def build_runtime_components(config_path: str | None = None, signal_indicators: list[dict[str, Any]] | None = None):
    load_local_runtime_env()
    require_runtime_environment()
    config = load_runtime_config(config_path or str(DEFAULT_CONFIG))
    if signal_indicators is not None:
        config = replace(
            config,
            signal_indicators=[FeatureSpec.from_mapping(item) for item in signal_indicators],
        )
    adapter = EnvironmentAdapter(
        retry_attempts=config.adapter_retry_attempts,
        retry_backoff_seconds=config.adapter_retry_backoff_seconds,
        min_call_spacing_seconds=config.adapter_min_call_spacing_seconds,
    )
    state_builder = StateBuilder(adapter, config)
    executor = OrderExecutor(
        adapter,
        competition_id=config.competition_id,
        risk_limits=config.risk_limits,
        dry_run=config.dry_run,
    )
    transition_store = TransitionStore(
        maxlen=config.storage.max_in_memory_transitions,
        output_path=config.storage.transition_path,
    )
    runtime = MarketRuntime(
        config=config,
        adapter=adapter,
        state_builder=state_builder,
        executor=executor,
        transition_store=transition_store,
    )
    return config, adapter, state_builder, executor, transition_store, runtime


def build_base_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Runtime YAML config to use.",
    )
    return parser


def print_json(payload: Any) -> None:
    print(json.dumps(to_jsonable(payload), ensure_ascii=False))


def parse_action_payload(raw_payload: str | None, *, action: str | None, size: float | None, tp: float | None, sl: float | None) -> Action:
    if raw_payload:
        payload = json.loads(raw_payload)
    elif not os.isatty(0):
        stdin_payload = os.read(0, 1_000_000).decode().strip()
        payload = json.loads(stdin_payload) if stdin_payload else {}
    else:
        payload = {}

    action_name = payload.get("action") or payload.get("type") or action
    if action_name is None:
        raise SystemExit("Provide an action via --action, stdin JSON, or a JSON argument.")

    action_type = ActionType(str(action_name).upper())
    return Action(
        type=action_type,
        size=_coalesce_float(payload.get("size"), size),
        take_profit=_coalesce_float(payload.get("tp", payload.get("take_profit")), tp),
        stop_loss=_coalesce_float(payload.get("sl", payload.get("stop_loss")), sl),
        metadata=dict(payload.get("metadata", {})),
    )


def read_last_transition(path: str | None) -> TransitionEvent | dict[str, Any] | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        return None

    last_line = ""
    with file_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                last_line = line
    if not last_line:
        return None
    return json.loads(last_line)


def _coalesce_float(value: Any, fallback: float | None) -> float | None:
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
