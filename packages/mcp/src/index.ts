/**
 * Arena MCP Server
 *
 * Thin TypeScript MCP server that delegates operations to the
 * Python arena_agent runtime via a stdio child process bridge.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { PythonBridge } from "./python-bridge.js";
import { findArenaRoot } from "./util/paths.js";

// Runtime tools (original 4)
import * as marketState from "./tools/market-state.js";
import * as competitionInfo from "./tools/competition-info.js";
import * as tradeAction from "./tools/trade-action.js";
import * as lastTransition from "./tools/last-transition.js";

// Native tools
import * as runtimeStart from "./tools/runtime-start.js";
import * as runtimeStop from "./tools/runtime-stop.js";

// Platform API tools
import { all as marketDataTools } from "./tools/platform-market.js";
import { all as discoveryTools } from "./tools/platform-discovery.js";
import { all as registrationTools } from "./tools/platform-registration.js";
import { all as leaderboardTools } from "./tools/platform-leaderboard.js";
import { all as profileTools } from "./tools/platform-profile.js";
import { all as socialTools } from "./tools/platform-social.js";
import { all as notificationTools } from "./tools/platform-notifications.js";
import { all as systemTools } from "./tools/platform-system.js";
import { all as hubTools } from "./tools/platform-hub.js";
import { all as seasonTools } from "./tools/platform-seasons.js";
import { all as liveTools } from "./tools/platform-live.js";
import { all as predictionTools } from "./tools/platform-predictions.js";

export function createServer(arenaRoot?: string): McpServer {
  const root = arenaRoot ?? findArenaRoot();
  const bridge = new PythonBridge(root);

  const server = new McpServer({
    name: "arena-agent",
    version: "0.2.0",
  });

  // --- Forwarded tools (Python bridge) ---

  const forwardedTools = [
    // Runtime tools
    marketState,
    competitionInfo,
    tradeAction,
    lastTransition,
    // Platform API tools
    ...marketDataTools,
    ...discoveryTools,
    ...registrationTools,
    ...leaderboardTools,
    ...profileTools,
    ...socialTools,
    ...notificationTools,
    ...systemTools,
    ...hubTools,
    ...seasonTools,
    ...liveTools,
    ...predictionTools,
  ];

  for (const tool of forwardedTools) {
    server.tool(
      tool.name,
      tool.description,
      tool.inputSchema.shape,
      async (args: Record<string, unknown>) => {
        try {
          const result = await bridge.callTool(tool.pythonTool, args);
          return {
            content: [
              { type: "text" as const, text: JSON.stringify(result, null, 2) },
            ],
          };
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          return {
            content: [{ type: "text" as const, text: `Error: ${msg}` }],
            isError: true,
          };
        }
      }
    );
  }

  // --- Native tools (TypeScript) ---

  server.tool(
    runtimeStart.name,
    runtimeStart.description,
    runtimeStart.inputSchema.shape,
    async (args) => {
      const result = runtimeStart.execute(
        args as ReturnType<typeof runtimeStart.inputSchema.parse>,
        root
      );
      return {
        content: [
          { type: "text" as const, text: JSON.stringify(result, null, 2) },
        ],
      };
    }
  );

  server.tool(
    runtimeStop.name,
    runtimeStop.description,
    runtimeStop.inputSchema.shape,
    async () => {
      const result = runtimeStop.execute();
      return {
        content: [
          { type: "text" as const, text: JSON.stringify(result, null, 2) },
        ],
      };
    }
  );

  return server;
}

/**
 * Start the MCP server on stdio (default entry point for MCP clients).
 */
export async function serve(arenaRoot?: string): Promise<void> {
  const server = createServer(arenaRoot);
  const transport = new StdioServerTransport();
  await server.connect(transport);
}
