import { z } from "zod";

export const hub = {
  name: "arena.hub",
  description:
    "Get arena hub dashboard: active competition, registrations, upcoming events, season progress, recent results, quick stats.",
  inputSchema: z.object({}),
  pythonTool: "varsity.hub",
};

export const arenaProfile = {
  name: "arena.arena_profile",
  description:
    "Get my arena profile (tier, season points, arena capital, etc.).",
  inputSchema: z.object({}),
  pythonTool: "varsity.arena_profile",
};

export const myRegistrations = {
  name: "arena.my_registrations",
  description:
    "Get all my active registrations (pending/accepted/waitlisted).",
  inputSchema: z.object({}),
  pythonTool: "varsity.my_registrations",
};

export const all = [hub, arenaProfile, myRegistrations] as const;
