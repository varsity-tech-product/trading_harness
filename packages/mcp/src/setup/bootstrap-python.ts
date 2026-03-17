import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { localPythonSourcePath } from "../util/home.js";

export interface BootstrapOptions {
  home: string;
  pythonInstallSource: string;
  reinstall?: boolean;
  installMonitor?: boolean;
  installMcp?: boolean;
}

export function detectSystemPython(): string | null {
  const candidates: Array<{ command: string; args: string[] }> = [
    { command: "python3", args: ["--version"] },
    { command: "python", args: ["--version"] },
  ];
  if (process.platform === "win32") {
    candidates.unshift({ command: "py", args: ["-3", "--version"] });
  }

  for (const candidate of candidates) {
    const result = spawnSync(candidate.command, candidate.args, {
      stdio: "ignore",
    });
    if (result.status === 0) {
      return candidate.command;
    }
  }
  return null;
}

export function venvPythonPath(home: string): string {
  return process.platform === "win32"
    ? resolve(home, ".venv", "Scripts", "python.exe")
    : resolve(home, ".venv", "bin", "python");
}

export function bootstrapPythonRuntime(options: BootstrapOptions): string {
  const pythonBin = detectSystemPython();
  if (!pythonBin) {
    throw new Error("Python 3 was not found in PATH. Install Python 3.10+ first.");
  }

  const venvPython = venvPythonPath(options.home);
  if (!existsSync(venvPython)) {
    const args =
      pythonBin === "py"
        ? ["-3", "-m", "venv", resolve(options.home, ".venv")]
        : ["-m", "venv", resolve(options.home, ".venv")];
    execFileSync(pythonBin, args, { stdio: "inherit" });
  }

  try {
    execFileSync(
      venvPython,
      ["-m", "pip", "install", "--upgrade", "pip"],
      { stdio: "inherit" }
    );
  } catch {
    // Keep bootstrap moving even when pip upgrade is unavailable offline.
  }

  const installSource = resolveInstallSource(options.pythonInstallSource);
  if (existsSync(installSource)) {
    installLocalSource({
      venvPython,
      sourcePath: installSource,
      forceReinstall: options.reinstall ?? false,
      fallbackBuilderPython: pythonBin,
    });
  } else {
    const installArgs = ["-m", "pip", "install"];
    if (options.reinstall) {
      installArgs.push("--force-reinstall");
    }
    installArgs.push(installSource);
    execFileSync(venvPython, installArgs, { stdio: "inherit" });
  }

  const extraPackages: string[] = [];
  if (options.installMcp ?? true) {
    extraPackages.push("mcp>=1.12.0");
  }
  if (options.installMonitor ?? true) {
    extraPackages.push("textual>=0.79.0", "rich>=13.7.0");
  }
  if (extraPackages.length > 0) {
    execFileSync(
      venvPython,
      ["-m", "pip", "install", ...extraPackages],
      { stdio: "inherit" }
    );
  }

  return venvPython;
}

export function resolveInstallSource(source: string): string {
  if (source === "local") {
    const localSource = localPythonSourcePath();
    if (!localSource) {
      throw new Error("Local Python source is unavailable from this npm install.");
    }
    return localSource;
  }
  return source;
}

function installLocalSource(options: {
  venvPython: string;
  sourcePath: string;
  forceReinstall: boolean;
  fallbackBuilderPython: string;
}): void {
  const tempDir = mkdtempSync(join(tmpdir(), "arena-agent-wheel-"));
  try {
    const builderPython = resolveBuilderPython(
      options.sourcePath,
      options.fallbackBuilderPython
    );
    execFileSync(
      builderPython,
      [
        "-m",
        "pip",
        "wheel",
        options.sourcePath,
        "--wheel-dir",
        tempDir,
        "--no-deps",
        "--no-build-isolation",
      ],
      { stdio: "inherit", cwd: options.sourcePath }
    );

    const wheelName = readdirSync(tempDir).find((name) => name.endsWith(".whl"));
    if (!wheelName) {
      throw new Error("No wheel was produced from the local Python source.");
    }

    const installArgs = ["-m", "pip", "install"];
    if (options.forceReinstall) {
      installArgs.push("--force-reinstall");
    }
    if (runtimeDepsInstalled(options.venvPython)) {
      installArgs.push("--no-deps");
    }
    installArgs.push(resolve(tempDir, wheelName));
    execFileSync(options.venvPython, installArgs, { stdio: "inherit" });
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

function resolveBuilderPython(sourcePath: string, fallbackPython: string): string {
  const candidates = [
    resolve(sourcePath, ".venv", "bin", "python"),
    resolve(sourcePath, ".venv", "bin", "python3"),
    resolve(sourcePath, ".venv", "Scripts", "python.exe"),
    fallbackPython,
  ];
  for (const candidate of candidates) {
    if (candidate === fallbackPython && builderPythonReady(candidate)) {
      return candidate;
    }
    if (existsSync(candidate) && builderPythonReady(candidate)) {
      return candidate;
    }
  }
  return fallbackPython;
}

function builderPythonReady(python: string): boolean {
  const result = spawnSync(
    python,
    ["-c", "import setuptools.build_meta"],
    { stdio: "ignore" }
  );
  return result.status === 0;
}

function runtimeDepsInstalled(python: string): boolean {
  const result = spawnSync(
    python,
    ["-c", "import requests, yaml, numpy, talib"],
    { stdio: "ignore" }
  );
  return result.status === 0;
}

export function commandAvailable(command: string): boolean {
  const locator = process.platform === "win32" ? "where" : "which";
  const result = spawnSync(locator, [command], { stdio: "ignore" });
  return result.status === 0;
}

export interface CommandProbe {
  available: boolean;
  runnable: boolean;
  detail: string;
}

export function probeCliCommand(command: string): CommandProbe {
  if (!commandAvailable(command)) {
    return {
      available: false,
      runnable: false,
      detail: `${command} not found in PATH`,
    };
  }

  for (const args of [["--version"], ["--help"]]) {
    const result = spawnSync(command, args, {
      stdio: "pipe",
      timeout: 5000,
    });
    if (result.status === 0) {
      return {
        available: true,
        runnable: true,
        detail: `${command} responds to ${args.join(" ")}`,
      };
    }
  }

  return {
    available: true,
    runnable: false,
    detail: `${command} exists but did not respond cleanly to --version/--help`,
  };
}
