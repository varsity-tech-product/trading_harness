import { z } from "zod";
import { readFileSync, writeFileSync } from "node:fs";
import { extname, join, basename, dirname } from "node:path";
import { parse, stringify } from "yaml";
import { findConfigPath } from "./runtime-start.js";

// ── arena.runtime_config — read current config ─────────────────────

export const readName = "arena.runtime_config";
export const readDescription =
  "Read the current runtime config as JSON. Shows all settings the agent can customize: " +
  "interval, tick_interval_seconds, kline_limit, strategy (sizing, tpsl, entry_filters, exit_rules), " +
  "risk_limits, signal_indicators, policy (indicator_mode, timeout_seconds), and more.";

export const readInputSchema = z.object({
  config: z
    .string()
    .optional()
    .describe("Path to config file. Omit for default."),
  agent: z
    .enum(["config", "rule", "claude", "gemini", "openclaw", "codex", "auto", "tap"])
    .optional()
    .default("auto")
    .describe("Agent type (determines which default config to read)."),
});

export function executeRead(
  args: z.infer<typeof readInputSchema>,
  arenaRoot: string
): Record<string, unknown> {
  const configPath = findConfigPath(arenaRoot, args.config, args.agent);
  const content = readFileSync(configPath, "utf-8");
  const config = parse(content) as Record<string, unknown>;
  return { config_path: configPath, ...config };
}

// ── arena.update_runtime_config — modify config fields ──────────────

export const updateName = "arena.update_runtime_config";
export const updateDescription =
  "Update runtime config fields. Deep-merges your changes into the existing YAML config. " +
  "Use this to customize strategy before calling runtime_start. " +
  "Changeable: interval, tick_interval_seconds, kline_limit, orderbook_depth, " +
  "strategy (sizing, tpsl, entry_filters, exit_rules), risk_limits, " +
  "signal_indicators, policy (indicator_mode, extra_instructions). " +
  "Cannot change: symbol (fixed per competition).";

export const updateInputSchema = z.object({
  config: z
    .string()
    .optional()
    .describe("Path to config file. Omit for default."),
  agent: z
    .enum(["config", "rule", "claude", "gemini", "openclaw", "codex", "auto", "tap"])
    .optional()
    .default("auto")
    .describe("Agent type (determines which default config to read)."),
  overrides: z
    .record(z.unknown())
    .describe(
      "JSON object to deep-merge into config. Examples: " +
      '{ "interval": "5m", "tick_interval_seconds": 15 } or ' +
      '{ "strategy": { "sizing": { "type": "fixed", "size": 0.005 } } } or ' +
      '{ "risk_limits": { "max_trades": 30, "min_seconds_between_trades": 120 } } or ' +
      '{ "signal_indicators": [{ "indicator": "RSI", "params": { "period": 14 } }] }'
    ),
});

/** Fields agents must not change (tied to competition or infrastructure). */
const PROTECTED_FIELDS = new Set(["symbol", "competition_id"]);
const ATOMIC_REPLACE_PATHS = new Set([
  "policy.params",
  "policy.members",
  "signal_indicators",
  "strategy.sizing",
  "strategy.tpsl",
  "strategy.entry_filters",
  "strategy.exit_rules",
]);

export function executeUpdate(
  args: z.infer<typeof updateInputSchema>,
  arenaRoot: string
): { config_path: string; updated_fields: string[]; config: Record<string, unknown> } {
  const configPath = findConfigPath(arenaRoot, args.config, args.agent);
  const content = readFileSync(configPath, "utf-8");
  const config = parse(content) as Record<string, unknown>;

  // Strip protected fields from overrides
  const overrides = { ...args.overrides };
  for (const key of PROTECTED_FIELDS) {
    if (key in overrides) {
      delete overrides[key];
    }
  }

  const updatedFields = collectKeys(overrides);
  deepMerge(config, overrides);

  writeFileSync(configPath, stringify(config, { indent: 2 }), "utf-8");

  return { config_path: configPath, updated_fields: updatedFields, config };
}

export function syncCompetitionConfig(
  configPath: string,
  competitionId: number,
  symbol: string
): { config_path: string; updated_fields: string[]; config: Record<string, unknown> } {
  const content = readFileSync(configPath, "utf-8");
  const config = parse(content) as Record<string, unknown>;
  const updatedFields: string[] = [];

  if (config.competition_id !== competitionId) {
    config.competition_id = competitionId;
    updatedFields.push("competition_id");
  }
  if (config.symbol !== symbol) {
    config.symbol = symbol;
    updatedFields.push("symbol");
  }

  ensureCompetitionScopedStorage(config, competitionId, updatedFields);
  if (updatedFields.length > 0) {
    writeFileSync(configPath, stringify(config, { indent: 2 }), "utf-8");
  }
  return { config_path: configPath, updated_fields: updatedFields, config };
}

// ── Helpers ─────────────────────────────────────────────────────────

function deepMerge(
  target: Record<string, unknown>,
  source: Record<string, unknown>,
  path = ""
): void {
  for (const [key, value] of Object.entries(source)) {
    const currentPath = path ? `${path}.${key}` : key;
    if (ATOMIC_REPLACE_PATHS.has(currentPath)) {
      target[key] = value;
      continue;
    }
    if (
      value !== null &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      typeof target[key] === "object" &&
      target[key] !== null &&
      !Array.isArray(target[key])
    ) {
      deepMerge(
        target[key] as Record<string, unknown>,
        value as Record<string, unknown>,
        currentPath,
      );
    } else {
      target[key] = value;
    }
  }
}

function ensureCompetitionScopedStorage(
  config: Record<string, unknown>,
  competitionId: number,
  updatedFields: string[]
): void {
  const storage = ensureObject(config, "storage");
  for (const field of ["transition_path", "journal_path"] as const) {
    const current = storage[field];
    if (typeof current !== "string" || !current.trim()) {
      continue;
    }
    const nextValue = withCompetitionSuffix(current, competitionId);
    if (nextValue !== current) {
      storage[field] = nextValue;
      updatedFields.push(`storage.${field}`);
    }
  }
}

function withCompetitionSuffix(path: string, competitionId: number): string {
  const preserveDotPrefix = path.startsWith("./");
  const suffix = extname(path);
  const filename = basename(path, suffix).replace(/-c\d+$/, "");
  const scoped = join(dirname(path), `${filename}-c${competitionId}${suffix}`);
  return preserveDotPrefix && !scoped.startsWith("./") ? `./${scoped}` : scoped;
}

function ensureObject(
  target: Record<string, unknown>,
  key: string
): Record<string, unknown> {
  const value = target[key];
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  const created: Record<string, unknown> = {};
  target[key] = created;
  return created;
}

function collectKeys(obj: Record<string, unknown>, prefix = ""): string[] {
  const keys: string[] = [];
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (
      value !== null &&
      typeof value === "object" &&
      !Array.isArray(value)
    ) {
      keys.push(...collectKeys(value as Record<string, unknown>, path));
    } else {
      keys.push(path);
    }
  }
  return keys;
}
