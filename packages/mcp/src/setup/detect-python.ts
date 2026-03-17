import { execSync, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { isManagedArenaHome } from "../util/home.js";

export interface PythonCheck {
  ok: boolean;
  python: string | null;
  venv: boolean;
  deps: boolean;
  errors: string[];
}

export function checkPythonEnvironment(arenaRoot: string): PythonCheck {
  const errors: string[] = [];
  let python: string | null = null;
  let venv = false;
  let deps = false;

  // Check venv
  const venvPython = resolve(arenaRoot, ".venv", "bin", "python");
  const venvPythonWin = resolve(arenaRoot, ".venv", "Scripts", "python.exe");

  if (existsSync(venvPython)) {
    python = venvPython;
    venv = true;
  } else if (existsSync(venvPythonWin)) {
    python = venvPythonWin;
    venv = true;
  } else {
    errors.push(
      isManagedArenaHome(arenaRoot)
        ? "No venv found. Run: arena-agent init"
        : `No venv found. Run: python3 -m venv ${arenaRoot}/.venv`
    );
    // Try system python
    try {
      execSync("python3 --version", { stdio: "pipe" });
      python = "python3";
    } catch {
      errors.push("python3 not found in PATH.");
    }
  }

  if (!python) return { ok: false, python, venv, deps, errors };

  // Check deps
  try {
    const result = spawnSync(
      python,
      ["-c", "import mcp; import arena_agent; import numpy; import talib"],
      {
        stdio: "pipe",
        cwd: arenaRoot,
      }
    );
    deps = result.status === 0;
    if (!deps) {
      throw new Error("python dependency probe failed");
    }
  } catch {
    errors.push(
      isManagedArenaHome(arenaRoot)
        ? "Missing Python deps. Run: arena-agent init --reinstall"
        : `Missing Python deps. Run: ${python} -m pip install -e ${arenaRoot} mcp`
    );
  }

  // Check env file
  if (!existsSync(resolve(arenaRoot, ".env.runtime.local"))) {
    errors.push(
      "Missing .env.runtime.local — copy .env.runtime.local.example and set VARSITY_API_KEY."
    );
  }

  return { ok: errors.length === 0, python, venv, deps, errors };
}
