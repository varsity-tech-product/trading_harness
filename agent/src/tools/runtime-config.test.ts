import { describe, expect, it } from "vitest";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { parse as parseYaml } from "yaml";

import { executeUpdate, syncCompetitionConfig } from "./runtime-config.js";

describe("runtime-config updates", () => {
  it("atomically replaces strategy blocks instead of deep-merging stale params", () => {
    const root = mkdtempSync(join(tmpdir(), "arena-config-"));
    const configPath = join(root, "config.yaml");
    writeFileSync(
      configPath,
      [
        "competition_id: 4",
        "symbol: BTCUSDT",
        "strategy:",
        "  sizing:",
        "    type: volatility_scaled",
        "    target_risk_pct: 0.02",
        "    atr_multiplier: 2",
        "  tpsl:",
        "    type: atr_multiple",
        "    atr_tp_mult: 2",
        "    atr_sl_mult: 1.5",
      ].join("\n"),
      "utf-8"
    );

    const result = executeUpdate(
      {
        agent: "auto",
        config: configPath,
        overrides: {
          strategy: {
            sizing: { type: "fixed_fraction", fraction: 0.25 },
            tpsl: { type: "fixed_pct", tp_pct: 0.02, sl_pct: 0.01 },
          },
        },
      },
      root
    );

    const config = result.config as Record<string, any>;
    expect(config.strategy.sizing).toEqual({
      type: "fixed_fraction",
      fraction: 0.25,
    });
    expect(config.strategy.tpsl).toEqual({
      type: "fixed_pct",
      tp_pct: 0.02,
      sl_pct: 0.01,
    });
  });

  it("syncs competition symbol and isolates storage paths per competition", () => {
    const root = mkdtempSync(join(tmpdir(), "arena-config-"));
    const configPath = join(root, "config.yaml");
    writeFileSync(
      configPath,
      [
        "competition_id: 4",
        "symbol: BTCUSDT",
        "storage:",
        "  transition_path: ./artifacts/transitions_agent_exec.jsonl",
        "  journal_path: ./artifacts/journal_agent_exec.jsonl",
      ].join("\n"),
      "utf-8"
    );

    syncCompetitionConfig(configPath, 10, "SOLUSDT");
    const config = parseYaml(readFileSync(configPath, "utf-8")) as Record<string, any>;

    expect(config.competition_id).toBe(10);
    expect(config.symbol).toBe("SOLUSDT");
    expect(config.storage.transition_path).toBe(
      "./artifacts/transitions_agent_exec-c10.jsonl"
    );
    expect(config.storage.journal_path).toBe(
      "./artifacts/journal_agent_exec-c10.jsonl"
    );
  });
});
