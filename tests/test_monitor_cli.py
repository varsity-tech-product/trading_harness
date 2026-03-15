from __future__ import annotations

import subprocess
import sys
import unittest


class MonitorCLITest(unittest.TestCase):
    def test_monitor_help_works_without_textual_installed(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "arena_agent", "monitor", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("observability monitor", result.stdout)


if __name__ == "__main__":
    unittest.main()
