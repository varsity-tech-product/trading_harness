import { z } from "zod";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve, isAbsolute } from "node:path";
import { findPython } from "../util/paths.js";
import { buildChildEnv } from "../util/env.js";
import { isManagedArenaHome, readArenaHomeState } from "../util/home.js";

export const name = "arena.runtime_start";
export const description =
  "Start the autonomous trading agent runtime in the background.";

export const inputSchema = z.object({
  config: z
    .string()
    .optional()
    .describe("Path to runtime YAML config."),
  agent: z
    .enum(["config", "rule", "claude", "gemini", "openclaw", "codex", "auto", "tap"])
    .optional()
    .default("auto")
    .describe("Agent type."),
  model: z.string().optional().describe("Model override (e.g. sonnet)."),
  iterations: z
    .number()
    .optional()
    .describe("Max iterations. Omit for unlimited."),
});

let runtimeProcess: ChildProcess | null = null;

export function execute(
  args: z.infer<typeof inputSchema>,
  arenaRoot: string
): { pid: number | null; status: string; config: string; agent: string } {
  const configPath = resolveConfigPath(arenaRoot, args.config, args.agent);
  if (runtimeProcess && !runtimeProcess.killed) {
    return {
      pid: runtimeProcess.pid ?? null,
      status: "already_running",
      config: configPath,
      agent: args.agent,
    };
  }

  const python = findPython(arenaRoot);
  const env = buildChildEnv(arenaRoot);

  const cmdArgs = [
    "-m",
    "arena_agent",
    "run",
    "--agent",
    args.agent,
    "--config",
    configPath,
  ];
  if (args.model) cmdArgs.push("--model", args.model);
  if (args.iterations !== undefined)
    cmdArgs.push("--iterations", String(args.iterations));

  runtimeProcess = spawn(python, cmdArgs, {
    cwd: arenaRoot,
    env,
    stdio: "ignore",
    detached: true,
  });
  runtimeProcess.unref();

  const pid = runtimeProcess.pid ?? null;

  runtimeProcess.on("exit", () => {
    runtimeProcess = null;
  });

  return { pid, status: "started", config: configPath, agent: args.agent };
}

export function stop(): { status: string; pid: number | null } {
  if (!runtimeProcess || runtimeProcess.killed) {
    runtimeProcess = null;
    return { status: "not_running", pid: null };
  }
  const pid = runtimeProcess.pid ?? null;
  runtimeProcess.kill("SIGTERM");
  runtimeProcess = null;
  return { status: "stopped", pid };
}

function resolveConfigPath(
  arenaRoot: string,
  rawConfig: string | undefined,
  agent: string
): string {
  const candidates: string[] = [];
  if (rawConfig) {
    if (isAbsolute(rawConfig)) {
      return rawConfig;
    }
    candidates.push(resolve(arenaRoot, rawConfig));
    candidates.push(resolve(arenaRoot, "arena_agent", "config", rawConfig));
  } else if (isManagedArenaHome(arenaRoot)) {
    const state = readArenaHomeState(arenaRoot);
    if (agent === "rule" || agent === "config") {
      candidates.push(
        state?.profiles.rule ?? resolve(arenaRoot, "config", "rule.yaml")
      );
    } else {
      candidates.push(
        state?.profiles.agentExec ??
          resolve(arenaRoot, "config", "agent_exec.yaml")
      );
    }
  } else if (agent === "rule" || agent === "config") {
    candidates.push(resolve(arenaRoot, "arena_agent", "config", "agent_config.yaml"));
  } else {
    candidates.push(resolve(arenaRoot, "arena_agent", "config", "codex_agent_config.yaml"));
  }

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return candidates[0];
}
