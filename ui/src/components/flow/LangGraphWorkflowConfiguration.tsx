'use client';

import { AlertTriangle } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { listLanggraphEndpointsApiV1LanggraphEndpointsGet, listLanggraphValidationReportsApiV1LanggraphEndpointsEndpointUuidValidationReportsGet } from '@/client/sdk.gen';
import type { EndpointResponse, ValidationReportResponse } from '@/client/types.gen';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { useOrgConfig } from '@/context/OrgConfigContext';
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';
import type { LangGraphEndpointBinding } from '@/types/workflow-configurations';

const manifestArray = (manifest: Record<string, unknown>, key: string) => Array.isArray(manifest[key]) ? (manifest[key] as unknown[]).map(String) : [];
const manifestRecord = (manifest: Record<string, unknown>, key: string) => manifest[key] && typeof manifest[key] === 'object' && !Array.isArray(manifest[key]) ? manifest[key] as Record<string, unknown> : {};
const normalizeTransition = (value: string) => value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');

export function transitionNameCollisions(labels: string[]) {
  const seen = new Set<string>();
  const collisions = new Set<string>();
  labels.forEach((label) => { const name = normalizeTransition(label); if (!name) return; if (seen.has(name)) collisions.add(name); seen.add(name); });
  return [...collisions];
}

