import { z } from "zod";

export const register = {
  name: "arena.register",
  description:
    "Register for a competition. Must be in 'registration_open' state.",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
  }),
  pythonTool: "varsity.register",
};

export const withdraw = {
  name: "arena.withdraw",
  description:
    "Withdraw registration from a competition (before it goes live).",
  inputSchema: z.object({
    competition_id: z.number().int().describe("Competition ID."),
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
