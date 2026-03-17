import { writeFileSync, readFileSync, existsSync, mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { homedir } from "node:os";
import { ensureOpenClawTradingAgent } from "./openclaw-agent.js";
import {
  mergeArenaMcpServer,
  readOpenClawGlobalConfig,
  writeOpenClawGlobalConfig,
  openclawGlobalConfigPath,
} from "./openclaw-config.js";

interface McpServerEntry {
  type?: string;
  command: string;
  args: string[];
  env?: Record<string, string>;
}

function mergeConfig(
  path: string,
  serverName: string,
  entry: McpServerEntry
): void {
  let existing: Record<string, unknown> = {};
  if (existsSync(path)) {
    try {
      existing = JSON.parse(readFileSync(path, "utf-8"));
    } catch {
      // Overwrite invalid JSON
    }
  }
  const servers =
    (existing.mcpServers as Record<string, unknown>) ?? {};
  servers[serverName] = entry;
  existing.mcpServers = servers;

  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(existing, null, 2) + "\n");
}

export function setupClaudeCode(arenaRoot: string): string {
  const configPath = resolve(arenaRoot, ".mcp.json");
  mergeConfig(configPath, "arena", {
    type: "stdio",
    command: "arena-mcp",
    args: ["serve"],
    env: { ARENA_ROOT: arenaRoot },
  });
  return configPath;
}

export function setupClaudeDesktop(arenaRoot: string): string {
  const platform = process.platform;
  let configDir: string;
  if (platform === "darwin") {
    configDir = resolve(
      homedir(),
      "Library",
      "Application Support",
      "Claude"
    );
  } else {
    configDir = resolve(homedir(), ".config", "Claude");
  }
  const configPath = resolve(configDir, "claude_desktop_config.json");
  mergeConfig(configPath, "arena", {
    command: "arena-mcp",
    args: ["serve"],
    env: { ARENA_ROOT: arenaRoot },
  });
  return configPath;
}

export function setupCursor(arenaRoot: string): string {
  const configPath = resolve(arenaRoot, ".cursor", "mcp.json");
  mergeConfig(configPath, "arena", {
    command: "arena-mcp",
    args: ["serve"],
    env: { ARENA_ROOT: arenaRoot },
  });
  return configPath;
}

export function setupOpenClaw(
  arenaRoot: string,
  options?: { mode?: string }
): string {
  const mode = options?.mode ?? "cli";

  ensureOpenClawTradingAgent(arenaRoot);

  if (mode === "mcp") {
    const existing = readOpenClawGlobalConfig();
    const merged = mergeArenaMcpServer(existing, arenaRoot);
    writeOpenClawGlobalConfig(merged);
    return openclawGlobalConfigPath();
  }

  return resolve(arenaRoot, "openclaw", "arena-trader");
}

export const CLIENT_SETUP: Record<
  string,
  (root: string, options?: { mode?: string }) => string
> = {
  "claude-code": setupClaudeCode,
  "claude-desktop": setupClaudeDesktop,
  cursor: setupCursor,
  openclaw: setupOpenClaw,
};
