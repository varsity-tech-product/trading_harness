import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";
import { dirname, resolve } from "node:path";

export const HOME_MARKER = ".arena-home.json";
export const DEFAULT_MONITOR_PORT = 8767;
export const DEFAULT_PYTHON_INSTALL_SOURCE =
  process.env.ARENA_PYTHON_INSTALL_SOURCE ??
  "git+https://github.com/varsity-tech-product/arena.git";

export type ManagedAgent =
  | "auto"
  | "rule"
  | "claude"
  | "gemini"
  | "openclaw"
  | "codex";

export interface ArenaHomeState {
  version: number;
  createdAt: string;
  defaultAgent: ManagedAgent;
  defaultModel: string | null;
  liveTrading: boolean;
  monitorPort: number;
  pythonInstallSource: string;
  openclawMode?: "cli" | "mcp";
  profiles: {
    agentExec: string;
    rule: string;
  };
}

function packageRepoRoot(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), "../../../../");
}

export function localPythonSourcePath(): string | null {
  const repoRoot = packageRepoRoot();
  if (existsSync(resolve(repoRoot, "arena_agent", "__init__.py"))) {
    return repoRoot;
  }
  return null;
}

export function defaultArenaHome(): string {
  return resolve(homedir(), ".arena-agent");
}

export function resolveArenaHome(explicitPath?: string): string {
  const raw =
    explicitPath ??
    process.env.ARENA_HOME ??
    process.env.ARENA_ROOT ??
    defaultArenaHome();
  return resolve(raw);
}

export function arenaHomeMarkerPath(home: string): string {
  return resolve(home, HOME_MARKER);
}

export function envFilePath(home: string): string {
  return resolve(home, ".env.runtime.local");
}

export function configDirPath(home: string): string {
  return resolve(home, "config");
}

export function artifactsDirPath(home: string): string {
  return resolve(home, "artifacts");
}

export function logsDirPath(home: string): string {
  return resolve(home, "logs");
}

export function profilePath(
  home: string,
  profile: "agent_exec" | "rule"
): string {
  return resolve(configDirPath(home), `${profile}.yaml`);
}

export function isManagedArenaHome(home: string): boolean {
  return existsSync(arenaHomeMarkerPath(home));
}

export function isRepoArenaRoot(home: string): boolean {
  return existsSync(resolve(home, "arena_agent", "__init__.py"));
}

export function isArenaHome(home: string): boolean {
  return isManagedArenaHome(home) || isRepoArenaRoot(home);
}

export function readArenaHomeState(home: string): ArenaHomeState | null {
  const markerPath = arenaHomeMarkerPath(home);
  if (!existsSync(markerPath)) {
    return null;
  }
  try {
    return JSON.parse(readFileSync(markerPath, "utf-8")) as ArenaHomeState;
  } catch {
    return null;
  }
}

export function ensureArenaHomeDirectories(home: string): void {
  mkdirSync(home, { recursive: true });
  mkdirSync(configDirPath(home), { recursive: true });
  mkdirSync(artifactsDirPath(home), { recursive: true });
  mkdirSync(logsDirPath(home), { recursive: true });
}

export function createArenaHomeState(
  home: string,
  options: {
    defaultAgent: ManagedAgent;
    defaultModel?: string | null;
    liveTrading: boolean;
    monitorPort?: number;
    pythonInstallSource?: string;
    openclawMode?: "cli" | "mcp";
  }
): ArenaHomeState {
  const state: ArenaHomeState = {
    version: 1,
    createdAt: new Date().toISOString(),
    defaultAgent: options.defaultAgent,
    defaultModel: options.defaultModel ?? null,
    liveTrading: options.liveTrading,
    monitorPort: options.monitorPort ?? DEFAULT_MONITOR_PORT,
    pythonInstallSource:
      options.pythonInstallSource ?? DEFAULT_PYTHON_INSTALL_SOURCE,
    profiles: {
      agentExec: profilePath(home, "agent_exec"),
      rule: profilePath(home, "rule"),
    },
  };
  if (options.openclawMode) {
    state.openclawMode = options.openclawMode;
  }
  return state;
}

export function writeArenaHomeState(home: string, state: ArenaHomeState): void {
  ensureArenaHomeDirectories(home);
  writeFileSync(
    arenaHomeMarkerPath(home),
    JSON.stringify(state, null, 2) + "\n",
    "utf-8"
  );
}

export function writeArenaEnvFile(home: string, apiKey: string): void {
  ensureArenaHomeDirectories(home);
  writeFileSync(
    envFilePath(home),
    `VARSITY_API_KEY=${apiKey.trim()}\n`,
    "utf-8"
  );
}

