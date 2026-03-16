import { z } from "zod";

export const tiers = {
  name: "arena.tiers",
  description:
    "List all tier definitions (iron to diamond) with point thresholds and leverage multipliers.",
  inputSchema: z.object({}),
  pythonTool: "varsity.tiers",
};

export const seasons = {
  name: "arena.seasons",
  description: "List all non-archived seasons, sorted by start date descending.",
  inputSchema: z.object({}),
  pythonTool: "varsity.seasons",
};

export const seasonDetail = {
  name: "arena.season_detail",
  description:
    "Get a single season's details including competition counts.",
  inputSchema: z.object({
    season_id: z.number().int().describe("Season ID."),
  }),
  pythonTool: "varsity.season_detail",
};

export const all = [tiers, seasons, seasonDetail] as const;
