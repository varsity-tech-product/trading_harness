/**
 * Arena Agent Dashboard — lightweight HTTP server.
 *
 * Serves a single-page web dashboard showing:
 *   - Kline chart with buy/sell markers
 *   - Equity curve
 *   - AI reasoning log per round
 *
 * Data comes from the Python MCP bridge (live API) and local
 * transition JSONL files (AI reasoning history).
 */
import {
  createServer as createHttpServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { PythonBridge } from "../python-bridge.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

export function startDashboard(opts: {
  arenaRoot: string;
  port: number;
  competitionId?: number;
  transitionsPath?: string;
}): void {
  const { arenaRoot, port, competitionId, transitionsPath } = opts;
  const bridge = new PythonBridge(arenaRoot);

  const htmlPath = resolve(__dirname, "index.html");
  if (!existsSync(htmlPath)) {
    throw new Error(
      `Dashboard HTML not found at ${htmlPath}. Run \`npm run build\` first.`
    );
  }
  const html = readFileSync(htmlPath, "utf-8");

  const server = createHttpServer(async (req, res) => {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");

    if (req.method === "OPTIONS") {
      res.writeHead(204);
      res.end();
      return;
    }

    const url = new URL(req.url ?? "/", `http://localhost:${port}`);

    if (url.pathname === "/" || url.pathname === "/index.html") {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(html);
      return;
    }

    if (url.pathname.startsWith("/api/")) {
      await handleApi(url, res, bridge, competitionId, transitionsPath);
      return;
    }

    res.writeHead(404);
    res.end("Not Found");
  });

  server.listen(port, "127.0.0.1", () => {
    console.log(`Arena Dashboard: http://localhost:${port}`);
    if (competitionId) {
      console.log(`Competition: ${competitionId}`);
    }
    if (transitionsPath) {
      console.log(`Transitions: ${transitionsPath}`);
    }
  });
}

function jsonResponse(res: ServerResponse, data: unknown, status = 200): void {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
}

async function handleApi(
  url: URL,
  res: ServerResponse,
  bridge: PythonBridge,
  defaultCompetitionId?: number,
  transitionsPath?: string
): Promise<void> {
  const endpoint = url.pathname.replace("/api/", "");
  const compId =
    Number(url.searchParams.get("competition_id")) || defaultCompetitionId;

  try {
    switch (endpoint) {
      case "config":
        jsonResponse(res, {
          competition_id: defaultCompetitionId ?? null,
          transitions_path: transitionsPath ?? null,
        });
        return;

      case "klines": {
        const result = await bridge.callTool("varsity.klines", {
          symbol: url.searchParams.get("symbol") ?? "BTCUSDT",
          interval: url.searchParams.get("interval") ?? "5m",
          size: Number(url.searchParams.get("size") ?? "300"),
        });
        jsonResponse(res, result);
        return;
      }

      case "account": {
        if (!compId) {
          jsonResponse(res, { error: "competition_id required" }, 400);
          return;
        }
        const result = await bridge.callTool("varsity.live_account", {
          competition_id: compId,
        });
        jsonResponse(res, result);
        return;
      }

      case "trades": {
        if (!compId) {
          jsonResponse(res, { error: "competition_id required" }, 400);
          return;
        }
        const result = await bridge.callTool("varsity.live_trades", {
          competition_id: compId,
        });
        jsonResponse(res, result);
        return;
      }

      case "position": {
        if (!compId) {
          jsonResponse(res, { error: "competition_id required" }, 400);
          return;
        }
        const result = await bridge.callTool("varsity.live_position", {
          competition_id: compId,
        });
        jsonResponse(res, result);
        return;
      }

      case "competition": {
        const id = url.searchParams.get("id") ?? String(compId ?? "");
        if (!id) {
          jsonResponse(res, { error: "id required" }, 400);
          return;
        }
        const result = await bridge.callTool("varsity.competition_detail", {
          identifier: id,
        });
        jsonResponse(res, result);
        return;
      }

      case "transitions": {
        const transitions = readTransitions(transitionsPath);
        const limit = Number(url.searchParams.get("limit") ?? "100");
        jsonResponse(res, transitions.slice(-limit));
        return;
      }

      default:
        jsonResponse(res, { error: `Unknown endpoint: ${endpoint}` }, 404);
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    jsonResponse(res, { error: msg }, 500);
  }
}

function readTransitions(path?: string): object[] {
  if (!path) return [];

  // If path is a directory, find the most recent .jsonl file
  let filePath = path;
  if (existsSync(path)) {
    try {
      const stat = readFileSync(path); // will throw if directory
      void stat;
    } catch {
      // It's a directory — find latest .jsonl
      const files = readdirSync(path)
        .filter((f) => f.endsWith(".jsonl") && f.startsWith("transitions"))
        .sort();
      if (files.length > 0) {
        filePath = resolve(path, files[files.length - 1]);
      } else {
        return [];
      }
    }
  }

  if (!existsSync(filePath)) return [];

  try {
    const content = readFileSync(filePath, "utf-8").trim();
    if (!content) return [];
    return content
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  } catch {
    return [];
  }
}
