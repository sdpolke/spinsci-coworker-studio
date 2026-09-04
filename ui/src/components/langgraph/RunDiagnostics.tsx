'use client';

import { ExternalLink } from 'lucide-react';
import { useEffect, useState } from 'react';

import { getLanggraphRunDiagnosticsApiV1WorkflowRunsWorkflowRunIdLanggraphDiagnosticsGet } from '@/client/sdk.gen';
import type { RunDiagnosticsResponse } from '@/client/types.gen';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';

const SENSITIVE_KEYS = new Set(['authorization', 'credential', 'credentials', 'secret', 'token', 'api_key', 'prompt', 'transcript', 'arguments', 'result', 'checkpoint', 'checkpoint_reference']);
export function redactDiagnosticDetails(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redactDiagnosticDetails);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, SENSITIVE_KEYS.has(key.toLowerCase()) ? '[REDACTED]' : redactDiagnosticDetails(item)]));
  return typeof value === 'string' && value.length > 512 ? `${value.slice(0, 509)}...` : value;
}

export function RunDiagnostics({ runId, initialData }: { runId: number; initialData?: RunDiagnosticsResponse | null }) {
  const { user, loading: authLoading } = useAuth();
  const [data, setData] = useState<RunDiagnosticsResponse | null>(initialData ?? null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (initialData !== undefined || authLoading || !user) return;
    void (async () => {
      const response = await getLanggraphRunDiagnosticsApiV1WorkflowRunsWorkflowRunIdLanggraphDiagnosticsGet({ path: { workflow_run_id: runId } });
      if (response.error) {
        const detail = detailFromError(response.error, 'Run diagnostics unavailable');
        if (detail !== 'Run diagnostics not found') setError(detail);
        return;
      }
      setData(response.data ?? null);
    })();
  }, [authLoading, initialData, runId, user]);
  if (!data && !error) return null;
  if (error) return <div role="alert" className="rounded-md border border-destructive/40 p-3 text-sm text-destructive">{error}</div>;
  if (!data) return null;
  return <Card className="border-border"><CardHeader><CardTitle>LangGraph diagnostics</CardTitle><CardDescription>Tenant-scoped causal timeline combining Pipecat and endpoint execution records.</CardDescription><div className="flex flex-wrap gap-2 pt-2"><Badge variant="secondary">{data.compatibility_profile}</Badge><Badge variant="secondary">contract {data.contract_version}</Badge><Badge variant="secondary">{data.state_mode}</Badge></div></CardHeader><CardContent className="space-y-4">
    {Object.keys(data.external_identifiers ?? {}).length > 0 && <div><h4 className="text-sm font-semibold">External identifiers</h4><pre className="mt-1 overflow-auto rounded-md bg-muted p-2 text-xs">{JSON.stringify(redactDiagnosticDetails(data.external_identifiers), null, 2)}</pre></div>}
    <ol className="relative space-y-3 border-l pl-5">{data.events.map((event) => <li key={event.id} className="relative"><span className="absolute -left-[1.55rem] top-1.5 h-2 w-2 rounded-full bg-primary" /><div className="flex flex-wrap items-center gap-2"><Badge variant={event.category === 'error' ? 'destructive' : 'outline'}>{event.category.replaceAll('_', ' ')}</Badge><span className="text-sm font-medium">{event.order + 1}. {event.title}</span><time className="text-xs text-muted-foreground">{new Date(event.occurred_at).toLocaleString()}</time>{event.sequence != null && <span className="text-xs text-muted-foreground">seq {event.sequence}</span>}</div>{event.invocation_id && <p className="mt-1 font-mono text-[11px] text-muted-foreground">invocation {event.invocation_id}{event.attempt_id ? ` · attempt ${event.attempt_id}` : ''}</p>}<pre className="mt-2 overflow-auto rounded bg-muted/60 p-2 text-xs">{JSON.stringify(redactDiagnosticDetails(event.details), null, 2)}</pre>{event.trace_url && <a className="mt-2 inline-flex items-center gap-1 text-xs text-primary underline" href={event.trace_url}>Open trace {event.trace_id}<ExternalLink className="h-3 w-3" /></a>}</li>)}</ol>
  </CardContent></Card>;
}
