from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from arena_agent.runtime_env import load_local_runtime_env, require_runtime_environment


class RuntimeEnvTest(unittest.TestCase):
    def test_load_local_runtime_env_sets_missing_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "runtime.env"
            env_file.write_text("VARSITY_API_KEY=test-key\nEXTRA_VALUE=abc\n", encoding="utf-8")

            original_api_key = os.environ.pop("VARSITY_API_KEY", None)
            original_extra = os.environ.pop("EXTRA_VALUE", None)
            try:
                load_local_runtime_env(str(env_file))
                self.assertEqual(os.environ["VARSITY_API_KEY"], "test-key")
                self.assertEqual(os.environ["EXTRA_VALUE"], "abc")
            finally:
                _restore_env("VARSITY_API_KEY", original_api_key)
                _restore_env("EXTRA_VALUE", original_extra)

    def test_load_local_runtime_env_preserves_existing_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "runtime.env"
            env_file.write_text("VARSITY_API_KEY=file-key\n", encoding="utf-8")

            original_api_key = os.environ.get("VARSITY_API_KEY")
            os.environ["VARSITY_API_KEY"] = "existing-key"
            try:
                load_local_runtime_env(str(env_file))
                self.assertEqual(os.environ["VARSITY_API_KEY"], "existing-key")
            finally:
                _restore_env("VARSITY_API_KEY", original_api_key)

    def test_require_runtime_environment_raises_when_api_key_missing(self) -> None:
        original_api_key = os.environ.pop("VARSITY_API_KEY", None)
        try:
            with self.assertRaises(SystemExit):
                require_runtime_environment()
        finally:
            _restore_env("VARSITY_API_KEY", original_api_key)


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
        return
    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
