import { describe, it, expect } from "vitest";
import { mergeArenaMcpServer, type OpenClawGlobalConfig } from "./openclaw-config.js";
import { mergeCodexToml } from "./client-configs.js";

describe("mergeArenaMcpServer", () => {
  it("creates fresh config from null", () => {
    const result = mergeArenaMcpServer(null, "/home/user/.arena-agent");

    expect(result.acp?.backend).toBe("acpx");
    expect((result.plugins?.entries?.acpx as any)?.enabled).toBe(true);
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

  it("preserves existing acp.backend (additive only)", () => {
    const existing: OpenClawGlobalConfig = {
      acp: { backend: "something-else" },
    };

    const result = mergeArenaMcpServer(existing, "/arena");
    expect(result.acp?.backend).toBe("something-else");
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

  it("adds VARSITY_BASE_URL when provided", () => {
    const result = mergeArenaMcpServer(
      null,
      "/arena",
      "https://api.varsity.lol/v1"
    );
    const arena = result.plugins?.entries?.acpx?.config?.mcpServers?.arena;
    expect(arena?.env).toEqual({
      ARENA_ROOT: "/arena",
      VARSITY_BASE_URL: "https://api.varsity.lol/v1",
    });
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

describe("mergeCodexToml", () => {
  it("creates fresh TOML from empty content", () => {
    const result = mergeCodexToml("", "/home/user/.arena-agent");

    expect(result).toContain("[mcp_servers.arena]");
    expect(result).toContain('command = "arena-mcp"');
    expect(result).toContain('args = ["serve"]');
    expect(result).toContain("[mcp_servers.arena.env]");
    expect(result).toContain('ARENA_ROOT = "/home/user/.arena-agent"');
  });

  it("appends to existing content without arena section", () => {
    const existing = [
      "[mcp_servers.context7]",
      'command = "npx"',
      'args = ["-y", "@upstash/context7-mcp"]',
      "",
    ].join("\n");

    const result = mergeCodexToml(existing, "/arena");

    // Original preserved
    expect(result).toContain("[mcp_servers.context7]");
    expect(result).toContain('command = "npx"');

    // Arena added
    expect(result).toContain("[mcp_servers.arena]");
    expect(result).toContain('command = "arena-mcp"');
  });

  it("replaces existing arena section", () => {
    const existing = [
      "[mcp_servers.arena]",
      'command = "old-command"',
      'args = ["old"]',
      "",
      "[mcp_servers.arena.env]",
      'ARENA_ROOT = "/old/path"',
      "",
      "[mcp_servers.other]",
      'command = "other-cmd"',
    ].join("\n");

    const result = mergeCodexToml(existing, "/new/path");

    // Old arena removed, new arena added
    expect(result).not.toContain("old-command");
    expect(result).not.toContain("/old/path");
    expect(result).toContain('command = "arena-mcp"');
    expect(result).toContain('ARENA_ROOT = "/new/path"');

    // Other section preserved
    expect(result).toContain("[mcp_servers.other]");
    expect(result).toContain('command = "other-cmd"');
  });

  it("preserves other TOML sections", () => {
    const existing = [
      "[general]",
      'model = "o3"',
      "",
      "[mcp_servers.figma]",
      'url = "https://mcp.figma.com"',
      "",
    ].join("\n");

    const result = mergeCodexToml(existing, "/arena");

    expect(result).toContain("[general]");
    expect(result).toContain('model = "o3"');
    expect(result).toContain("[mcp_servers.figma]");
    expect(result).toContain("[mcp_servers.arena]");
  });

  it("escapes backslashes in paths", () => {
    const result = mergeCodexToml("", "C:\\Users\\user\\.arena-agent");
    expect(result).toContain('ARENA_ROOT = "C:\\\\Users\\\\user\\\\.arena-agent"');
  });

  it("never contains VARSITY_API_KEY", () => {
    const result = mergeCodexToml("", "/arena");
    expect(result).not.toContain("VARSITY_API_KEY");
  });

  it("adds VARSITY_BASE_URL to the arena env section when provided", () => {
    const result = mergeCodexToml(
      "",
      "/arena",
      { baseUrl: "https://api.varsity.lol/v1" }
    );
    expect(result).toContain(
      'VARSITY_BASE_URL = "https://api.varsity.lol/v1"'
    );
  });
});
