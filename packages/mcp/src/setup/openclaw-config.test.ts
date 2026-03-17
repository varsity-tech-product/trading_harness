import { describe, it, expect } from "vitest";
import { mergeArenaMcpServer, type OpenClawGlobalConfig } from "./openclaw-config.js";

describe("mergeArenaMcpServer", () => {
  it("creates fresh config from null", () => {
    const result = mergeArenaMcpServer(null, "/home/user/.arena-agent");

    expect(result.acp?.backend).toBe("acpx");
    const arena = result.plugins?.entries?.acpx?.config?.mcpServers?.arena;
    expect(arena).toBeDefined();
    expect(arena!.command).toBe("arena-mcp");
    expect(arena!.args).toEqual(["serve"]);
    expect(arena!.env).toEqual({ ARENA_ROOT: "/home/user/.arena-agent" });
  });

  it("preserves existing keys and other MCP servers", () => {
    const existing: OpenClawGlobalConfig = {
      someTopLevel: "keep-me",
      acp: { backend: "acpx", otherAcpKey: true },
      plugins: {
        entries: {
          acpx: {
            config: {
              mcpServers: {
                "other-server": {
                  command: "other-cmd",
                  args: ["run"],
                },
              },
              otherConfigKey: "preserved",
            },
            pluginMeta: "kept",
          },
          otherPlugin: { data: 123 },
        },
        pluginsExtra: "also-kept",
      },
    };

    const result = mergeArenaMcpServer(existing, "/arena");

    expect((result as any).someTopLevel).toBe("keep-me");
    expect(result.acp?.backend).toBe("acpx");
    expect((result.acp as any).otherAcpKey).toBe(true);
    expect((result.plugins as any).pluginsExtra).toBe("also-kept");
    expect((result.plugins?.entries as any).otherPlugin).toEqual({ data: 123 });
    expect((result.plugins?.entries?.acpx as any).pluginMeta).toBe("kept");
    expect((result.plugins?.entries?.acpx?.config as any).otherConfigKey).toBe("preserved");

    // Other server preserved
    const otherServer = result.plugins?.entries?.acpx?.config?.mcpServers?.["other-server"];
    expect(otherServer).toEqual({ command: "other-cmd", args: ["run"] });

    // Arena server added
    const arena = result.plugins?.entries?.acpx?.config?.mcpServers?.arena;
    expect(arena?.command).toBe("arena-mcp");
  });

  it("overwrites stale arena server entry", () => {
    const existing: OpenClawGlobalConfig = {
      acp: { backend: "acpx" },
      plugins: {
        entries: {
          acpx: {
            config: {
              mcpServers: {
                arena: {
                  command: "old-command",
                  args: ["old"],
                  env: { ARENA_ROOT: "/old/path" },
                },
              },
            },
          },
        },
      },
    };

    const result = mergeArenaMcpServer(existing, "/new/path");

    const arena = result.plugins?.entries?.acpx?.config?.mcpServers?.arena;
    expect(arena?.command).toBe("arena-mcp");
    expect(arena?.args).toEqual(["serve"]);
    expect(arena?.env).toEqual({ ARENA_ROOT: "/new/path" });
  });

  it("sets acp.backend to acpx even if previously different", () => {
    const existing: OpenClawGlobalConfig = {
      acp: { backend: "something-else" },
    };

    const result = mergeArenaMcpServer(existing, "/arena");
    expect(result.acp?.backend).toBe("acpx");
  });

  it("never contains VARSITY_API_KEY", () => {
    const result = mergeArenaMcpServer(null, "/arena");
    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain("VARSITY_API_KEY");
  });

  it("sets ARENA_ROOT correctly in env", () => {
    const arenaRoot = "/custom/arena/path";
    const result = mergeArenaMcpServer(null, arenaRoot);
    const arena = result.plugins?.entries?.acpx?.config?.mcpServers?.arena;
    expect(arena?.env?.ARENA_ROOT).toBe(arenaRoot);
  });

  it("does not mutate the input config", () => {
    const existing: OpenClawGlobalConfig = {
      acp: { backend: "old" },
      plugins: {
        entries: {
          acpx: {
            config: {
              mcpServers: {},
            },
          },
        },
      },
    };

    const before = JSON.stringify(existing);
    mergeArenaMcpServer(existing, "/arena");
    expect(JSON.stringify(existing)).toBe(before);
  });
});
