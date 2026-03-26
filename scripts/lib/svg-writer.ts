// Converts layout result to SVG — clean hand-drawn sketch style
// Reference: autoresearch loop / agent loop diagram aesthetic
// Key: no fills on most nodes, red arrows, large title, subtle wobble

import type { LayoutResult, LayoutNode, LayoutSubgraph, LayoutAnnotation, MermaidEdge, NodeRole } from "./types.js";

function prng(seed: number): number {
  const x = Math.sin(seed * 9301 + 49297) * 49297;
  return x - Math.floor(x);
}
function jitter(seed: number, range: number): number {
  return (prng(seed) - 0.5) * range;
}

// --- Only success/error get fills, everything else is transparent ---

function bgColor(role: NodeRole): string {
  if (role === "result") return "#d8f5a2";
  if (role === "error") return "#ffc9c9";
  return "#ffffff"; // white fill (matches page)
}

function strokeColorForRole(role: NodeRole): string {
  if (role === "result") return "#2b8a3e";
  if (role === "error") return "#c92a2a";
  return "#1e1e1e";
}

function escapeXml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const FONT = `'Virgil', 'Segoe Print', 'Comic Sans MS', 'Patrick Hand', cursive`;

// --- Subtle sketchy shapes (less aggressive than before) ---

function sketchRect(x: number, y: number, w: number, h: number, seed: number): string {
  const wobble = 1.2; // subtle
  const r = 5;
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
  const wobble = 1.5;
  const j = (i: number) => jitter(seed + i, wobble);
  return `M ${cx + j(1)},${cy - hh + j(2)}
    L ${cx + hw + j(3)},${cy + j(4)}
    L ${cx + j(5)},${cy + hh + j(6)}
    L ${cx - hw + j(7)},${cy + j(8)} Z`;
}

// --- Render ---

function renderTitle(title: string, layout: LayoutResult): string {
  const allX = layout.nodes.map((n) => n.x + n.width / 2);
  const centerX = (Math.min(...allX) + Math.max(...allX)) / 2;
  const topY = Math.min(...layout.nodes.map((n) => n.y));

  return `<text x="${centerX}" y="${topY - 35}" text-anchor="middle" dominant-baseline="auto" font-family="${FONT}" font-size="30" font-weight="600" fill="#1e1e1e">${escapeXml(title)}</text>`;
}

function renderNode(node: LayoutNode, idx: number): string {
  const cx = node.x + node.width / 2;
  const cy = node.y + node.height / 2;
  const fill = bgColor(node.role);
  const stroke = strokeColorForRole(node.role);
  const sw = node.role === "primary" ? 1.5 : 1;
  const lines = node.label.split("\n");
  const lineHeight = node.fontSize * 1.4;
  const seed = idx * 100;

  let shape: string;
  if (node.shape === "diamond") {
    const hw = node.width / 2;
    const hh = node.height / 2;
    shape = `<path d="${sketchDiamond(cx, cy, hw, hh, seed)}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" />`;
  } else {
    shape = `<path d="${sketchRect(node.x, node.y, node.width, node.height, seed)}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" />`;
  }

  const textStartY = cy - ((lines.length - 1) * lineHeight) / 2;
  const fontWeight = node.role === "primary" ? "600" : "normal";
  const textEls = lines
    .map((line, i) => `<tspan x="${cx}" dy="${i === 0 ? 0 : lineHeight}">${escapeXml(line)}</tspan>`)
    .join("");
  const text = `<text x="${cx}" y="${textStartY}" text-anchor="middle" dominant-baseline="central" font-family="${FONT}" font-size="${node.fontSize}" font-weight="${fontWeight}" fill="${stroke}">${textEls}</text>`;

  return `<g>${shape}\n${text}</g>`;
}

function renderSubgraph(sg: LayoutSubgraph): string {
  const path = sketchRect(sg.x, sg.y, sg.width, sg.height, 9999);
  const rect = `<path d="${path}" fill="none" stroke="#adb5bd" stroke-width="1" stroke-dasharray="8,5" />`;
  const label = `<text x="${sg.x + 12}" y="${sg.y + 18}" font-family="${FONT}" font-size="13" fill="#868e96" font-weight="600">${escapeXml(sg.label)}</text>`;
  return rect + "\n" + label;
}

