'use client';

import { Background, BackgroundVariant, BaseEdge, EdgeLabelRenderer, type EdgeProps, getBezierPath, Handle, type NodeProps, Position, ReactFlow } from '@xyflow/react';
import { Bot, CircleDot, GitBranch, LoaderCircle, Network, Square, Wrench } from 'lucide-react';
import { type ComponentProps, type ComponentType, type ReactNode, useEffect, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';

import {
  EXTERNAL_TOPOLOGY_EDGE_TYPE,
  EXTERNAL_TOPOLOGY_NODE_TYPE,
  type ExternalTopologyEdge,
  type ExternalTopologyNode,
  type ExternalTopologyResponse,
  layoutGraph,
  mapEndpointTopology,
  type TopologyNodeKind,
} from './topology';
import type { RecoveryProgress } from './topologyRecovery';

// Per-kind presentation. Colors use Tailwind palette classes with dark variants so
// the graph reads at a glance (start/end/agent/tool/condition) and themes correctly.
const KIND_STYLES: Record<TopologyNodeKind, { container: string; handle: string; icon: ComponentType<{ className?: string }>; label: string }> = {
  start: { container: 'border-emerald-400 bg-emerald-50 dark:border-emerald-700 dark:bg-emerald-950', handle: '!bg-emerald-500', icon: CircleDot, label: 'Start' },
  end: { container: 'border-rose-400 bg-rose-50 dark:border-rose-700 dark:bg-rose-950', handle: '!bg-rose-500', icon: Square, label: 'End' },
  agent: { container: 'border-blue-400 bg-blue-50 dark:border-blue-700 dark:bg-blue-950', handle: '!bg-blue-500', icon: Bot, label: 'Agent' },
  tool: { container: 'border-amber-400 bg-amber-50 dark:border-amber-700 dark:bg-amber-950', handle: '!bg-amber-500', icon: Wrench, label: 'Tool' },
  condition: { container: 'border-violet-400 bg-violet-50 dark:border-violet-700 dark:bg-violet-950', handle: '!bg-violet-500', icon: GitBranch, label: 'Condition' },
};

function ExternalTopologyNodeComponent({ data }: NodeProps<ExternalTopologyNode>) {
  const style = KIND_STYLES[data.kind] ?? KIND_STYLES.agent;
  const Icon = style.icon;
  return <div className={`min-w-[180px] rounded-lg border px-4 py-3 shadow-sm ${style.container}`}>
    <Handle type="target" position={Position.Top} isConnectable={false} className={style.handle} />
    <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground"><Icon className="h-3 w-3" />{style.label}</div>
    <div className="mt-1 text-sm font-semibold text-foreground">{data.label}</div>
    <div className="mt-1 text-xs text-muted-foreground">Endpoint node · {data.endpointNodeId}</div>
    {data.nodeType && <div className="mt-0.5 text-xs text-muted-foreground">{data.nodeType}</div>}
    <Handle type="source" position={Position.Bottom} isConnectable={false} className={style.handle} />
  </div>;
}

function ExternalTopologyEdgeComponent(props: EdgeProps<ExternalTopologyEdge>) {
  const [path, labelX, labelY] = getBezierPath(props);
  const conditional = props.data?.conditional === true;
  const stroke = conditional ? '#94a3b8' : '#7c3aed';
  return <><BaseEdge id={props.id} path={path} markerEnd={props.markerEnd} style={{ stroke, strokeWidth: 2, strokeDasharray: conditional ? '6 4' : undefined }} />
    {props.data?.label && <EdgeLabelRenderer><span className={`nodrag nopan absolute rounded px-1.5 py-0.5 text-xs ${conditional ? 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200' : 'bg-violet-100 text-violet-900 dark:bg-violet-900 dark:text-violet-100'}`} style={{ transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)` }}>{props.data.label}</span></EdgeLabelRenderer>}
  </>;
}

const nodeTypes = { [EXTERNAL_TOPOLOGY_NODE_TYPE]: ExternalTopologyNodeComponent };
const edgeTypes = { [EXTERNAL_TOPOLOGY_EDGE_TYPE]: ExternalTopologyEdgeComponent };

const guidance: Record<string, string> = {
  snapshot_unavailable: 'No topology snapshot is pinned. Update or refresh this Current Draft to retrieve one.',
  binding_stale: 'This draft uses older endpoint evidence. Update its endpoint binding to the current validated evidence and refresh topology.',
  topology_unsupported: 'Current endpoint discovery does not advertise operations.topology. Inspect authenticated discovery, then restart or update the endpoint.',
  endpoint_revalidation_required: 'Current passing endpoint evidence is unavailable. Revalidate the endpoint before updating this draft.',
  endpoint_validation_failed: 'Endpoint validation failed. Review the validation report, endpoint contract, credentials, and network access.',
  topology_auth_failed: 'Topology authentication failed. Verify the saved endpoint credential; secret values are never displayed here.',
  topology_network_failed: 'The endpoint could not be reached. Verify endpoint availability, its URL, and private-network policy.',
  topology_schema_invalid: 'The endpoint returned an invalid topology schema. Verify its advertised contract and topology response.',
  draft_changed: 'The draft changed concurrently. Reload the draft and retry the topology update.',
  binding_incompatible: 'The endpoint profile or selected capabilities no longer match this draft. Reconfigure the endpoint binding explicitly.',
  snapshot_required_for_immutable_version: 'This immutable version has no pinned snapshot. Create or open a Current Draft to retrieve topology.',
  immutable_snapshot_only: 'This immutable version shows only its version-local pinned topology.',
  endpoint_unavailable: 'The saved endpoint is unavailable in this organization. Verify the endpoint registration and permissions.',
};

function statusMessage(response: ExternalTopologyResponse | null) {
  const reason = response?.reason ?? response?.binding_status?.reason ?? response?.binding_status?.state;
  if (!reason || (reason === 'binding_current' && response?.status === 'available')) return null;
  return guidance[reason] ?? `Topology is unavailable (${reason.replaceAll('_', ' ')}).`;
}

type ActionFailureStage = 'validation' | 'binding_update' | 'topology_refresh';

function LifecycleStages({ response, progress, failureStage }: { response: ExternalTopologyResponse; progress: RecoveryProgress | null; failureStage: ActionFailureStage | null }) {
  const validation = failureStage === 'validation' ? 'failed' : progress === 'validation_pending' ? 'pending' : progress === 'validation_passed' || progress === 'activation_pending' || progress === 'binding_update_pending' ? 'passed' : response.stages?.validation ?? 'not_required';
  const binding = failureStage === 'binding_update' ? 'failed' : progress === 'binding_update_pending' ? 'pending' : response.stages?.binding_update ?? 'not_required';
  const refresh = failureStage === 'binding_update' || failureStage === 'topology_refresh' ? 'failed' : progress === 'binding_update_pending' || progress === 'topology_refresh_pending' ? 'pending' : response.stages?.topology_refresh ?? 'not_started';
  const retrieval = refresh === 'pinned' ? 'succeeded' : refresh === 'pending' ? 'in progress' : refresh === 'failed' ? 'failed' : 'not started';
  const pinning = refresh === 'pinned' ? 'pinned' : refresh === 'pending' ? 'waiting' : refresh === 'failed' ? 'failed' : 'not started';
  return <div className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-2" aria-label="Topology lifecycle">
    <span>Endpoint validation: {validation.replaceAll('_', ' ')}</span>
    <span>Binding update: {binding.replaceAll('_', ' ')}</span>
    <span>Topology retrieval: {retrieval}</span>
    <span>Snapshot pinning: {pinning}</span>
  </div>;
}

type TopologyAction = (signal?: AbortSignal) => Promise<ExternalTopologyResponse>;

type TopologyPanelProps = {
  /** When true the panel loads/renders; when false it resets. Drives both the dialog and embedded usage. */
  active: boolean;
  loadTopology: () => Promise<ExternalTopologyResponse>;
  refreshTopology?: TopologyAction;
  updateBinding?: TopologyAction;
  recoverBinding?: (signal: AbortSignal, onProgress: (progress: RecoveryProgress) => void) => Promise<ExternalTopologyResponse>;
  mutationBlockedReason?: string;
  /** Extra classes for the graph container (e.g. a fixed height when embedded). */
  className?: string;
};

/**
 * The read-only LangGraph topology graph plus its lifecycle/actions UI, with no
 * surrounding chrome. Reused by both the dialog ({@link ExternalLangGraphTopologyView})
 * and the embedded editor panel ({@link EmbeddedLangGraphTopologyPanel}).
 */
export function ExternalLangGraphTopologyPanel({
  active,
  loadTopology,
  refreshTopology,
  updateBinding,
  recoverBinding,
  mutationBlockedReason,
  className,
}: TopologyPanelProps) {
  const open = active;
  const [response, setResponse] = useState<ExternalTopologyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [failureStage, setFailureStage] = useState<ActionFailureStage | null>(null);
  const [progress, setProgress] = useState<RecoveryProgress | null>(null);
  const actionController = useRef<AbortController | null>(null);
  const autoRefreshed = useRef(false);

  useEffect(() => {
    if (!open) {
      actionController.current?.abort();
      setProgress(null);
      autoRefreshed.current = false;
      return;
    }
    let cancelled = false;
    setResponse(null);
    setLoading(true);
    setActionError(null);
    setFailureStage(null);
    void loadTopology().then((next) => {
      if (!cancelled) setResponse(next);
    }).catch((cause: unknown) => {
      if (!cancelled) setActionError(cause instanceof Error ? cause.message : 'Failed to retrieve endpoint topology');
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
      actionController.current?.abort();
    };
  }, [loadTopology, open]);

  const elements = useMemo(() => response?.topology
    ? (() => { const mapped = mapEndpointTopology(response.topology); return { nodes: layoutGraph(mapped.nodes, mapped.edges), edges: mapped.edges }; })()
    : null, [response]);

  const runAction = async (
    action: TopologyAction | undefined,
    recovery = false,
    initialProgress: RecoveryProgress = 'binding_update_pending',
  ) => {
    if ((!action && !recovery) || progress || mutationBlockedReason) return;
    const controller = new AbortController();
    actionController.current = controller;
    setActionError(null);
    setFailureStage(null);
    let activeProgress: RecoveryProgress = recovery ? 'validation_pending' : initialProgress;
    setProgress(activeProgress);
    try {
      const next = recovery && recoverBinding
        ? await recoverBinding(controller.signal, (nextProgress) => {
          activeProgress = nextProgress;
          setProgress(nextProgress);
        })
        : await action!(controller.signal);
      if (!controller.signal.aborted) {
        setResponse((previous) => next.topology || !previous?.topology
          ? next
          : { ...next, topology: previous.topology });
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        setActionError(cause instanceof Error ? cause.message : 'Topology update failed');
        setFailureStage(
          activeProgress === 'topology_refresh_pending'
            ? 'topology_refresh'
            : activeProgress === 'binding_update_pending'
              ? 'binding_update'
              : 'validation',
        );
      }
    } finally {
      setProgress(null);
      if (actionController.current === controller) actionController.current = null;
    }
  };

  // A current binding carries no pinned snapshot until topology is refreshed once, and
  // GET stays side-effect free by design. Pin it here so a correctly bound draft renders
  // its graph without the operator pressing Refresh first. Stale bindings are left alone:
  // adopting new endpoint evidence stays an explicit decision.
  useEffect(() => {
    if (!open || loading || progress || autoRefreshed.current) return;
    if (response?.topology || response?.reason !== 'snapshot_unavailable') return;
    if (!refreshTopology || !response.actions?.can_refresh_topology || mutationBlockedReason) return;
    autoRefreshed.current = true;
    void runAction(refreshTopology, false, 'topology_refresh_pending');
    // runAction is recreated every render; the ref guard keeps this to one attempt per open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, mutationBlockedReason, open, progress, refreshTopology, response]);

  const immutable = response?.actions?.immutable === true || response?.binding_status?.state === 'immutable_snapshot_only';
  const message = statusMessage(response);
  const empty = response?.topology?.nodes.length === 0;

  return <>
    {(message || actionError || mutationBlockedReason) && <div role={actionError ? 'alert' : 'status'} className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm"><p>{actionError ?? mutationBlockedReason ?? message}</p>{response?.topology && (actionError || message) && <p className="mt-1 text-xs text-muted-foreground">The previously pinned topology remains displayed below.</p>}</div>}
    {response && <LifecycleStages response={response} progress={progress} failureStage={failureStage} />}
    {!immutable && response?.actions && <div className="flex flex-wrap gap-2">
      {response.actions.can_revalidate && recoverBinding && <Button type="button" size="sm" disabled={Boolean(progress) || Boolean(mutationBlockedReason)} onClick={() => void runAction(undefined, true)}>{progress ? <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> : null}Revalidate endpoint and update draft</Button>}
      {response.actions.can_update_binding && updateBinding && <Button type="button" size="sm" disabled={Boolean(progress) || Boolean(mutationBlockedReason)} onClick={() => void runAction(updateBinding)}>{progress ? <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> : null}Update endpoint binding and refresh topology</Button>}
      {response.actions.can_refresh_topology && refreshTopology && <Button type="button" size="sm" variant="outline" disabled={Boolean(progress) || Boolean(mutationBlockedReason)} onClick={() => void runAction(refreshTopology, false, 'topology_refresh_pending')}>{progress ? <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> : null}Refresh topology</Button>}
    </div>}
    <div className={`min-h-0 flex-1 ${className ?? ''}`}>
      {(loading || progress) && !response?.topology ? <div className="flex h-full min-h-56 items-center justify-center gap-2 text-sm text-muted-foreground" role="status"><LoaderCircle className="h-5 w-5 animate-spin" />Loading endpoint topology…</div>
        : response?.topology && !empty ? <ReactFlow
          nodes={elements?.nodes ?? []} edges={elements?.edges ?? []} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
          nodesDraggable={false} nodesConnectable={false} nodesFocusable={false} edgesFocusable={false}
          edgesReconnectable={false} elementsSelectable={false} deleteKeyCode={null} fitView fitViewOptions={{ padding: 0.2 }}
          panOnDrag zoomOnScroll zoomOnPinch
        ><Background variant={BackgroundVariant.Dots} gap={16} size={1} /></ReactFlow>
          : <div className="flex h-full min-h-56 items-center justify-center rounded-md border border-dashed p-6 text-sm text-muted-foreground" role="status">{empty ? 'The endpoint topology has no nodes to display.' : (message ?? actionError ?? 'No endpoint topology is available.')}</div>}
    </div>
  </>;
}

export function ExternalLangGraphTopologyView({
  open,
  onOpenChange,
  ...panelProps
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
} & Omit<TopologyPanelProps, 'active'>) {
  // sm:max-w-6xl, not max-w-6xl: DialogContent's own sm:max-w-lg would otherwise win at
  // every breakpoint above 640px and squeeze the graph into a narrow column.
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="flex h-[80vh] w-full sm:max-w-6xl flex-col p-6">
    <DialogHeader><DialogTitle className="flex items-center gap-2"><Network className="h-5 w-5" />External LangGraph topology</DialogTitle><DialogDescription>Endpoint-owned topology is read-only.</DialogDescription></DialogHeader>
    <ExternalLangGraphTopologyPanel active={open} {...panelProps} />
  </DialogContent></Dialog>;
}

/**
 * Embeds the topology graph inline (e.g. inside the workflow editor) instead of
 * behind a modal. Loads as soon as it mounts.
 */
export function EmbeddedLangGraphTopologyPanel(props: Omit<TopologyPanelProps, 'active'>) {
  return <div className="flex flex-col gap-3"><ExternalLangGraphTopologyPanel active {...props} className="h-[480px] rounded-md border" /></div>;
}

export function ExternalTopologyLaunchButton({ children, ...props }: Omit<ComponentProps<typeof ExternalLangGraphTopologyView>, 'open' | 'onOpenChange'> & { children?: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <><Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>{children ?? 'View endpoint topology'}</Button><ExternalLangGraphTopologyView {...props} open={open} onOpenChange={setOpen} /></>;
}

export { ExternalTopologyEdgeComponent, ExternalTopologyNodeComponent };
