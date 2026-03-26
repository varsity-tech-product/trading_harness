#!/usr/bin/env npx tsx
// Generate Excalidraw + SVG diagram files from Mermaid definitions

import { writeFileSync, mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { parseMermaid } from "./lib/mermaid-parser.js";
import { computeLayout } from "./lib/layout-engine.js";
import { toExcalidraw } from "./lib/excalidraw-writer.js";
import { toSvg } from "./lib/svg-writer.js";
import { DIAGRAMS } from "./lib/diagrams.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(__dirname, "..", "docs", "diagrams");
mkdirSync(outDir, { recursive: true });

let count = 0;
for (const diagram of DIAGRAMS) {
  const graph = parseMermaid(diagram.mermaid);
  const layout = computeLayout(graph, diagram.annotations);

  writeFileSync(
    resolve(outDir, diagram.outputFile),
    JSON.stringify(toExcalidraw(layout), null, 2),
  );

  const svgName = diagram.outputFile.replace(".excalidraw", ".svg");
  writeFileSync(resolve(outDir, svgName), toSvg(layout));

  const roles = layout.nodes.map((n) => n.role);
  const roleCounts = roles.reduce((acc, r) => { acc[r] = (acc[r] || 0) + 1; return acc; }, {} as Record<string, number>);
  const roleStr = Object.entries(roleCounts).map(([r, c]) => `${c} ${r}`).join(", ");

  console.log(`  ✓ ${diagram.name} (${roleStr}, ${diagram.annotations.length} annotations)`);
  count++;
}

console.log(`\nGenerated ${count} diagrams in ${outDir}`);
