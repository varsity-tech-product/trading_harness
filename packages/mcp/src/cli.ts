#!/usr/bin/env node

/**
 * arena-mcp / arena-agent CLI
 *
 * MCP usage:
 *   arena-mcp serve
 *   arena-mcp setup --client <name>
 *   arena-mcp check
 *
 * User workflow:
 *   arena-agent init
 *   arena-agent doctor
 *   arena-agent up --agent gemini
 *   arena-agent monitor
 */
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { closeSync, existsSync, openSync } from "node:fs";
import { basename, isAbsolute, resolve } from "node:path";
import { stdin as input, stdout as output } from "node:process";
import { setTimeout as sleep } from "node:timers/promises";
import { createInterface } from "node:readline/promises";

import { serve } from "./index.js";
import { findArenaRoot, findPython } from "./util/paths.js";
import { checkPythonEnvironment } from "./setup/detect-python.js";
import { CLIENT_SETUP } from "./setup/client-configs.js";
import {
  bootstrapPythonRuntime,
  commandAvailable,
  probeCliCommand,
} from "./setup/bootstrap-python.js";
import { buildChildEnv, loadEnvFile } from "./util/env.js";
import {
  DEFAULT_MONITOR_PORT,
  DEFAULT_PYTHON_INSTALL_SOURCE,
  ManagedAgent,
  artifactsDirPath,
  configDirPath,
  createArenaHomeState,
  defaultArenaHome,
  envFilePath,
  isArenaHome,
  isManagedArenaHome,
  logsDirPath,
  profilePath,
  readArenaHomeState,
  resolveArenaHome,
  writeArenaEnvFile,
  writeArenaHomeState,
  writeManagedConfigs,
} from "./util/home.js";
import {
  clearRuntimeState,
  isProcessRunning,
  latestRuntimeLogPath,
  readRuntimeState,
  tailLines,
  writeRuntimeState,
} from "./util/runtime-state.js";

const argv = process.argv.slice(2);
const invokedAs = basename(process.argv[1] ?? "arena-agent");
const command = argv[0] ?? defaultCommand(invokedAs);

async function main(): Promise<void> {
  if (command === "serve") {
    const root = resolveHomeOrRoot(optionValue("--arena-root") ?? optionValue("--home"));
    await serve(root);
    return;
  }

  if (command === "check") {
    const root = resolveConfiguredHome(optionValue("--home"));
    const result = checkPythonEnvironment(root);
    console.log(`Arena home:  ${root}`);
    console.log(`Python:      ${result.python ?? "not found"}`);
    console.log(`Venv:        ${result.venv ? "ok" : "missing"}`);
    console.log(`Deps:        ${result.deps ? "ok" : "missing"}`);
    if (result.errors.length > 0) {
      console.log("\nIssues:");
      for (const err of result.errors) {
        console.log(`  - ${err}`);
      }
      process.exit(1);
    }
    console.log("\nAll checks passed.");
    return;
  }

  if (command === "setup") {
    const clientName = requireOption(
      "--client",
      `Usage: ${invokedAs} setup --client <${Object.keys(CLIENT_SETUP).join("|")}>`
    );
    const setupFn = CLIENT_SETUP[clientName];
    if (!setupFn) {
      throw new Error(
        `Unknown client: ${clientName}. Supported: ${Object.keys(CLIENT_SETUP).join(", ")}`
      );
    }

    const root = resolveConfiguredHome(optionValue("--home"));
    console.log("Checking Python environment...");
    const check = checkPythonEnvironment(root);
    if (check.errors.length > 0) {
      console.log("\nIssues found:");
      for (const err of check.errors) {
        console.log(`  - ${err}`);
      }
      console.log("\nFix the issues above, then re-run setup.");
      process.exit(1);
    }

    const configPath = setupFn(root);
    console.log(`\nConfigured ${clientName} at: ${configPath}`);
    console.log(`Arena home: ${root}`);
    console.log("\nTools available:");
    console.log("  arena.market_state       Get market/account/position state");
    console.log("  arena.competition_info   Competition metadata");
    console.log("  arena.trade_action       Submit a trade");
    console.log("  arena.last_transition    Last trade event");
    console.log("  arena.runtime_start      Start autonomous agent");
    console.log("  arena.runtime_stop       Stop autonomous agent");
    return;
  }

  if (command === "init") {
    await initManagedHome();
    return;
  }

  if (command === "doctor") {
    runDoctor();
    return;
  }

  if (command === "up") {
    const code = await runUp();
    process.exit(code);
  }

  if (command === "monitor") {
    const code = await runMonitorOnly();
    process.exit(code);
  }

  if (command === "upgrade") {
    await runUpgrade();
    return;
  }

  if (command === "status") {
    runStatus();
    return;
  }

  if (command === "down") {
    runDown();
    return;
  }

  if (command === "logs") {
    runLogs();
    return;
  }

  printUsage(invokedAs);
  process.exit(command ? 1 : 0);
}

