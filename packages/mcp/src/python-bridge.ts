/**
 * Spawns the Python MCP server as a child process and forwards tool calls.
 */
import { spawn, type ChildProcess } from "node:child_process";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { findPython } from "./util/paths.js";
import { buildChildEnv } from "./util/env.js";

export class PythonBridge {
  private arenaRoot: string;
  private client: Client | null = null;
  private transport: StdioClientTransport | null = null;
  private ready = false;

  constructor(arenaRoot: string) {
    this.arenaRoot = arenaRoot;
  }

  async connect(): Promise<void> {
    if (this.ready) return;

    const python = findPython(this.arenaRoot);
    const env = buildChildEnv(this.arenaRoot);

    this.transport = new StdioClientTransport({
      command: python,
      args: ["-m", "arena_agent.mcp.server", "--transport", "stdio"],
      env,
      cwd: this.arenaRoot,
    });

    this.client = new Client(
      { name: "arena-mcp-bridge", version: "0.1.0" },
      { capabilities: {} }
    );

    await this.client.connect(this.transport);
    this.ready = true;
  }

  async callTool(
    name: string,
    args: Record<string, unknown> = {},
    options?: { timeout?: number }
  ): Promise<unknown> {
    await this.connect();
    const requestOptions = options?.timeout
      ? { timeout: options.timeout }
      : undefined;
    const result = await this.client!.callTool(
      { name, arguments: args },
      undefined,
      requestOptions
    );
    // MCP callTool returns { content: [...] }
    // Extract the text/json content
    if (result.content && Array.isArray(result.content)) {
      for (const block of result.content) {
        if (
          block.type === "text" &&
          typeof block.text === "string"
        ) {
          try {
            return JSON.parse(block.text);
          } catch {
            return block.text;
          }
        }
      }
    }
    return result;
  }

  async disconnect(): Promise<void> {
    if (this.transport) {
      await this.transport.close();
      this.transport = null;
    }
    this.client = null;
    this.ready = false;
  }
}
