// Converts layout result to Excalidraw JSON — clean hand-drawn sketch style
// Reference: autoresearch loop / agent loop diagram aesthetic

import type { LayoutResult, LayoutNode, LayoutSubgraph, LayoutAnnotation, MermaidEdge, NodeRole } from "./types.js";

let _nextId = 1;
let _nextSeed = 100000;
function uid(prefix: string): string { return `${prefix}_${_nextId++}`; }
function seed(): number { return _nextSeed++; }

// --- Style: minimal fills, only success/error get color ---

function bgColor(role: NodeRole): string {
  if (role === "result") return "#d8f5a2";   // soft green
  if (role === "error") return "#ffc9c9";    // soft red
  return "transparent";                       // everything else: no fill
}

function strokeColor(role: NodeRole): string {
  if (role === "result") return "#2b8a3e";
  if (role === "error") return "#c92a2a";
  return "#1e1e1e";
}

interface ExcalidrawElement { [key: string]: unknown; }

function baseProps(id: string, type: string, x: number, y: number, w: number, h: number): ExcalidrawElement {
  return {
    id, type, x, y, width: w, height: h,
    angle: 0,
    strokeColor: "#1e1e1e",
    backgroundColor: "transparent",
    fillStyle: "solid",
    strokeWidth: 1,
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

function makeTitle(title: string, layout: LayoutResult): ExcalidrawElement {
  const id = uid("title");
  // Center title above all nodes
  const allX = layout.nodes.map((n) => n.x + n.width / 2);
  const centerX = (Math.min(...allX) + Math.max(...allX)) / 2;
  const topY = Math.min(...layout.nodes.map((n) => n.y));

  const fontSize = 32;
  const width = title.length * 18;

  return {
    ...baseProps(id, "text", centerX - width / 2, topY - 70, width, fontSize * 1.3),
    text: title,
    fontSize,
    fontFamily: 1, // Virgil
    textAlign: "center",
    verticalAlign: "middle",
    strokeColor: "#1e1e1e",
    originalText: title,
    autoResize: true,
    lineHeight: 1.25,
    roughness: 0,
  };
}

function makeShape(node: LayoutNode): { shape: ExcalidrawElement; text: ExcalidrawElement } {
  const shapeId = uid("shape");
  const textId = uid("text");
  const type = node.shape === "diamond" ? "diamond" : "rectangle";
  const bg = bgColor(node.role);
  const stroke = strokeColor(node.role);
  const sw = node.role === "primary" ? 1.5 : 1;

  const shape: ExcalidrawElement = {
    ...baseProps(shapeId, type, node.x, node.y, node.width, node.height),
    backgroundColor: bg,
    strokeColor: stroke,
    strokeWidth: sw,
    roundness: type === "rectangle" ? { type: 3 } : { type: 2 },
    boundElements: [{ id: textId, type: "text" }],
  };

  const lines = node.label.split("\n");
  const textHeight = lines.length * node.fontSize * 1.25;
  const textWidth = node.width - 16;

  const text: ExcalidrawElement = {
    ...baseProps(textId, "text",
      node.x + (node.width - textWidth) / 2,
      node.y + (node.height - textHeight) / 2,
      textWidth, textHeight),
    text: node.label,
    fontSize: node.fontSize,
    fontFamily: 1,
    textAlign: "center",
    verticalAlign: "middle",
    strokeColor: stroke,
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
    backgroundColor: "transparent",
    strokeStyle: "dashed",
    strokeWidth: 1,
    strokeColor: "#adb5bd",
    roughness: 1,
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
    strokeColor: "#868e96",
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
  const fontSize = 14;
  const maxLen = Math.max(...lines.map((l) => l.length));
  const width = maxLen * 8 + 12;
  const height = lines.length * fontSize * 1.5;

  return {
    ...baseProps(id, "text", ann.x - width / 2, ann.y - height / 2, width, height),
    text: ann.text,
    fontSize,
    fontFamily: 1,
    textAlign: "left",
    verticalAlign: "middle",
    strokeColor: "#868e96",
    opacity: 90,
    originalText: ann.text,
    autoResize: true,
    lineHeight: 1.5,
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

  // Red arrows for main flow, dark for back-edges
  const isBackEdge = (toNode.layer ?? 0) <= (fromNode.layer ?? 0);
  const arrowColor = isBackEdge ? "#495057" : "#e03131";

  const arrow: ExcalidrawElement = {
    ...baseProps(arrowId, "arrow", fromCx, fromCy, Math.abs(dx), Math.abs(dy)),
    strokeColor: arrowColor,
    backgroundColor: "transparent",
    fillStyle: "solid",
    strokeWidth: 1.5,
    roundness: { type: 2 },
    points: [[0, 0], [dx, dy]],
    lastCommittedPoint: null,
    startBinding: { elementId: "", focus: 0, gap: 5, fixedPoint: null },
    endBinding: { elementId: "", focus: 0, gap: 5, fixedPoint: null },
    startArrowhead: null,
    endArrowhead: "arrow",
    elbowed: false,
  };

  let labelEl: ExcalidrawElement | undefined;
  if (edge.label) {
    const labelId = uid("elabel");
    const fontSize = 14;
    const labelWidth = edge.label.length * 8 + 12;
    const labelHeight = fontSize * 1.25;
    const midX = fromCx + dx / 2 - labelWidth / 2;
    const midY = fromCy + dy / 2 - labelHeight / 2 - 10;

    labelEl = {
      ...baseProps(labelId, "text", midX, midY, labelWidth, labelHeight),
      text: edge.label,
      fontSize,
      fontFamily: 1,
      textAlign: "center",
      verticalAlign: "middle",
      strokeColor: arrowColor,
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

export function toExcalidraw(layout: LayoutResult, title?: string): object {
  _nextId = 1;
  _nextSeed = 100000;

  const elements: ExcalidrawElement[] = [];
  const nodeToShapeId = new Map<string, string>();
  const nodeLayoutMap = new Map(layout.nodes.map((n) => [n.id, n]));

  // Title
  if (title) elements.push(makeTitle(title, layout));

  // Subgraphs
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

  // Patch boundElements
  for (const el of elements) {
    if (el.type === "rectangle" || el.type === "diamond") {
      const arrows = shapeArrows.get(el.id as string) || [];
      const existing = (el.boundElements as { id: string; type: string }[]) || [];
      el.boundElements = [...existing, ...arrows];
    }
  }

  // Annotations
  for (const ann of layout.annotations) elements.push(makeAnnotation(ann));

  return {
    type: "excalidraw",
    version: 2,
    source: "arena-diagram-generator",
    elements,
    appState: { gridSize: null, viewBackgroundColor: "#ffffff" },
    files: {},
  };
}
