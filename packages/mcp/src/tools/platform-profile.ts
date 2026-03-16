import { z } from "zod";

export const myProfile = {
  name: "arena.my_profile",
  description:
    "Get the authenticated user's full profile (username, email, role, etc.).",
  inputSchema: z.object({}),
  pythonTool: "varsity.my_profile",
};

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

export const achievements = {
  name: "arena.achievements",
  description:
    "Get the full achievement catalog with my unlock status for each badge.",
  inputSchema: z.object({}),
  pythonTool: "varsity.achievements",
};

export const publicProfile = {
  name: "arena.public_profile",
  description: "Get a user's public arena profile by username.",
  inputSchema: z.object({
    username: z.string().describe("Username to look up."),
  }),
  pythonTool: "varsity.public_profile",
};

export const publicHistory = {
  name: "arena.public_history",
  description: "Get a user's public competition history by username.",
  inputSchema: z.object({
    username: z.string().describe("Username to look up."),
    page: z.number().int().optional().default(1).describe("Page number."),
    size: z
      .number()
      .int()
      .optional()
      .default(10)
      .describe("Items per page (1-50)."),
  }),
  pythonTool: "varsity.public_history",
};

export const updateProfile = {
  name: "arena.update_profile",
  description: "Update the authenticated user's profile fields.",
  inputSchema: z.object({
    username: z
      .string()
      .optional()
      .describe("New username (3-50 chars, unique)."),
    display_name: z
      .string()
      .optional()
      .describe("Display name (max 64 chars)."),
    bio: z.string().optional().describe("Bio (max 280 chars)."),
    country: z
      .string()
      .optional()
      .describe("ISO alpha-2 country code (e.g. 'US')."),
    participant_type: z
      .enum(["student", "professional", "independent"])
      .optional()
      .describe("Participant type."),
  }),
  pythonTool: "varsity.update_profile",
};

export const all = [
  myProfile,
  myHistory,
  myHistoryDetail,
  achievements,
  publicProfile,
  publicHistory,
  updateProfile,
] as const;
