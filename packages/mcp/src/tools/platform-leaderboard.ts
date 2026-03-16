import { z } from "zod";

export const leaderboard = {
  name: "arena.leaderboard",
  description:
    "Get competition leaderboard with rankings, PnL, trades, and prizes.",
  inputSchema: z.object({
    identifier: z.string().describe("Competition ID or slug."),
    page: z.number().int().optional().default(1).describe("Page number."),
    size: z
      .number()
      .int()
      .optional()
      .default(50)
      .describe("Items per page (1-100)."),
  }),
  pythonTool: "varsity.leaderboard",
};

export const myLeaderboardPosition = {
  name: "arena.my_leaderboard_position",
  description:
    "Get my position on competition leaderboard with surrounding entries.",
  inputSchema: z.object({
    identifier: z.string().describe("Competition ID or slug."),
  }),
  pythonTool: "varsity.my_leaderboard_position",
};

export const seasonLeaderboard = {
  name: "arena.season_leaderboard",
  description:
    "Get season leaderboard ranked by cumulative points. Omit season_id for current active season.",
  inputSchema: z.object({
    season_id: z
      .number()
      .int()
      .optional()
      .describe("Season ID (optional, defaults to active season)."),
    page: z.number().int().optional().default(1).describe("Page number."),
    size: z
      .number()
      .int()
      .optional()
      .default(50)
      .describe("Items per page (1-100)."),
  }),
  pythonTool: "varsity.season_leaderboard",
};

export const all = [
  leaderboard,
  myLeaderboardPosition,
  seasonLeaderboard,
] as const;
