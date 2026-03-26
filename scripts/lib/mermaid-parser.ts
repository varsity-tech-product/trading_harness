// Lightweight Mermaid flowchart parser — handles the subset used in our docs

import type { MermaidGraph, MermaidNode, MermaidEdge, MermaidSubgraph, Direction, NodeShape } from "./types.js";

export function parseMermaid(source: string): MermaidGraph {
  const lines = source.split("\n").map((l) => l.trim()).filter(Boolean);
  let direction: Direction = "LR";
  const nodesMap = new Map<string, MermaidNode>();
  const edges: MermaidEdge[] = [];
  const subgraphs: MermaidSubgraph[] = [];
  let currentSubgraph: string | undefined;
  let subgraphCounter = 0;

  for (const line of lines) {
    // Direction header
    const dirMatch = line.match(/^graph\s+(LR|TD|TB|RL)$/);
    if (dirMatch) {
      direction = (dirMatch[1] === "TB" ? "TD" : dirMatch[1]) as Direction;
      continue;
    }

    // Subgraph start
    const sgMatch = line.match(/^subgraph\s+"([^"]+)"$/);
    if (sgMatch) {
      const id = `sg_${subgraphCounter++}`;
      subgraphs.push({ id, label: sgMatch[1] });
      currentSubgraph = id;
      continue;
    }

    // Subgraph end
    if (line === "end") {
      currentSubgraph = undefined;
      continue;
    }

    // Parse connection lines: NodeRef (-->|label|? NodeRef)*
    parseConnectionLine(line, nodesMap, edges, currentSubgraph);
  }

  return {
    direction,
    nodes: Array.from(nodesMap.values()),
    edges,
    subgraphs,
  };
}

// Extract a node definition from text like: A[label], A["label"], A{label}, or bare A
interface NodeRef {
  id: string;
  endIndex: number;
}

function parseNodeRef(text: string, startIndex: number, nodesMap: Map<string, MermaidNode>, subgraph?: string): NodeRef | null {
  const remaining = text.slice(startIndex).trimStart();
  const offset = text.length - text.slice(startIndex).length + (text.slice(startIndex).length - remaining.length);

  // Match node ID
  const idMatch = remaining.match(/^(\w+)/);
  if (!idMatch) return null;

  const id = idMatch[1];
  let pos = idMatch[0].length;

  // Check for shape definition after ID
  const afterId = remaining.slice(pos);

  if (afterId.startsWith('["')) {
    // Quoted rectangle: A["some text"]
    const closeIdx = afterId.indexOf('"]', 2);
    if (closeIdx !== -1) {
      const label = afterId.slice(2, closeIdx).replace(/<br\/?>/g, "\n");
      upsertNode(nodesMap, id, label, "rectangle", subgraph);
      pos += closeIdx + 2;
    }
  } else if (afterId.startsWith("[")) {
    // Unquoted rectangle: A[some text]
    const closeIdx = afterId.indexOf("]", 1);
    if (closeIdx !== -1) {
      const label = afterId.slice(1, closeIdx).replace(/<br\/?>/g, "\n");
      upsertNode(nodesMap, id, label, "rectangle", subgraph);
      pos += closeIdx + 1;
    }
  } else if (afterId.startsWith("{")) {
    // Diamond: D{some text} or D{text?}
    const closeIdx = afterId.indexOf("}", 1);
    if (closeIdx !== -1) {
      const label = afterId.slice(1, closeIdx).replace(/<br\/?>/g, "\n");
      upsertNode(nodesMap, id, label, "diamond", subgraph);
      pos += closeIdx + 1;
    }
  } else {
    // Bare reference — node should already exist, but create placeholder if not
    if (!nodesMap.has(id)) {
      upsertNode(nodesMap, id, id, "rectangle", subgraph);
    }
  }

  return { id, endIndex: offset + pos };
}

function upsertNode(
  map: Map<string, MermaidNode>,
  id: string,
  label: string,
  shape: NodeShape,
  subgraph?: string,
) {
  const existing = map.get(id);
  if (existing) {
    // Update if we now have a richer definition
    if (label !== id) existing.label = label;
    if (shape !== "rectangle") existing.shape = shape;
    if (subgraph) existing.subgraph = subgraph;
  } else {
    map.set(id, { id, label, shape, subgraph });
  }
}

function parseConnectionLine(
  line: string,
  nodesMap: Map<string, MermaidNode>,
  edges: MermaidEdge[],
  subgraph?: string,
) {
  // Parse first node
  const first = parseNodeRef(line, 0, nodesMap, subgraph);
  if (!first) return;

  let pos = first.endIndex;
  let prevId = first.id;

  // Parse subsequent --> NodeRef pairs
  while (pos < line.length) {
    const remaining = line.slice(pos).trimStart();
    if (!remaining.startsWith("-->")) break;

    let arrowEnd = 3; // skip -->
    let edgeLabel: string | undefined;

    // Check for |label|
    const afterArrow = remaining.slice(arrowEnd).trimStart();
    const labelOffset = remaining.length - remaining.slice(arrowEnd).length + (remaining.slice(arrowEnd).length - afterArrow.length);

    if (afterArrow.startsWith("|")) {
      const closeBar = afterArrow.indexOf("|", 1);
      if (closeBar !== -1) {
        edgeLabel = afterArrow.slice(1, closeBar);
        arrowEnd = labelOffset + closeBar + 1;
      }
    } else {
      arrowEnd = labelOffset;
    }

    // Parse next node
    const actualPos = pos + (line.slice(pos).length - remaining.length) + arrowEnd;
    const next = parseNodeRef(line, actualPos, nodesMap, subgraph);
    if (!next) break;

    edges.push({ from: prevId, to: next.id, label: edgeLabel });
    prevId = next.id;
    pos = next.endIndex;
  }
}
