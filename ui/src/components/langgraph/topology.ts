import dagre from '@dagrejs/dagre';
import type { Edge, Node } from '@xyflow/react';

import type {
  DraftBindingStatus,
  ExternalTopologyResponse as GeneratedExternalTopologyResponse,
  TopologyActionAvailability,
  TopologyLifecycleStages,
} from '@/client/types.gen';

export const EXTERNAL_TOPOLOGY_NODE_TYPE = 'externalTopologyNode';
export const EXTERNAL_TOPOLOGY_EDGE_TYPE = 'externalTopologyEdge';

export type EndpointTopologyNode = {
  id: string;
  label: string;
  type?: string | null;
  metadata?: Record<string, unknown> | null;
};

export type EndpointTopologyEdge = {
  id?: string | null;
  source: string;
  target: string;
  label?: string | null;
  metadata?: Record<string, unknown> | null;
};

export type EndpointTopology = {
  schema_version: string;
  graph_id: string;
  revision: string;
  view: 'collapsed' | 'expanded';
  nodes: EndpointTopologyNode[];
  edges: EndpointTopologyEdge[];
};

export type ExternalTopologyResponse = Omit<GeneratedExternalTopologyResponse, 'topology'> & {
  topology?: EndpointTopology | null;
  binding_status?: DraftBindingStatus | null;
  actions?: TopologyActionAvailability | null;
  stages?: TopologyLifecycleStages | null;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/** OpenAPI intentionally exposes topology as an object, so validate its render shape at the UI boundary. */
export function isEndpointTopology(value: unknown): value is EndpointTopology {
  if (!isRecord(value)
    || typeof value.schema_version !== 'string'
    || typeof value.graph_id !== 'string'
    || typeof value.revision !== 'string'
    || (value.view !== 'collapsed' && value.view !== 'expanded')
    || !Array.isArray(value.nodes)
    || !Array.isArray(value.edges)) return false;
  return value.nodes.every((node) => isRecord(node)
      && typeof node.id === 'string'
      && typeof node.label === 'string')
    && value.edges.every((edge) => isRecord(edge)
      && typeof edge.source === 'string'
      && typeof edge.target === 'string');
}

export function adaptExternalTopologyResponse(response: GeneratedExternalTopologyResponse): ExternalTopologyResponse {
  if (response.topology == null) return response as ExternalTopologyResponse;
  if (isEndpointTopology(response.topology)) return response as ExternalTopologyResponse;
  return { ...response, status: 'unavailable', reason: 'topology_schema_invalid', topology: null };
}

export type ExternalTopologyNodeData = {
  endpointNodeId: string;
  label: string;
  nodeType?: string | null;
};

export type ExternalTopologyEdgeData = {
  label?: string | null;
};

export type ExternalTopologyNode = Node<ExternalTopologyNodeData, typeof EXTERNAL_TOPOLOGY_NODE_TYPE>;
export type ExternalTopologyEdge = Edge<ExternalTopologyEdgeData, typeof EXTERNAL_TOPOLOGY_EDGE_TYPE>;

export const namespaceEndpointNodeId = (graphId: string, nodeId: string) =>
  `endpoint:${graphId}:${nodeId}`;

export function mapEndpointTopology(topology: EndpointTopology): {
  nodes: ExternalTopologyNode[];
  edges: ExternalTopologyEdge[];
} {
  const nodeIds = new Set(topology.nodes.map((node) => node.id));
  const nodes: ExternalTopologyNode[] = topology.nodes.map((node) => ({
    id: namespaceEndpointNodeId(topology.graph_id, node.id),
    type: EXTERNAL_TOPOLOGY_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: { endpointNodeId: node.id, label: node.label, nodeType: node.type },
    draggable: false,
    selectable: false,
    connectable: false,
    deletable: false,
  }));
  const edges: ExternalTopologyEdge[] = topology.edges
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .map((edge, index) => ({
      id: edge.id ? `endpoint:${topology.graph_id}:${edge.id}` : `endpoint:${topology.graph_id}:${edge.source}:${edge.target}:${index}`,
      source: namespaceEndpointNodeId(topology.graph_id, edge.source),
      target: namespaceEndpointNodeId(topology.graph_id, edge.target),
      type: EXTERNAL_TOPOLOGY_EDGE_TYPE,
      data: { label: edge.label },
      selectable: false,
      reconnectable: false,
      deletable: false,
    }));
  return { nodes, edges };
}

/** Generic layout: it only needs graph elements and never inspects node semantics. */
export function layoutGraph<TNode extends Node, TEdge extends Edge>(
  nodes: TNode[],
  edges: TEdge[],
  options: { direction?: 'TB' | 'LR'; nodeWidth?: number; nodeHeight?: number } = {},
): TNode[] {
  const { direction = 'TB', nodeWidth = 220, nodeHeight = 88 } = options;
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: direction, nodesep: 56, ranksep: 96 });
  nodes.forEach((node) => graph.setNode(node.id, { width: node.measured?.width ?? nodeWidth, height: node.measured?.height ?? nodeHeight }));
  edges.forEach((edge) => graph.setEdge(edge.source, edge.target));
  dagre.layout(graph);
  return nodes.map((node) => {
    const position = graph.node(node.id) as { x: number; y: number };
    const width = node.measured?.width ?? nodeWidth;
    const height = node.measured?.height ?? nodeHeight;
    return { ...node, position: { x: position.x - width / 2, y: position.y - height / 2 } };
  });
}
