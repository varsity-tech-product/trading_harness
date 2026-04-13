import { commandAvailable } from "./bootstrap-python.js";

/**
 * Verify OpenClaw is available. The arena package never creates agents or
 * modifies the user's OpenClaw global config — it uses the user's own agent
 * and passes complete prompts via --message.
 *
 * MCP tool access is optional: users who want their agent to call arena_*
 * tools can follow the printed instructions to add the arena MCP server
 * to their own OpenClaw config.
 */
export function ensureOpenClawTradingAgent(home: string): void {
  if (!commandAvailable("openclaw")) {
    throw new Error("openclaw is not available in PATH.");
  }
  // Nothing else to do — the user's own openclaw agent is used as-is.
  // The runtime passes complete prompts with all instructions inline.
}

/**
 * Return setup instructions for users who want MCP tools available inside
 * their OpenClaw agent. This is printed during init — never auto-applied.
 */
export function openclawMcpInstructions(
  home: string,
  baseUrl?: string
): string {
  const env = {
    ARENA_ROOT: home,
    ...(baseUrl ? { VARSITY_BASE_URL: baseUrl } : {}),
  };
  return [
    "",
    "To give your OpenClaw agent access to Arena MCP tools (optional):",
    "Add the following to your ~/.openclaw/openclaw.json under",
    'plugins.entries.acpx.config.mcpServers:',
    "",
    '  "arena": {',
    '    "command": "arena-mcp",',
    '    "args": ["serve"],',
    `    "env": ${JSON.stringify(env)}`,
    "  }",
    "",
    "Make sure acpx plugin is enabled (plugins.entries.acpx.enabled = true)",
    "and acp.backend is set to \"acpx\".",
  ].join("\n");
}