async function initManagedHome(): Promise<void> {
  const home = resolveArenaHome(optionValue("--home"));
  const existingState = readArenaHomeState(home);
  const existingEnv = loadEnvFile(home);
  const availableCliBackends = detectInstalledCliBackends();

  let apiKey = optionValue("--api-key") ?? existingEnv.VARSITY_API_KEY ?? "";
  let agent = (optionValue("--agent") ??
    existingState?.defaultAgent ??
    (availableCliBackends.length > 0 ? "auto" : "rule")) as ManagedAgent;
  let model = optionValue("--model") ?? existingState?.defaultModel ?? "";
  let liveTrading =
    parseTradingMode(optionValue("--mode")) ??
    existingState?.liveTrading ??
    false;
  const pythonInstallSource =
    optionValue("--python-source") ??
    existingState?.pythonInstallSource ??
    DEFAULT_PYTHON_INSTALL_SOURCE;

  if (!hasFlag("--non-interactive")) {
    const rl = createInterface({ input, output });
    try {
      if (!apiKey) {
        apiKey = await promptRequired(rl, "Varsity API key");
      } else {
        apiKey = await promptValue(rl, "Varsity API key", apiKey);
      }
      agent = (await promptValue(
        rl,
        `Default agent backend [auto/rule/claude/gemini/openclaw/codex]`,
        agent
      )) as ManagedAgent;
      model = await promptValue(
        rl,
        "Default model override (leave blank for backend default)",
        model
      );
      const modeAnswer = await promptValue(
        rl,
        "Trading mode [live/dry-run]",
        liveTrading ? "live" : "dry-run"
      );
      liveTrading = modeAnswer.trim().toLowerCase() !== "dry-run";
      if (liveTrading) {
        await confirmLiveTrading(rl);
      }
    } finally {
      rl.close();
    }
  } else if (liveTrading && !hasFlag("--yes-live")) {
    throw new Error(
      "Live trading requires explicit confirmation. Re-run init with --yes-live or choose --mode dry-run."
    );
  }

  if (!apiKey.trim()) {
    throw new Error("VARSITY_API_KEY is required.");
  }
  if (!isManagedAgent(agent)) {
    throw new Error(
      "Invalid agent backend. Use one of: auto, rule, claude, gemini, openclaw, codex."
    );
  }
  validateAgentAvailability(agent, availableCliBackends);

  console.log(`Preparing Arena home at ${home}`);
  const state = createArenaHomeState(home, {
    defaultAgent: agent,
    defaultModel: model.trim() || null,
    liveTrading,
    pythonInstallSource,
  });
  writeArenaEnvFile(home, apiKey);
  writeManagedConfigs(home, state, { overwrite: true });
  writeArenaHomeState(home, state);

  console.log("\nBootstrapping Python runtime...");
  bootstrapPythonRuntime({
    home,
    pythonInstallSource,
    reinstall: hasFlag("--reinstall"),
    installMonitor: true,
    installMcp: true,
  });

  console.log("\nArena agent is ready.");
  console.log(`Home:          ${home}`);
  console.log(`API key file:  ${envFilePath(home)}`);
  console.log(`Config dir:    ${configDirPath(home)}`);
  console.log(`Artifacts dir: ${artifactsDirPath(home)}`);
  console.log("\nNext steps:");
  console.log(`  arena-agent doctor --home ${home}`);
  console.log(`  arena-agent up --home ${home}`);
}

