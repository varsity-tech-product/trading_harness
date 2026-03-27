import { z } from "zod";

export const myStatus = {
  name: "arena.my_status",
  description:
    "Full agent status in one call: account, position, PnL, rank, competition, and season. Pass competition_id or auto-detects from active registrations.",
  inputSchema: z.object({
    competition_id: z
      .number()
      .int()
      .optional()
      .describe("Competition ID. Omit to auto-detect from active registrations."),
  }),
  pythonTool: "varsity.my_status",
};

export const bestCompetition = {
  name: "arena.best_competition",
  description:
    "Find the best competition to join. Returns top pick with entry requirements, reward, participants, schedule, and alternatives.",
  inputSchema: z.object({}),
  pythonTool: "varsity.best_competition",
};

export const autoJoin = {
  name: "arena.auto_join",
  description:
    "Find the best competition and register for it automatically. Returns registration result or reason for failure.",
  inputSchema: z.object({}),
  pythonTool: "varsity.auto_join",
};

export const all = [myStatus, bestCompetition, autoJoin] as const;