function renderAnnotation(ann: LayoutAnnotation): string {
  const lines = ann.text.split("\n");
  const fontSize = 13;
  const lineHeight = fontSize * 1.5;
  const textEls = lines
    .map((line, i) => `<tspan x="${ann.x}" dy="${i === 0 ? 0 : lineHeight}">${escapeXml(line)}</tspan>`)
    .join("");
  return `<text x="${ann.x}" y="${ann.y}" font-family="${FONT}" font-size="${fontSize}" fill="#868e96" font-style="italic" opacity="0.85">${textEls}</text>`;
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

  // Red arrows for forward, dark gray for back-edges
  const isBackEdge = (to.layer ?? 0) <= (from.layer ?? 0);
  const color = isBackEdge ? "#495057" : "#e03131";
  const markerId = isBackEdge ? "arrowhead-gray" : "arrowhead-red";

  // Subtle curve
  const midX = (start.x + end.x) / 2 + jitter(idx * 13, 4);
  const midY = (start.y + end.y) / 2 + jitter(idx * 13 + 1, 4);
  const line = `<path d="M ${start.x},${start.y} Q ${midX},${midY} ${end.x},${end.y}" fill="none" stroke="${color}" stroke-width="1.5" marker-end="url(#${markerId})" />`;

  let label = "";
  if (edge.label) {
    const lx = (start.x + end.x) / 2;
    const ly = (start.y + end.y) / 2;
    const tw = edge.label.length * 8 + 10;
    const th = 20;
    // White background behind label for readability
    label = `<rect x="${lx - tw / 2 - 2}" y="${ly - th / 2 - 3}" width="${tw + 4}" height="${th + 4}" rx="3" fill="white" stroke="none" />`;
    label += `\n<text x="${lx}" y="${ly}" text-anchor="middle" dominant-baseline="central" font-family="${FONT}" font-size="13" fill="${color}" font-style="italic">${escapeXml(edge.label)}</text>`;
  }

  return line + "\n" + label;
}

// --- Main ---

export function toSvg(layout: LayoutResult, title?: string): string {
  const pad = 60;

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of layout.nodes) {
    minX = Math.min(minX, n.x);     minY = Math.min(minY, n.y);
    maxX = Math.max(maxX, n.x + n.width); maxY = Math.max(maxY, n.y + n.height);
  }
  for (const sg of layout.subgraphs) {
    minX = Math.min(minX, sg.x);    minY = Math.min(minY, sg.y);
    maxX = Math.max(maxX, sg.x + sg.width); maxY = Math.max(maxY, sg.y + sg.height);
  }
  for (const ann of layout.annotations) {
    minX = Math.min(minX, ann.x - 120); maxX = Math.max(maxX, ann.x + 120);
    minY = Math.min(minY, ann.y - 25);  maxY = Math.max(maxY, ann.y + 35);
  }

  // Extra top space for title
  if (title) minY -= 60;

  const width = maxX - minX + pad * 2;
  const height = maxY - minY + pad * 2;
  const offsetX = -minX + pad;
  const offsetY = -minY + pad;

  const parts: string[] = [];
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">`);
  parts.push(`<rect width="${width}" height="${height}" fill="#ffffff" />`);
  parts.push(`<defs>`);
  parts.push(`  <marker id="arrowhead-red" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#e03131" /></marker>`);
  parts.push(`  <marker id="arrowhead-gray" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#495057" /></marker>`);
  parts.push(`</defs>`);
  parts.push(`<g transform="translate(${offsetX}, ${offsetY})">`);

  // Title
  if (title) parts.push(renderTitle(title, layout));

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

  // Annotations
  for (const ann of layout.annotations) parts.push(renderAnnotation(ann));

  parts.push("</g>");
  parts.push("</svg>");
  return parts.join("\n");
}
