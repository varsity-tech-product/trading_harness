import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { resolve } from "node:path";
import type { ArenaHomeState } from "../util/home.js";

export type OpenClawMode = "cli" | "mcp";

const OPENCLAW_AGENT_ID = "arena-trader";

export interface AcpxMcpServerEntry {
  command: string;
  args: string[];
  env?: Record<string, string>;
}

export interface OpenClawGlobalConfig {
  acp?: {
    backend?: string;
    [key: string]: unknown;
  };
  plugins?: {
    entries?: {
      acpx?: {
        config?: {
          mcpServers?: Record<string, AcpxMcpServerEntry>;
          [key: string]: unknown;
        };
        [key: string]: unknown;
      };
      [key: string]: unknown;
    };
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export function openclawGlobalConfigPath(): string {
  return resolve(homedir(), ".openclaw", "openclaw.json");
}

export function readOpenClawGlobalConfig(): OpenClawGlobalConfig | null {
  const configPath = openclawGlobalConfigPath();
  if (!existsSync(configPath)) return null;
  try {
    return JSON.parse(readFileSync(configPath, "utf-8")) as OpenClawGlobalConfig;
  } catch {
    return null;
  }
}

export function writeOpenClawGlobalConfig(config: OpenClawGlobalConfig): void {
  const configPath = openclawGlobalConfigPath();
  mkdirSync(resolve(configPath, ".."), { recursive: true });
  writeFileSync(configPath, JSON.stringify(config, null, 2) + "\n", "utf-8");
}

/**
 * Pure function: merges arena MCP server entry into an OpenClaw global config.
 * Never includes VARSITY_API_KEY — only ARENA_ROOT.
 */
export function mergeArenaMcpServer(
  existing: OpenClawGlobalConfig | null,
  arenaRoot: string
): OpenClawGlobalConfig {
  const config: OpenClawGlobalConfig = existing ? structuredClone(existing) : {};

  // Ensure acp.backend = "acpx"
  if (!config.acp) config.acp = {};
  config.acp.backend = "acpx";

  // Ensure plugins.entries.acpx is enabled with mcpServers path
  if (!config.plugins) config.plugins = {};
  if (!config.plugins.entries) config.plugins.entries = {};
  if (!config.plugins.entries.acpx) config.plugins.entries.acpx = {};
  (config.plugins.entries.acpx as Record<string, unknown>).enabled = true;
  if (!config.plugins.entries.acpx.config) config.plugins.entries.acpx.config = {};
  if (!config.plugins.entries.acpx.config.mcpServers) {
    config.plugins.entries.acpx.config.mcpServers = {};
  }

  config.plugins.entries.acpx.config.mcpServers.arena = {
    command: "arena-mcp",
    args: ["serve"],
    env: { ARENA_ROOT: arenaRoot },
  };

  return config;
}

export function openclawWorkspaceValid(
  home: string,
  agentId: string = OPENCLAW_AGENT_ID
): { valid: boolean; issues: string[] } {
  const workspace = resolve(home, "openclaw", agentId);
  const issues: string[] = [];

  if (!existsSync(workspace)) {
    issues.push(`Workspace directory missing: ${workspace}`);
    return { valid: false, issues };
  }
  if (!existsSync(resolve(workspace, "AGENTS.md"))) {
    issues.push(`Missing AGENTS.md in workspace: ${workspace}`);
  }
  if (!existsSync(resolve(workspace, "IDENTITY.md"))) {
    issues.push(`Missing IDENTITY.md in workspace: ${workspace}`);
  }

  return { valid: issues.length === 0, issues };
}

export function openclawAgentRegistered(
  agentId: string = OPENCLAW_AGENT_ID
): boolean {
  return existsSync(resolve(homedir(), ".openclaw", "agents", agentId));
}

/**
 * Check if VARSITY_API_KEY appears anywhere in the OpenClaw global config JSON.
 */
function configContainsApiKey(config: OpenClawGlobalConfig): boolean {
  return JSON.stringify(config).includes("VARSITY_API_KEY");
}

export interface OpenClawDiagnostic {
  display: string[];
  errors: string[];
}

export function diagnoseOpenClaw(
  home: string,
  state: ArenaHomeState | null
): OpenClawDiagnostic {
  const display: string[] = [];
  const errors: string[] = [];

  // Workspace check
  const ws = openclawWorkspaceValid(home);
  if (ws.valid) {
    display.push(`OpenClaw workspace: ok`);
  } else {
    display.push(`OpenClaw workspace: incomplete`);
    for (const issue of ws.issues) {
      errors.push(`${issue}. Run: arena-agent setup --client openclaw`);
    }
  }

  // Agent registration check
  if (openclawAgentRegistered()) {
    display.push(`OpenClaw agent:    registered`);
  } else {
    display.push(`OpenClaw agent:    not registered`);
    errors.push(
      `OpenClaw agent '${OPENCLAW_AGENT_ID}' not registered. Run: arena-agent setup --client openclaw`
    );
  }

  // MCP mode checks (only when openclawMode is "mcp")
  const mode = state?.openclawMode;
  if (mode === "mcp") {
    const config = readOpenClawGlobalConfig();
    if (!config) {
      display.push(`ACP config:        missing`);
      errors.push(
        `OpenClaw global config not found. Run: arena-agent setup --client openclaw --mode mcp`
      );
    } else {
      const acpBackend = config.acp?.backend;
      if (acpBackend === "acpx") {
        display.push(`ACP backend:       acpx (ok)`);
      } else {
        display.push(`ACP backend:       ${acpBackend ?? "not set"}`);
        errors.push(
          `ACP backend is not 'acpx'. Run: arena-agent setup --client openclaw --mode mcp`
        );
      }

      const acpxEnabled =
        (config.plugins?.entries?.acpx as Record<string, unknown> | undefined)
          ?.enabled === true;
      if (acpxEnabled) {
        display.push(`ACPX plugin:       enabled (ok)`);
      } else {
        display.push(`ACPX plugin:       disabled`);
        errors.push(
          `ACPX plugin is not enabled. Run: arena-agent setup --client openclaw --mode mcp`
        );
      }

      const arenaServer =
        config.plugins?.entries?.acpx?.config?.mcpServers?.arena;
      if (arenaServer) {
        const cmdOk = arenaServer.command === "arena-mcp";
        const argsOk =
          Array.isArray(arenaServer.args) && arenaServer.args.includes("serve");
        if (cmdOk && argsOk) {
          display.push(`Arena MCP server:  configured`);
        } else {
          display.push(`Arena MCP server:  misconfigured`);
          errors.push(
            `Arena MCP server entry is invalid. Run: arena-agent setup --client openclaw --mode mcp`
          );
        }
      } else {
        display.push(`Arena MCP server:  not configured`);
        errors.push(
          `Arena MCP server not found in OpenClaw config. Run: arena-agent setup --client openclaw --mode mcp`
        );
      }

      // Credential isolation check
      if (configContainsApiKey(config)) {
        display.push(`Credentials:       LEAKED — API key found in OpenClaw config`);
        errors.push(
          `WARNING: VARSITY_API_KEY found in OpenClaw global config. Remove it and keep the key only in ~/.arena-agent/.env.runtime.local`
        );
      } else {
        display.push(`Credentials:       isolated (ok)`);
      }
    }
  }

  return { display, errors };
}
