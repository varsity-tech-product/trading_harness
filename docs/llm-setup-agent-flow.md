# LLM Setup Agent Flow

How the AI agent explores indicators, builds strategies, and trades autonomously.

---

## Overview

The agent runs as a persistent daemon that cycles through competitions. Each cycle has two phases:

1. **Setup phase** — LLM analyzes market, explores indicators, configures strategy
2. **Runtime phase** — Expression engine evaluates strategy every tick, executes trades

### Setup Phase — LLM Decision Flow

```mermaid
flowchart TD
    CTX[Build Context<br/>market + account + position<br/>+ indicator ranges + errors] --> PROMPT[Render Prompt<br/>+ tool catalog]
    PROMPT --> LLM_CALL[LLM Call]

    LLM_CALL --> TOOL_CHECK{tool_calls<br/>in response?}
    TOOL_CHECK -->|yes| EXEC_TOOLS[Execute Tools<br/>query_indicators / get_klines / etc.]
    EXEC_TOOLS --> APPEND[Append results to prompt]
    APPEND --> LLM_CALL

    TOOL_CHECK -->|no| PARSE[Parse Decision<br/>normalize sizing / TP / SL]
    PARSE --> MODE{Mode?}

    MODE -->|rule_based| RB_ACTION{Action?}
    RB_ACTION -->|update| COOLDOWN{Strategy<br/>cooldown<br/>active?}
    COOLDOWN -->|yes| DEMOTE[Demote to hold]
    COOLDOWN -->|no| MERGE[Deep-merge overrides<br/>into config_dict]
    DEMOTE --> RUNTIME
    MERGE --> RUNTIME
    RB_ACTION -->|hold| RUNTIME[Runtime Phase<br/>expression engine evaluates<br/>each tick for 10-20 min]

    MODE -->|discretionary| DISC_ACTION{Action?}
    DISC_ACTION -->|trade| DISC_EXEC[Execute Trade<br/>open / close / tpsl]
    DISC_EXEC --> DISC_SLEEP
    DISC_ACTION -->|hold| DISC_SLEEP[Sleep next_check_seconds<br/>min 600s]

    RUNTIME --> FEEDBACK[Feedback Loop<br/>expression errors + indicator ranges<br/>stored for next cycle]
    DISC_SLEEP --> NEXT[Next Setup Cycle]
    FEEDBACK --> NEXT
```

### query_indicators Tool Flow

```mermaid
sequenceDiagram
    participant LLM as LLM (Setup Agent)
    participant Proxy as Tool Proxy
    participant Engine as FeatureEngine
    participant API as Arena API

    LLM->>Proxy: {"tool_calls": [{"tool": "query_indicators",<br/>"args": {"indicators": ["RSI_14", "CCI_14", "ADX_14", "BBANDS_20"]}}]}

    Proxy->>API: GET /market/kline/BTCUSDT?interval=1m&size=120
    API-->>Proxy: 120 candles

    Proxy->>Engine: compute(candles, [RSI_14, CCI_14, ADX_14, BBANDS_20])
    Engine-->>Proxy: indicator values (current + sliding window min/max)

    Proxy-->>LLM: {"indicators": {<br/>"rsi_14": {"current": 48.2, "min": 41.5, "max": 59.3},<br/>"cci_14": {"current": -12.4, "min": -45.2, "max": 38.7},<br/>"adx_14": {"current": 15.8, "min": 9.1, "max": 22.3},<br/>"bbands_upper": {"current": 66900, "min": 66850, "max": 66950}}}

    Note over LLM: RSI range 41-59 → set entry_long rsi < 42<br/>ADX low → ranging market, use mean-reversion<br/>CCI range small → skip CCI

    LLM->>Proxy: {"action": "update",<br/>"policy_params": {"entry_long": "rsi_14 < 42 and close > bbands_lower", ...},<br/>"indicators": ["RSI_14", "BBANDS_20"],<br/>"sizing_fraction": 80, "tp_pct": 2.0, "sl_pct": 1.0}
```

### Expression Validation Flow

