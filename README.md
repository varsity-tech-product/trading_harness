# Arena Trading Agent Runtime

Current status: this repo contains a working v1 trading-agent runtime for the Varsity Arena API. The current runtime also includes a versioned `signal_state.v1` contract backed by a feature engine that prefers TA-Lib when available and falls back to builtin indicators otherwise.

## Quick Start

For most users, the recommended workflow is:

```bash
npm install -g @varsity-arena/agent
arena-agent init
arena-agent doctor
arena-agent up --agent gemini
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

- `arena-agent init` creates `~/.arena-agent`, stores your `VARSITY_API_KEY`, installs the Python runtime into `~/.arena-agent/.venv`, and writes starter configs.
- `arena-agent init` defaults to `dry-run`. Use `--mode live --yes-live` only when you want real order writes.
- Supported agent backends in the current runtime are `claude`, `gemini`, `openclaw`, `codex`, `rule`, and `auto`.
- `openclaw` uses OpenClaw CLI in local mode. Run `arena-agent setup --client openclaw` to configure. For MCP tool access inside OpenClaw, use `--mode mcp`.
- `arena-agent doctor` checks Python, runtime deps, monitor deps, API key presence, backend CLI readiness, and OpenClaw workspace/config health.

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
- Terminal monitor:
  - `arena_agent/tui/`
  - `.venv/bin/python -m arena_agent monitor`

## Current architecture

The runtime is intentionally small:

1. Build `AgentState` from Arena data.
2. Ask a policy for an `Action`.
3. Execute that action with risk checks.
4. Build the next state.
5. Persist a neutral `TransitionEvent`.

The runtime does not own reward logic. If an agent wants a scalar objective, it can derive one from transitions in `arena_agent/agents/reward_models.py`.

The runtime now also owns a versioned `signal_state` contract. Agents can request indicator bundles, and the framework computes them centrally through the feature engine.

Indicator support policy:

- TA-Lib backend is used automatically when available in the runtime environment.
- Builtin fallback backend is used otherwise.
- All TA-Lib indicators that can be computed from runtime market data are supported.
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
- `backend` is `talib`, `builtin`, or `none`.
- `warmup_complete` tells the agent whether every requested feature is ready.
- `indicator_metadata[*].lookback_required` is the normalized warmup requirement for that indicator.
- Use explicit `key` values for indicators with large or structured params.

### Policy-driven indicator selection

The policy can control which indicators are computed via `indicator_mode` in the policy config section:

| Mode | Behavior |
|------|----------|
| `full` | Computes all builtin indicators with default params, plus a curated set of TA-Lib indicators if available. The agent sees everything and picks what matters. |
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
- generic TA-Lib-backed indicators plus builtin fallback
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
  agents/       agent exec policy, built-in rule policies, reward models
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
