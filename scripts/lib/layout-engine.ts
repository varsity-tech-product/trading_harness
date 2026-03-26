// Layered graph layout engine — assigns (x,y) coordinates to nodes

import type { MermaidGraph, LayoutNode, LayoutSubgraph, LayoutResult } from "./types.js";

const NODE_H_GAP = 280; // horizontal gap between layers (LR)
const NODE_V_GAP = 160; // vertical gap between layers (TD)
const NODE_SPACING = 100; // gap between nodes in same layer
const SUBGRAPH_PAD = 40;
const SUBGRAPH_TOP_PAD = 50; // extra top for label
const BASE_WIDTH = 160;
const MAX_WIDTH = 300;
const BASE_HEIGHT = 50;
const LINE_HEIGHT = 22;
const CHAR_WIDTH = 8;
const DIAMOND_SCALE = 1.4;

function measureNode(label: string, shape: string): { width: number; height: number } {
  const lines = label.split("\n");
  const maxLineLen = Math.max(...lines.map((l) => l.length));
  let width = Math.max(BASE_WIDTH, maxLineLen * CHAR_WIDTH + 40);
  width = Math.min(width, MAX_WIDTH);
  let height = BASE_HEIGHT + (lines.length - 1) * LINE_HEIGHT;

  if (shape === "diamond") {
    width = Math.max(width * DIAMOND_SCALE, 130);
    height = Math.max(height * DIAMOND_SCALE, 100);
  }

  return { width, height };
}

export function computeLayout(graph: MermaidGraph): LayoutResult {
  const { direction, nodes, edges, subgraphs } = graph;

  // Build adjacency for layer assignment
  const children = new Map<string, string[]>();
  const parents = new Map<string, string[]>();
  const nodeIds = new Set(nodes.map((n) => n.id));

  for (const n of nodes) {
    children.set(n.id, []);
    parents.set(n.id, []);
  }
  // Track back-edges (cycles) — skip them in layer assignment
  const forwardEdges: typeof edges = [];
  const backEdges: typeof edges = [];

  // First pass: assign layers via BFS ignoring cycles
  for (const e of edges) {
    if (nodeIds.has(e.from) && nodeIds.has(e.to)) {
      children.get(e.from)!.push(e.to);
      parents.get(e.to)!.push(e.from);
      forwardEdges.push(e);
    }
  }

  // Topological layer assignment (Kahn's algorithm variant)
  const layers = new Map<string, number>();
  const roots = nodes.filter((n) => parents.get(n.id)!.length === 0).map((n) => n.id);

  // If no roots (everything in a cycle), pick first node
  if (roots.length === 0 && nodes.length > 0) {
    roots.push(nodes[0].id);
  }

  const queue = [...roots];
  for (const r of roots) layers.set(r, 0);

  while (queue.length > 0) {
    const current = queue.shift()!;
    const currentLayer = layers.get(current)!;
    for (const child of children.get(current) || []) {
      const existing = layers.get(child);
      if (existing === undefined || existing < currentLayer + 1) {
        layers.set(child, currentLayer + 1);
        // Only enqueue if not already processed at this or higher layer
        if (existing === undefined) {
          queue.push(child);
        }
      }
    }
  }

  // Detect back-edges: edge goes to same or earlier layer
  const actualForward: typeof edges = [];
  for (const e of forwardEdges) {
    const fromLayer = layers.get(e.from) ?? 0;
    const toLayer = layers.get(e.to) ?? 0;
    if (toLayer <= fromLayer) {
      backEdges.push(e);
    } else {
      actualForward.push(e);
    }
  }

  // Group nodes by layer
  const layerGroups = new Map<number, string[]>();
  for (const n of nodes) {
    const layer = layers.get(n.id) ?? 0;
    if (!layerGroups.has(layer)) layerGroups.set(layer, []);
    layerGroups.get(layer)!.push(n.id);
  }

  const nodeMap = new Map(nodes.map((n) => [n.id, n]));

  // Compute positions
  const layoutNodes: LayoutNode[] = [];
  const isLR = direction === "LR";

  const sortedLayers = Array.from(layerGroups.keys()).sort((a, b) => a - b);

  for (const layerIdx of sortedLayers) {
    const group = layerGroups.get(layerIdx)!;

    for (let i = 0; i < group.length; i++) {
      const nodeId = group[i];
      const node = nodeMap.get(nodeId)!;
      const { width, height } = measureNode(node.label, node.shape);

      let x: number, y: number;
      if (isLR) {
        x = layerIdx * NODE_H_GAP;
        y = i * (height + NODE_SPACING);
      } else {
        x = i * (width + NODE_SPACING);
        y = layerIdx * NODE_V_GAP;
      }

      layoutNodes.push({
        ...node,
        x,
        y,
        width,
        height,
        layer: layerIdx,
      });
    }
  }

  // Center each layer's nodes around the midpoint of the widest layer
  const layerSizes = new Map<number, number>();
  for (const layerIdx of sortedLayers) {
    const layerNodes = layoutNodes.filter((n) => n.layer === layerIdx);
    if (layerNodes.length === 0) continue;

    if (isLR) {
      const totalHeight = layerNodes.reduce((sum, n) => sum + n.height, 0) + (layerNodes.length - 1) * NODE_SPACING;
      layerSizes.set(layerIdx, totalHeight);
    } else {
      const totalWidth = layerNodes.reduce((sum, n) => sum + n.width, 0) + (layerNodes.length - 1) * NODE_SPACING;
      layerSizes.set(layerIdx, totalWidth);
    }
  }

  const maxSpan = Math.max(...layerSizes.values());

  for (const layerIdx of sortedLayers) {
    const layerNodes = layoutNodes.filter((n) => n.layer === layerIdx);
    const span = layerSizes.get(layerIdx) || 0;
    const offset = (maxSpan - span) / 2;

    if (isLR) {
      // Recompute y with centering
      let yAccum = offset;
      for (const n of layerNodes) {
        n.y = yAccum;
        yAccum += n.height + NODE_SPACING;
      }
    } else {
      // Recompute x with centering
      let xAccum = offset;
      for (const n of layerNodes) {
        n.x = xAccum;
        xAccum += n.width + NODE_SPACING;
      }
    }
  }

  // Compute subgraph bounding boxes
  const layoutSubgraphs: LayoutSubgraph[] = subgraphs.map((sg) => {
    const members = layoutNodes.filter((n) => n.subgraph === sg.id);
    if (members.length === 0) {
      return { ...sg, x: 0, y: 0, width: 200, height: 100 };
    }

    const minX = Math.min(...members.map((n) => n.x));
    const minY = Math.min(...members.map((n) => n.y));
    const maxX = Math.max(...members.map((n) => n.x + n.width));
    const maxY = Math.max(...members.map((n) => n.y + n.height));

    return {
      ...sg,
      x: minX - SUBGRAPH_PAD,
      y: minY - SUBGRAPH_TOP_PAD,
      width: maxX - minX + SUBGRAPH_PAD * 2,
      height: maxY - minY + SUBGRAPH_PAD + SUBGRAPH_TOP_PAD,
    };
  });

  return {
    direction,
    nodes: layoutNodes,
    edges, // return all edges including back-edges
    subgraphs: layoutSubgraphs,
  };
}
