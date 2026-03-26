// Diagram definitions with semantic annotations

import type { Annotation } from "./types.js";

export interface DiagramDef {
  name: string;
  title: string;
  outputFile: string;
  mermaid: string;
  annotations: Annotation[];
}

export const DIAGRAMS: DiagramDef[] = [
  {
    name: "two-loop-architecture",
    title: "Two-Loop Architecture",
    outputFile: "two-loop-architecture.excalidraw",
    mermaid: `graph TD
    subgraph "Outer Loop (LLM) — every 10-60 min"
        A[Setup Agent] -->|defines| B["entry_long = rsi_14 < 30 and close > sma_50"]
    end
    subgraph "Inner Loop (deterministic) — every candle"
        C[Expression Engine] -->|evaluates| D{Signal?}
        D -->|Yes| E[Strategy Layer]
        E --> F[Execute Trade]
        D -->|No| G[HOLD]
    end
    B --> C
    F -->|performance feedback| A`,
    annotations: [
      { text: "~$0.005 / cycle\nno per-tick API calls", nearNode: "A", offsetX: -200, offsetY: 5 },
      { text: "pure math, zero latency", nearNode: "C", offsetX: -190, offsetY: 5 },
      { text: "closes the loop", nearNode: "F", offsetX: 160, offsetY: 0 },
    ],
  },
  {
    name: "dual-tool-path-simple",
    title: "Dual Tool Path",
    outputFile: "dual-tool-path-simple.excalidraw",
    mermaid: `graph TD
    A[Setup Agent] --> B{Backend?}
    B -->|Claude| C["Native MCP<br/>(--mcp-config)"]
    B -->|Gemini / Codex / OpenClaw| D["Tool Proxy<br/>(prompt injection + tool_calls JSON)"]
    C --> E["varsity_tools.dispatch()"]
    D --> E
    E --> F[Arena API]`,
    annotations: [
      { text: "built-in MCP support", nearNode: "C", offsetX: -180, offsetY: 5 },
      { text: "catalog injected into prompt", nearNode: "D", offsetX: 200, offsetY: 5 },
      { text: "same function, zero reimplementation", nearNode: "E", offsetX: 210, offsetY: 0 },
    ],
  },
  {
    name: "context-pipeline-simple",
    title: "Context Engineering Pipeline",
    outputFile: "context-pipeline-simple.excalidraw",
    mermaid: `graph TD
    A["6+ API calls<br/>(market, account,<br/>position, trades,<br/>leaderboard, chat)"] --> B[Context Builder]
    C["Per-strategy<br/>performance isolation"] --> B
    D["Indicator values<br/>for threshold calibration"] --> B
    E["Expression validation<br/>errors from last cycle"] --> B
    B --> F["Structured JSON<br/>~15 keys"]
    F --> G["Prompt Template<br/>(role + schema + guidelines)"]
    G --> H["Complete Prompt"]`,
    annotations: [
      { text: "curated, not raw dump", nearNode: "B", offsetX: 200, offsetY: 0 },
      { text: "LLM sees this →\nminimize cognitive load", nearNode: "H", offsetX: 190, offsetY: 0 },
    ],
  },
  {
    name: "context-pipeline-full",
    title: "Full Setup Agent Context Pipeline",
    outputFile: "context-pipeline-full.excalidraw",
    mermaid: `graph TD
    A[API Calls] --> B[Context Builder]
    C[Runtime Config] --> B
    D[Trade History] --> B
    E[Competition Memory] --> B
    B --> F[JSON Context<br/>~15 keys]
    F --> G[Prompt Template]
    H[Tool Catalog] --> G
    G --> I[Complete Prompt<br/>2-50KB]
    I --> J[LLM]
    J --> K[Tool Proxy Loop]
    K --> L[Final Decision JSON]
    L --> M[Decision Parser]
    M --> N[Cooldown Filter]
    N --> O[Config Overrides]`,
    annotations: [
      { text: "6+ live endpoints", nearNode: "A", offsetX: -160, offsetY: 5 },
      { text: "max 5 rounds, 80KB budget", nearNode: "K", offsetX: 200, offsetY: 0 },
      { text: "prevents spam trading", nearNode: "N", offsetX: 185, offsetY: 0 },
    ],
  },
  {
    name: "expression-engine-flow",
    title: "Expression Engine Decision Flow",
    outputFile: "expression-engine-flow.excalidraw",
    mermaid: `graph TD
    A[Expression Policy] --> B{Warmup complete?}
    B -->|No| C[HOLD - indicators still computing]
    B -->|Yes| D{Validation errors?}
    D -->|Yes| E[HOLD - report errors to setup agent]
    D -->|No| F[Build namespace from signal_state]
    F --> G{Position open?}
    G -->|Yes| H{Eval exit expression}
    H -->|True| I[CLOSE_POSITION]
    H -->|False| J[HOLD]
    G -->|No| K{Eval entry_long}
    K -->|True| L[OPEN_LONG]
    K -->|False| M{Eval entry_short}
    M -->|True| N[OPEN_SHORT]
    M -->|False| O[HOLD]`,
    annotations: [
      { text: "AST-validated\n158 indicators available", nearNode: "A", offsetX: -210, offsetY: 5 },
      { text: "safe eval() — empty __builtins__", nearNode: "F", offsetX: 220, offsetY: 0 },
      { text: "errors fed back\nto LLM next cycle", nearNode: "E", offsetX: 200, offsetY: 0 },
    ],
  },
  {
    name: "dual-tool-path-detailed",
    title: "Dual Tool Path — Detailed",
    outputFile: "dual-tool-path-detailed.excalidraw",
    mermaid: `graph TD
    A[Setup Agent] --> B{Which backend?}
    B -->|Claude| C[Native MCP Path]
    B -->|Gemini / Codex / OpenClaw| D[Tool Proxy Path]
    C --> E["claude -p --mcp-config .mcp.json"]
    E --> F[MCP Server - TypeScript]
    F --> G[Python Bridge - stdio]
    G --> H["varsity_tools.dispatch()"]
    D --> I["Inject tool catalog into prompt"]
    I --> J[LLM returns tool_calls JSON]
    J --> K["Execute locally via dispatch()"]
    K --> L[Append results to prompt]
    L --> M{More tool calls?}
    M -->|Yes| J
    M -->|No| N[Final decision]
    H --> O[Arena API]
    K --> O`,
    annotations: [
      { text: "per-call --mcp-config", nearNode: "E", offsetX: -200, offsetY: 0 },
      { text: "budget: 80KB total\nmax 5 rounds", nearNode: "M", offsetX: 210, offsetY: 0 },
      { text: "same dispatch() →\nzero reimplementation", nearNode: "O", offsetX: 200, offsetY: 0 },
    ],
  },
];
