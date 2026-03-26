// Intermediate representation for Mermaid → Excalidraw conversion

export type NodeShape = "rectangle" | "diamond";
export type Direction = "LR" | "TD";

export interface MermaidNode {
  id: string;
  label: string; // display text, newlines for <br/>
  shape: NodeShape;
  subgraph?: string; // parent subgraph ID
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

export interface LayoutNode extends MermaidNode {
  x: number;
  y: number;
  width: number;
  height: number;
  layer: number;
}

export interface LayoutSubgraph extends MermaidSubgraph {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface LayoutResult {
  direction: Direction;
  nodes: LayoutNode[];
  edges: MermaidEdge[];
  subgraphs: LayoutSubgraph[];
}