export function writeManagedConfigs(
  home: string,
  state: ArenaHomeState,
  options: { overwrite?: boolean } = {}
): void {
  ensureArenaHomeDirectories(home);
  const overwrite = options.overwrite ?? true;
  const configs: Array<[string, string]> = [
    [state.profiles.agentExec, renderAgentExecConfig(state)],
    [state.profiles.rule, renderRuleConfig(state)],
  ];

  for (const [path, content] of configs) {
    if (!overwrite && existsSync(path)) {
      continue;
    }
    writeFileSync(path, content, "utf-8");
  }
}

function boolText(value: boolean): string {
  return value ? "true" : "false";
}

function renderAgentExecConfig(state: ArenaHomeState): string {
  return `# Managed by arena-agent init
competition_id: 4
symbol: BTCUSDT
interval: 1m
tick_interval_seconds: 60
kline_limit: 120
orderbook_depth: 20
max_iterations: null
stop_when_competition_inactive: true
error_backoff_seconds: 5
dry_run: ${boolText(!state.liveTrading)}
adapter_retry_attempts: 3
adapter_retry_backoff_seconds: 0.5
adapter_min_call_spacing_seconds: 0.0

policy:
  type: agent_exec
  backend: auto
  indicator_mode: full
  timeout_seconds: 120
  recent_transition_limit: 5
  fail_open_to_hold: true
  sandbox_mode: read-only
  bootstrap_from_transition_log: true
  strategy_context: active_momentum
  extra_instructions: >-
    All available technical indicators are pre-computed in the features section.
    Use trend, momentum, volatility, and volume signals together.
    Be decisive, but prefer HOLD when the market regime is ambiguous.

strategy:
  sizing:
    type: volatility_scaled
    target_risk_pct: 0.02
    atr_multiplier: 2.0
  tpsl:
    type: atr_multiple
    atr_tp_mult: 2.0
    atr_sl_mult: 1.5
  entry_filters:
    - type: trade_budget
      min_remaining_trades: 5
  exit_rules:
    - type: trailing_stop
      atr_multiplier: 2.0
    - type: drawdown_exit
      max_drawdown_pct: 0.02

risk_limits:
  max_position_size_pct: 0.1
  max_absolute_size: 0.01
  min_size: 0.001
  quantity_precision: 3
  price_precision: 2
  max_trades: 40
  min_seconds_between_trades: 60
  allow_long: true
  allow_short: true

storage:
  transition_path: ./artifacts/transitions_agent_exec.jsonl
  journal_path: ./artifacts/journal_agent_exec.jsonl
  max_in_memory_transitions: 1000

observability:
  enabled: true
  host: 127.0.0.1
  port: ${state.monitorPort}
  max_transitions: 20
  max_logs: 50
  no_transition_threshold_seconds: 90
  no_transition_error_threshold_seconds: 180
  max_decision_latency_seconds: 120
  max_consecutive_runtime_errors: 10
  supervisor_stop_on_error: false
`;
}

function renderRuleConfig(state: ArenaHomeState): string {
  return `# Managed by arena-agent init
competition_id: 4
symbol: BTCUSDT
interval: 1m
tick_interval_seconds: 60
kline_limit: 120
orderbook_depth: 20
max_iterations: null
stop_when_competition_inactive: true
error_backoff_seconds: 5
dry_run: ${boolText(!state.liveTrading)}
adapter_retry_attempts: 3
adapter_retry_backoff_seconds: 0.5
adapter_min_call_spacing_seconds: 0.0

signal_indicators:
  - indicator: SMA
    params:
      period: 20
  - indicator: RSI
    params:
      period: 14
  - indicator: OBV
    params: {}

policy:
  type: ensemble
  members:
    - type: ma_crossover
      params:
        fast_period: 20
        slow_period: 50
    - type: rsi_mean_reversion
      params:
        rsi_period: 14
        oversold: 30
        overbought: 70
        exit_level: 50
    - type: channel_breakout
      params:
        lookback: 20

risk_limits:
  max_position_size_pct: 0.1
  max_absolute_size: 0.01
  min_size: 0.001
  quantity_precision: 3
  price_precision: 2
  max_trades: 40
  min_seconds_between_trades: 60
  allow_long: true
  allow_short: true

storage:
  transition_path: ./artifacts/transitions_rule.jsonl
  journal_path: ./artifacts/journal_rule.jsonl
  max_in_memory_transitions: 1000

observability:
  enabled: true
  host: 127.0.0.1
  port: ${state.monitorPort}
  max_transitions: 20
  max_logs: 50
  no_transition_threshold_seconds: 90
  no_transition_error_threshold_seconds: 180
  max_consecutive_runtime_errors: 3
  supervisor_stop_on_error: true
`;
}
