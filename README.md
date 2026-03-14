# Arena Trading Agent Runtime

Current status: this repo contains a working v1 trading-agent runtime for the Varsity Arena API, plus the older script-based bots that predate the runtime package.

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
- Legacy scripts:
  - `bot_framework.py`
  - `strategy_1_ma.py`
  - `strategy_2_rsi.py`
  - `strategy_3_breakout.py`
  - `run_all.py`

## Current architecture

The runtime is intentionally small:

1. Build `AgentState` from Arena data.
2. Ask a policy for an `Action`.
3. Execute that action with risk checks.
4. Build the next state.
5. Persist a neutral `TransitionEvent`.

The runtime does not own reward logic. If an agent wants a scalar objective, it can derive one from transitions in `arena_agent/agents/reward_models.py`.

The runtime now also owns a versioned `signal_state` contract. Agents can request a curated set of indicators and parameters, and the framework computes them centrally through the feature engine.

If TA-Lib is available in the runtime environment, the engine can serve the full TA-Lib surface. Indicators that need extra non-OHLCV inputs, such as `MAVP`, can still be used by supplying those series explicitly in the indicator params.

## External-agent support

There is a minimal TAP layer in `arena_agent/tap/` for plug-in agents.

- Request: `POST /decision`
- Payload: `{"timestamp": ..., "state": {...}}`
- Response: `{"action": {...}}`

This is deliberately minimal and not a larger protocol framework.

## Local skill tools

The repo now exposes the runtime as local CLI tools for Codex-style tool use. These tools auto-load `.env.runtime.local` when present and keep secrets in the local host environment rather than passing them to the model.

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

The repo also exposes the same Arena capabilities through a universal MCP server in `arena_agent/mcp/`.

Exposed MCP tools:

- `varsity.market_state`
- `varsity.trade_action`
- `varsity.last_transition`
- `varsity.competition_info`

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

agent = Arena()

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

## Configuration

Configs live in `arena_agent/config/`.

- `agent_config.yaml`
  - local rule/ensemble runtime example
- `tap_agent_config.yaml`
  - external HTTP policy example

`VARSITY_API_KEY` must be injected via the runtime environment before starting the runtime.

Example:

```bash
export VARSITY_API_KEY='...'
python3 -m arena_agent --config arena_agent/config/agent_config.yaml
```

For local convenience, this repo also supports an ignored runtime env file:

- `.env.runtime.local`
- `.env.runtime.local.example`
- `run_live_tap_once.sh`
- `run_mcp_server.sh`

`run_live_tap_once.sh` sources `.env.runtime.local`, starts the local Claude-backed TAP server, and runs one or more runtime iterations without re-entering secrets manually.

Example:

```bash
cp .env.runtime.local.example .env.runtime.local
# fill in VARSITY_API_KEY and CLAUDE_CODE_OAUTH_TOKEN once
./run_live_tap_once.sh 1
```

## Verification status

Local verification currently passes:

- `python3 -m unittest discover -s tests -v`
- `python3 -m compileall arena_agent run_agent.py varsity_tools.py tests`

Current automated tests cover:

- state normalization
- versioned signal-state contract
- inferred position fallback from unresolved live trades
- execution sizing and validation
- transition-oriented runtime flow
- optional reward derivation from transitions
- TAP request/response translation
- TAP HTTP fallback behavior
- MCP tool wrappers
- SDK view and action helpers

## Known limitations

- Live Arena reads and one dry-run TAP-backed runtime iteration have been verified from this environment.
- Real Arena trade writes have not been exercised yet.
- The repo still contains legacy script bots alongside the new runtime.
- The repo currently includes generated files and caches from earlier work; cleanup has not been completed yet.

## File map

```text
arena_agent/
  core/         runtime loop, models, adapter, state builder
  interfaces/   action schema and policy interface
  execution/    order execution
  memory/       transition store and journal
  agents/       built-in policies and optional reward models
  tap/          minimal external-agent HTTP adapter
  skills/       local CLI skill implementations
  mcp/          MCP server and plain tool wrappers
  sdk/          thin developer SDK on top of MCP
  config/       sample configs
tests/          unit tests for runtime, executor, state builder, TAP
run_live_tap_once.sh
run_mcp_server.sh
arena_market_state
arena_trade
arena_last_transition
arena_competition_info
examples/sdk_quickstart.py
```
