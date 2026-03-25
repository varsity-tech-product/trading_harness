import { z } from "zod";

export const tradeHistory = {
  name: "arena.trade_history",
  description: "List completed trades (history) in a live competition.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
  }),
  pythonTool: "varsity.trade_history",
};

export const livePosition = {
  name: "arena.live_position",
  description:
    "Get my current open position in a live competition (null if no position).",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
  }),
  pythonTool: "varsity.live_position",
};

export const liveAccount = {
  name: "arena.live_account",
  description:
    "Get my engine account state in a live competition: balance, equity, unrealized PnL, trade count.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
  }),
  pythonTool: "varsity.live_account",
};

export const liveInfo = {
  name: "arena.live_info",
  description:
    "Get competition metadata: status, times, trade limits for a live match.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
  }),
  pythonTool: "varsity.live_info",
};

export const all = [tradeHistory, livePosition, liveAccount, liveInfo] as const;
