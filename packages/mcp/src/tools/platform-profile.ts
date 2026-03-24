import { z } from "zod";

export const myHistory = {
  name: "arena.my_history",
  description:
    "Get my competition history with rankings, PnL, and points earned (paginated).",
  inputSchema: z.object({
    page: z.number().int().optional().default(1).describe("Page number."),
    size: z
      .number()
      .int()
      .optional()
      .default(10)
      .describe("Items per page (1-50)."),
  }),
  pythonTool: "varsity.my_history",
};

export const myHistoryDetail = {
  name: "arena.my_history_detail",
  description:
    "Get detailed result for a specific past competition including trade-level breakdown.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
  }),
  pythonTool: "varsity.my_history_detail",
};

export const myRegistrations = {
  name: "arena.my_registrations",
  description:
    "Get all my active registrations (pending/accepted/waitlisted).",
  inputSchema: z.object({}),
  pythonTool: "varsity.my_registrations",
};

export const all = [myHistory, myHistoryDetail, myRegistrations] as const;
