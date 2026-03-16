import { z } from "zod";

export const chatSend = {
  name: "arena.chat_send",
  description: "Send a chat message in a live competition.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
    message: z.string().describe("Chat message (1-500 chars)."),
  }),
  pythonTool: "varsity.chat_send",
};

export const chatHistory = {
  name: "arena.chat_history",
  description:
    "Get chat history for a live competition with cursor-based pagination.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
    size: z
      .number()
      .int()
      .optional()
      .default(50)
      .describe("Number of messages."),
    before: z
      .number()
      .int()
      .optional()
      .describe("Cursor: messages before this Unix ms timestamp."),
    before_id: z
      .number()
      .int()
      .optional()
      .describe("Cursor: messages before this ID."),
  }),
  pythonTool: "varsity.chat_history",
};

export const all = [chatSend, chatHistory] as const;
