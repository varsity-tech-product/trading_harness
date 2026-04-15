import {
  existsSync,
  readFileSync,
  readdirSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { resolve } from "node:path";
import { logsDirPath } from "./home.js";

export interface RuntimeState {
  pid: number;
  agent: string;
  configPath: string;
  logPath: string;
  startedAt: string;
}

export function runtimeStatePath(home: string): string {
  return resolve(home, ".runtime-state.json");
}

export function readRuntimeState(home: string): RuntimeState | null {
  const path = runtimeStatePath(home);
  if (!existsSync(path)) {
    return null;
  }
  try {
    return JSON.parse(readFileSync(path, "utf-8")) as RuntimeState;
  } catch {
    return null;
  }
}

export function writeRuntimeState(home: string, state: RuntimeState): void {
  writeFileSync(runtimeStatePath(home), JSON.stringify(state, null, 2) + "\n");
}

export function clearRuntimeState(home: string): void {
  const path = runtimeStatePath(home);
  if (existsSync(path)) {
    unlinkSync(path);
  }
}

export function isProcessRunning(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

export function latestRuntimeLogPath(home: string): string | null {
  const dir = logsDirPath(home);
  if (!existsSync(dir)) {
    return null;
  }
  const candidates = readdirSync(dir)
    .filter((name) => name.startsWith("runtime-") && name.endsWith(".log"))
    .sort();
  if (candidates.length === 0) {
    return null;
  }
  return resolve(dir, candidates[candidates.length - 1]);
}

export function tailLines(path: string, limit: number): string {
  const content = readFileSync(path, "utf-8");
  const lines = content.split("\n");
  return lines.slice(Math.max(0, lines.length - limit)).join("\n");
}
