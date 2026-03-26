// Intent-driven layout engine — semantic roles control sizing, spacing, and visual weight

import type {
  MermaidGraph, MermaidNode, LayoutNode, LayoutSubgraph, LayoutResult,
  NodeRole, Annotation, LayoutAnnotation,
} from "./types.js";

// Seeded PRNG for deterministic asymmetry
function jitter(seed: number, range: number): number {
  const x = Math.sin(seed * 9301 + 49297) * 49297;
  return (x - Math.floor(x) - 0.5) * range;
}

// --- Semantic role detection ---

function detectRole(
  node: MermaidNode,
  parentCount: number,
  childCount: number,
  convergenceIds: Set<string>,
): NodeRole {
  const label = node.label.toLowerCase();

  if (node.shape === "diamond") return "decision";
  if (/\b(hold|close_position|open_long|open_short|final decision)\b/.test(label)) return "result";
  if (/\b(error|report error|fail)\b/.test(label)) return "error";
  if (convergenceIds.has(node.id)) return "convergence";
  if (parentCount === 0) return "primary"; // root nodes
  return "system";
}

// --- Sizing per role ---

const CHAR_WIDTH = 8.5;
const LINE_HEIGHT = 22;

interface SizeSpec {
  baseWidth: number;
  maxWidth: number;
  baseHeight: number;
  fontSize: number;
  diamondScale: number;
}

const ROLE_SIZES: Record<NodeRole, SizeSpec> = {
  primary:      { baseWidth: 200, maxWidth: 340, baseHeight: 60, fontSize: 18, diamondScale: 1.4 },
  decision:     { baseWidth: 160, maxWidth: 280, baseHeight: 50, fontSize: 15, diamondScale: 1.4 },
  system:       { baseWidth: 150, maxWidth: 300, baseHeight: 46, fontSize: 14, diamondScale: 1.4 },
  convergence:  { baseWidth: 180, maxWidth: 320, baseHeight: 50, fontSize: 15, diamondScale: 1.4 },
  result:       { baseWidth: 130, maxWidth: 240, baseHeight: 40, fontSize: 13, diamondScale: 1.3 },
  error:        { baseWidth: 130, maxWidth: 260, baseHeight: 40, fontSize: 13, diamondScale: 1.3 },
};

function measureNode(label: string, shape: string, role: NodeRole): { width: number; height: number; fontSize: number } {
  const spec = ROLE_SIZES[role];
  const lines = label.split("\n");
  const maxLineLen = Math.max(...lines.map((l) => l.length));
  let width = Math.max(spec.baseWidth, maxLineLen * CHAR_WIDTH + 36);
  width = Math.min(width, spec.maxWidth);
  let height = spec.baseHeight + (lines.length - 1) * LINE_HEIGHT;

  if (shape === "diamond") {
    width = Math.max(width * spec.diamondScale, 120);
    height = Math.max(height * spec.diamondScale, 90);
  }

  return { width, height, fontSize: spec.fontSize };
}

// --- Spacing per role ---

function gapAfterLayer(dominantRole: NodeRole): number {
  switch (dominantRole) {
    case "primary": return 160;
    case "decision": return 140;
    case "convergence": return 130;
    default: return 110;
  }
}

const SIBLING_GAP = 50;

// --- Main layout ---

