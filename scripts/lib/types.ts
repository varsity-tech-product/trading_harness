// Intermediate representation for Mermaid → Excalidraw conversion

export type NodeShape = "rectangle" | "diamond";
export type Direction = "LR" | "TD";

// Semantic layer — drives sizing, color, and visual weight
export type NodeRole = "primary" | "decision" | "result" | "error" | "system" | "convergence";

export interface MermaidNode {
  id: string;
  label: string;
  shape: NodeShape;
  subgraph?: string;
}

export interface MermaidEdge {
  from: string;
  to: string;
  label?: string;
}

export interface MermaidSubgraph {
  id: string;
  label: string;
}

export interface MermaidGraph {
  direction: Direction;
  nodes: MermaidNode[];
  edges: MermaidEdge[];
  subgraphs: MermaidSubgraph[];
}

// Annotation — floating explanatory text (the "human" layer)
export interface Annotation {
  text: string;
  nearNode: string; // node ID to anchor near
  offsetX?: number; // px offset from node
  offsetY?: number;
}

export interface LayoutNode extends MermaidNode {
  x: number;
  y: number;
  width: number;
  height: number;
  layer: number;
  role: NodeRole;
  fontSize: number;
}

export interface LayoutSubgraph extends MermaidSubgraph {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface LayoutAnnotation extends Annotation {
  x: number;
  y: number;
}

export interface LayoutResult {
  direction: Direction;
  nodes: LayoutNode[];
  edges: MermaidEdge[];
  subgraphs: LayoutSubgraph[];
  annotations: LayoutAnnotation[];
}
