import { z } from "zod";

export const setupDecide = {
  name: "arena.setup_decide",
  description:
    "Run the LLM setup agent to decide config changes for a competition. " +
    "Returns action (update/hold), overrides to apply, reason, and whether runtime needs restart.",
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
