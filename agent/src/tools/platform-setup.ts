import { z } from "zod";

export const setupDecide = {
  name: "arena.setup_decide",
  description:
    "Run the LLM setup agent to decide config changes or execute discretionary trades. " +
    "Returns action (update/hold/trade), overrides, trade details, mode (rule_based/discretionary), and reason.",
  inputSchema: z.object({
    competition_id: z
      .number()
      .int()
      .describe("Competition ID to analyze and configure strategy for."),
    backend: z
      .enum(["auto", "claude", "gemini", "openclaw", "codex"])
      .optional()
      .default("auto")
      .describe("LLM backend to use for setup decisions."),
    model: z
      .string()
      .optional()
      .describe("Model override (e.g. sonnet, opus)."),
    config_path: z
      .string()
      .optional()
      .describe("Path to runtime YAML config. Omit for default."),
    inactivity_alert: z
      .boolean()
      .optional()
      .describe("Whether the runtime inactivity watchdog is currently active."),
    inactive_minutes: z
      .number()
      .int()
      .optional()
      .describe("Minutes since the inactivity watchdog window started."),
    consecutive_hold_cycles: z
      .number()
      .int()
      .optional()
      .describe("Consecutive setup cycles with zero executed runtime trades."),
    total_runtime_iterations: z
      .number()
      .int()
      .optional()
      .describe("Runtime iterations elapsed since the last strategy change."),
  }),
  pythonTool: "varsity.setup_decide",
};

export const setupRecord = {
  name: "arena.setup_record",
  description:
    "Record a competition result in setup agent memory for future strategy decisions.",
  inputSchema: z.object({
    competition_id: z
      .number()
      .int()
      .describe("Competition ID to record results for."),
    title: z
      .string()
      .optional()
      .default("")
      .describe("Competition title."),
    strategy_summary: z
      .string()
      .optional()
      .default("")
      .describe("Summary of the strategy used."),
    adjustments_made: z
      .number()
      .int()
      .optional()
      .default(0)
      .describe("Number of mid-competition config adjustments."),
  }),
  pythonTool: "varsity.setup_record",
};

export const all = [setupDecide, setupRecord] as const;
