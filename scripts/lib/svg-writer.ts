// Converts layout result to SVG — hand-drawn sketch style with semantic hierarchy

import type { LayoutResult, LayoutNode, LayoutSubgraph, LayoutAnnotation, MermaidEdge, NodeRole } from "./types.js";

// Seeded PRNG for deterministic wobble
function prng(seed: number): number {
  const x = Math.sin(seed * 9301 + 49297) * 49297;
  return x - Math.floor(x);
}
function jitter(seed: number, range: number): number {
  return (prng(seed) - 0.5) * range;
}

// --- Semantic colors ---
const ROLE_COLORS: Record<NodeRole, string> = {
  primary:     "#a5d8ff",
  decision:    "#ffec99",
  result:      "#b2f2bb",
  error:       "#ffc9c9",
  system:      "#d0ebff",
  convergence: "#e5dbff",
};

// Darker stroke per role for contrast
const ROLE_STROKES: Record<NodeRole, string> = {
  primary:     "#1864ab",
  decision:    "#e67700",
  result:      "#2b8a3e",
  error:       "#c92a2a",
  system:      "#1971c2",
  convergence: "#7048e8",
};

function escapeXml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const FONT = `'Virgil', 'Segoe Print', 'Comic Sans MS', 'Patrick Hand', cursive`;

// --- Sketchy shape generators ---

function sketchRect(x: number, y: number, w: number, h: number, seed: number): string {
  const wobble = 1.8;
  const r = 6;
  const j = (i: number) => jitter(seed + i, wobble);
  return `M ${x + r + j(1)},${y + j(2)}
    L ${x + w - r + j(3)},${y + j(4)}
    Q ${x + w + j(5)},${y + j(6)} ${x + w + j(7)},${y + r + j(8)}
    L ${x + w + j(9)},${y + h - r + j(10)}
    Q ${x + w + j(11)},${y + h + j(12)} ${x + w - r + j(13)},${y + h + j(14)}
    L ${x + r + j(15)},${y + h + j(16)}
    Q ${x + j(17)},${y + h + j(18)} ${x + j(19)},${y + h - r + j(20)}
    L ${x + j(21)},${y + r + j(22)}
    Q ${x + j(23)},${y + j(24)} ${x + r + j(25)},${y + j(26)} Z`;
}

function sketchDiamond(cx: number, cy: number, hw: number, hh: number, seed: number): string {
  const wobble = 2.5;
  const j = (i: number) => jitter(seed + i, wobble);
  return `M ${cx + j(1)},${cy - hh + j(2)}
    L ${cx + hw + j(3)},${cy + j(4)}
    L ${cx + j(5)},${cy + hh + j(6)}
    L ${cx - hw + j(7)},${cy + j(8)} Z`;
}

function hachureLines(x: number, y: number, w: number, h: number, color: string, seed: number): string {
  const gap = 9;
  const lines: string[] = [];
  for (let offset = -h; offset < w + h; offset += gap) {
    const x1 = x + offset;
    const x2 = x + offset + h * 0.35;
    const clipX1 = Math.max(x, Math.min(x + w, x1));
    const clipX2 = Math.max(x, Math.min(x + w, x2));
    if (Math.abs(clipX2 - clipX1) > 3) {
      const t1 = (clipX1 - x1) / ((x2 - x1) || 1);
      const t2 = (clipX2 - x1) / ((x2 - x1) || 1);
      lines.push(`<line x1="${clipX1 + jitter(seed + offset, 1)}" y1="${y + t1 * h + jitter(seed + offset + 1, 1)}" x2="${clipX2 + jitter(seed + offset + 2, 1)}" y2="${y + t2 * h + jitter(seed + offset + 3, 1)}" stroke="${color}" stroke-width="0.7" opacity="0.25" />`);
    }
  }
  return lines.join("\n");
}

// --- Render functions ---

function renderNode(node: LayoutNode, idx: number): string {
  const cx = node.x + node.width / 2;
  const cy = node.y + node.height / 2;
  const fill = ROLE_COLORS[node.role];
  const stroke = ROLE_STROKES[node.role];
  const strokeWidth = node.role === "primary" ? 2.2 : 1.5;
  const lines = node.label.split("\n");
  const lineHeight = node.fontSize * 1.4;
  const shapeSeed = idx * 100;

  let shape: string;
  if (node.shape === "diamond") {
    const hw = node.width / 2;
    const hh = node.height / 2;
    shape = `<path d="${sketchDiamond(cx, cy, hw, hh, shapeSeed)}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" />`;
  } else {
    shape = `<path d="${sketchRect(node.x, node.y, node.width, node.height, shapeSeed)}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" />`;
  }

  const hachure = hachureLines(node.x, node.y, node.width, node.height, stroke, shapeSeed + 50);

  const textStartY = cy - ((lines.length - 1) * lineHeight) / 2;
  const textEls = lines
    .map((line, i) => `<tspan x="${cx}" dy="${i === 0 ? 0 : lineHeight}">${escapeXml(line)}</tspan>`)
    .join("");
  const fontWeight = node.role === "primary" ? "600" : "normal";
  const text = `<text x="${cx}" y="${textStartY}" text-anchor="middle" dominant-baseline="central" font-family="${FONT}" font-size="${node.fontSize}" font-weight="${fontWeight}" fill="#000000">${textEls}</text>`;

  return `<g>${shape}\n${hachure}\n${text}</g>`;
}