function runDoctor(): void {
  const home = resolveConfiguredHome(optionValue("--home"));
  const state = readArenaHomeState(home);
  const env = loadEnvFile(home);
  const pythonCheck = checkPythonEnvironment(home);
  const errors = [...pythonCheck.errors];

  console.log(`Arena home:    ${home}`);
  console.log(`Managed home:  ${isManagedArenaHome(home) ? "yes" : "no"}`);
  console.log(`Python:        ${pythonCheck.python ?? "not found"}`);
  console.log(`Venv:          ${pythonCheck.venv ? "ok" : "missing"}`);
  console.log(`Runtime deps:  ${pythonCheck.deps ? "ok" : "missing"}`);
  console.log(`Env file:      ${existsSync(envFilePath(home)) ? "ok" : "missing"}`);
  console.log(`API key:       ${env.VARSITY_API_KEY ? "set" : "missing"}`);

  if (state) {
    console.log(`Default agent: ${state.defaultAgent}`);
    console.log(`Default model: ${state.defaultModel ?? "default"}`);
    console.log(`Mode:          ${state.liveTrading ? "live" : "dry-run"}`);
    console.log(`Monitor port:  ${state.monitorPort}`);
    console.log(`Agent config:  ${state.profiles.agentExec}`);
    console.log(`Rule config:   ${state.profiles.rule}`);
    if (!existsSync(state.profiles.agentExec)) {
      errors.push(`Missing managed config: ${state.profiles.agentExec}`);
    }
    if (!existsSync(state.profiles.rule)) {
      errors.push(`Missing managed config: ${state.profiles.rule}`);
    }
    const backendStatus = describeBackendStatus(state.defaultAgent);
    console.log(`Backend CLI:   ${backendStatus}`);
    if (backendStatus.startsWith("missing")) {
      errors.push(`Missing CLI backend for ${state.defaultAgent}.`);
    }
  } else if (isManagedArenaHome(home)) {
    errors.push(`Arena home marker exists but is invalid: ${home}`);
  } else {
    errors.push(`Arena home is not initialized. Run: arena-agent init --home ${home}`);
  }

  if (pythonCheck.python) {
    const monitorDepsOk = pythonImportsOk(
      pythonCheck.python,
      home,
      ["textual", "rich"]
    );
    console.log(`Monitor deps:  ${monitorDepsOk ? "ok" : "missing"}`);
    if (!monitorDepsOk) {
      errors.push("Monitor dependencies are missing.");
    }
  }

  if (errors.length > 0) {
    console.log("\nIssues:");
    for (const err of errors) {
      console.log(`  - ${err}`);
    }
    process.exit(1);
  }

  console.log("\nAll checks passed.");
}

