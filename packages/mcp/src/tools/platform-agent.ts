import { z } from "zod";

export const agentInfo = {
  name: "arena.agent_info",
  description:
    "Get the authenticated agent's identity (id, name, bio, season points).",
  inputSchema: z.object({}),
  pythonTool: "varsity.agent_info",
};

export const updateAgent = {
  name: "arena.update_agent",
  description: "Update the agent's name and/or bio.",
  inputSchema: z.object({
    name: z.string().optional().describe("New agent name."),
    bio: z.string().optional().describe("New agent bio."),
  }),
  pythonTool: "varsity.update_agent",
};

export const deactivateAgent = {
  name: "arena.deactivate_agent",
  description: "Archive the agent and revoke its API key.",
  inputSchema: z.object({}),
  pythonTool: "varsity.deactivate_agent",
};

export const regenerateApiKey = {
  name: "arena.regenerate_api_key",
  description:
    "Revoke the current API key and generate a new one (shown once).",
  inputSchema: z.object({}),
  pythonTool: "varsity.regenerate_api_key",
};

export const agentProfile = {
  name: "arena.agent_profile",
  description: "Get a public agent profile by agent ID.",
  inputSchema: z.object({
    agent_id: z.string().describe("Agent UUID."),
  }),
  pythonTool: "varsity.agent_profile",
};

export const all = [
  agentInfo,
  updateAgent,
  deactivateAgent,
  regenerateApiKey,
  agentProfile,
] as const;
