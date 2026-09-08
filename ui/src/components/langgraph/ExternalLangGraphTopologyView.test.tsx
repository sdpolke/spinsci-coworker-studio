import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { ExternalLangGraphTopologyView } from './ExternalLangGraphTopologyView';
import { adaptExternalTopologyResponse, type EndpointTopology, layoutGraph, mapEndpointTopology, namespaceEndpointNodeId } from './topology';

const flowProps = vi.hoisted(() => vi.fn());
vi.mock('@xyflow/react', async () => {
  const actual = await vi.importActual<typeof import('@xyflow/react')>('@xyflow/react');
  return {
    ...actual,
    ReactFlow: (props: { nodes: Array<{ id: string; data: { label: string } }>; children: ReactNode }) => {
      flowProps(props);
      return <div data-testid="topology-flow">{props.nodes.map((node) => <span key={node.id}>{node.data.label}</span>)}{props.children}</div>;
    },
    Background: () => null,
  };
});

const topology: EndpointTopology = {
  schema_version: '1.2', graph_id: 'endpoint-graph', revision: 'rev-1', view: 'collapsed',
  nodes: [{ id: '__start__', label: 'Start' }, { id: 'triage', label: 'Triage', type: 'agent' }],
  edges: [{ source: '__start__', target: 'triage', label: 'route' }],
};

const available = (overrides = {}) => ({
  status: 'available' as const,
  topology,
  binding_status: { state: 'binding_current' as const },
  actions: { can_revalidate: false, can_update_binding: false, can_refresh_topology: true, immutable: false },
  stages: { validation: 'passed' as const, binding_update: 'not_required' as const, topology_refresh: 'pinned' as const },
  ...overrides,
});

describe('external topology mapper and adapter', () => {
  it('namespaces endpoint IDs and creates non-editable React Flow elements', () => {
    const mapped = mapEndpointTopology(topology);
    expect(mapped.nodes[0]).toMatchObject({ id: 'endpoint:endpoint-graph:__start__', draggable: false, selectable: false, connectable: false, deletable: false });
    expect(mapped.edges[0]).toMatchObject({ source: namespaceEndpointNodeId('endpoint-graph', '__start__'), target: namespaceEndpointNodeId('endpoint-graph', 'triage'), reconnectable: false, selectable: false, deletable: false });
  });

  it('lays out generic graph elements without relying on node type semantics', () => {
    const mapped = mapEndpointTopology(topology);
    const positioned = layoutGraph(mapped.nodes, mapped.edges);
    expect(positioned.every((node) => Number.isFinite(node.position.x) && Number.isFinite(node.position.y))).toBe(true);
    expect(positioned[0].position).not.toEqual(positioned[1].position);
  });

  it('rejects malformed generic OpenAPI topology payloads with a stable schema reason', () => {
    expect(adaptExternalTopologyResponse({ status: 'available', topology: { graph_id: 'missing-fields' } })).toMatchObject({ status: 'unavailable', reason: 'topology_schema_invalid', topology: null });
  });
});