export function LangGraphWorkflowConfiguration({ value, onChange, realtime = false, immutable = false, transitionLabels = [] }: { value?: LangGraphEndpointBinding | null; onChange: (value: LangGraphEndpointBinding | null) => void; realtime?: boolean; immutable?: boolean; transitionLabels?: string[] }) {
  const { user, loading: authLoading } = useAuth();
  const { langGraphEnabled } = useOrgConfig();
  const [endpoints, setEndpoints] = useState<EndpointResponse[]>([]);
  const [reports, setReports] = useState<Record<string, ValidationReportResponse>>({});
  const [error, setError] = useState<string | null>(null);
  const collisions = useMemo(() => transitionNameCollisions(transitionLabels), [transitionLabels]);

  useEffect(() => { if (authLoading || !user || !langGraphEnabled) return; void (async () => { const response = await listLanggraphEndpointsApiV1LanggraphEndpointsGet(); if (response.error) { setError(detailFromError(response.error, 'Failed to load endpoints')); return; } setEndpoints((response.data ?? []).filter((endpoint) => endpoint.lifecycle_status === 'active')); })(); }, [authLoading, langGraphEnabled, user]);

  const selectEndpoint = async (endpointUuid: string) => {
    if (endpointUuid === 'none') { onChange(null); return; }
    const endpoint = endpoints.find((item) => item.endpoint_uuid === endpointUuid);
    if (!endpoint?.current_capability_snapshot) return;
    const response = await listLanggraphValidationReportsApiV1LanggraphEndpointsEndpointUuidValidationReportsGet({ path: { endpoint_uuid: endpointUuid } });
    if (response.error) { setError(detailFromError(response.error, 'Failed to load endpoint evidence')); return; }
    const report = (response.data ?? []).find((item) => item.report_uuid === endpoint.current_validation_report_uuid) ?? response.data?.[0];
    if (!report) { setError('The endpoint has no current validation evidence.'); return; }
    setReports((current) => ({ ...current, [endpointUuid]: report }));
    const manifest = endpoint.current_capability_snapshot.manifest as Record<string, unknown>;
    const regions = manifestArray(manifest, 'data_regions');
    const modes = manifestArray(manifest, 'invocation_modes');
    if (!modes.includes('streaming')) { setError('This endpoint lacks streaming capability and cannot be used for live voice.'); return; }
    const evidence = report.evidence as Record<string, unknown>;
    onChange({
      registration_uuid: endpoint.endpoint_uuid,
      validation_report_uuid: report.report_uuid,
      validation_report_digest: report.report_digest,
      contract_version: report.contract_version,
      compatibility_profile: endpoint.selected_profile as 'chat' | 'stateful_run',
      state_mode: (manifestArray(manifest, 'state_modes')[0] ?? 'mural_authoritative') as 'mural_authoritative' | 'endpoint_checkpointed',
      live_invocation_mode: 'streaming',
      non_conversational_modes: {},
      selected_capabilities: endpoint.selected_capabilities,
      capability_snapshot_uuid: endpoint.current_capability_snapshot.snapshot_uuid,
      capability_snapshot_digest: endpoint.current_capability_snapshot.manifest_digest,
      capability_snapshot: manifest,
      data_sharing_policy: { context_fields: ['locale'] },
      redaction_policy_id: null,
      compiled_policy_versions: {},
      data_region: regions[0] ?? '',
      first_event_deadline_ms: 1500,
      first_event_action: 'fallback_message',
      terminal_failure_action: 'fallback_message',
      evidence: {
        text_session_conformance: evidence.text_session_conformance === true,
        accepted_transition: evidence.accepted_transition === true,
        cancellation_verified: evidence.cancellation_verified === true,
        recording_verified: evidence.recording_verified === true,
      },
      endpoint_url: endpoint.endpoint_url,
      credential_reference: endpoint.credential.reference_id,
      operations: Object.fromEntries(Object.entries(manifestRecord(manifest, 'operations')).map(([key, item]) => [key, String(item)])),
      limits: Object.fromEntries(Object.entries(manifestRecord(manifest, 'limits')).filter(([, item]) => typeof item === 'number')) as Record<string, number>,
      ownership: { prompts: 'mural', conversation_history: 'mural', transitions: 'mural', platform_tools: 'mural', endpoint_internal_tools: 'endpoint', telephony: 'mural', recordings: 'mural' },
    });
  };

  if (!langGraphEnabled) return null;
  const report = value ? reports[value.registration_uuid] : undefined;
  const hasEndpointInternalTools = value ? manifestArray(value.capability_snapshot, 'capabilities').includes('endpoint_internal_tools') || value.selected_capabilities.includes('endpoint_internal_tools') : false;
  return <section className="space-y-4 border-t pt-5" aria-label="Reasoning endpoint">
    <div><div className="flex items-center gap-2"><h3 className="text-sm font-semibold">Reasoning endpoint</h3><Badge variant="secondary">Experimental</Badge></div><p className="text-xs text-muted-foreground">Attach a validated endpoint to workflow configuration—not to an individual node. Publishing creates a new immutable workflow version.</p></div>
    {error && <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">{error}</div>}
    {immutable && <p className="text-xs text-amber-600">Published versions are immutable. Create or edit a draft to change this binding.</p>}
    {realtime && <div role="alert" className="flex gap-2 rounded-md border border-destructive/40 p-3 text-xs text-destructive"><AlertTriangle className="h-4 w-4" />LangGraph chat endpoints are unavailable for realtime speech-to-speech workflows.</div>}
    <div className="space-y-2"><Label>Endpoint</Label><Select disabled={immutable || realtime} value={value?.registration_uuid ?? 'none'} onValueChange={(next) => void selectEndpoint(next)}><SelectTrigger><SelectValue placeholder="Use existing model reasoning" /></SelectTrigger><SelectContent><SelectItem value="none">Existing model reasoning</SelectItem>{endpoints.map((endpoint) => <SelectItem key={endpoint.endpoint_uuid} value={endpoint.endpoint_uuid}>{endpoint.name} · {endpoint.selected_profile}</SelectItem>)}</SelectContent></Select></div>
    {value && <div className="space-y-4 rounded-md border p-3">
      <div className="flex flex-wrap gap-2">{Object.entries(value.ownership).map(([field, owner]) => <Badge key={field} variant={owner === 'mural' ? 'default' : 'secondary'}>{field.replaceAll('_', ' ')}: {owner === 'mural' ? 'Mural-owned' : 'Endpoint-owned'}</Badge>)}</div>
      <div className="space-y-2"><Label htmlFor="data-region">Endpoint data region</Label><Select disabled={immutable} value={value.data_region} onValueChange={(data_region) => onChange({ ...value, data_region })}><SelectTrigger id="data-region"><SelectValue /></SelectTrigger><SelectContent>{manifestArray(value.capability_snapshot, 'data_regions').map((region) => <SelectItem key={region} value={region}>{region}</SelectItem>)}</SelectContent></Select></div>
      <div className="space-y-2"><Label htmlFor="first-event-deadline">First-event deadline (ms)</Label><Input id="first-event-deadline" type="number" min={500} max={3000} disabled={immutable} value={value.first_event_deadline_ms} onChange={(event) => onChange({ ...value, first_event_deadline_ms: Number(event.target.value) })} /></div>
      <div className="flex items-center justify-between"><div><Label htmlFor="share-locale">Share locale</Label><p className="text-xs text-muted-foreground">Only allowlisted fields are transmitted after redaction.</p></div><Switch id="share-locale" disabled={immutable} checked={(value.data_sharing_policy.context_fields as string[] | undefined)?.includes('locale') ?? false} onCheckedChange={(checked) => onChange({ ...value, data_sharing_policy: { ...value.data_sharing_policy, context_fields: checked ? ['locale'] : [] } })} /></div>
      <div className="rounded-md bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">Tool-call turns can create caller silence until tool completion and a subsequent text event. Slow first events execute the pinned caller-facing action.</div>
      {hasEndpointInternalTools && <div className="rounded-md border p-3 text-xs">Endpoint-internal tools are endpoint-owned and outside Mural&apos;s authorization guarantee.</div>}
      {report && <p className="text-xs text-muted-foreground">Pinned report: {report.report_uuid}</p>}
    </div>}
    {collisions.length > 0 && <div role="alert" className="rounded-md border border-destructive/40 p-3 text-xs text-destructive">Transition names collide after normalization: {collisions.join(', ')}. Rename the affected edges before publication.</div>}
  </section>;
}
