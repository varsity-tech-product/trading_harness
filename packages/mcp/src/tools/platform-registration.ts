import { z } from "zod";

export const register = {
  name: "arena.register",
  description:
    "Register for an agent competition. Must be in 'registration_open' state.",
  inputSchema: z.object({
    slug: z.string().describe("Competition slug."),
  }),
  pythonTool: "varsity.register",
};

export const withdraw = {
  name: "arena.withdraw",
  description:
    "Withdraw registration from an agent competition (before it goes live).",
  inputSchema: z.object({
    slug: z.string().describe("Competition slug."),
  }),
  pythonTool: "varsity.withdraw",
};

export const myRegistration = {
  name: "arena.my_registration",
  description: "Get my registration status for a specific competition.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
  }),
  pythonTool: "varsity.my_registration",
};

export const all = [register, withdraw, myRegistration] as const;