export function computeLayout(
  graph: MermaidGraph,
  annotations: Annotation[] = [],
): LayoutResult {
  const { nodes, edges, subgraphs } = graph;

  // Build adjacency
  const children = new Map<string, string[]>();
  const parents = new Map<string, string[]>();
  const nodeIds = new Set(nodes.map((n) => n.id));

  for (const n of nodes) {
    children.set(n.id, []);
    parents.set(n.id, []);
  }

  for (const e of edges) {
    if (nodeIds.has(e.from) && nodeIds.has(e.to)) {
      children.get(e.from)!.push(e.to);
      parents.get(e.to)!.push(e.from);
    }
  }

  // Topological layer assignment (BFS from roots) — needed before role detection
  const layers = new Map<string, number>();
  const bfsRoots = nodes.filter((n) => parents.get(n.id)!.length === 0).map((n) => n.id);
  if (bfsRoots.length === 0 && nodes.length > 0) bfsRoots.push(nodes[0].id);

  const queue = [...bfsRoots];
  for (const r of bfsRoots) layers.set(r, 0);

  while (queue.length > 0) {
    const current = queue.shift()!;
    const currentLayer = layers.get(current)!;
    for (const child of children.get(current) || []) {
      const existing = layers.get(child);
      if (existing === undefined || existing < currentLayer + 1) {
        layers.set(child, currentLayer + 1);
        if (existing === undefined) queue.push(child);
      }
    }
  }

  // Count only forward-edge parents (ignore back-edges for role detection)
  const forwardParentCount = new Map<string, number>();
  for (const n of nodes) forwardParentCount.set(n.id, 0);
  for (const e of edges) {
    if (nodeIds.has(e.from) && nodeIds.has(e.to)) {
      const fromLayer = layers.get(e.from) ?? 0;
      const toLayer = layers.get(e.to) ?? 0;
      if (toLayer > fromLayer) { // forward edge only
        forwardParentCount.set(e.to, (forwardParentCount.get(e.to) || 0) + 1);
      }
    }
  }

  // Detect convergence nodes (multiple forward parents)
  const convergenceIds = new Set<string>();
  for (const [id, count] of forwardParentCount) {
    if (count >= 2) convergenceIds.add(id);
  }

  // Assign semantic roles using forward-edge parent counts
  const roles = new Map<string, NodeRole>();
  for (const n of nodes) {
    roles.set(n.id, detectRole(n, forwardParentCount.get(n.id) || 0, children.get(n.id)!.length, convergenceIds));
  }

  // Group nodes by layer
  const layerGroups = new Map<number, string[]>();
  for (const n of nodes) {
    const layer = layers.get(n.id) ?? 0;
    if (!layerGroups.has(layer)) layerGroups.set(layer, []);
    layerGroups.get(layer)!.push(n.id);
  }

  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  const sortedLayers = Array.from(layerGroups.keys()).sort((a, b) => a - b);

  // --- Compute Y positions (variable spacing per layer) ---
  const layerY = new Map<number, number>();
  let yAccum = 0;

  for (let i = 0; i < sortedLayers.length; i++) {
    const layerIdx = sortedLayers[i];
    layerY.set(layerIdx, yAccum);

    // Variable gap after this layer based on dominant role
    const group = layerGroups.get(layerIdx)!;
    const dominantRole = group.map((id) => roles.get(id)!).sort((a, b) => {
      const priority: Record<NodeRole, number> = { primary: 0, decision: 1, convergence: 2, system: 3, result: 4, error: 4 };
      return priority[a] - priority[b];
    })[0];

    if (i < sortedLayers.length - 1) {
      // Measure max height in this layer for spacing
      const maxH = Math.max(...group.map((id) => {
        const n = nodeMap.get(id)!;
        return measureNode(n.label, n.shape, roles.get(id)!).height;
      }));
      yAccum += maxH + gapAfterLayer(dominantRole);
    }
  }

  // --- Compute X positions (asymmetric branching) ---
  const layoutNodes: LayoutNode[] = [];

  for (const layerIdx of sortedLayers) {
    const group = layerGroups.get(layerIdx)!;
    const y = layerY.get(layerIdx)!;

    // Measure all nodes in this layer
    const measured = group.map((id) => {
      const node = nodeMap.get(id)!;
      const role = roles.get(id)!;
      const m = measureNode(node.label, node.shape, role);
      return { id, node, role, ...m };
    });

    // Total width of this layer
    const totalWidth = measured.reduce((sum, m) => sum + m.width, 0) + (measured.length - 1) * SIBLING_GAP;
    let xStart = -totalWidth / 2; // center around 0

    for (let i = 0; i < measured.length; i++) {
      const m = measured[i];
      // Intentional asymmetry: alternate ±8-18px nudge, skip primary
      const nudge = m.role === "primary" ? 0 : jitter(layerIdx * 100 + i * 17, 20);

      layoutNodes.push({
        ...m.node,
        x: xStart + nudge,
        y: y + jitter(layerIdx * 100 + i * 31, 8), // slight vertical wobble
        width: m.width,
        height: m.height,
        layer: layerIdx,
        role: m.role,
        fontSize: m.fontSize,
      });

      xStart += m.width + SIBLING_GAP;
    }
  }

  // --- Shift all nodes so min x is at a reasonable origin ---
  const minX = Math.min(...layoutNodes.map((n) => n.x));
  const minY = Math.min(...layoutNodes.map((n) => n.y));
  for (const n of layoutNodes) {
    n.x -= minX;
    n.y -= minY;
  }

  // --- Subgraph bounding boxes ---
  const SUBGRAPH_PAD = 40;
  const SUBGRAPH_TOP_PAD = 50;

  const layoutSubgraphs: LayoutSubgraph[] = subgraphs.map((sg) => {
    const members = layoutNodes.filter((n) => n.subgraph === sg.id);
    if (members.length === 0) return { ...sg, x: 0, y: 0, width: 200, height: 100 };

    const sMinX = Math.min(...members.map((n) => n.x));
    const sMinY = Math.min(...members.map((n) => n.y));
    const sMaxX = Math.max(...members.map((n) => n.x + n.width));
    const sMaxY = Math.max(...members.map((n) => n.y + n.height));

    return {
      ...sg,
      x: sMinX - SUBGRAPH_PAD,
      y: sMinY - SUBGRAPH_TOP_PAD,
      width: sMaxX - sMinX + SUBGRAPH_PAD * 2,
      height: sMaxY - sMinY + SUBGRAPH_PAD + SUBGRAPH_TOP_PAD,
    };
  });

  // --- Position annotations near their anchor nodes ---
  const nodeLayoutMap = new Map(layoutNodes.map((n) => [n.id, n]));

  const layoutAnnotations: LayoutAnnotation[] = annotations
    .map((a) => {
      const anchor = nodeLayoutMap.get(a.nearNode);
      if (!anchor) return null;
      return {
        ...a,
        x: anchor.x + anchor.width / 2 + (a.offsetX ?? 0),
        y: anchor.y + anchor.height / 2 + (a.offsetY ?? 0),
      };
    })
    .filter(Boolean) as LayoutAnnotation[];

  return {
    direction: graph.direction,
    nodes: layoutNodes,
    edges,
    subgraphs: layoutSubgraphs,
    annotations: layoutAnnotations,
  };
}
