import { z } from "zod";

export const symbols = {
  name: "arena.symbols",
  description:
    "List all available trading symbols (BTCUSDT, ETHUSDT, etc.) with precision and min quantity config.",
  inputSchema: z.object({}),
  pythonTool: "varsity.symbols",
};

export const orderbook = {
  name: "arena.orderbook",
  description: "Get order book snapshot (bids & asks) for a trading symbol.",
  inputSchema: z.object({
    symbol: z.string().describe("Trading pair, e.g. 'BTCUSDT'."),
    depth: z
      .number()
      .int()
      .optional()
      .default(20)
      .describe("Price levels per side (5, 10, 20, 50). Default 20."),
  }),
  pythonTool: "varsity.orderbook",
};

export const klines = {
  name: "arena.klines",
  description:
    "Get OHLCV candlestick data for a symbol. Use for price charts and technical analysis.",
  inputSchema: z.object({
    symbol: z.string().describe("Trading pair, e.g. 'BTCUSDT'."),
    interval: z
      .enum(["1m", "5m", "15m", "1h", "4h", "1d"])
      .describe("Candle interval."),
    size: z
      .number()
      .int()
      .optional()
      .default(500)
      .describe("Number of candles (max 1500). Default 500."),
    start_time: z
      .number()
      .int()
      .optional()
      .describe("Start timestamp in Unix milliseconds."),
    end_time: z
      .number()
      .int()
      .optional()
      .describe("End timestamp in Unix milliseconds."),
  }),
  pythonTool: "varsity.klines",
};

export const marketInfo = {
  name: "arena.market_info",
  description:
    "Get full market info for a symbol: last price, mark price, index price, funding rate, 24h volume.",
  inputSchema: z.object({
    symbol: z.string().describe("Trading pair, e.g. 'BTCUSDT'."),
  }),
  pythonTool: "varsity.market_info",
};

export const all = [symbols, orderbook, klines, marketInfo] as const;
