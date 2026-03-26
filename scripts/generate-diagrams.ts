#!/usr/bin/env npx tsx
// Generate Excalidraw diagram files from Mermaid definitions

import { writeFileSync, mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { parseMermaid } from "./lib/mermaid-parser.js";
import { computeLayout } from "./lib/layout-engine.js";
import { toExcalidraw } from "./lib/excalidraw-writer.js";
import { DIAGRAMS } from "./lib/diagrams.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(__dirname, "..", "docs", "diagrams");
mkdirSync(outDir, { recursive: true });

let count = 0;
for (const diagram of DIAGRAMS) {
  const graph = parseMermaid(diagram.mermaid);
  const layout = computeLayout(graph);
  const excalidraw = toExcalidraw(layout, { title: diagram.title });
  const outPath = resolve(outDir, diagram.outputFile);
  writeFileSync(outPath, JSON.stringify(excalidraw, null, 2));
  console.log(`  ✓ ${diagram.name} → ${diagram.outputFile} (${graph.nodes.length} nodes, ${graph.edges.length} edges)`);
  count++;
}

console.log(`\nGenerated ${count} Excalidraw diagrams in ${outDir}`);
