# Arena Trading Agent Runtime

Current status: this repo contains a working v1 trading-agent runtime for the Varsity Arena API. The runtime includes a versioned `signal_state.v1` contract backed by a TA-Lib feature engine, and an autonomous **setup → control → runtime** loop where an LLM-powered setup agent continuously tunes strategy for a runtime trading agent.

## Quick Start

For most users, the recommended workflow is:

```bash
npm install -g @varsity-arena/agent
arena-agent init
arena-agent doctor
arena-agent up --agent gemini
```

For autonomous trading with setup agent control:

```bash
arena-agent up --auto --competition 9 --agent claude
# or directly:
arena-agent-runtime auto --competition-id 9 --agent claude --setup-interval 300
```

Useful follow-ups:

```bash
arena-agent up --no-monitor --daemon
arena-agent status
arena-agent logs
arena-agent monitor
arena-agent down
arena-agent upgrade
arena-agent dashboard --competition 4 -d
arena-agent competitions --status live
arena-agent register 5
arena-agent leaderboard 5
```

Notes:

- `arena-agent init` creates `~/.arena-agent`, stores your `VARSITY_API_KEY`, installs the Python runtime into `~/.arena-agent/.venv`, and writes starter configs. It **never modifies your agent's global config** — MCP setup instructions are printed for you to apply manually.
- `arena-agent init` defaults to `dry-run`. Use `--mode live --yes-live` only when you want real order writes.
- Supported agent backends in the current runtime are `claude`, `gemini`, `openclaw`, `codex`, `rule`, and `auto`.
- Tool access uses dual paths (zero user config required for either):
  - **Claude Code**: native MCP via per-call `--mcp-config .mcp.json` (project-local, no global config changes)
  - **Gemini / Codex / OpenClaw**: tool proxy — tools described in the prompt, agent returns `tool_calls` JSON, runtime executes locally via `varsity_tools.dispatch()`
- `arena-agent doctor` checks Python, runtime deps, monitor deps, API key presence, and backend CLI readiness.

## What exists now

- `arena_agent/`
  - General runtime loop built around `state -> action -> transition`.
  - Arena API adapter with retries and light validation.
  - State builder for market, account, position, and competition snapshots.
  - Risk-aware execution layer for open, close, TP/SL update, and hold.
  - Neutral transition store and journal output.
  - Built-in rule policies:
    - moving-average crossover
    - RSI mean reversion
    - channel breakout
    - ensemble composition
  - Minimal TAP support for external agents through a single HTTP decision endpoint.
- `run_agent.py`
  - Convenience entrypoint for `python3 -m arena_agent`.
- Local skill commands:
  - `arena_market_state`
  - `arena_trade`
  - `arena_last_transition`
  - `arena_competition_info`
- MCP server:
  - `arena_agent/mcp/server.py`
  - `run_mcp_server.sh`
- SDK:
  - `arena_agent/sdk/`
  - `examples/sdk_quickstart.py`
- Agent exec policy (CLI-backed, supports Claude Code and Codex):
  - current backends: Claude Code, Gemini, OpenClaw, Codex
  - `arena_agent/agents/agent_exec_policy.py`
  - `arena_agent/agents/prompt_template.md`
  - `arena_agent/agents/action_schema.json`
  - `arena_agent/config/codex_agent_config.yaml`
- LLM-powered setup agent (strategy manager):
  - analyzes market + performance context, picks rule policy + params via flat schema
  - strategy change cooldown (20 min / 5 trades) prevents thrashing
  - per-strategy performance tracking (separate from overall stats)
  - `arena_agent/agents/setup_agent.py` (decision parsing, cooldown, flat→config translation)
  - `arena_agent/agents/setup_action_schema.json` (flat schema: policy, tp_pct, sl_pct, sizing_fraction, direction_bias)
  - `arena_agent/agents/setup_prompt_template.md` (layered prompt with per-strategy stats)
  - `arena_agent/setup/context_builder.py` (account, PnL, fees, hold times, multi-timeframe market)
  - `arena_agent/setup/memory.py` (cross-competition learning)
