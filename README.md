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

## External-agent support

There is a minimal TAP layer in `arena_agent/tap/` for plug-in agents.

- Request: `POST /decision`
- Payload: `{"timestamp": ..., "state": {...}}`
- Response: `{"action": {...}}`

This is deliberately minimal and not a larger protocol framework.

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
- inferred position fallback from unresolved live trades
- execution sizing and validation
- transition-oriented runtime flow
- optional reward derivation from transitions
- TAP request/response translation
- TAP HTTP fallback behavior

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
  config/       sample configs
tests/          unit tests for runtime, executor, state builder, TAP
run_live_tap_once.sh
```