describe('ExternalLangGraphTopologyView', () => {
  it('renders an isolated read-only graph and combined lifecycle labels', async () => {
    render(<ExternalLangGraphTopologyView open onOpenChange={vi.fn()} loadTopology={async () => available()} />);
    expect(await screen.findByText('Triage')).toBeTruthy();
    expect(screen.getByText('Topology retrieval: succeeded')).toBeTruthy();
    expect(screen.getByText('Snapshot pinning: pinned')).toBeTruthy();
    expect(screen.queryByText(/Topology is unavailable \(binding current\)/i)).toBeNull();
    expect(flowProps.mock.lastCall?.[0]).toMatchObject({ nodesDraggable: false, nodesConnectable: false, elementsSelectable: false, edgesReconnectable: false, deleteKeyCode: null });
  });

  it('keeps a pinned graph visible for stale evidence and updates it from one explicit action', async () => {
    const updateBinding = vi.fn(async () => available({ topology: { ...topology, revision: 'rev-2' } }));
    render(<ExternalLangGraphTopologyView
      open onOpenChange={vi.fn()}
      loadTopology={async () => available({ reason: 'binding_stale', binding_status: { state: 'binding_stale' }, actions: { can_update_binding: true, immutable: false } })}
      updateBinding={updateBinding}
    />);
    expect(await screen.findByText('Triage')).toBeTruthy();
    expect(screen.getByText(/older endpoint evidence/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Update endpoint binding/i }));
    await waitFor(() => expect(updateBinding).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('topology-flow')).toBeTruthy();
  });

  it('retains the pinned graph and shows normalized action errors', async () => {
    render(<ExternalLangGraphTopologyView
      open onOpenChange={vi.fn()}
      loadTopology={async () => available()}
      refreshTopology={async () => { throw new Error('The endpoint could not be reached. Verify network policy.'); }}
    />);
    await screen.findByText('Triage');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh topology' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/Verify network policy/);
    expect(screen.getByText('Topology retrieval: failed')).toBeTruthy();
    expect(screen.getByText('Snapshot pinning: failed')).toBeTruthy();
    expect(screen.getByText(/previously pinned topology remains displayed/i)).toBeTruthy();
    expect(screen.getByTestId('topology-flow')).toBeTruthy();
  });

  it('retains the pinned graph when an action returns a schema-invalid payload', async () => {
    render(<ExternalLangGraphTopologyView
      open onOpenChange={vi.fn()}
      loadTopology={async () => available()}
      refreshTopology={async () => ({ status: 'unavailable', reason: 'topology_schema_invalid', topology: null })}
    />);
    await screen.findByText('Triage');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh topology' }));
    expect(await screen.findByText(/invalid topology schema/i)).toBeTruthy();
    expect(screen.getByTestId('topology-flow')).toBeTruthy();
  });

  it('disables mutation actions while endpoint configuration has unsaved changes', async () => {
    render(<ExternalLangGraphTopologyView
      open onOpenChange={vi.fn()}
      loadTopology={async () => available()}
      refreshTopology={vi.fn(async () => available())}
      mutationBlockedReason="Save or discard endpoint configuration changes before updating topology."
    />);
    const action = await screen.findByRole('button', { name: 'Refresh topology' });
    expect((action as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Save or discard endpoint configuration changes/i)).toBeTruthy();
  });

  it.each([
    ['topology_unsupported', /does not advertise operations\.topology/i],
    ['topology_auth_failed', /Verify the saved endpoint credential/i],
    ['topology_network_failed', /private-network policy/i],
    ['topology_schema_invalid', /invalid topology schema/i],
    ['draft_changed', /changed concurrently/i],
    ['snapshot_unavailable', /No topology snapshot is pinned/i],
  ])('shows redacted actionable guidance for %s', async (reason, expected) => {
    render(<ExternalLangGraphTopologyView open onOpenChange={vi.fn()} loadTopology={async () => ({ status: 'unavailable', reason: reason as 'topology_unsupported' })} />);
    expect((await screen.findAllByText(expected)).length).toBeGreaterThan(0);
  });

  it('pins the snapshot automatically for a current binding that has none yet', async () => {
    const refreshTopology = vi.fn(async () => available());
    render(<ExternalLangGraphTopologyView
      open onOpenChange={vi.fn()}
      loadTopology={async () => ({ status: 'unavailable' as const, reason: 'snapshot_unavailable' as const, binding_status: { state: 'binding_current' as const }, actions: { can_revalidate: false, can_update_binding: false, can_refresh_topology: true, immutable: false } })}
      refreshTopology={refreshTopology}
    />);
    expect(await screen.findByText('Triage')).toBeTruthy();
    expect(refreshTopology).toHaveBeenCalledTimes(1);
  });

  it('does not auto-pin while endpoint configuration changes are unsaved', async () => {
    const refreshTopology = vi.fn(async () => available());
    render(<ExternalLangGraphTopologyView
      open onOpenChange={vi.fn()}
      loadTopology={async () => ({ status: 'unavailable' as const, reason: 'snapshot_unavailable' as const, actions: { can_revalidate: false, can_update_binding: false, can_refresh_topology: true, immutable: false } })}
      refreshTopology={refreshTopology}
      mutationBlockedReason="Save or discard endpoint configuration changes before updating topology."
    />);
    expect(await screen.findByText(/Save or discard endpoint configuration changes/i)).toBeTruthy();
    expect(refreshTopology).not.toHaveBeenCalled();
  });

  it('leaves stale evidence adoption to an explicit action', async () => {
    const refreshTopology = vi.fn(async () => available());
    const updateBinding = vi.fn(async () => available());
    render(<ExternalLangGraphTopologyView
      open onOpenChange={vi.fn()}
      loadTopology={async () => ({ status: 'unavailable' as const, reason: 'binding_stale' as const, binding_status: { state: 'binding_stale' as const }, actions: { can_revalidate: false, can_update_binding: true, can_refresh_topology: false, immutable: false } })}
      refreshTopology={refreshTopology}
      updateBinding={updateBinding}
    />);
    expect((await screen.findAllByText(/older endpoint evidence/i)).length).toBeGreaterThan(0);
    expect(refreshTopology).not.toHaveBeenCalled();
    expect(updateBinding).not.toHaveBeenCalled();
  });

  it('runs revalidation progress and hides every mutation action for immutable versions', async () => {
    const recoverBinding = vi.fn(async (_signal: AbortSignal, onProgress: (stage: 'validation_passed') => void) => {
      onProgress('validation_passed');
      return available();
    });
    const { rerender } = render(<ExternalLangGraphTopologyView
      open onOpenChange={vi.fn()}
      loadTopology={async () => ({ status: 'unavailable', reason: 'endpoint_revalidation_required', actions: { can_revalidate: true, immutable: false }, stages: { validation: 'required' } })}
      recoverBinding={recoverBinding}
    />);
    const action = await screen.findByRole('button', { name: /Revalidate endpoint and update draft/i });
    fireEvent.click(action);
    await waitFor(() => expect(recoverBinding).toHaveBeenCalledTimes(1));

    rerender(<ExternalLangGraphTopologyView
      open onOpenChange={vi.fn()}
      loadTopology={async () => available({ reason: 'immutable_snapshot_only', binding_status: { state: 'immutable_snapshot_only' }, actions: { can_revalidate: true, can_update_binding: true, can_refresh_topology: true, immutable: true } })}
      refreshTopology={vi.fn()} updateBinding={vi.fn()} recoverBinding={recoverBinding}
    />);
    await screen.findByText(/version-local pinned topology/i);
    expect(screen.queryByRole('button', { name: /refresh topology/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /update endpoint binding/i })).toBeNull();
  });

  it('clears a prior version snapshot when the topology loader identity changes', async () => {
    const firstLoader = vi.fn(async () => available());
    const secondLoader = vi.fn(async () => { throw new Error('new version unavailable'); });
    const { rerender } = render(<ExternalLangGraphTopologyView open onOpenChange={vi.fn()} loadTopology={firstLoader} />);
    await screen.findByText('Triage');
    rerender(<ExternalLangGraphTopologyView open onOpenChange={vi.fn()} loadTopology={secondLoader} />);
    await waitFor(() => expect(screen.queryByText('Triage')).toBeNull());
    expect((await screen.findByRole('alert')).textContent).toContain('new version unavailable');
    expect(screen.queryByTestId('topology-flow')).toBeNull();
  });

  it('shows an empty state without creating workflow/runtime state', async () => {
    const workflowNodes = [{ id: 'startCall' }];
    render(<ExternalLangGraphTopologyView open onOpenChange={vi.fn()} loadTopology={async () => available({ topology: { ...topology, nodes: [] } })} />);
    expect(await screen.findByText(/has no nodes to display/i)).toBeTruthy();
    expect(workflowNodes).toEqual([{ id: 'startCall' }]);
  });
});