- Auto mode (`arena-agent-runtime auto`):
  - continuous loop: setup agent picks rule policy → deterministic runtime executes → repeat
  - setup agent controls policy type, params, TP/SL%, sizing%, direction bias
  - runtime uses rule policies (no per-tick LLM calls), strategy layer handles sizing/TP/SL/exits
  - naked order protection: action demoted to HOLD if strategy refine fails
- Terminal monitor:
  - `arena_agent/tui/`
  - `.venv/bin/python -m arena_agent monitor`

## Current architecture

The system uses a **setup agent → rule policy** architecture. The LLM (setup agent) picks the strategy; a deterministic rule policy executes it. No per-tick LLM calls.

```
┌──────────────────────────────────────────────────────────┐
│                 Auto Loop (__main__.py)                   │
│                                                          │
│  ┌──────────┐  flat decision   ┌──────────────┐         │
│  │  Setup   │─────────────────→│ Config Dict  │         │
│  │  Agent   │  (policy,tp/sl,  │  (mutable)   │         │
│  │ (LLM)   │   sizing,bias)   └──────┬───────┘         │
│  │ +tools   │                        │                   │
│  └──────────┘              RuntimeConfig                 │
│       ↑                          │                       │
│       │ every 5-20 min           ▼                       │
│       │                  ┌──────────────┐                │
│       │                  │ Rule Policy  │ deterministic  │
│       │                  │ (ma_crossover│ 30s ticks      │
│       │                  │  rsi_revert  │ no LLM calls   │
│       │                  │  ch_breakout │                 │
│       │                  │  ensemble)   │                 │
│       │                  └──────┬───────┘                │
│       │                         │                        │
│       │                  ┌──────▼───────┐                │
│       │                  │ Strategy     │                │
│       │                  │ Layer        │                │
│       │                  │ (sizing,     │                │
│       │                  │  TP/SL,      │                │
│       │                  │  exit rules) │                │
│       │                  └──────┬───────┘                │
│       │                         │                        │
│       │  context + performance  │ execute                │
│       └─────────────────────────┘                        │
└──────────────────────────────────────────────────────────┘
```

**Setup agent** (outer loop, every 5-20 min):
- Receives context: price, equity, PnL, fees, win rate, per-strategy performance, multi-timeframe trends
- Returns a flat decision: policy type, params, TP/SL percentages, sizing fraction, direction bias
- Can call arena tools for deeper analysis (klines, orderbook, leaderboard, chat, etc.)
- Strategy change cooldown: 20 min or 5 trades minimum between changes (enforced server-side)
- Backends: Claude, Codex, Gemini, OpenClaw
- Tool access: Claude uses native MCP; others use the tool proxy (JSON `tool_calls` protocol, executed locally via `varsity_tools.dispatch()`)

**Rule policy** (inner loop, per tick, deterministic):
- `ma_crossover(fast_period, slow_period)` — trades SMA crossovers
- `rsi_mean_reversion(rsi_period, oversold, overbought, exit_level)` — trades RSI extremes
- `channel_breakout(lookback)` — trades price channel breakouts
- `ensemble([policies...])` — first non-HOLD signal wins

**Strategy layer** (applied to every trade action):
- Sizing: `fixed_fraction` of equity (setup agent controls the percentage)
- TP/SL: `fixed_pct` from entry price (setup agent controls the percentages)
- Entry filters: trade budget enforcement
- Exit rules: trailing stop, drawdown exit
- Safety: if strategy refine fails, action demoted to HOLD (no naked orders)

**Key design decisions:**
- The LLM never sees internal config nesting — it uses a flat schema with percentages
- The LLM never places trades directly — it configures a rule engine
- Per-strategy performance is tracked separately from overall stats
- Direction bias (long_only/short_only/both) is enforced at the risk limits level
- `--agent claude/codex/gemini` selects the setup agent backend; the runtime always uses rule policies
- `--agent auto` in auto mode defaults to rule policy; the setup agent picks which one
- Backward compatible: `--agent claude` in `run` mode still uses `agent_exec` with per-tick LLM calls

Indicator support:

- TA-Lib is required (installed during `arena-agent init` bootstrap).
- All 158 TA-Lib indicators that can be computed from runtime market data are supported.
- Indicators that need extra non-OHLCV inputs, such as `MAVP`, are also supported if those extra series are supplied in the indicator params.
- If an indicator needs inputs the runtime does not have and the agent does not supply, the request fails clearly instead of silently degrading.

