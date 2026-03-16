import { z } from "zod";

export const health = {
  name: "arena.health",
  description:
    "Get system health status including database, redis, and matching engine connectivity.",
  inputSchema: z.object({}),
  pythonTool: "varsity.health",
};

export const version = {
  name: "arena.version",
  description: "Get API version and build hash.",
  inputSchema: z.object({}),
  pythonTool: "varsity.version",
};

export const arenaHealth = {
  name: "arena.arena_health",
  description: "Get arena module health status.",
  inputSchema: z.object({}),
  pythonTool: "varsity.arena_health",
};

export const trackEvent = {
  name: "arena.track_event",
  description: "Track a user behaviour event.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
    event_type: z.string().describe("Event type identifier."),
    payload: z
      .record(z.unknown())
      .optional()
      .describe("Arbitrary JSON payload."),
  }),
  pythonTool: "varsity.track_event",
};

export const all = [health, version, arenaHealth, trackEvent] as const;
