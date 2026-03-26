// Converts layout result to Excalidraw JSON

import type { LayoutResult, LayoutNode, LayoutSubgraph, MermaidEdge } from "./types.js";

let _nextId = 1;
let _nextSeed = 100000;
function uid(prefix: string): string {
  return `${prefix}_${_nextId++}`;
}
function seed(): number {
  return _nextSeed++;
}

// Color logic
function fillColor(node: LayoutNode): string {
  const label = node.label.toLowerCase();
  if (node.shape === "diamond") return "#ffec99"; // yellow
  if (/\b(hold|close_position|open_long|open_short)\b/.test(label)) return "#b2f2bb"; // green
  if (/\b(error|report error|fail)\b/.test(label)) return "#ffc9c9"; // red
  return "#a5d8ff"; // blue
}

interface ExcalidrawElement {
  [key: string]: unknown;
}

function baseProps(id: string, type: string, x: number, y: number, w: number, h: number): ExcalidrawElement {
  return {
    id,
    type,
    x,
    y,
    width: w,
    height: h,
    angle: 0,
    strokeColor: "#1e1e1e",
    backgroundColor: "transparent",
    fillStyle: "solid",
    strokeWidth: 2,
    strokeStyle: "solid",
    roughness: 1,
    opacity: 100,
    groupIds: [],
    frameId: null,
    index: `a${_nextId}`,
    roundness: null,
    seed: seed(),
    version: 1,
    versionNonce: seed(),
    isDeleted: false,
    boundElements: null,
    updated: Date.now(),
    link: null,
    locked: false,
  };
}

function makeShape(node: LayoutNode): { shape: ExcalidrawElement; text: ExcalidrawElement } {
  const shapeId = uid("shape");
  const textId = uid("text");
  const type = node.shape === "diamond" ? "diamond" : "rectangle";

  const shape: ExcalidrawElement = {
    ...baseProps(shapeId, type, node.x, node.y, node.width, node.height),
    backgroundColor: fillColor(node),
    roundness: type === "rectangle" ? { type: 3 } : { type: 2 },
    boundElements: [{ id: textId, type: "text" }],
  };

  const fontSize = 16;
  const lines = node.label.split("\n");
  const textHeight = lines.length * fontSize * 1.25;
  const textWidth = node.width - 20;

  const text: ExcalidrawElement = {
    ...baseProps(textId, "text", node.x + (node.width - textWidth) / 2, node.y + (node.height - textHeight) / 2, textWidth, textHeight),
    text: node.label,
    fontSize,
    fontFamily: 1,
    textAlign: "center",
    verticalAlign: "middle",
    containerId: shapeId,
    originalText: node.label,
    autoResize: true,
    lineHeight: 1.25,
  };

  return { shape, text };
}

function makeSubgraph(sg: LayoutSubgraph): { rect: ExcalidrawElement; label: ExcalidrawElement } {
  const rectId = uid("sg");
  const labelId = uid("sglabel");

  const rect: ExcalidrawElement = {
    ...baseProps(rectId, "rectangle", sg.x, sg.y, sg.width, sg.height),
    backgroundColor: "#f8f9fa",
    strokeStyle: "dashed",
    strokeWidth: 1,
    strokeColor: "#868e96",
    roundness: { type: 3 },
    boundElements: [{ id: labelId, type: "text" }],
  };

  const fontSize = 14;
  const labelHeight = fontSize * 1.25;

  const label: ExcalidrawElement = {
    ...baseProps(labelId, "text", sg.x + 10, sg.y + 8, sg.width - 20, labelHeight),
    text: sg.label,
    fontSize,
    fontFamily: 1,
    textAlign: "left",
    verticalAlign: "top",
    containerId: rectId,
    originalText: sg.label,
    autoResize: true,
    lineHeight: 1.25,
  };

  return { rect, label };
}