## Signal State Contract

`AgentState` now contains:

```python
state.signal_state
```

Contract shape:

```json
{
  "version": "signal_state.v1",
  "backend": "talib",
  "requested": [
    {"indicator": "SMA", "params": {"period": 20}, "key": null}
  ],
  "values": {
    "sma_20": 70477.005
  },
  "warmup_complete": true,
  "metadata": {
    "timestamp": 1773483839999,
    "candle_count": 120,
    "indicator_metadata": [
      {
        "key": "sma_20",
        "indicator": "SMA",
        "params": {"timeperiod": 20},
        "outputs": ["value"],
        "lookback_required": 20,
        "supported_inputs_only": true,
        "unsupported_inputs": []
      }
    ]
  }
}
```

Notes:

- `version` is the stable contract version for external agents.
- `backend` is `talib` or `none`.
- `warmup_complete` tells the agent whether every requested feature is ready.
- `indicator_metadata[*].lookback_required` is the normalized warmup requirement for that indicator.
- Use explicit `key` values for indicators with large or structured params.

### Policy-driven indicator selection

The policy can control which indicators are computed via `indicator_mode` in the policy config section:

| Mode | Behavior |
|------|----------|
| `full` | Computes all 30 curated TA-Lib indicators with default params. The agent sees everything and picks what matters. |
| `custom` | Uses a `signal_indicators` list declared in the policy section. |
| *(omitted)* | Falls back to the top-level `signal_indicators` in the runtime config (backward compatible). |

Example:

```yaml
policy:
  type: agent_exec
  indicator_mode: full
```

## External-agent support

There is a minimal TAP layer in `arena_agent/tap/` for plug-in agents.

- Request: `POST /decision`
- Payload: `{"timestamp": ..., "state": {...}}`
- Response: `{"action": {...}}`

This is deliberately minimal and not a larger protocol framework.

For the local Claude-backed TAP server in `arena_agent/tap/local_claude_server.py`, the response is normalized so each action includes:

- `action.metadata.reason`
- `action.metadata.raw_claude_response`
- `action.metadata.claude_model`

That makes live trading decisions auditable after the fact through the transition journal.

## Local skill tools

The repo now exposes the runtime as local CLI tools for agent tool use. These tools auto-load `.env.runtime.local` when present and keep secrets in the local host environment rather than passing them to the model.

- `arena_market_state`
  - returns the full current `AgentState`
- `arena_trade`
  - submits an action and stores the resulting transition
- `arena_last_transition`
  - returns the last stored transition from the transition log
- `arena_competition_info`
  - returns compact competition metadata useful for decision-making

Examples:

```bash
./arena_market_state
./arena_competition_info
./arena_trade --action HOLD
echo '{"action":"OPEN_LONG","size":0.001}' | ./arena_trade --execute
./arena_last_transition
./arena_market_state --signal-indicators '[{"indicator":"SMA","params":{"period":20}},{"indicator":"RSI","params":{"period":14}}]'
```

## MCP server

The repo exposes the full Arena platform through a universal MCP server in `arena_agent/mcp/`. The server provides 47 tools covering every API endpoint, plus 2 native TypeScript tools for runtime management (49 total through the npm package).

### Runtime tools (local agent runtime)

- `varsity.market_state` — full market, account, position, and indicator state
- `varsity.trade_action` — submit trades through the risk-aware execution layer
- `varsity.competition_info` — compact competition metadata
- `varsity.last_transition` — last stored transition event

### Platform API tools (direct API access, 43 tools)

| Category | Tools |
|---|---|
| System | `health`, `version`, `arena_health` |
| Market Data | `symbols`, `orderbook`, `klines`, `market_info` |
| Seasons & Tiers | `tiers`, `seasons`, `season_detail` |
| Competitions | `competitions`, `competition_detail`, `participants` |
| Registration | `register`, `withdraw`, `my_registration` |
| Hub | `hub`, `arena_profile`, `my_registrations` |
| Leaderboards | `leaderboard`, `my_leaderboard_position`, `season_leaderboard` |
| Profile | `my_profile`, `my_history`, `my_history_detail`, `achievements`, `public_profile`, `public_history`, `update_profile` |
| Live Trading | `live_trades`, `live_position`, `live_account` |
| Social | `chat_send`, `chat_history` |
| Predictions | `predictions`, `submit_prediction`, `polls`, `vote_poll` |
| Notifications | `notifications`, `unread_count`, `mark_read`, `mark_all_read` |
| Events | `track_event` |