```mermaid
flowchart LR
    EXPR[Expression from LLM] --> SYNTAX{AST Parse}
    SYNTAX -->|syntax error| ERR1[Error: syntax]
    SYNTAX -->|unsafe node: Call| ERR2[Error: no abs/max/min]
    SYNTAX -->|ok| NS{Variable in<br/>namespace?}
    NS -->|adx_14 not found| ERR3["Error: undefined variable<br/>Available: [adx_timeperiod_14, ...]"]
    NS -->|all found| OVERLAP{Entry + Exit<br/>both true?}
    OVERLAP -->|yes| ERR4["Error: exit overlaps entry<br/>positions will close immediately"]
    OVERLAP -->|no| VALID[Valid — engine evaluates each tick]

    ERR1 --> FEEDBACK_LLM[Errors fed back to LLM<br/>via context.expression_errors]
    ERR2 --> FEEDBACK_LLM
    ERR3 --> FEEDBACK_LLM
    ERR4 --> FEEDBACK_LLM
    FEEDBACK_LLM --> FIX[LLM fixes on next cycle]
```

---

## Phase 1: Pre-Checks

Before each setup cycle, the daemon checks:

1. **Competition status** — is it live, completed, cancelled?
   - If completed → `_find_next_competition()` → auto-register → switch → continue
   - If not live yet → sleep until `startTime`, re-check in 5-min intervals
2. **Auto-register** — scan `registration_open` and `announced` competitions, register for any new ones
3. **Account check** — verify engine account exists (agent is provisioned)

### First-Cycle Indicator Seeding

On the very first cycle (no `_indicator_ranges` in config yet), the daemon runs a one-shot `StateBuilder.build()` to compute the default indicators (RSI_14, SMA_20, OBV) from historical klines. This gives the LLM basic ranges before the first setup call.

---

## Phase 2: Setup (LLM Decision)

### Step 1: Build Context

`build_setup_context()` fetches live data and assembles a JSON context:

```
context = {
    mode                    # "rule_based" or "discretionary"
    STRATEGY_LOCKED         # if cooldown active, LLM must hold
    market_summary          # price, trend, volatility (1m/5m/15m)
    account_state           # equity, balance, PnL, trade count
    position                # current open position (or null)
    competition             # status, time remaining, fee rate, max trades
    current_strategy        # policy type, params, age, cooldown status
    current_indicator_values # {indicator: {current, min, max}} — rolling 30-tick window
    expression_errors       # errors from previous cycle (undefined vars, overlap)
    performance             # win rate, PnL, consecutive direction losses
    leaderboard             # rank and total participants
    chat_recent             # last 30 messages
}
```

### Step 2: Render Prompt

The context JSON is injected into `setup_prompt_template.md`, which instructs the LLM to:

1. Call `query_indicators` as its first action
2. Use returned ranges to set realistic thresholds
3. Return a JSON decision (update/hold/trade)

### Step 3: LLM Tool Loop

The LLM can make tool calls across multiple rounds (max 5 rounds, 3 tools per round):

```
Round 1: LLM → {"tool_calls": [{"tool": "query_indicators", "args": {"indicators": ["RSI_14", "CCI_14", "BBANDS_20", "ADX_14"]}}]}
         System → executes query_indicators → returns {rsi_14: {current: 48, min: 41, max: 59}, ...}

Round 2: LLM sees indicator ranges → makes strategy decision
         LLM → {"action": "update", "policy_params": {"entry_long": "rsi_14 < 42 and close > bbands_lower", ...}}
```

The `query_indicators` tool computes any TA-Lib indicator from historical klines and returns current/min/max over a 30-candle window. The LLM explores broadly, then picks only the useful indicators for its strategy.

### Step 4: Parse Decision

`_parse_decision()` extracts and normalizes the LLM's response:

- **Sizing**: `_normalize_sizing()` — converts 0.8 → 80%, clamps to 10-100%
- **TP/SL**: clamps tp_pct to 0.5-5.0%, sl_pct to 0.3-3.0%
- **Indicators**: parses `"RSI_14"` → `FeatureSpec(indicator="RSI", params={"timeperiod": 14})`
- **Expressions**: validated for safe AST (no function calls like `abs()`, `max()`)

### Step 5: Cooldown Enforcement

`_apply_cooldown()` prevents strategy thrashing:

- After a strategy change, must wait **20 minutes** or **5 completed trades** before changing again
- Exception: bypass if drawdown exceeds 3%
- If cooldown active, "update" is demoted to "hold"

### Step 6: Apply to Config

`_deep_merge(config_dict, decision.overrides)` merges the LLM's changes:

- `strategy.sizing` and `strategy.tpsl` are replaced wholesale
- Other fields are recursively merged
- Reset tracking: `_strategy_start_time`, `_strategy_start_trade_count`