async function runUp(): Promise<number> {
  const home = resolveConfiguredHome(optionValue("--home"));
  const state = readArenaHomeState(home);
  if (!state) {
    throw new Error(`Arena home is not initialized at ${home}. Run \`arena-agent init\` first.`);
  }

  const agent = (optionValue("--agent") ?? state.defaultAgent) as ManagedAgent;
  const model = optionValue("--model") ?? state.defaultModel ?? undefined;
  validateAgentAvailability(agent, detectInstalledCliBackends());
  if (state.liveTrading) {
    console.log("LIVE trading is enabled for this Arena home.");
  } else {
    console.log("Dry-run mode is enabled for this Arena home.");
  }

  const configPath = resolveUserConfigPath(
    home,
    state,
    optionValue("--config"),
    agent
  );
  const python = findPython(home);
  const env = buildChildEnv(home);
  const runtimeArgs = [
    "-m",
    "arena_agent",
    "run",
    "--agent",
    agent,
    "--config",
    configPath,
  ];
  if (model) {
    runtimeArgs.push("--model", model);
  }
  const iterations = optionValue("--iterations");
  if (iterations) {
    runtimeArgs.push("--iterations", iterations);
  }

  const monitorPort = Number(
    optionValue("--port") ?? String(state.monitorPort ?? DEFAULT_MONITOR_PORT)
  );
  const daemonMode = hasFlag("--daemon");
  if (daemonMode && !hasFlag("--no-monitor")) {
    throw new Error("Use --daemon together with --no-monitor. Attach later with `arena-agent monitor`.");
  }
  if (hasFlag("--no-monitor")) {
    const logPath = resolve(logsDirPath(home), `runtime-${Date.now()}.log`);
    if (daemonMode) {
      const logFd = openSync(logPath, "a");
      const child = spawn(python, runtimeArgs, {
        cwd: home,
        env,
        stdio: ["ignore", logFd, logFd],
        detached: true,
      });
      closeSync(logFd);
      child.unref();
      if (child.pid) {
        writeRuntimeState(home, {
          pid: child.pid,
          agent,
          configPath,
          logPath,
          startedAt: new Date().toISOString(),
          monitorPort,
        });
      }
      console.log(`Runtime started in background with pid ${child.pid ?? "unknown"}`);
      console.log(`Logs: ${logPath}`);
      console.log(`Monitor: arena-agent monitor --home ${home}`);
      return 0;
    }

    const child = spawn(python, runtimeArgs, {
      cwd: home,
      env,
      stdio: "inherit",
    });
    return waitForExit(child);
  }

  const logPath = resolve(logsDirPath(home), `runtime-${Date.now()}.log`);
  const logFd = openSync(logPath, "a");
  const runtimeChild = spawn(python, runtimeArgs, {
    cwd: home,
    env,
    stdio: ["ignore", logFd, logFd],
  });
  closeSync(logFd);
  if (runtimeChild.pid) {
    writeRuntimeState(home, {
      pid: runtimeChild.pid,
      agent,
      configPath,
      logPath,
      startedAt: new Date().toISOString(),
      monitorPort,
    });
  }

  console.log(`Runtime started with pid ${runtimeChild.pid ?? "unknown"}`);
  console.log(`Runtime logs: ${logPath}`);
  await sleep(800);

  const monitorArgs = [
    "-m",
    "arena_agent",
    "monitor",
    "--host",
    "127.0.0.1",
    "--port",
    String(monitorPort),
  ];
  const monitorChild = spawn(python, monitorArgs, {
    cwd: home,
    env,
    stdio: "inherit",
  });

  const shutdown = () => {
    if (!monitorChild.killed) {
      monitorChild.kill("SIGINT");
    }
    if (!runtimeChild.killed) {
      runtimeChild.kill("SIGTERM");
    }
  };

  const onSignal = () => shutdown();
  process.once("SIGINT", onSignal);
  process.once("SIGTERM", onSignal);

  runtimeChild.once("exit", (code) => {
    if (code && !monitorChild.killed) {
      console.error(`Runtime exited with code ${code}. Check ${logPath}`);
      monitorChild.kill("SIGINT");
    }
  });

  const monitorCode = await waitForExit(monitorChild);
  if (!runtimeChild.killed) {
    runtimeChild.kill("SIGTERM");
    await waitForExit(runtimeChild);
  }
  clearRuntimeState(home);
  return monitorCode;
}

async function runMonitorOnly(): Promise<number> {
  const home = resolveConfiguredHome(optionValue("--home"));
  const state = readArenaHomeState(home);
  const monitorPort = Number(
    optionValue("--port") ?? String(state?.monitorPort ?? DEFAULT_MONITOR_PORT)
  );
  const python = findPython(home);
  const env = buildChildEnv(home);
  const child = spawn(
    python,
    [
      "-m",
      "arena_agent",
      "monitor",
      "--host",
      "127.0.0.1",
      "--port",
      String(monitorPort),
    ],
    {
      cwd: home,
      env,
      stdio: "inherit",
    }
  );
  return waitForExit(child);
}

function resolveConfiguredHome(explicitHome?: string): string {
  if (explicitHome) {
    return resolveArenaHome(explicitHome);
  }
  return findArenaRoot();
}

function resolveHomeOrRoot(explicitHome?: string): string {
  if (explicitHome) {
    return resolveArenaHome(explicitHome);
  }
  return findArenaRoot();
}

