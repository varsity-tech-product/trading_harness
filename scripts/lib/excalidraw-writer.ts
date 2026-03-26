// Converts layout result to Excalidraw JSON — intent-driven sketch style

import type { LayoutResult, LayoutNode, LayoutSubgraph, LayoutAnnotation, MermaidEdge, NodeRole } from "./types.js";

let _nextId = 1;
let _nextSeed = 100000;
function uid(prefix: string): string { return `${prefix}_${_nextId++}`; }
function seed(): number { return _nextSeed++; }

// --- Semantic color mapping ---

const ROLE_COLORS: Record<NodeRole, string> = {
  primary:     "#a5d8ff", // strong blue
  decision:    "#ffec99", // yellow
  result:      "#b2f2bb", // green
  error:       "#ffc9c9", // red
  system:      "#d0ebff", // light blue
  convergence: "#e5dbff", // light purple — where paths merge
};

interface ExcalidrawElement { [key: string]: unknown; }

function baseProps(id: string, type: string, x: number, y: number, w: number, h: number): ExcalidrawElement {
  return {
    id, type, x, y, width: w, height: h,
    angle: 0,
    strokeColor: "#000000",
    backgroundColor: "transparent",
    fillStyle: "hachure",
    strokeWidth: 1.5,
    strokeStyle: "solid",
    roughness: 2,
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

  const strokeWidth = node.role === "primary" ? 2 : 1.5;

  const shape: ExcalidrawElement = {
    ...baseProps(shapeId, type, node.x, node.y, node.width, node.height),
    backgroundColor: ROLE_COLORS[node.role],
    strokeWidth,
    roundness: type === "rectangle" ? { type: 3 } : { type: 2 },
    boundElements: [{ id: textId, type: "text" }],
  };

  const lines = node.label.split("\n");
  const textHeight = lines.length * node.fontSize * 1.25;
  const textWidth = node.width - 20;

  const text: ExcalidrawElement = {
    ...baseProps(textId, "text",
      node.x + (node.width - textWidth) / 2,
      node.y + (node.height - textHeight) / 2,
      textWidth, textHeight),
    text: node.label,
    fontSize: node.fontSize,
    fontFamily: 1, // Virgil
    textAlign: "center",
    verticalAlign: "middle",
    containerId: shapeId,
    originalText: node.label,
    autoResize: true,
    lineHeight: 1.25,
    roughness: 0,
  };

  return { shape, text };
}

function makeSubgraph(sg: LayoutSubgraph): { rect: ExcalidrawElement; label: ExcalidrawElement } {
  const rectId = uid("sg");
  const labelId = uid("sglabel");

  const rect: ExcalidrawElement = {
    ...baseProps(rectId, "rectangle", sg.x, sg.y, sg.width, sg.height),
    backgroundColor: "#f8f9fa",
    fillStyle: "solid",
    strokeStyle: "dashed",
    strokeWidth: 1,
    strokeColor: "#868e96",
    roughness: 2,
    roundness: { type: 3 },
    boundElements: [{ id: labelId, type: "text" }],
  };

  const label: ExcalidrawElement = {
    ...baseProps(labelId, "text", sg.x + 10, sg.y + 8, sg.width - 20, 17),
    text: sg.label,
    fontSize: 14,
    fontFamily: 1,
    textAlign: "left",
    verticalAlign: "top",
    containerId: rectId,
    originalText: sg.label,
    autoResize: true,
    lineHeight: 1.25,
    roughness: 0,
  };

  return { rect, label };
}

function makeAnnotation(ann: LayoutAnnotation): ExcalidrawElement {
  const id = uid("ann");
  const lines = ann.text.split("\n");
  const fontSize = 13;
  const maxLen = Math.max(...lines.map((l) => l.length));
  const width = maxLen * 7 + 16;
  const height = lines.length * fontSize * 1.4;

  return {
    ...baseProps(id, "text", ann.x - width / 2, ann.y - height / 2, width, height),
    text: ann.text,
    fontSize,
    fontFamily: 1,
    textAlign: "left",
    verticalAlign: "middle",
    strokeColor: "#868e96", // gray — annotation layer
    opacity: 85,
    originalText: ann.text,
    autoResize: true,
    lineHeight: 1.4,
    roughness: 0,
  };
}

function makeArrow(
  edge: MermaidEdge,
  fromNode: LayoutNode,
  toNode: LayoutNode,
): { arrow: ExcalidrawElement; label?: ExcalidrawElement } {
  const arrowId = uid("arrow");

  const fromCx = fromNode.x + fromNode.width / 2;
  const fromCy = fromNode.y + fromNode.height / 2;
  const toCx = toNode.x + toNode.width / 2;
  const toCy = toNode.y + toNode.height / 2;
  const dx = toCx - fromCx;
  const dy = toCy - fromCy;

  const arrow: ExcalidrawElement = {
    ...baseProps(arrowId, "arrow", fromCx, fromCy, Math.abs(dx), Math.abs(dy)),
    backgroundColor: "transparent",
    fillStyle: "solid",
    roundness: { type: 2 },
    points: [[0, 0], [dx, dy]],
    lastCommittedPoint: null,
    startBinding: { elementId: "", focus: 0, gap: 8, fixedPoint: null },
    endBinding: { elementId: "", focus: 0, gap: 8, fixedPoint: null },
    startArrowhead: null,
    endArrowhead: "arrow",
    elbowed: false,
  };

  let labelEl: ExcalidrawElement | undefined;
  if (edge.label) {
    const labelId = uid("elabel");
    const fontSize = 13;
    const labelWidth = edge.label.length * 7 + 16;
    const labelHeight = fontSize * 1.25;
    const midX = fromCx + dx / 2 - labelWidth / 2;
    const midY = fromCy + dy / 2 - labelHeight / 2 - 12;

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
      roughness: 0,
    };
    (arrow.boundElements as unknown[]) = [{ id: labelId, type: "text" }];
  }

  return { arrow, label: labelEl };
}

export function toExcalidraw(layout: LayoutResult): object {
  _nextId = 1;
  _nextSeed = 100000;

  const elements: ExcalidrawElement[] = [];
  const nodeToShapeId = new Map<string, string>();
  const nodeLayoutMap = new Map(layout.nodes.map((n) => [n.id, n]));

  // Subgraphs (background)
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

  // Arrows
  const shapeArrows = new Map<string, { id: string; type: string }[]>();

  for (const edge of layout.edges) {
    const fromNode = nodeLayoutMap.get(edge.from);
    const toNode = nodeLayoutMap.get(edge.to);
    if (!fromNode || !toNode) continue;

    const { arrow, label } = makeArrow(edge, fromNode, toNode);
    const fromShapeId = nodeToShapeId.get(edge.from)!;
    const toShapeId = nodeToShapeId.get(edge.to)!;
    (arrow.startBinding as { elementId: string }).elementId = fromShapeId;
    (arrow.endBinding as { elementId: string }).elementId = toShapeId;

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

  // Annotations (floating gray text — the human layer)
  for (const ann of layout.annotations) {
    elements.push(makeAnnotation(ann));
  }

  return {
    type: "excalidraw",
    version: 2,
    source: "arena-diagram-generator",
    elements,
    appState: { gridSize: null, viewBackgroundColor: "#ffffff" },
    files: {},
  };
}