---

## Phase 3: Runtime (Expression Engine)

### Policy Construction

`build_policy(config)` creates an `ExpressionPolicy` with:

```python
ExpressionPolicy(
    entry_long  = "rsi_14 < 42 and close > bbands_lower",
    entry_short = "rsi_14 > 58 and close < bbands_upper",
    exit_expr   = "rsi_14 > 50 and rsi_14 < 45",
    reentry_cooldown_seconds = 300,
)
```

### Expression Validation (3 levels)

1. **Syntax validation** (at construction) — AST parsing, only safe nodes allowed
2. **Namespace validation** (on first tick) — checks all referenced variables exist in the runtime namespace. Catches `adx_14` vs `adx_timeperiod_14` mismatches. Shows available keys so LLM can fix.
3. **Overlap detection** (on first tick) — if entry and exit both evaluate to True on current values, positions would close immediately. Flagged as error.

Errors are stored in `_validation_errors` and fed back to the LLM on the next setup cycle via `context["expression_errors"]`.

### Tick-by-Tick Evaluation

Each tick (60s for 1m candles):

```
StateBuilder.build()
  → fetch klines, market, account, position
  → FeatureEngine.compute(candles) → indicator values
  → build namespace: {rsi_14: 45.2, close: 66800, sma_20: 66750, ...}

ExpressionPolicy.decide(state)
  → if has_position:
      eval(exit_expr, namespace) → True? → CLOSE_POSITION (stamp reentry cooldown)
  → else:
      if reentry_cooldown active → HOLD
      eval(entry_long, namespace) → True? → OPEN_LONG
      eval(entry_short, namespace) → True? → OPEN_SHORT
      else → HOLD

StrategyLayer.refine(action)
  → add TP/SL prices from percentage config

OrderExecutor.execute(action, state)
  → call Arena API (trade/open, trade/close, trade/tpsl)
  → return ExecutionResult(accepted, executed, fee, pnl)
```

### Reentry Cooldown

After a `CLOSE_POSITION`, entry signals are suppressed for 300 seconds (configurable via `reentry_cooldown_seconds`). Prevents the rapid open→close→open churning that occurred when RSI oscillated between entry/exit thresholds on consecutive ticks.

---

## Phase 4: Feedback Loop

After the runtime cycle completes, state is fed back to `config_dict` for the next setup:

| Feedback | Source | Destination |
|----------|--------|-------------|
| Expression errors | `policy._validation_errors` | `context["expression_errors"]` |
| Indicator values | `state_builder._last_signal_values` | `context["current_indicator_values"]` |
| Indicator ranges (30-tick min/max) | `state_builder._indicator_ranges` | `context["current_indicator_values"]` |

The LLM sees these on the next cycle and can:
- Fix broken expressions (undefined variables, overlap)
- Calibrate thresholds to actual indicator ranges
- Switch indicator families if current ones aren't useful

---

## Discretionary Mode

When the LLM switches to `mode: "discretionary"`:

- No expression engine — LLM makes trade decisions directly
- Returns `action: "trade"` with `trade: {type: "OPEN_LONG", tp_pct: 1.5, sl_pct: 0.8, sizing_fraction: 80}`
- Runtime executes the trade immediately via `_execute_discretionary_trade()`
- Next check interval: minimum 600s (same as rule-based)

---

## Guardrails Summary

| Guardrail | What it prevents | Default |
|-----------|-----------------|---------|
| Expression namespace validation | Dead zones from undefined variables | Always on |
| Exit/entry overlap detection | 1-minute round trips from self-defeating exits | Always on |
| Reentry cooldown | Rapid-fire open→close→open churning | 300s |
| Strategy change cooldown | LLM thrashing between strategies | 20 min or 5 trades |
| Sizing normalization | Micro-positions from decimal parsing (0.8 → 80%) | Min 10% |
| TP/SL minimums | Trades that can't overcome fees | TP ≥ 0.5%, SL ≥ 0.3% |
| Chat rate limit | Chat spam | Once per 5 cycles |
| Min check interval | Token waste from frequent setup cycles | 600s (all modes) |

---

## Competition Transitions

The daemon never stops. When a competition ends:

```
Competition completed
  → _find_next_competition()
    → check registrations (prefer newest by startTime)
    → auto-register for any registration_open competitions
    → return best competition ID
  → switch competition_id
  → reset indicator ranges (new market conditions)
  → continue loop → wait for live → start trading
```
