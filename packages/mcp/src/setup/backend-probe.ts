import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { resolve } from "node:path";
import { commandAvailable } from "./bootstrap-python.js";
import type { ManagedAgent } from "../util/home.js";

export interface BackendProbe {
  backend: ManagedAgent;
  available: boolean;
  ready: boolean;
  confidence: "high" | "medium" | "low";
  summary: string;
  details: string;
}

export function probeBackend(backend: ManagedAgent): BackendProbe {
  if (backend === "rule") {
    return {
      backend,
      available: true,
      ready: true,
      confidence: "high",
      summary: "builtin",
      details: "Rule-based policy requires no external agent CLI.",
    };
  }

  if (backend === "auto") {
    const probes = (["claude", "gemini", "openclaw", "codex"] as const)
      .map((item) => probeBackend(item));
    const ready = probes.filter((item) => item.ready);
    if (ready.length > 0) {
      return {
        backend,
        available: true,
        ready: true,
        confidence: "medium",
        summary: `ready (${ready.map((item) => item.backend).join(", ")})`,
        details: ready.map((item) => item.summary).join("; "),
      };
    }
    const available = probes.filter((item) => item.available);
    if (available.length > 0) {
      return {
        backend,
        available: true,
        ready: false,
        confidence: "medium",
        summary: `not ready (${available.map((item) => item.backend).join(", ")})`,
        details: available.map((item) => item.summary).join("; "),
      };
    }
    return {
      backend,
      available: false,
      ready: false,
      confidence: "high",
      summary: "missing (no supported CLI found)",
      details: "Install claude, gemini, openclaw, or codex.",
    };
  }

  if (!commandAvailable(backend)) {
    return {
      backend,
      available: false,
      ready: false,
      confidence: "high",
      summary: `missing (${backend})`,
      details: `${backend} is not in PATH.`,
    };
  }

  switch (backend) {
    case "claude":
      return probeClaude();
    case "codex":
      return probeCodex();
    case "gemini":
      return probeGemini();
    case "openclaw":
      return probeOpenClaw();
    default:
      return {
        backend,
        available: true,
        ready: false,
        confidence: "low",
        summary: `${backend} exists but no probe is implemented`,
        details: "No backend-specific readiness check is available.",
      };
  }
}

function probeClaude(): BackendProbe {
  const result = spawnSync("claude", ["auth", "status"], {
    encoding: "utf-8",
    timeout: 5000,
  });
  if (result.status === 0) {
    const stdout = String(result.stdout || "").trim();
    try {
      const payload = JSON.parse(stdout) as { loggedIn?: boolean; email?: string };
      if (payload.loggedIn) {
        return {
          backend: "claude",
          available: true,
          ready: true,
          confidence: "high",
          summary: payload.email
            ? `ready (signed in as ${payload.email})`
            : "ready (authenticated)",
          details: stdout,
        };
      }
    } catch {
      if (stdout) {
        return {
          backend: "claude",
          available: true,
          ready: true,
          confidence: "medium",
          summary: "ready (auth status returned successfully)",
          details: stdout,
        };
      }
    }
    return {
      backend: "claude",
      available: true,
      ready: true,
      confidence: "medium",
      summary: "ready (auth status command succeeded)",
      details: stdout || "claude auth status exited successfully.",
    };
  }

  return fallbackProbe("claude", ["--version"], "auth status failed");
}

function probeCodex(): BackendProbe {
  const result = spawnSync("codex", ["login", "status"], {
    encoding: "utf-8",
    timeout: 5000,
  });
  const output = `${result.stdout ?? ""}${result.stderr ?? ""}`.trim();
  if (result.status === 0) {
    const summaryLine =
      output
        .split("\n")
        .map((line) => line.trim())
        .find((line) => /^logged in/i.test(line)) ?? firstMeaningfulLine(output);
    return {
      backend: "codex",
      available: true,
      ready: true,
      confidence: "high",
      summary: summaryLine
        ? `ready (${summaryLine})`
        : "ready (login status succeeded)",
      details: output || "codex login status exited successfully.",
    };
  }

  return fallbackProbe("codex", ["--version"], "login status failed");
}

function probeGemini(): BackendProbe {
  const statusResult = spawnSync("gemini", ["auth", "status"], {
    encoding: "utf-8",
    timeout: 5000,
  });
  const statusOutput = `${statusResult.stdout ?? ""}${statusResult.stderr ?? ""}`.trim();
  if (statusResult.status === 0) {
    return {
      backend: "gemini",
      available: true,
      ready: true,
      confidence: statusOutput ? "medium" : "low",
      summary: statusOutput
        ? `ready (${firstLine(statusOutput)})`
        : "ready (auth status exited successfully)",
      details: statusOutput || "gemini auth status exited successfully.",
    };
  }

  return fallbackProbe("gemini", ["--version"], "auth status failed");
}

function probeOpenClaw(): BackendProbe {
  const helpResult = spawnSync("openclaw", ["agent", "--help"], {
    encoding: "utf-8",
    timeout: 5000,
  });
  const output = `${helpResult.stdout ?? ""}${helpResult.stderr ?? ""}`.trim();
  if (helpResult.status === 0) {
    const agentDir = resolve(homedir(), ".openclaw", "agents", "arena-trader");
    const agentRegistered = existsSync(agentDir);
    const confidence = agentRegistered ? "medium" : "low";
    const agentNote = agentRegistered
      ? ""
      : ". Agent 'arena-trader' not registered — run: arena-agent setup --client openclaw";
    return {
      backend: "openclaw",
      available: true,
      ready: true,
      confidence,
      summary: `ready (openclaw agent help succeeded${agentNote})`,
      details: (output || "openclaw agent --help exited successfully.") +
        (agentRegistered ? "" : `\nAgent directory missing: ${agentDir}`),
    };
  }

  return fallbackProbe("openclaw", ["--help"], "agent help failed");
}

function fallbackProbe(
  backend: Exclude<ManagedAgent, "auto" | "rule">,
  args: string[],
  failurePrefix: string
): BackendProbe {
  const result = spawnSync(backend, args, {
    encoding: "utf-8",
    timeout: 5000,
  });
  const output = `${result.stdout ?? ""}${result.stderr ?? ""}`.trim();
  if (result.status === 0) {
    return {
      backend,
      available: true,
      ready: true,
      confidence: "low",
      summary: `ready (${backend} responds to ${args.join(" ")})`,
      details: output || `${backend} ${args.join(" ")} exited successfully.`,
    };
  }
  return {
    backend,
    available: true,
    ready: false,
    confidence: "medium",
    summary: `not ready (${failurePrefix})`,
    details: output || `${backend} ${args.join(" ")} failed with code ${result.status ?? "unknown"}.`,
  };
}

function firstLine(text: string): string {
  return text.split("\n").map((line) => line.trim()).find(Boolean) ?? text.trim();
}

function firstMeaningfulLine(text: string): string {
  return (
    text
      .split("\n")
      .map((line) => line.trim())
      .find((line) => line && !/^warning:/i.test(line)) ?? firstLine(text)
  );
}
