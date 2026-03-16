import { z } from "zod";

export const competitions = {
  name: "arena.competitions",
  description:
    "List competitions with optional filters (season, status, type). Returns paginated results.",
  inputSchema: z.object({
    season_id: z.number().int().optional().describe("Filter by season ID."),
    status: z
      .enum([
        "draft",
        "announced",
        "registration_open",
        "registration_closed",
        "live",
        "settling",
        "completed",
        "ended_early",
        "cancelled",
      ])
      .optional()
      .describe("Filter by status."),
    competition_type: z
      .enum(["regular", "grand_final", "special", "practice"])
      .optional()
      .describe("Filter by competition type."),
    page: z.number().int().optional().default(1).describe("Page number."),
    size: z
      .number()
      .int()
      .optional()
      .default(20)
      .describe("Items per page (1-100)."),
  }),
  pythonTool: "varsity.competitions",
};

export const competitionDetail = {
  name: "arena.competition_detail",
  description:
    "Get full competition detail including rules, prize tables, and registration windows.",
  inputSchema: z.object({
    identifier: z
      .string()
      .describe("Competition ID (number) or slug (string)."),
  }),
  pythonTool: "varsity.competition_detail",
};

export const participants = {
  name: "arena.participants",
  description:
    "List accepted participants for a competition (public, paginated).",
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
  pythonTool: "varsity.participants",
};

export const all = [competitions, competitionDetail, participants] as const;
