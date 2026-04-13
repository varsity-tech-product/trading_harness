import { writeFileSync, readFileSync, existsSync, mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { homedir } from "node:os";
import {
  ensureOpenClawTradingAgent,
  openclawMcpInstructions,
} from "./openclaw-agent.js";
import type { ManagedAgent } from "../util/home.js";

interface McpServerEntry {
  type?: string;
  command: string;
  args: string[];
  env?: Record<string, string>;
}

export interface ClientSetupOptions {
  mode?: string;
  baseUrl?: string;
}

// ── Shared MCP server snippet ────────────────────────────────────────

function arenaServerEnv(
  arenaRoot: string,
  baseUrl?: string
): Record<string, string> {
  const env: Record<string, string> = { ARENA_ROOT: arenaRoot };
  if (baseUrl) {
    env.VARSITY_BASE_URL = baseUrl;
  }
  return env;
}

function tomlEscape(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function arenaServerJson(
  arenaRoot: string,
  baseUrl?: string,
  includeType = false
): string {
  const entry: Record<string, unknown> = {
    command: "arena-mcp",
    args: ["serve"],
    env: arenaServerEnv(arenaRoot, baseUrl),
  };
  if (includeType) entry.type = "stdio";
  return JSON.stringify(entry, null, 4);
}

function arenaServerToml(arenaRoot: string, baseUrl?: string): string {
  const lines = [
    "[mcp_servers.arena]",
    'command = "arena-mcp"',
    'args = ["serve"]',
    "",
    "[mcp_servers.arena.env]",
    `ARENA_ROOT = "${tomlEscape(arenaRoot)}"`,
  ];
  if (baseUrl) {
    lines.push(`VARSITY_BASE_URL = "${tomlEscape(baseUrl)}"`);
  }
  return lines.join("\n");
}

// ── Project-local .mcp.json (safe — inside the arena project dir) ────

export function setupClaudeCode(
  arenaRoot: string,
  options?: ClientSetupOptions
): string {
  const configPath = resolve(arenaRoot, ".mcp.json");
  mergeConfig(configPath, "arena", {
    type: "stdio",
    command: "arena-mcp",
    args: ["serve"],
    env: arenaServerEnv(arenaRoot, options?.baseUrl),
  });
  return configPath;
}

// ── Instructions generators (never modify user config) ───────────────

function claudeCodeInstructions(
  arenaRoot: string,
  baseUrl?: string
): string {
  return [
    "",
    "To add Arena MCP tools to Claude Code, add to ~/.claude.json:",
    "",
    '  "mcpServers": {',
    `    "arena": ${arenaServerJson(arenaRoot, baseUrl, true).split("\n").join("\n    ")}`,
    "  }",
    "",
    "Or run: claude mcp add arena -- arena-mcp serve",
  ].join("\n");
}

function claudeDesktopInstructions(
  arenaRoot: string,
  baseUrl?: string
): string {
  const platform = process.platform;
  const configPath =
    platform === "darwin"
      ? "~/Library/Application Support/Claude/claude_desktop_config.json"
      : "~/.config/Claude/claude_desktop_config.json";
  return [
    "",
    `To add Arena MCP tools to Claude Desktop, add to ${configPath}:`,
    "",
    '  "mcpServers": {',
    `    "arena": ${arenaServerJson(arenaRoot, baseUrl).split("\n").join("\n    ")}`,
    "  }",
  ].join("\n");
}

function geminiInstructions(arenaRoot: string, baseUrl?: string): string {
  return [
    "",
    "To add Arena MCP tools to Gemini CLI, add to ~/.gemini/settings.json:",
    "",
    '  "mcpServers": {',
    `    "arena": ${arenaServerJson(arenaRoot, baseUrl).split("\n").join("\n    ")}`,
    "  }",
  ].join("\n");
}

function codexInstructions(arenaRoot: string, baseUrl?: string): string {
  return [
    "",
    "To add Arena MCP tools to Codex CLI, add to ~/.codex/config.toml:",
    "",
    arenaServerToml(arenaRoot, baseUrl),
  ].join("\n");
}

function cursorInstructions(arenaRoot: string, baseUrl?: string): string {
  return [
    "",
    `To add Arena MCP tools to Cursor, add to ${arenaRoot}/.cursor/mcp.json:`,
    "",
    '  "mcpServers": {',
    `    "arena": ${arenaServerJson(arenaRoot, baseUrl).split("\n").join("\n    ")}`,
    "  }",
  ].join("\n");
}

// ── Setup functions (print instructions, never auto-modify) ──────────

export function setupClaudeCodeUser(
  arenaRoot: string,
  options?: ClientSetupOptions
): string {
  console.log(claudeCodeInstructions(arenaRoot, options?.baseUrl));
  return "(see instructions above)";
}

export function setupClaudeDesktop(
  arenaRoot: string,
  options?: ClientSetupOptions
): string {
  console.log(claudeDesktopInstructions(arenaRoot, options?.baseUrl));
  return "(see instructions above)";
}

export function setupCursor(
  arenaRoot: string,
  options?: ClientSetupOptions
): string {
  console.log(cursorInstructions(arenaRoot, options?.baseUrl));
  return "(see instructions above)";
}

export function setupGemini(
  arenaRoot: string,
  options?: ClientSetupOptions
): string {
  console.log(geminiInstructions(arenaRoot, options?.baseUrl));
  return "(see instructions above)";
}

export function setupCodex(
  arenaRoot: string,
  options?: ClientSetupOptions
): string {
  console.log(codexInstructions(arenaRoot, options?.baseUrl));
  return "(see instructions above)";
}

/**
 * Pure function: merge arena MCP server into Codex config.toml content.
 * Kept for tests and manual `arena-agent setup --apply` future use.
 */
export function mergeCodexToml(
  content: string,
  arenaRoot: string,
  options?: ClientSetupOptions
): string {
  const lines = content.split("\n");
  const filtered: string[] = [];
  let inArenaSection = false;

  for (const line of lines) {
    const trimmed = line.trim();
    if (/^\[/.test(trimmed)) {
      inArenaSection = /^\[mcp_servers\.arena(?:\..*)?\]$/.test(trimmed);
    }
    if (!inArenaSection) {
      filtered.push(line);
    }
  }

  // Trim trailing blank lines
  while (filtered.length > 0 && filtered[filtered.length - 1].trim() === "") {
    filtered.pop();
  }

  const base = filtered.length > 0 ? filtered.join("\n") + "\n" : "";
  const section = "\n" + arenaServerToml(arenaRoot, options?.baseUrl) + "\n";

  return base + section;
}

// ── OpenClaw ────────────────────────────────────────────────────────

export function setupOpenClaw(
  arenaRoot: string,
  options?: ClientSetupOptions
): string {
  // Verify openclaw is available — never modify user's global config or agents
  ensureOpenClawTradingAgent(arenaRoot);

  // Print instructions for optional MCP tools setup (user applies manually)
  console.log(openclawMcpInstructions(arenaRoot, options?.baseUrl));

  return "(no config modified — see instructions above)";
}

// ── Client setup registry ───────────────────────────────────────────

export const CLIENT_SETUP: Record<
  string,
  (root: string, options?: ClientSetupOptions) => string
> = {
  "claude-code": setupClaudeCode,
  "claude-desktop": setupClaudeDesktop,
  cursor: setupCursor,
  gemini: setupGemini,
  codex: setupCodex,
  openclaw: setupOpenClaw,
};

// ── Auto-wire: called during `arena-agent init` ─────────────────────

interface WiredEntry {
  backend: string;
  configPath: string;
}

export function autoWireMcpForAgent(
  home: string,
  agent: ManagedAgent,
  detectedBackends: ManagedAgent[],
  options?: ClientSetupOptions
): WiredEntry[] {
  const wired: WiredEntry[] = [];

  const wireOne = (label: string, fn: () => string): void => {
    try {
      const configPath = fn();
      wired.push({ backend: label, configPath });
    } catch {
      // Don't fail init if setup fails
    }
  };

  switch (agent) {
    case "claude":
      wireOne("Claude Code", () => setupClaudeCodeUser(home, options));
      break;
    case "gemini":
      wireOne("Gemini CLI", () => setupGemini(home, options));
      break;
    case "codex":
      wireOne("Codex CLI", () => setupCodex(home, options));
      break;
    case "openclaw":
      wireOne("OpenClaw", () => setupOpenClaw(home, options));
      break;
    case "auto":
      // Print instructions for all detected backends
      for (const b of detectedBackends) {
        wired.push(...autoWireMcpForAgent(home, b, [], options));
      }
      break;
    // "rule" → no MCP wiring needed
  }

  return wired;
}

// ── Internal helper (kept for project-local .mcp.json only) ──────────

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