function makeArrow(
  edge: MermaidEdge,
  fromNode: LayoutNode,
  toNode: LayoutNode,
): { arrow: ExcalidrawElement; label?: ExcalidrawElement } {
  const arrowId = uid("arrow");

  // Compute start/end points at node centers
  const fromCx = fromNode.x + fromNode.width / 2;
  const fromCy = fromNode.y + fromNode.height / 2;
  const toCx = toNode.x + toNode.width / 2;
  const toCy = toNode.y + toNode.height / 2;

  const dx = toCx - fromCx;
  const dy = toCy - fromCy;

  const arrow: ExcalidrawElement = {
    ...baseProps(arrowId, "arrow", fromCx, fromCy, Math.abs(dx), Math.abs(dy)),
    backgroundColor: "transparent",
    roundness: { type: 2 },
    points: [[0, 0], [dx, dy]],
    lastCommittedPoint: null,
    startBinding: {
      elementId: "", // will be patched
      focus: 0,
      gap: 8,
      fixedPoint: null,
    },
    endBinding: {
      elementId: "", // will be patched
      focus: 0,
      gap: 8,
      fixedPoint: null,
    },
    startArrowhead: null,
    endArrowhead: "arrow",
    elbowed: false,
  };

  let labelEl: ExcalidrawElement | undefined;
  if (edge.label) {
    const labelId = uid("elabel");
    const fontSize = 14;
    const labelWidth = edge.label.length * 8 + 16;
    const labelHeight = fontSize * 1.25;
    const midX = fromCx + dx / 2 - labelWidth / 2;
    const midY = fromCy + dy / 2 - labelHeight / 2 - 12; // offset above arrow

    labelEl = {
      ...baseProps(labelId, "text", midX, midY, labelWidth, labelHeight),
      text: edge.label,
      fontSize,
      fontFamily: 1,
      textAlign: "center",
      verticalAlign: "middle",
      containerId: arrowId,
      originalText: edge.label,
      autoResize: true,
      lineHeight: 1.25,
    };

    (arrow.boundElements as unknown[]) = [{ id: labelId, type: "text" }];
  }

  return { arrow, label: labelEl };
}

export interface WriterOptions {
  title?: string;
}

export function toExcalidraw(layout: LayoutResult, _options?: WriterOptions): object {
  // Reset ID counters per diagram
  _nextId = 1;
  _nextSeed = 100000;

  const elements: ExcalidrawElement[] = [];

  // Map node IDs to shape element IDs for arrow binding
  const nodeToShapeId = new Map<string, string>();
  const nodeLayoutMap = new Map<string, LayoutNode>();

  for (const n of layout.nodes) {
    nodeLayoutMap.set(n.id, n);
  }

  // Subgraphs first (behind nodes)
  for (const sg of layout.subgraphs) {
    const { rect, label } = makeSubgraph(sg);
    elements.push(rect, label);
  }

  // Nodes
  for (const node of layout.nodes) {
    const { shape, text } = makeShape(node);
    nodeToShapeId.set(node.id, shape.id as string);
    elements.push(shape, text);
  }

  // Arrows — collect which arrows bind to each shape
  const shapeArrows = new Map<string, { id: string; type: string }[]>();

  for (const edge of layout.edges) {
    const fromNode = nodeLayoutMap.get(edge.from);
    const toNode = nodeLayoutMap.get(edge.to);
    if (!fromNode || !toNode) continue;

    const { arrow, label } = makeArrow(edge, fromNode, toNode);

    // Patch bindings
    const fromShapeId = nodeToShapeId.get(edge.from)!;
    const toShapeId = nodeToShapeId.get(edge.to)!;
    (arrow.startBinding as { elementId: string }).elementId = fromShapeId;
    (arrow.endBinding as { elementId: string }).elementId = toShapeId;

    // Track arrow bindings on shapes
    if (!shapeArrows.has(fromShapeId)) shapeArrows.set(fromShapeId, []);
    if (!shapeArrows.has(toShapeId)) shapeArrows.set(toShapeId, []);
    shapeArrows.get(fromShapeId)!.push({ id: arrow.id as string, type: "arrow" });
    shapeArrows.get(toShapeId)!.push({ id: arrow.id as string, type: "arrow" });

    elements.push(arrow);
    if (label) elements.push(label);
  }

  // Patch shape boundElements to include arrows
  for (const el of elements) {
    if (el.type === "rectangle" || el.type === "diamond") {
      const arrows = shapeArrows.get(el.id as string) || [];
      const existing = (el.boundElements as { id: string; type: string }[]) || [];
      el.boundElements = [...existing, ...arrows];
    }
  }

  return {
    type: "excalidraw",
    version: 2,
    source: "arena-diagram-generator",
    elements,
    appState: {
      gridSize: null,
      viewBackgroundColor: "#ffffff",
    },
    files: {},
  };
}