function resolveUserConfigPath(
  home: string,
  state: ReturnType<typeof readArenaHomeState>,
  rawConfig: string | undefined,
  agent: ManagedAgent
): string {
  const candidates: string[] = [];
  if (rawConfig) {
    if (isAbsolute(rawConfig)) {
      return rawConfig;
    }
    candidates.push(resolve(home, rawConfig));
    candidates.push(resolve(home, "arena_agent", "config", rawConfig));
  } else if (isManagedArenaHome(home) && state) {
    if (agent === "rule") {
      candidates.push(state.profiles.rule);
    } else {
      candidates.push(state.profiles.agentExec);
    }
  } else if (agent === "rule") {
    candidates.push(resolve(home, "arena_agent", "config", "agent_config.yaml"));
  } else {
    candidates.push(resolve(home, "arena_agent", "config", "codex_agent_config.yaml"));
  }

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return candidates[0];
}

function detectInstalledCliBackends(): ManagedAgent[] {
  const installed: ManagedAgent[] = [];
  if (commandAvailable("claude")) {
    installed.push("claude");
  }
  if (commandAvailable("gemini")) {
    installed.push("gemini");
  }
  if (commandAvailable("openclaw")) {
    installed.push("openclaw");
  }
  if (commandAvailable("codex")) {
    installed.push("codex");
  }
  return installed;
}

function describeBackendStatus(agent: ManagedAgent): string {
  if (agent === "rule") {
    return "builtin";
  }
  if (agent === "auto") {
    const available = detectInstalledCliBackends();
    return available.length > 0
      ? `ok (${available.join(", ")})`
      : "missing (no claude/gemini/openclaw/codex CLI found)";
  }
  const probe = probeCliCommand(agent);
  if (!probe.available) {
    return `missing (${agent})`;
  }
  if (!probe.runnable) {
    return `degraded (${probe.detail})`;
  }
  return `ok (${probe.detail})`;
}

function validateAgentAvailability(
  agent: ManagedAgent,
  availableCliBackends: ManagedAgent[]
): void {
  if (agent === "rule") {
    return;
  }
  if (agent === "auto" && availableCliBackends.length > 0) {
    return;
  }
  if (agent === "auto") {
    throw new Error(
      "No CLI backend found in PATH for auto mode. Install claude, gemini, openclaw, or codex, or use --agent rule."
    );
  }
  if (!commandAvailable(agent)) {
    throw new Error(`The ${agent} CLI is not available in PATH.`);
  }
}

function pythonImportsOk(
  python: string,
  cwd: string,
  modules: string[]
): boolean {
  const script = modules.map((name) => `import ${name}`).join("; ");
  const result = spawnSync(python, ["-c", script], {
    cwd,
    stdio: "ignore",
  });
  return result.status === 0;
}

function defaultCommand(invocation: string): string {
  if (invocation === "arena-mcp") {
    return "serve";
  }
  return "help";
}

function printUsage(invocation: string): void {
  console.log(`Usage: ${invocation} <command> [options]`);
  console.log("");
  console.log("Commands:");
  console.log("  serve                    Start MCP server on stdio");
  console.log("  setup --client <name>    Configure an MCP client");
  console.log("  check                    Validate Python environment");
  console.log("  init                     Bootstrap a managed Arena home");
  console.log("  doctor                   Check managed home, Python, deps, and backend CLI");
  console.log("  up                       Start trading runtime and open the TUI monitor");
  console.log("  monitor                  Attach to the TUI monitor only");
  console.log("  upgrade                  Reinstall or refresh the managed Python runtime");
  console.log("  status                   Show runtime pid, config, and monitor port");
  console.log("  down                     Stop the background runtime");
  console.log("  logs                     Print recent runtime logs");
  console.log("");
  console.log("Examples:");
  console.log("  arena-agent init");
  console.log("  arena-agent init --agent openclaw --mode dry-run");
  console.log("  arena-agent up --agent gemini");
  console.log("  arena-agent up --no-monitor --daemon");
  console.log("  arena-agent upgrade");
  console.log("  arena-mcp setup --client claude-code");
}

function optionValue(name: string): string | undefined {
  const idx = argv.indexOf(name);
  if (idx < 0 || idx + 1 >= argv.length) {
    return undefined;
  }
  return argv[idx + 1];
}

function requireOption(name: string, usage: string): string {
  const value = optionValue(name);
  if (!value) {
    throw new Error(usage);
  }
  return value;
}

function hasFlag(name: string): boolean {
  return argv.includes(name);
}

