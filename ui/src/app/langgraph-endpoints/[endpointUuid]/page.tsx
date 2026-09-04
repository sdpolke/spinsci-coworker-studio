'use client';

import { Pencil } from 'lucide-react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { activateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidActivatePost, deactivateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidDeactivatePost, deleteLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidDelete, getLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidGet, listLanggraphValidationReportsApiV1LanggraphEndpointsEndpointUuidValidationReportsGet, validateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidValidatePost } from '@/client/sdk.gen';
import type { EndpointResponse, ValidationReportResponse } from '@/client/types.gen';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';

const values = (manifest: Record<string, unknown> | undefined, key: string) => Array.isArray(manifest?.[key]) ? (manifest?.[key] as unknown[]).map(String) : [];

export default function LangGraphEndpointDetailPage() {
  const { endpointUuid } = useParams<{ endpointUuid: string }>();
  const { user, loading: authLoading } = useAuth();
  const [endpoint, setEndpoint] = useState<EndpointResponse | null>(null);
  const [reports, setReports] = useState<ValidationReportResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    if (authLoading || !user) return;
    const [endpointResponse, reportsResponse] = await Promise.all([
      getLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidGet({ path: { endpoint_uuid: endpointUuid } }),
      listLanggraphValidationReportsApiV1LanggraphEndpointsEndpointUuidValidationReportsGet({ path: { endpoint_uuid: endpointUuid } }),
    ]);
    if (endpointResponse.error) { setError(detailFromError(endpointResponse.error, 'Endpoint unavailable')); return; }
    if (reportsResponse.error) { setError(detailFromError(reportsResponse.error, 'Validation history unavailable')); return; }
    setEndpoint(endpointResponse.data ?? null); setReports(reportsResponse.data ?? []);
  }, [authLoading, endpointUuid, user]);
  useEffect(() => { void load(); }, [load]);

  const action = async (name: string, call: () => Promise<{ error?: unknown }>) => { setBusy(true); try { const response = await call(); if (response.error) throw new Error(detailFromError(response.error, `Failed to ${name}`)); toast.success(`Endpoint ${name} request accepted`); await load(); } catch (cause) { toast.error(cause instanceof Error ? cause.message : `Failed to ${name}`); } finally { setBusy(false); } };
  const retire = async () => { await action('retire', () => deleteLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidDelete({ path: { endpoint_uuid: endpointUuid } })); if (endpoint?.lifecycle_status !== 'retired') await load(); };

  if (error) return <div className="container mx-auto px-4 py-8"><div role="alert" className="rounded-md border border-destructive/40 p-4 text-destructive">{error}</div></div>;
  if (!endpoint) return <div className="container mx-auto px-4 py-8">Loading endpoint…</div>;
  const manifest = endpoint.current_capability_snapshot?.manifest as Record<string, unknown> | undefined;
  const latest = reports[0];
  const latencyEligible = latest?.status === 'passed' || latest?.status === 'live_voice_eligible';
  return <div className="container mx-auto max-w-5xl space-y-5 px-4 py-8">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-2"><h1 className="text-3xl font-bold">{endpoint.name}</h1><Badge>{endpoint.lifecycle_status.replaceAll('_', ' ')}</Badge><Badge variant="secondary">Experimental</Badge></div><p className="mt-2 text-muted-foreground">{endpoint.endpoint_url}</p></div><div className="flex flex-wrap gap-2"><Button variant="outline" asChild><Link href={`/langgraph-endpoints/${endpointUuid}/edit`}><Pencil className="mr-2 h-4 w-4" />Edit</Link></Button><Button variant="outline" disabled={busy} onClick={() => action('validation', () => validateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidValidatePost({ path: { endpoint_uuid: endpointUuid } }))}>Validate</Button><Button disabled={busy || endpoint.lifecycle_status === 'active'} onClick={() => action('activation', () => activateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidActivatePost({ path: { endpoint_uuid: endpointUuid } }))}>Activate</Button><Button variant="outline" disabled={busy || endpoint.lifecycle_status !== 'active'} onClick={() => action('deactivation', () => deactivateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidDeactivatePost({ path: { endpoint_uuid: endpointUuid } }))}>Deactivate</Button><Button variant="destructive" disabled={busy || endpoint.lifecycle_status === 'retired'} onClick={retire}>Retire</Button></div></div>
    <div className="grid gap-4 md:grid-cols-2"><Card><CardHeader><CardTitle>Compatibility</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><p><strong>Profile:</strong> {endpoint.selected_profile}</p><p><strong>Contract:</strong> {latest?.contract_version ?? (values(manifest, 'contract_versions').join(', ') || 'Pending validation')}</p><p><strong>Invocation modes:</strong> {values(manifest, 'invocation_modes').join(', ') || 'Unknown'}</p><p><strong>State modes:</strong> {values(manifest, 'state_modes').join(', ') || 'Unknown'}</p><p><strong>Capabilities:</strong> {endpoint.selected_capabilities.join(', ')}</p><p><strong>Region:</strong> {values(manifest, 'data_regions').join(', ') || 'Required before activation'}</p><p><strong>Latency eligibility:</strong> {latencyEligible ? 'Live voice eligible' : 'Not yet eligible'}</p></CardContent></Card><Card><CardHeader><CardTitle>Credential</CardTitle><CardDescription>Non-secret projection</CardDescription></CardHeader><CardContent className="space-y-2 text-sm"><p><strong>Type:</strong> {endpoint.credential.credential_type}</p><p><strong>Reference:</strong> ••••{endpoint.credential.reference_id.slice(-4)}</p><p><strong>Updated:</strong> {endpoint.credential.last_updated_at ? new Date(endpoint.credential.last_updated_at).toLocaleString() : 'Unknown'}</p><p className="text-muted-foreground">Credential values and reversible derivatives are never displayed.</p></CardContent></Card></div>
    <Card><CardHeader><CardTitle>Known limitations and ownership</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><p>Mural owns prompts, canonical history, workflow transitions, platform tools, telephony, media, and recordings.</p><p>Endpoint-internal tools remain endpoint-owned and are outside Mural&apos;s authorization guarantee.</p>{values(manifest, 'limitations').map((limitation) => <p key={limitation}>• {limitation}</p>)}</CardContent></Card>
    <Card><CardHeader><CardTitle>Immutable validation history</CardTitle><CardDescription>Every revalidation creates a retained report.</CardDescription></CardHeader><CardContent className="space-y-3">{reports.length === 0 ? <p className="text-sm text-muted-foreground">No reports yet.</p> : reports.map((report) => <div key={report.report_uuid} className="rounded-md border p-3"><div className="flex flex-wrap items-center gap-2"><Badge variant={report.status.includes('pass') ? 'default' : 'secondary'}>{report.status}</Badge><span className="font-medium">Contract {report.contract_version}</span><span className="text-xs text-muted-foreground">{new Date(report.created_at).toLocaleString()}</span></div><p className="mt-2 text-xs text-muted-foreground">Report {report.report_uuid} · matrix {report.matrix_version} · suite {report.suite_version}</p><div className="mt-2 grid gap-1 text-sm">{report.results.map((result) => <div key={`${result.test_identifier}-${result.test_version}`} className="flex justify-between"><span>{result.test_identifier}</span><span>{result.outcome}</span></div>)}</div></div>)}</CardContent></Card>
  </div>;
}
