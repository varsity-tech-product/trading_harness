"""Helpers for loading the local Arena runtime environment."""

from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT_DIR / ".env.runtime.local"


def load_local_runtime_env(env_file: str | None = None, *, override: bool = False) -> Path | None:
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
        if override:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)
    return path


def require_runtime_environment() -> None:
    if not os.environ.get("VARSITY_API_KEY", "").strip():
        raise SystemExit("VARSITY_API_KEY must be injected via the runtime environment.")