function parseTradingMode(
  value: string | undefined
): boolean | undefined {
  if (!value) {
    return undefined;
  }
  const normalized = value.trim().toLowerCase();
  if (normalized === "live") {
    return true;
  }
  if (normalized === "dry-run" || normalized === "dryrun") {
    return false;
  }
  throw new Error("Trading mode must be `live` or `dry-run`.");
}

function isManagedAgent(value: string): value is ManagedAgent {
  return ["auto", "rule", "claude", "gemini", "openclaw", "codex"].includes(value);
}

async function promptValue(
  rl: ReturnType<typeof createInterface>,
  label: string,
  defaultValue = ""
): Promise<string> {
  const suffix = defaultValue ? ` [${defaultValue}]` : "";
  const answer = (await rl.question(`${label}${suffix}: `)).trim();
  return answer || defaultValue;
}

async function promptRequired(
  rl: ReturnType<typeof createInterface>,
  label: string
): Promise<string> {
  while (true) {
    const answer = (await rl.question(`${label}: `)).trim();
    if (answer) {
      return answer;
    }
  }
}

function waitForExit(child: ChildProcess): Promise<number> {
  return new Promise((resolvePromise) => {
    child.once("exit", (code) => {
      resolvePromise(code ?? 0);
    });
  });
}

async function runUpgrade(): Promise<void> {
  const home = resolveConfiguredHome(optionValue("--home"));
  const state = readArenaHomeState(home);
  if (!state) {
    throw new Error(`Arena home is not initialized at ${home}. Run \`arena-agent init\` first.`);
  }

  const pythonInstallSource =
    optionValue("--python-source") ?? state.pythonInstallSource;
  console.log(`Upgrading managed runtime in ${home}`);
  bootstrapPythonRuntime({
    home,
    pythonInstallSource,
    reinstall: true,
    installMonitor: true,
    installMcp: true,
  });
  console.log("Managed runtime upgraded.");
}

async function confirmLiveTrading(
  rl: ReturnType<typeof createInterface>
): Promise<void> {
  console.log("");
  console.log("Live trading will send real orders from this machine.");
  const answer = (
    await rl.question("Type LIVE to confirm: ")
  ).trim();
  if (answer !== "LIVE") {
    throw new Error("Live trading confirmation was not provided.");
  }
}

function runStatus(): void {
  const home = resolveConfiguredHome(optionValue("--home"));
  const runtimeState = readRuntimeState(home);
  if (!runtimeState) {
    console.log(`Arena home: ${home}`);
    console.log("Runtime:    stopped");
    return;
  }

  const running = isProcessRunning(runtimeState.pid);
  console.log(`Arena home:   ${home}`);
  console.log(`Runtime:      ${running ? "running" : "stopped"}`);
  console.log(`PID:          ${runtimeState.pid}`);
  console.log(`Agent:        ${runtimeState.agent}`);
  console.log(`Config:       ${runtimeState.configPath}`);
  console.log(`Logs:         ${runtimeState.logPath}`);
  console.log(`Monitor port: ${runtimeState.monitorPort}`);
  console.log(`Started at:   ${runtimeState.startedAt}`);

  if (!running) {
    clearRuntimeState(home);
  }
}

function runDown(): void {
  const home = resolveConfiguredHome(optionValue("--home"));
  const runtimeState = readRuntimeState(home);
  if (!runtimeState) {
    console.log("Runtime is not running.");
    return;
  }
  if (!isProcessRunning(runtimeState.pid)) {
    clearRuntimeState(home);
    console.log("Runtime is already stopped.");
    return;
  }

  process.kill(runtimeState.pid, "SIGTERM");
  clearRuntimeState(home);
  console.log(`Stopped runtime pid ${runtimeState.pid}.`);
}

function runLogs(): void {
  const home = resolveConfiguredHome(optionValue("--home"));
  const runtimeState = readRuntimeState(home);
  const logPath = runtimeState?.logPath ?? latestRuntimeLogPath(home);
  if (!logPath || !existsSync(logPath)) {
    throw new Error("No runtime log file found.");
  }
  const lines = Number(optionValue("--lines") ?? "50");
  console.log(tailLines(logPath, lines));
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