function renderSubgraph(sg: LayoutSubgraph): string {
  const path = sketchRect(sg.x, sg.y, sg.width, sg.height, 9999);
  const rect = `<path d="${path}" fill="#f8f9fa" stroke="#868e96" stroke-width="1" stroke-dasharray="8,5" />`;
  const label = `<text x="${sg.x + 12}" y="${sg.y + 20}" font-family="${FONT}" font-size="13" fill="#868e96" font-weight="600">${escapeXml(sg.label)}</text>`;
  return rect + "\n" + label;
}

function renderAnnotation(ann: LayoutAnnotation): string {
  const lines = ann.text.split("\n");
  const fontSize = 12;
  const lineHeight = fontSize * 1.5;
  const textEls = lines
    .map((line, i) => `<tspan x="${ann.x}" dy="${i === 0 ? 0 : lineHeight}">${escapeXml(line)}</tspan>`)
    .join("");
  return `<text x="${ann.x}" y="${ann.y}" font-family="${FONT}" font-size="${fontSize}" fill="#868e96" font-style="italic" opacity="0.8">${textEls}</text>`;
}

function edgePoint(node: LayoutNode, targetCx: number, targetCy: number): { x: number; y: number } {
  const cx = node.x + node.width / 2;
  const cy = node.y + node.height / 2;
  const dx = targetCx - cx;
  const dy = targetCy - cy;
  if (dx === 0 && dy === 0) return { x: cx, y: cy };

  if (node.shape === "diamond") {
    const hw = node.width / 2;
    const hh = node.height / 2;
    const t = Math.min(hw / (Math.abs(dx) || 1), hh / (Math.abs(dy) || 1));
    return { x: cx + dx * t * 0.88, y: cy + dy * t * 0.88 };
  }

  const hw = node.width / 2;
  const hh = node.height / 2;
  const scaleX = Math.abs(dx) > 0 ? hw / Math.abs(dx) : Infinity;
  const scaleY = Math.abs(dy) > 0 ? hh / Math.abs(dy) : Infinity;
  const scale = Math.min(scaleX, scaleY);
  return { x: cx + dx * scale, y: cy + dy * scale };
}

function renderArrow(edge: MermaidEdge, from: LayoutNode, to: LayoutNode, idx: number): string {
  const fromCx = from.x + from.width / 2;
  const fromCy = from.y + from.height / 2;
  const toCx = to.x + to.width / 2;
  const toCy = to.y + to.height / 2;

  const start = edgePoint(from, toCx, toCy);
  const end = edgePoint(to, fromCx, fromCy);

  // Wobbly curve
  const midX = (start.x + end.x) / 2 + jitter(idx * 13, 5);
  const midY = (start.y + end.y) / 2 + jitter(idx * 13 + 1, 5);
  const line = `<path d="M ${start.x},${start.y} Q ${midX},${midY} ${end.x},${end.y}" fill="none" stroke="#000000" stroke-width="1.5" marker-end="url(#arrowhead)" />`;

  let label = "";
  if (edge.label) {
    const lx = (start.x + end.x) / 2;
    const ly = (start.y + end.y) / 2;
    const tw = edge.label.length * 7.5 + 14;
    const th = 20;
    label = `<rect x="${lx - tw / 2 - 3}" y="${ly - th / 2 - 4}" width="${tw + 6}" height="${th + 6}" rx="4" fill="white" stroke="none" />`;
    label += `\n<text x="${lx}" y="${ly - 1}" text-anchor="middle" dominant-baseline="central" font-family="${FONT}" font-size="12" fill="#495057" font-style="italic">${escapeXml(edge.label)}</text>`;
  }

  return line + "\n" + label;
}

// --- Main export ---

export function toSvg(layout: LayoutResult): string {
  const pad = 50;

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of layout.nodes) {
    minX = Math.min(minX, n.x);
    minY = Math.min(minY, n.y);
    maxX = Math.max(maxX, n.x + n.width);
    maxY = Math.max(maxY, n.y + n.height);
  }
  for (const sg of layout.subgraphs) {
    minX = Math.min(minX, sg.x);
    minY = Math.min(minY, sg.y);
    maxX = Math.max(maxX, sg.x + sg.width);
    maxY = Math.max(maxY, sg.y + sg.height);
  }
  // Expand for annotations
  for (const ann of layout.annotations) {
    minX = Math.min(minX, ann.x - 100);
    maxX = Math.max(maxX, ann.x + 100);
    minY = Math.min(minY, ann.y - 20);
    maxY = Math.max(maxY, ann.y + 30);
  }

  const width = maxX - minX + pad * 2;
  const height = maxY - minY + pad * 2;
  const offsetX = -minX + pad;
  const offsetY = -minY + pad;

  const parts: string[] = [];
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">`);
  parts.push(`<rect width="${width}" height="${height}" fill="#ffffff" />`);
  parts.push(`<defs><marker id="arrowhead" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#000000" /></marker></defs>`);
  parts.push(`<g transform="translate(${offsetX}, ${offsetY})">`);

  // Subgraphs
  for (const sg of layout.subgraphs) parts.push(renderSubgraph(sg));

  // Arrows (behind nodes)
  const nodeMap = new Map(layout.nodes.map((n) => [n.id, n]));
  let arrowIdx = 0;
  for (const edge of layout.edges) {
    const from = nodeMap.get(edge.from);
    const to = nodeMap.get(edge.to);
    if (from && to) parts.push(renderArrow(edge, from, to, arrowIdx++));
  }

  // Nodes
  layout.nodes.forEach((node, idx) => parts.push(renderNode(node, idx)));

  // Annotations (the human layer — gray, italic, floating)
  for (const ann of layout.annotations) parts.push(renderAnnotation(ann));

  parts.push("</g>");
  parts.push("</svg>");
  return parts.join("\n");
}
