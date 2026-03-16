import { z } from "zod";

export const liveTrades = {
  name: "arena.live_trades",
  description: "List my completed trades in a live competition.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
  }),
  pythonTool: "varsity.live_trades",
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

export const all = [liveTrades, livePosition, liveAccount] as const;
