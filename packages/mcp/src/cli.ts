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
import { PythonBridge } from "./python-bridge.js";
import { startDashboard } from "./dashboard/serve.js";
import { findArenaRoot, findPython } from "./util/paths.js";
import { checkPythonEnvironment } from "./setup/detect-python.js";
import { CLIENT_SETUP, autoWireMcpForAgent } from "./setup/client-configs.js";
import { ensureOpenClawTradingAgent } from "./setup/openclaw-agent.js";
import { probeBackend } from "./setup/backend-probe.js";
import { diagnoseOpenClaw } from "./setup/openclaw-config.js";
import type { OpenClawMode } from "./setup/openclaw-config.js";
import {
  bootstrapPythonRuntime,
  commandAvailable,
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
import { executeUpdate } from "./tools/runtime-config.js";

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
    const mode = optionValue("--mode") ?? (clientName === "openclaw" ? "cli" : undefined);

    // OpenClaw MCP mode: warn about global config mutation and require confirmation
    if (clientName === "openclaw" && mode === "mcp" && !hasFlag("--non-interactive")) {
      const rl = createInterface({ input, output });
      try {
        console.log("");
        console.log("WARNING: --mode mcp will modify the global OpenClaw config at");
        console.log("  ~/.openclaw/openclaw.json");
        console.log("This adds the arena MCP server to the ACP/acpx plugin.");
        console.log("API keys are NOT stored in this config.");
        console.log("");
        const answer = (await rl.question("Continue? [y/N] ")).trim().toLowerCase();
        if (answer !== "y" && answer !== "yes") {
          console.log("Aborted.");
          return;
        }
      } finally {
        rl.close();
      }
    }

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

    const configPath = setupFn(root, mode ? { mode } : undefined);

    // Save openclawMode to ArenaHomeState if applicable
    if (clientName === "openclaw" && mode) {
      const existingState = readArenaHomeState(root);
      if (existingState) {
        existingState.openclawMode = mode as OpenClawMode;
        writeArenaHomeState(root, existingState);
      }
    }

    console.log(`\nConfigured ${clientName} at: ${configPath}`);
    console.log(`Arena home: ${root}`);

    if (clientName === "openclaw") {
      if (mode === "mcp") {
        console.log("\nOpenClaw ACP/acpx plugin configured with arena MCP server.");
        console.log("The arena.* tools are now available in OpenClaw sessions.");
      } else {
        console.log("\nOpenClaw workspace and agent registered.");
        console.log("Use: openclaw agent --local --agent arena-trader");
        console.log("To also wire arena MCP tools into OpenClaw, re-run with --mode mcp.");
      }
    } else {
      console.log("\nTools available (29 total):");
      console.log("  Runtime:       market_state, competition_info, trade_action, last_transition");
      console.log("  Market:        symbols, orderbook, klines, market_info");
      console.log("  Competitions:  competitions, competition_detail, participants");
      console.log("  Registration:  register, withdraw, my_registration");
      console.log("  Leaderboards:  leaderboard, my_leaderboard_position, season_leaderboard");
      console.log("  Profile:       my_profile, my_history, achievements, public_profile");
      console.log("  Social:        chat_send, chat_history");
      console.log("  Notifications: notifications, unread_count, mark_read");
      console.log("  System:        health, runtime_start, runtime_stop");
    }
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

  if (command === "auto") {
    const code = await runAutoTrade();
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

  if (command === "debug-env") {
    runDebugEnv();
    return;
  }

  if (command === "dashboard") {
    await runDashboard();
    return;
  }

  if (command === "competitions") {
    await runCompetitions();
    return;
  }

  if (command === "register") {
    await runRegister();
    return;
  }

  if (command === "leaderboard") {
    await runLeaderboard();
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
  if (agent === "openclaw") {
    console.log("Provisioning dedicated OpenClaw trading agent...");
    ensureOpenClawTradingAgent(home);
  }

  // Auto-wire MCP tools for the chosen agent backend
  const wired = autoWireMcpForAgent(home, agent, availableCliBackends);
  if (wired.length > 0) {
    console.log("\nMCP tools auto-wired:");
    for (const entry of wired) {
      console.log(`  ${entry.backend}: ${entry.configPath}`);
    }
  }

  // Register for a competition
  const registeredCompetition = await initCompetitionRegistration(home, hasFlag("--non-interactive"), optionValue("--competition"));

  console.log("\nArena agent is ready.");
  console.log(`Home:          ${home}`);
  console.log(`API key file:  ${envFilePath(home)}`);
  console.log(`Config dir:    ${configDirPath(home)}`);
  console.log(`Artifacts dir: ${artifactsDirPath(home)}`);
  if (registeredCompetition) {
    console.log(`Competition:   #${registeredCompetition} (registered)`);
  }
  console.log("\nNext steps:");
  console.log(`  arena-agent doctor --home ${home}`);
  console.log(`  arena-agent up --home ${home}${registeredCompetition ? "" : "  # register for a competition first"}`);
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
    const backendProbe = probeBackend(state.defaultAgent);
    console.log(`Backend CLI:   ${backendProbe.summary}`);
    if (!backendProbe.ready) {
      errors.push(backendProbe.details);
    }
  } else if (isManagedArenaHome(home)) {
    errors.push(`Arena home marker exists but is invalid: ${home}`);
  } else {
    errors.push(`Arena home is not initialized. Run: arena-agent init --home ${home}`);
  }

  // OpenClaw-specific diagnostics
  if (
    state?.defaultAgent === "openclaw" ||
    (!state && commandAvailable("openclaw"))
  ) {
    const ocDiag = diagnoseOpenClaw(home, state ?? null);
    for (const line of ocDiag.display) {
      console.log(line);
    }
    errors.push(...ocDiag.errors);
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
  if (agent === "openclaw") {
    ensureOpenClawTradingAgent(home);
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

async function runAutoTrade(): Promise<number> {
  const home = resolveConfiguredHome(optionValue("--home"));
  const state = readArenaHomeState(home);
  if (!state) {
    throw new Error(`Arena home is not initialized at ${home}. Run \`arena-agent init\` first.`);
  }

  const agent = (optionValue("--agent") ?? state.defaultAgent) as ManagedAgent;
  const model = optionValue("--model") ?? state.defaultModel ?? undefined;
  const pollMinutes = Number(optionValue("--poll") ?? "5");
  const noSetup = hasFlag("--no-setup");
  const python = findPython(home);
  const env = buildChildEnv(home);

  console.log("Arena auto-trade daemon starting.");
  console.log(`Agent: ${agent} | Mode: ${state.liveTrading ? "LIVE" : "dry-run"} | Poll: ${pollMinutes}m | Setup: ${noSetup ? "off" : "on"}`);

  // Catch SIGTERM/SIGINT for graceful shutdown
  let shutdownRequested = false;
  const onShutdown = () => { shutdownRequested = true; };
  process.once("SIGINT", onShutdown);
  process.once("SIGTERM", onShutdown);

  const bridge = new PythonBridge(home);

  try {
    while (!shutdownRequested) {
      // 1. Find a competition to trade in
      const competition = await autoFindCompetition(bridge);
      if (!competition) {
        console.log("No competition available. Retrying in 5 minutes...");
        await interruptableSleep(300_000, () => shutdownRequested);
        continue;
      }

      console.log(`\nTrading competition #${competition.id}: ${competition.title} [${competition.status}]`);

      // 2. Register if needed
      if (competition.status === "registration_open") {
        try {
          await bridge.callTool("varsity.register", { competition_id: competition.id });
          console.log(`Registered for #${competition.id}.`);
        } catch {
          console.log(`Registration failed for #${competition.id}, may already be registered.`);
        }
      }

      // 3. Wait for competition to go live
      while (!shutdownRequested && competition.status !== "live") {
        const detail = (await bridge.callTool("varsity.competition_detail", {
          identifier: String(competition.id),
        })) as any;
        competition.status = detail?.status ?? competition.status;
        if (competition.status === "live") break;
        if (competition.status === "cancelled" || competition.status === "completed") {
          console.log(`Competition #${competition.id} is ${competition.status}. Moving on.`);
          break;
        }
        console.log(`Competition #${competition.id} status: ${competition.status}. Waiting...`);
        await interruptableSleep(30_000, () => shutdownRequested);
      }
      if (shutdownRequested || competition.status !== "live") continue;

      // 4. Run setup agent for initial config (before runtime start)
      const configPath = resolveUserConfigPath(home, state, optionValue("--config"), agent);
      let setupAdjustments = 0;

      if (!noSetup) {
        try {
          console.log("Running setup agent for initial configuration...");
          const setupDecision = (await bridge.callTool("varsity.setup_decide", {
            competition_id: competition.id,
            backend: agent,
            model: model ?? null,
            config_path: configPath,
          })) as any;

          if (setupDecision?.action === "update" && setupDecision.overrides) {
            executeUpdate({ overrides: setupDecision.overrides, config: configPath, agent }, home);
            setupAdjustments++;
            console.log(`Setup agent: ${setupDecision.reason}`);
          } else {
            console.log(`Setup agent: hold — ${setupDecision?.reason ?? "no changes needed"}`);
          }
        } catch (err) {
          console.log(`Setup agent error (non-fatal): ${err instanceof Error ? err.message : err}`);
        }
      }

      // 5. Start runtime
      const runtimeArgs = [
        "-m", "arena_agent", "run",
        "--agent", agent,
        "--config", configPath,
        "--competition-id", String(competition.id),
      ];
      if (model) runtimeArgs.push("--model", model);

      const logPath = resolve(logsDirPath(home), `auto-${competition.id}-${Date.now()}.log`);
      const logFd = openSync(logPath, "a");
      let runtimeChild = spawn(python, runtimeArgs, { cwd: home, env, stdio: ["ignore", logFd, logFd] });
      closeSync(logFd);

      if (runtimeChild.pid) {
        writeRuntimeState(home, {
          pid: runtimeChild.pid,
          agent,
          configPath,
          logPath,
          startedAt: new Date().toISOString(),
          monitorPort: state.monitorPort,
        });
      }
      console.log(`Runtime started (pid ${runtimeChild.pid}). Logs: ${logPath}`);

      // 6. Monitor loop — poll until competition ends or shutdown
      let runtimeExited = false;
      runtimeChild.once("exit", () => { runtimeExited = true; });

      while (!shutdownRequested && !runtimeExited) {
        await interruptableSleep(pollMinutes * 60_000, () => shutdownRequested || runtimeExited);
        if (shutdownRequested || runtimeExited) break;

        try {
          const status = (await bridge.callTool("varsity.competition_detail", {
            identifier: String(competition.id),
          })) as any;
          const isLive = status?.status === "live";
          if (!isLive) {
            console.log(`Competition #${competition.id} ended (${status?.status}).`);
            break;
          }

          // Check performance
          const account = (await bridge.callTool("varsity.live_account", {
            competition_id: competition.id,
          })) as any;
          if (account?.capital) {
            const pnl = (account.capital - (account.initialBalance ?? 5000)).toFixed(2);
            console.log(
              `  #${competition.id} | equity: $${account.capital.toFixed(2)} | PnL: $${pnl} | trades: ${account.tradesCount ?? "?"}`,
            );
          }

          // Run setup agent for mid-competition adjustment
          if (!noSetup) {
            try {
              const adjustDecision = (await bridge.callTool("varsity.setup_decide", {
                competition_id: competition.id,
                backend: agent,
                model: model ?? null,
                config_path: configPath,
              })) as any;

              if (adjustDecision?.action === "update" && adjustDecision.overrides) {
                executeUpdate({ overrides: adjustDecision.overrides, config: configPath, agent }, home);
                setupAdjustments++;
                console.log(`  Setup agent adjustment: ${adjustDecision.reason}`);

                if (adjustDecision.restart_runtime && !runtimeExited) {
                  console.log("  Restarting runtime for config changes...");
                  runtimeChild.kill("SIGTERM");
                  await Promise.race([waitForExit(runtimeChild), sleep(5000)]);
                  if (!runtimeChild.killed) runtimeChild.kill("SIGKILL");

                  // Respawn runtime with updated config
                  const newLogFd = openSync(logPath, "a");
                  runtimeExited = false;
                  runtimeChild = spawn(python, runtimeArgs, { cwd: home, env, stdio: ["ignore", newLogFd, newLogFd] });
                  closeSync(newLogFd);
                  runtimeChild.once("exit", () => { runtimeExited = true; });
                  if (runtimeChild.pid) {
                    writeRuntimeState(home, {
                      pid: runtimeChild.pid,
                      agent,
                      configPath,
                      logPath,
                      startedAt: new Date().toISOString(),
                      monitorPort: state.monitorPort,
                    });
                  }
                  console.log(`  Runtime restarted (pid ${runtimeChild.pid}).`);
                }
              }
            } catch {
              // Non-fatal — setup agent errors don't stop trading
            }
          }
        } catch (err) {
          // Non-fatal — keep going
        }
      }

      // 7. Cleanup: close position, stop runtime
      console.log(`Stopping runtime for #${competition.id}...`);
      try {
        const pos = (await bridge.callTool("varsity.live_position", {
          competition_id: competition.id,
        })) as any;
        if (pos && pos.direction) {
          console.log(`Closing open ${pos.direction} position (size=${pos.size})...`);
          await bridge.callTool("varsity.trade_close", {
            competition_id: competition.id,
          });
          console.log("Position closed.");
        }
      } catch {
        // Best effort
      }

      if (!runtimeChild.killed && !runtimeExited) {
        runtimeChild.kill("SIGTERM");
        await Promise.race([waitForExit(runtimeChild), sleep(5000)]);
        if (!runtimeChild.killed) runtimeChild.kill("SIGKILL");
      }
      clearRuntimeState(home);

      // 8. Record results in setup memory
      try {
        const result = (await bridge.callTool("varsity.live_account", {
          competition_id: competition.id,
        })) as any;
        if (result?.capital) {
          const pnl = (result.capital - (result.initialBalance ?? 5000)).toFixed(2);
          console.log(`Competition #${competition.id} final: equity=$${result.capital.toFixed(2)}, PnL=$${pnl}`);
        }

        // Save to setup memory for future competitions
        if (!noSetup) {
          try {
            await bridge.callTool("varsity.setup_record", {
              competition_id: competition.id,
              title: competition.title,
              strategy_summary: `agent=${agent}, adjustments=${setupAdjustments}`,
              adjustments_made: setupAdjustments,
            });
            console.log("Competition result saved to setup memory.");
          } catch {
            // Non-fatal
          }
        }
      } catch {}

      if (shutdownRequested) break;
      console.log("Looking for next competition...");
    }
  } finally {
    await bridge.disconnect();
  }

  console.log("Auto-trade daemon stopped.");
  return 0;
}

async function autoFindCompetition(
  bridge: PythonBridge
): Promise<{ id: number; title: string; status: string } | null> {
  // Check if already registered for a live or upcoming competition
  try {
    const regs = (await bridge.callTool("varsity.my_registrations", {})) as any;
    const items = Array.isArray(regs) ? regs : regs?.items ?? regs?.list ?? [];
    for (const reg of items) {
      if (reg.competitionStatus === "live" || reg.competitionStatus === "registration_closed") {
        return { id: reg.competitionId, title: reg.competitionTitle, status: reg.competitionStatus };
      }
    }
  } catch {}

  // Find open competitions
  try {
    const comps = (await bridge.callTool("varsity.competitions", {
      status: "registration_open", page: 1, size: 5,
    })) as any;
    const items = comps?.items ?? comps?.list ?? (Array.isArray(comps) ? comps : []);
    const best = items.find((c: any) => c.allowApiWrite !== false) ?? items[0];
    if (best) {
      return { id: best.id, title: best.title ?? best.name, status: best.status };
    }
  } catch {}

  // Check live competitions we might be in
  try {
    const live = (await bridge.callTool("varsity.competitions", {
      status: "live", page: 1, size: 5,
    })) as any;
    const items = live?.items ?? live?.list ?? (Array.isArray(live) ? live : []);
    for (const c of items) {
      if (c.allowApiWrite !== false) {
        return { id: c.id, title: c.title ?? c.name, status: c.status };
      }
    }
  } catch {}

  return null;
}

async function interruptableSleep(ms: number, shouldStop: () => boolean): Promise<void> {
  const interval = 2000;
  let remaining = ms;
  while (remaining > 0 && !shouldStop()) {
    await sleep(Math.min(remaining, interval));
    remaining -= interval;
  }
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
  return probeBackend(agent).summary;
}

function validateAgentAvailability(
  agent: ManagedAgent,
  availableCliBackends: ManagedAgent[]
): void {
  if (agent === "rule") {
    return;
  }
  if (agent === "auto" && availableCliBackends.length > 0) {
    const autoProbe = probeBackend("auto");
    if (!autoProbe.ready) {
      throw new Error(autoProbe.details);
    }
    return;
  }
  if (agent === "auto") {
    throw new Error(
      "No CLI backend found in PATH for auto mode. Install claude, gemini, openclaw, or codex, or use --agent rule."
    );
  }
  const probe = probeBackend(agent);
  if (!probe.available || !probe.ready) {
    throw new Error(probe.details);
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
  console.log("  setup --client <name>    Configure an MCP client (claude-code, claude-desktop, cursor, openclaw)");
  console.log("  check                    Validate Python environment");
  console.log("  init                     Bootstrap a managed Arena home");
  console.log("  doctor                   Check managed home, Python, deps, and backend CLI");
  console.log("  up                       Start trading runtime and open the TUI monitor");
  console.log("  auto                     Autonomous daemon: find, join, trade, repeat (LLM setup agent configures strategy)");
  console.log("  monitor                  Attach to the TUI monitor only");
  console.log("  upgrade                  Reinstall or refresh the managed Python runtime");
  console.log("  status                   Show runtime pid, config, and monitor port");
  console.log("  down                     Stop the background runtime");
  console.log("  logs                     Print recent runtime logs");
  console.log("  dashboard                Open web dashboard (kline, equity, AI reasoning). Use -d to daemonize.");
  console.log("  competitions             List active competitions");
  console.log("  register <id>            Register for a competition");
  console.log("  leaderboard <id>         View competition leaderboard");
  console.log("  debug-env                Show environment diagnostics (API key, paths)");
  console.log("");
  console.log("Examples:");
  console.log("  arena-agent init");
  console.log("  arena-agent init --agent openclaw --mode dry-run");
  console.log("  arena-agent init --competition 7              # register during init");
  console.log("  arena-agent up --agent gemini");
  console.log("  arena-agent up --no-monitor --daemon");
  console.log("  arena-agent upgrade");
  console.log("  arena-mcp setup --client claude-code");
  console.log("  arena-mcp setup --client gemini");
  console.log("  arena-mcp setup --client codex");
  console.log("  arena-agent setup --client openclaw --mode cli");
  console.log("  arena-agent setup --client openclaw --mode mcp");
  console.log("  arena-agent dashboard --competition 5 -d");
  console.log("  arena-agent competitions --status live");
  console.log("  arena-agent register 5");
  console.log("  arena-agent leaderboard 5");
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
  if (state.defaultAgent === "openclaw") {
    ensureOpenClawTradingAgent(home);
  }
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

async function initCompetitionRegistration(
  home: string,
  nonInteractive: boolean,
  explicitId?: string
): Promise<number | null> {
  const bridge = new PythonBridge(home);
  try {
    // If explicit --competition flag, register directly
    if (explicitId) {
      const id = Number(explicitId);
      if (isNaN(id)) throw new Error(`Invalid competition ID: ${explicitId}`);
      const result = (await bridge.callTool("varsity.register", {
        competition_id: id,
      })) as any;
      if (result?.error || result?.code) {
        console.log(`\nRegistration for competition #${id}: ${result?.message ?? result?.error ?? "failed"}`);
        return null;
      }
      console.log(`\nRegistered for competition #${id}.`);
      return id;
    }

    // Fetch open competitions
    const comps = (await bridge.callTool("varsity.competitions", {
      status: "registration_open",
      page: 1,
      size: 10,
    })) as any;
    const items: any[] = comps?.items ?? comps?.list ?? (Array.isArray(comps) ? comps : []);

    // Also check live competitions (already joinable ones we might be registered for)
    const live = (await bridge.callTool("varsity.competitions", {
      status: "live",
      page: 1,
      size: 10,
    })) as any;
    const liveItems: any[] = live?.items ?? live?.list ?? (Array.isArray(live) ? live : []);

    if (items.length === 0 && liveItems.length === 0) {
      console.log("\nNo competitions available for registration right now.");
      return null;
    }

    console.log("\nAvailable competitions:");
    const allItems = [...items, ...liveItems];
    for (const c of allItems) {
      const id = c.id ?? c.competitionId ?? "?";
      const name = c.name ?? c.title ?? "Unnamed";
      const st = c.status ?? "unknown";
      const apiWrite = c.allowApiWrite !== false ? "yes" : "no";
      console.log(`  #${id}  ${name}  [${st}]  API write: ${apiWrite}`);
    }

    if (nonInteractive) {
      // Auto-join the best open competition
      if (items.length > 0) {
        const best = items.find((c: any) => c.allowApiWrite !== false) ?? items[0];
        const id = best.id ?? best.competitionId;
        const result = (await bridge.callTool("varsity.register", {
          competition_id: id,
        })) as any;
        if (result?.error || result?.code) {
          console.log(`Auto-registration for #${id}: ${result?.message ?? result?.error ?? "failed"}`);
          return null;
        }
        console.log(`Auto-registered for competition #${id}.`);
        return id;
      }
      return null;
    }

    // Interactive: let user pick
    if (items.length > 0) {
      const rl = createInterface({ input, output });
      try {
        const answer = (
          await rl.question(
            `\nEnter competition ID to register (or press Enter to skip): `
          )
        ).trim();
        if (!answer) return null;
        const id = Number(answer);
        if (isNaN(id)) {
          console.log("Skipping registration.");
          return null;
        }
        const result = (await bridge.callTool("varsity.register", {
          competition_id: id,
        })) as any;
        if (result?.error || result?.code) {
          console.log(`Registration failed: ${result?.message ?? result?.error}`);
          return null;
        }
        console.log(`Registered for competition #${id}.`);
        return id;
      } finally {
        rl.close();
      }
    }

    return null;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.log(`\nCompetition registration skipped: ${msg}`);
    return null;
  } finally {
    await bridge.disconnect();
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

function runDebugEnv(): void {
  const home = process.env.HOME ?? "(unset)";
  const arenaRoot = process.env.ARENA_ROOT ?? "(unset)";
  const arenaHome = process.env.ARENA_HOME ?? "(unset)";
  const apiKey = process.env.VARSITY_API_KEY ?? "(unset)";
  const cwd = process.cwd();
  const managedHome = defaultArenaHome();
  const managedExists = existsSync(managedHome);
  const managedEnv = existsSync(resolve(managedHome, ".env.runtime.local"));

  console.log("Arena Agent Environment Diagnostics\n");
  console.log(`HOME:              ${home}`);
  console.log(`CWD:               ${cwd}`);
  console.log(`ARENA_ROOT:        ${arenaRoot}`);
  console.log(`ARENA_HOME:        ${arenaHome}`);
  console.log(`VARSITY_API_KEY:   ${apiKey === "(unset)" ? "(unset)" : apiKey.slice(0, 12) + "..."}`);
  console.log("");
  console.log(`Managed home:      ${managedHome}`);
  console.log(`  Exists:          ${managedExists ? "yes" : "no"}`);
  console.log(`  .env file:       ${managedEnv ? "yes" : "no"}`);

  if (managedEnv) {
    const envContent = loadEnvFile(managedHome);
    const storedKey = envContent.VARSITY_API_KEY;
    console.log(`  Stored API key:  ${storedKey ? storedKey.slice(0, 12) + "..." : "(empty)"}`);
  }

  console.log("");
  try {
    const root = findArenaRoot();
    console.log(`Resolved root:     ${root}`);
    const rootEnv = loadEnvFile(root);
    const rootKey = rootEnv.VARSITY_API_KEY;
    console.log(`  .env API key:    ${rootKey ? rootKey.slice(0, 12) + "..." : "(empty or missing)"}`);

    const python = findPython(root);
    console.log(`  Python:          ${python}`);
  } catch (err) {
    console.log(`Resolved root:     FAILED — ${err instanceof Error ? err.message : err}`);
  }

  console.log("");
  console.log("If the API key shows (unset) and no stored key exists,");
  console.log("run: arena-agent init");
}

async function runDashboard(): Promise<void> {
  const home = resolveConfiguredHome(optionValue("--home"));
  const port = Number(optionValue("--port") ?? "3000");
  const competitionId = optionValue("--competition")
    ? Number(optionValue("--competition"))
    : undefined;

  // Find transitions file from artifacts dir
  let transitionsPath = optionValue("--transitions") ?? undefined;
  if (!transitionsPath) {
    const artifactsDir = resolve(home, "artifacts");
    if (existsSync(artifactsDir)) {
      transitionsPath = artifactsDir;
    }
  }

  const daemon = hasFlag("--daemon") || hasFlag("-d");

  if (daemon) {
    // Spawn dashboard as a detached background process
    const args = process.argv.slice(1).filter(a => a !== "--daemon" && a !== "-d");
    const child = spawn(process.execPath, args, {
      cwd: process.cwd(),
      env: process.env,
      stdio: "ignore",
      detached: true,
    });
    child.unref();
    const url = `http://localhost:${port}`;
    console.log(`Dashboard running in background (pid ${child.pid ?? "?"}).`);
    console.log(`Open ${url} in your browser.`);
    if (competitionId) console.log(`Competition: ${competitionId}`);

    // Try to open browser
    try {
      const openCmd = process.platform === "darwin"
        ? `open "${url}"`
        : process.platform === "win32"
          ? `start "${url}"`
          : `xdg-open "${url}" 2>/dev/null || true`;
      spawn("sh", ["-c", openCmd], { stdio: "ignore", detached: true }).unref();
    } catch {}
    return;
  }

  // Foreground mode — start server and keep running
  startDashboard({
    arenaRoot: home,
    port,
    competitionId,
    transitionsPath,
  });

  // Try to open browser
  const url = `http://localhost:${port}`;
  try {
    const openCmd = process.platform === "darwin"
      ? `open "${url}"`
      : process.platform === "win32"
        ? `start "${url}"`
        : `xdg-open "${url}" 2>/dev/null || true`;
    spawn("sh", ["-c", openCmd], { stdio: "ignore", detached: true }).unref();
  } catch {}
}

async function runCompetitions(): Promise<void> {
  const home = resolveConfiguredHome(optionValue("--home"));
  const bridge = new PythonBridge(home);
  try {
    const status = optionValue("--status") ?? undefined;
    const args: Record<string, unknown> = { page: 1, size: 20 };
    if (status) args.status = status;
    const result = await bridge.callTool("varsity.competitions", args) as any;
    if (result?.error) {
      console.error(`Error: ${result.error}`);
      process.exit(1);
    }
    const items = result?.items ?? result?.list ?? result;
    if (!Array.isArray(items) || items.length === 0) {
      console.log("No competitions found.");
      return;
    }
    console.log("Competitions:\n");
    for (const c of items) {
      const id = c.id ?? c.competitionId ?? "?";
      const name = c.name ?? c.title ?? "Unnamed";
      const st = c.status ?? "unknown";
      const type = c.type ?? c.competitionType ?? "";
      console.log(`  #${id}  ${name}`);
      console.log(`        Status: ${st}  Type: ${type}`);
      console.log("");
    }
  } finally {
    await bridge.disconnect();
  }
}

async function runRegister(): Promise<void> {
  const home = resolveConfiguredHome(optionValue("--home"));
  const idArg = argv[1];
  if (!idArg || isNaN(Number(idArg))) {
    console.error("Usage: arena-agent register <competition_id>");
    process.exit(1);
  }
  const bridge = new PythonBridge(home);
  try {
    const result = await bridge.callTool("varsity.register", {
      competition_id: Number(idArg),
    }) as any;
    if (result?.error) {
      console.error(`Error: ${result.error ?? result.message}`);
      process.exit(1);
    }
    console.log(`Registered for competition ${idArg}.`);
    if (result?.status) {
      console.log(`Status: ${result.status}`);
    }
  } finally {
    await bridge.disconnect();
  }
}

async function runLeaderboard(): Promise<void> {
  const home = resolveConfiguredHome(optionValue("--home"));
  const idArg = argv[1];
  if (!idArg) {
    console.error("Usage: arena-agent leaderboard <competition_id>");
    process.exit(1);
  }
  const bridge = new PythonBridge(home);
  try {
    const result = await bridge.callTool("varsity.leaderboard", {
      identifier: idArg,
      page: 1,
      size: 20,
    }) as any;
    if (result?.error) {
      console.error(`Error: ${result.error ?? result.message}`);
      process.exit(1);
    }
    const items = result?.items ?? result?.list ?? result;
    if (!Array.isArray(items) || items.length === 0) {
      console.log("No leaderboard data.");
      return;
    }
    console.log(`Leaderboard for competition ${idArg}:\n`);
    console.log("  Rank  Username             PnL");
    console.log("  ----  -------------------  ----------");
    for (const entry of items) {
      const rank = String(entry.rank ?? entry.position ?? "?").padStart(4);
      const user = (entry.username ?? entry.displayName ?? "unknown").padEnd(19);
      const pnl = entry.pnl ?? entry.totalPnl ?? entry.returnPct ?? "?";
      console.log(`  ${rank}  ${user}  ${pnl}`);
    }
  } finally {
    await bridge.disconnect();
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
