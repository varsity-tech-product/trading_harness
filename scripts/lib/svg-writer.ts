// Converts layout result to SVG string

import type { LayoutResult, LayoutNode, LayoutSubgraph, MermaidEdge } from "./types.js";

function fillColor(node: LayoutNode): string {
  const label = node.label.toLowerCase();
  if (node.shape === "diamond") return "#ffec99";
  if (/\b(hold|close_position|open_long|open_short)\b/.test(label)) return "#b2f2bb";
  if (/\b(error|report error|fail)\b/.test(label)) return "#ffc9c9";
  return "#a5d8ff";
}

function escapeXml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function renderNode(node: LayoutNode): string {
  const cx = node.x + node.width / 2;
  const cy = node.y + node.height / 2;
  const fill = fillColor(node);
  const lines = node.label.split("\n");
  const fontSize = 14;
  const lineHeight = fontSize * 1.4;

  let shape: string;
  if (node.shape === "diamond") {
    const hw = node.width / 2;
    const hh = node.height / 2;
    shape = `<polygon points="${cx},${node.y} ${node.x + node.width},${cy} ${cx},${node.y + node.height} ${node.x},${cy}" fill="${fill}" stroke="#1e1e1e" stroke-width="1.5" />`;
  } else {
    shape = `<rect x="${node.x}" y="${node.y}" width="${node.width}" height="${node.height}" rx="8" ry="8" fill="${fill}" stroke="#1e1e1e" stroke-width="1.5" />`;
  }

  const textStartY = cy - ((lines.length - 1) * lineHeight) / 2;
  const textEls = lines
    .map((line, i) => `<tspan x="${cx}" dy="${i === 0 ? 0 : lineHeight}">${escapeXml(line)}</tspan>`)
    .join("");

  const text = `<text x="${cx}" y="${textStartY}" text-anchor="middle" dominant-baseline="central" font-family="system-ui, -apple-system, sans-serif" font-size="${fontSize}" fill="#1e1e1e">${textEls}</text>`;

  return shape + "\n" + text;
}

function renderSubgraph(sg: LayoutSubgraph): string {
  const rect = `<rect x="${sg.x}" y="${sg.y}" width="${sg.width}" height="${sg.height}" rx="8" ry="8" fill="#f8f9fa" stroke="#868e96" stroke-width="1" stroke-dasharray="6,4" />`;
  const label = `<text x="${sg.x + 12}" y="${sg.y + 18}" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#868e96" font-weight="600">${escapeXml(sg.label)}</text>`;
  return rect + "\n" + label;
}

function edgePoint(node: LayoutNode, targetCx: number, targetCy: number): { x: number; y: number } {
  // Find the intersection of a line from node center to target with the node boundary
  const cx = node.x + node.width / 2;
  const cy = node.y + node.height / 2;
  const dx = targetCx - cx;
  const dy = targetCy - cy;

  if (dx === 0 && dy === 0) return { x: cx, y: cy };

  if (node.shape === "diamond") {
    const hw = node.width / 2;
    const hh = node.height / 2;
    // Diamond edges: use parametric intersection
    const absDx = Math.abs(dx);
    const absDy = Math.abs(dy);
    const t = Math.min(hw / (absDx || 1), hh / (absDy || 1));
    return { x: cx + dx * t * 0.9, y: cy + dy * t * 0.9 };
  }

  // Rectangle: find which edge the line intersects
  const hw = node.width / 2;
  const hh = node.height / 2;
  const scaleX = Math.abs(dx) > 0 ? hw / Math.abs(dx) : Infinity;
  const scaleY = Math.abs(dy) > 0 ? hh / Math.abs(dy) : Infinity;
  const scale = Math.min(scaleX, scaleY);
  return { x: cx + dx * scale, y: cy + dy * scale };
}

function renderArrow(edge: MermaidEdge, from: LayoutNode, to: LayoutNode): string {
  const fromCx = from.x + from.width / 2;
  const fromCy = from.y + from.height / 2;
  const toCx = to.x + to.width / 2;
  const toCy = to.y + to.height / 2;

  const start = edgePoint(from, toCx, toCy);
  const end = edgePoint(to, fromCx, fromCy);

  const line = `<line x1="${start.x}" y1="${start.y}" x2="${end.x}" y2="${end.y}" stroke="#495057" stroke-width="1.5" marker-end="url(#arrowhead)" />`;

  let label = "";
  if (edge.label) {
    const midX = (start.x + end.x) / 2;
    const midY = (start.y + end.y) / 2;
    const pad = 4;
    const textWidth = edge.label.length * 7 + 12;
    const textHeight = 18;
    label = `<rect x="${midX - textWidth / 2 - pad}" y="${midY - textHeight / 2 - pad - 2}" width="${textWidth + pad * 2}" height="${textHeight + pad * 2}" rx="4" fill="white" stroke="none" opacity="0.9" />`;
    label += `\n<text x="${midX}" y="${midY - 2}" text-anchor="middle" dominant-baseline="central" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#495057" font-style="italic">${escapeXml(edge.label)}</text>`;
  }

  return line + "\n" + label;
}

export function toSvg(layout: LayoutResult): string {
  const pad = 40;

  // Compute bounding box
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

  const width = maxX - minX + pad * 2;
  const height = maxY - minY + pad * 2;
  const offsetX = -minX + pad;
  const offsetY = -minY + pad;

  const parts: string[] = [];

  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">`);
  parts.push(`<defs><marker id="arrowhead" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#495057" /></marker></defs>`);
  parts.push(`<g transform="translate(${offsetX}, ${offsetY})">`);

  // Subgraphs (background)
  for (const sg of layout.subgraphs) {
    parts.push(renderSubgraph(sg));
  }

  // Arrows (behind nodes)
  const nodeMap = new Map(layout.nodes.map((n) => [n.id, n]));
  for (const edge of layout.edges) {
    const from = nodeMap.get(edge.from);
    const to = nodeMap.get(edge.to);
    if (from && to) parts.push(renderArrow(edge, from, to));
  }

  // Nodes (on top)
  for (const node of layout.nodes) {
    parts.push(renderNode(node));
  }

  parts.push("</g>");
  parts.push("</svg>");

  return parts.join("\n");
}