All platform tools use the `varsity.*` namespace on the Python side and `arena.*` on the TypeScript MCP side.

Run it locally with:

```bash
./run_mcp_server.sh --transport stdio
```

Or over HTTP:

```bash
./run_mcp_server.sh --transport streamable-http --host 127.0.0.1 --port 8000
```

The server reuses the same local runtime env file and underlying runtime components as the CLI skills.

Both CLI tools and MCP tools accept optional `signal_indicators` input so agents can request the indicator bundle they want without changing the runtime code.

## Tool access architecture

Agents access arena tools through two paths — **zero user configuration required** for either:

```
┌─────────────────────────────────────────────────────────────┐
│                   Arena Tool Access                         │
│                                                             │
│  Claude Code ──→ native MCP (--mcp-config .mcp.json)        │
│                  Claude calls MCP tools directly during      │
│                  its turn. Per-call config, no global setup.  │
│                                                             │
│  Gemini     ─┐                                              │
│  Codex      ─┤─→ tool proxy (JSON protocol)                 │
│  OpenClaw   ─┘   Agent returns {"tool_calls": [...]}        │
│                  Runtime executes via varsity_tools.dispatch()│
│                  Results appended to prompt, agent re-invoked│
│                  Loop until final answer (max 5 rounds)      │
│                                                             │
│  Both paths call the same 52 arena tools.                   │
│  Tools execute in the arena Python process — no MCP server  │
│  configuration needed for Gemini/Codex/OpenClaw.            │
└─────────────────────────────────────────────────────────────┘
```

**Why dual paths?** Claude Code blocks `tool_calls` JSON output (detects it as prompt injection against its native tool protocol). Claude Code is also the only backend with per-call `--mcp-config`, so it uses MCP natively. The other backends have no per-call MCP support, so the tool proxy fills the gap.

**Tool proxy protocol** (Gemini/Codex/OpenClaw):
1. Tool catalog appended to the agent's prompt (~1300 tokens for setup, ~500 for runtime)
2. Agent returns `{"tool_calls": [{"tool": "get_klines", "args": {"symbol": "BTCUSDT"}}]}`
3. Runtime executes locally: `varsity_tools.dispatch("get_klines", symbol="BTCUSDT")`
4. Results appended to prompt, agent re-invoked
5. Agent returns final decision (no `tool_calls`) → loop exits

Config: `tool_proxy_enabled` (default `true` for setup agent, `false` for runtime agent).

## Web Dashboard

The npm package includes a web dashboard for monitoring agent trading activity:

```bash
arena-agent dashboard --competition 4 -d
```

The dashboard shows:
- Kline chart with buy/sell markers (TradingView Lightweight Charts)
- Equity curve
- AI reasoning log from transition history

Use `-d` to daemonize (returns immediately, runs in background). The dashboard auto-refreshes every 10 seconds and reads transition data from the local JSONL files.

## Arena Agent SDK

There is also a thin SDK on top of the MCP layer in `arena_agent/sdk/`.

Design constraints:

- no strategy logic
- no reward system
- no training abstractions
- only state, actions, and an optional loop helper

Minimal example:

```python
from arena_agent import Arena

agent = Arena(
    signal_indicators=[
        {"indicator": "SMA", "params": {"period": 20}},
        {"indicator": "RSI", "params": {"period": 14}},
        {"indicator": "OBV", "params": {}},
    ]
)

state = agent.state()
info = agent.competition_info()

if state.position is None and state.price > 0 and state.market.orderbook_imbalance > 0.25:
    agent.long(size=0.001)
else:
    agent.hold()
```

Signal features are available under:

```python
state.signal_state.values["sma_20"]
state.features.sma_20
state.signal_state.metadata.indicator_metadata[0].lookback_required
```

For indicators with long or structured params, set an explicit key:

```python
agent = Arena(signal_indicators=[
    {"indicator": "MACD", "key": "macd_fast", "params": {"fast_period": 12, "slow_period": 26, "signal_period": 9}},
    {"indicator": "MAVP", "key": "mavp_test", "params": {"minperiod": 2, "maxperiod": 5, "periods": [2] * 120}},
])
```

Optional loop helper:

```python
from arena_agent import Arena

agent = Arena()

def policy(state):
    if state.position is None and state.market.orderbook_imbalance > 0.25:
        return {"type": "OPEN_LONG", "size": 0.001}
    return "HOLD"

agent.run(policy, max_steps=1)
```

## Run CLI

The runtime supports agent selection from the terminal. `--agent` selects both the policy type and the CLI backend in one flag:

```bash
# Use Claude Code as the decision engine
.venv/bin/python -m arena_agent run --agent claude --config arena_agent/config/codex_agent_config.yaml

# Use Codex CLI as the decision engine
.venv/bin/python -m arena_agent run --agent codex --model gpt-5

# Auto-detect (prefers Claude Code if installed)
.venv/bin/python -m arena_agent run --agent auto

# Use an external HTTP TAP endpoint
.venv/bin/python -m arena_agent run --agent tap --tap-endpoint http://localhost:8080/decision

# Use the rule-based ensemble from YAML config
.venv/bin/python -m arena_agent run --agent rule --config arena_agent/config/agent_config.yaml

# Keep whatever the YAML config specifies
.venv/bin/python -m arena_agent run --agent config --config arena_agent/config/agent_config.yaml
```

The agent exec policy (`--agent claude`, `--agent codex`, `--agent auto`) keeps the runtime loop stateless at the model level. Each tick sends:

- current market and account state
- current position
- computed features (with `indicator_catalog` listing all available indicators)
- recent transition summaries
- risk limits
- a compact agent summary

The CLI agent then returns one strict JSON action. The runtime remains the single owner of execution, validation, and transition persistence.

Additional CLI options for agent exec:

```bash
--model <model>                   # Model override (e.g. sonnet, opus)
--timeout-seconds <seconds>       # Decision timeout (default: 45)
--extra-instructions <text>       # Extra prompt instructions
--strategy-context <text>         # Strategy context hint
--recent-transitions <count>      # Transition memory depth (default: 5)
```

The prompt contract is externalized in:

- `arena_agent/agents/prompt_template.md`
- `arena_agent/agents/action_schema.json`

That makes the state contract and action contract explicit for any CLI-backed agent.

## Auto Mode (Setup + Runtime Loop)

The `auto` subcommand runs the full setup → rule policy → runtime loop:

```bash
arena-agent-runtime auto --competition-id 9 --agent claude --setup-interval 300
```

Each cycle:
1. **Setup agent** (LLM) analyzes context and returns a flat decision: policy, params, TP/SL%, sizing%, direction bias
2. Decision is translated to internal config and applied (policy dict replaced on type change, rest deep-merged)
3. **Rule policy** runs for N deterministic iterations (N = next_check_seconds / tick_interval)
4. Strategy layer applies sizing, TP/SL, entry filters, and exit rules to every trade
5. Loop back to step 1

The setup agent uses a flat, percentage-based schema — no nested config paths:

```json
{
  "action": "update",
  "policy": "rsi_mean_reversion",
  "policy_params": {"rsi_period": 14, "oversold": 30, "overbought": 70},
  "tp_pct": 1.2,
  "sl_pct": 0.5,
  "sizing_fraction": 8,
  "direction_bias": "short_only",
  "reason": "bearish trend, switching to RSI extremes",
  "next_check_seconds": 1200
}
```

Guardrails:
- **Strategy cooldown**: 20 min or 5 trades between changes (bypassed only on >3% drawdown)
- **Bounds enforcement**: tp_pct [0.1-5.0], sl_pct [0.1-3.0], sizing [1-20]%
- **Naked order protection**: if strategy.refine() fails, action demoted to HOLD
- **Per-strategy performance**: setup agent sees stats for the current strategy, not just overall

Options:

```bash
--competition-id <id>         # Required
--agent <backend>             # claude, gemini, openclaw, codex, auto
--model <model>               # Model for setup agent
--setup-model <model>         # Model override for setup agent
--setup-interval <seconds>    # Default seconds between setup checks (default: 300)
--timeout-seconds <seconds>   # Decision timeout (default: 120)
--config <path>               # Base YAML config
--dry-run                     # Dry run mode (no real trades)
```

