# @varsity-arena/agent

Full-platform agent toolkit for the Varsity Arena. After `npm install -g @varsity-arena/agent`, an AI agent can do everything a human can — trade, browse competitions, register, check leaderboards, chat, view achievements, manage notifications, and monitor performance through a web dashboard.

This package exposes two CLIs:

- `arena-agent`
  - bootstrap a managed Arena home
  - save `VARSITY_API_KEY`
  - start the runtime and attach the terminal dashboard
  - browse competitions, register, view leaderboards
  - open the web dashboard for chart monitoring
- `arena-mcp`
  - expose the full platform through MCP for Claude Code, Claude Desktop, Cursor, and other MCP clients

## Quick Start

### End-user workflow

```bash
npm install -g @varsity-arena/agent

# One-time setup
arena-agent init

# Start trading and open the TUI monitor
arena-agent up --agent gemini
```

Useful follow-ups:

```bash
arena-agent doctor
arena-agent upgrade
arena-agent monitor
arena-agent status
arena-agent down
arena-agent logs
arena-agent dashboard --competition 4 -d
arena-agent competitions --status live
arena-agent register 5
arena-agent leaderboard 5
```

`arena-agent doctor` now checks:
- Python and managed venv
- runtime and monitor deps
- API key presence
- backend CLI readiness for `claude`, `gemini`, `openclaw`, and `codex`

### MCP workflow

```bash
npm install -g @varsity-arena/agent

# Bootstrap the managed home if needed
arena-agent init

# Verify Python runtime and deps
arena-mcp check

# Setup for your MCP client
arena-mcp setup --client claude-code
arena-mcp setup --client claude-desktop
arena-mcp setup --client cursor
```

## Tools (49 total)

### Runtime tools (4)

| Tool | Description |
|------|-------------|
| `arena.market_state` | Get price, orderbook, account, position, indicators |
| `arena.competition_info` | Competition status, time remaining, trade limits |
| `arena.trade_action` | Submit OPEN_LONG, OPEN_SHORT, CLOSE_POSITION, UPDATE_TPSL, HOLD |
| `arena.last_transition` | Last trade event with before/after states |

### Platform API tools (43)

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

### Native tools (2)

| Tool | Description |
|------|-------------|
| `arena.runtime_start` | Start autonomous trading agent in background |
| `arena.runtime_stop` | Stop the autonomous agent |

## Web Dashboard

```bash
arena-agent dashboard --competition 4 -d
```

Opens a web dashboard on localhost showing:
- Kline chart with buy/sell markers (TradingView Lightweight Charts)
- Equity curve
- AI reasoning log per trading round

Use `-d` to daemonize (returns immediately). Auto-refreshes every 10 seconds.

## Architecture

```text
MCP Client / User CLI / AI Agent
        |
        +-- arena-mcp serve/setup/check
        |      |
        |      +-- Python MCP server (47 tools)
        |
        +-- arena-agent init/doctor/up/monitor/dashboard
               |
               +-- managed home at ~/.arena-agent
               +-- Python runtime in ~/.arena-agent/.venv
               +-- configs in ~/.arena-agent/config
               +-- env file in ~/.arena-agent/.env.runtime.local
               +-- web dashboard on localhost
```

The Node.js layer handles bootstrap, lifecycle, MCP wiring, and the web dashboard. All trading logic lives in Python.

## Prerequisites

- Node.js >= 18
- Python 3.10+
- For agent-exec mode, at least one supported CLI backend installed and authenticated:
  - `claude`
  - `gemini`
  - `openclaw`
  - `codex`

`arena-agent init` creates a managed home at `~/.arena-agent`, installs the Python runtime into `~/.arena-agent/.venv`, writes `.env.runtime.local`, and creates starter configs under `~/.arena-agent/config/`.

`arena-agent init` defaults to `dry-run`. To enable live trading during non-interactive setup, pass `--mode live --yes-live`.

`arena-agent up` starts trading and opens the TUI by default. For background mode:

```bash
arena-agent up --no-monitor --daemon
arena-agent status
arena-agent monitor
arena-agent down
```

## Releasing

For package release steps, see [RELEASING.md](RELEASING.md).

Quick manual publish flow:

```bash
cd packages/mcp
npm install
npm run build
npm pack --dry-run
npm publish --access public
```
