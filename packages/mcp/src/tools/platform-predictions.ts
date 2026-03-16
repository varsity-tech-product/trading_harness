import { z } from "zod";

export const predictions = {
  name: "arena.predictions",
  description:
    "Get current-hour prediction summary (up/down counts, my prediction, last result).",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
  }),
  pythonTool: "varsity.predictions",
};

export const submitPrediction = {
  name: "arena.submit_prediction",
  description: "Submit a direction prediction for the current hour.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
    direction: z.enum(["up", "down"]).describe("Predicted direction."),
    confidence: z
      .number()
      .int()
      .min(1)
      .max(5)
      .describe("Confidence level 1-5."),
  }),
  pythonTool: "varsity.submit_prediction",
};

export const polls = {
  name: "arena.polls",
  description: "List active polls in a live competition.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
  }),
  pythonTool: "varsity.polls",
};

export const votePoll = {
  name: "arena.vote_poll",
  description: "Vote on an active poll.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
    poll_id: z.number().int().describe("Poll ID."),
    option_index: z.number().int().describe("Zero-based option index."),
  }),
  pythonTool: "varsity.vote_poll",
};

export const all = [predictions, submitPrediction, polls, votePoll] as const;
