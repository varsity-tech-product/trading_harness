import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { defaultArenaHome, isArenaHome, localPythonSourcePath } from "./home.js";

/**
 * Find the arena project root.
 *
 * Resolution order (first match wins):
 *   1. ARENA_ROOT or ARENA_HOME env var
 *   2. Walk up from cwd looking for an arena home marker or repo root
 *   3. ~/.arena-agent (managed home created by `arena-agent init`)
 *   4. Bundled repo root (dev installs via npm link)
 *
 * The managed home at ~/.arena-agent is the recommended path for agents.
 * After `arena-agent init`, no env vars are needed — the CLI always finds it.
 */
export function findArenaRoot(): string {
  const envRoot = process.env.ARENA_ROOT;
  if (envRoot && isArenaHome(resolve(envRoot))) {
    return resolve(envRoot);
  }

  const envHome = process.env.ARENA_HOME;
  if (envHome && isArenaHome(resolve(envHome))) {
    return resolve(envHome);
  }

  let dir = process.cwd();
  for (let i = 0; i < 10; i++) {
    if (isArenaHome(dir)) {
      return dir;
    }
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }

  // ~/.arena-agent is the standard managed home — always check it.
  // This is the path agents rely on after `arena-agent init`.
  const managedHome = defaultArenaHome();
  if (isArenaHome(managedHome)) {
    return managedHome;
  }

  const localSource = localPythonSourcePath();
  if (localSource && isArenaHome(localSource)) {
    return localSource;
  }

  throw new Error(
    "Cannot find an Arena home. Run `arena-agent init`, or set ARENA_ROOT to a configured Arena directory."
  );
}

/**
 * Resolve the Python binary inside the arena venv.
 */
export function findPython(arenaRoot: string): string {
  const candidates = [
    resolve(arenaRoot, ".venv", "bin", "python"),
    resolve(arenaRoot, ".venv", "bin", "python3"),
    resolve(arenaRoot, ".venv", "Scripts", "python.exe"), // Windows
  ];
  for (const p of candidates) {
    if (existsSync(p)) return p;
  }
  throw new Error(
    `No Python venv found at ${arenaRoot}/.venv. Run \`arena-agent init\` to bootstrap the runtime.`
  );
}
