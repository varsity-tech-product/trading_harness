import { z } from "zod";

export const notifications = {
  name: "arena.notifications",
  description: "Get paginated notifications.",
  inputSchema: z.object({
    page: z.number().int().optional().default(1).describe("Page number."),
    size: z
      .number()
      .int()
      .optional()
      .default(20)
      .describe("Items per page (1-100)."),
  }),
  pythonTool: "varsity.notifications",
};

export const unreadCount = {
  name: "arena.unread_count",
  description:
    "Get count of unread notifications (lightweight, good for polling).",
  inputSchema: z.object({}),
  pythonTool: "varsity.unread_count",
};

export const markRead = {
  name: "arena.mark_read",
  description: "Mark a single notification as read.",
  inputSchema: z.object({
    notification_id: z.number().int().describe("Notification ID."),
  }),
  pythonTool: "varsity.mark_read",
};

export const markAllRead = {
  name: "arena.mark_all_read",
  description: "Mark all notifications as read.",
  inputSchema: z.object({}),
  pythonTool: "varsity.mark_all_read",
};

export const all = [notifications, unreadCount, markRead, markAllRead] as const;