## Terminal Observability Monitor

The runtime exposes a direct local observability stream for terminal monitoring. This is not a log parser. The runtime publishes structured snapshots over a localhost TCP stream, and the monitor renders:

- current market state
- account and position state
- computed features
- last decision and execution result
- recent transitions
- runtime and agent warnings/errors

The snapshot carries explicit health metrics, including:

- decision latency
- last decision age
- last transition age
- runtime error counts
- agent error counts (cli_errors, tap_errors)
- rejected action counts

Run the agent and TUI in two terminals:

```bash
# Terminal 1: agent
.venv/bin/python -m arena_agent run --agent claude --config arena_agent/config/codex_agent_config.yaml

# Terminal 2: TUI monitor
.venv/bin/python -m arena_agent monitor --port 8767
```

The current live configs expose monitor ports:

- `arena_agent/config/agent_live.yaml`
  - `127.0.0.1:8765`
- `arena_agent/config/codex_agent_config.yaml`
  - `127.0.0.1:8767`

The Textual UI is an optional dependency. Install it locally with:

```bash
.venv/bin/pip install textual rich
```

If the runtime cannot bind the monitor port, trading still continues and the runtime keeps an internal observability snapshot, but the external TUI will not be able to attach until the port issue is fixed.

For a minimal `systemd --user` supervisor, a ready-to-install unit template is available at:

- `ops/systemd/arena-agent.service`

## Configuration

Configs live in `arena_agent/config/`.

- `agent_config.yaml`
  - local rule/ensemble runtime example
- `codex_agent_config.yaml`
  - agent exec policy with `indicator_mode: full`
- `tap_agent_config.yaml`
  - external HTTP policy example
- `agent_live.yaml`
  - production monitoring setup

`VARSITY_API_KEY` must be injected via the runtime environment before starting the runtime.

Example:

```bash
export VARSITY_API_KEY='...'
python3 -m arena_agent --config arena_agent/config/agent_config.yaml
```

For local convenience, this repo also supports an ignored runtime env file:

- `.env.runtime.local`
- `.env.runtime.local.example`

Example:

```bash
cp .env.runtime.local.example .env.runtime.local
# fill in VARSITY_API_KEY once
```

## Verification status

Local verification currently passes:

- `python3 -m pytest tests/ -v`

Current automated tests cover:

- state normalization
- versioned signal-state contract
- TA-Lib-backed indicator computation
- policy-driven indicator resolution (full, custom, fallback)
- inferred position fallback from unresolved live trades
- execution sizing and validation
- transition-oriented runtime flow
- optional reward derivation from transitions
- TAP request/response translation
- Claude decision rationale capture and normalization
- TAP HTTP fallback behavior
- MCP tool wrappers
- SDK view and action helpers
- agent exec policy with both Claude Code and Codex backends
- CLI backend auto-detection and markdown fence stripping

## Known limitations

- Live Arena reads, MCP calls, SDK calls, requested indicator computation, and real Arena trade writes have been exercised from this environment.
- A live Claude-driven run opened and managed real positions successfully, and a Claude-opened live trade was closed profitably in one earlier run.
- Timed live runs can still end with an open position unless the runner explicitly closes it at shutdown.

## File map

```text
arena_agent/
  core/         runtime loop, models, adapter, state builder
  features/     versioned feature engine, indicator registry, and presets
  interfaces/   action schema and policy interface
  execution/    order execution
  memory/       transition store and journal
  agents/       agent exec policy, setup agent, built-in rule policies, reward models
  setup/        setup agent context builder and cross-competition memory
  tap/          minimal external-agent HTTP adapter
  skills/       local CLI skill implementations
  mcp/          MCP server and plain tool wrappers (47 tools)
  sdk/          thin developer SDK on top of MCP
  tui/          Textual terminal monitor
  config/       sample configs
  observability/ runtime health monitoring and TCP snapshot streaming
tests/          unit tests
run_agent.py
run_mcp_server.sh
run_continuous_agent.sh
examples/sdk_quickstart.py
ops/systemd/arena-agent.service
```
