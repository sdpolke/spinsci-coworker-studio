import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { LangGraphEndpointBinding } from '@/types/workflow-configurations';

import { LangGraphWorkflowConfiguration, transitionNameCollisions } from './LangGraphWorkflowConfiguration';

vi.mock('@/lib/auth', () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock('@/context/OrgConfigContext', () => ({ useOrgConfig: () => ({ langGraphEnabled: true }) }));
vi.mock('@/client/sdk.gen', () => ({
  listLanggraphEndpointsApiV1LanggraphEndpointsGet: vi.fn(async () => ({ data: [] })),
  listLanggraphValidationReportsApiV1LanggraphEndpointsEndpointUuidValidationReportsGet: vi.fn(async () => ({ data: [] })),
}));

const binding: LangGraphEndpointBinding = {
  registration_uuid: 'endpoint-1', validation_report_uuid: 'report-1', validation_report_digest: 'digest', contract_version: '1.1', compatibility_profile: 'chat', state_mode: 'mural_authoritative', live_invocation_mode: 'streaming', non_conversational_modes: {}, selected_capabilities: ['streaming', 'endpoint_internal_tools'], capability_snapshot_uuid: 'snapshot-1', capability_snapshot_digest: 'snapshot-digest', capability_snapshot: { data_regions: ['us-east'], invocation_modes: ['streaming'] }, data_sharing_policy: { context_fields: ['locale'] }, redaction_policy_id: null, compiled_policy_versions: {}, data_region: 'us-east', first_event_deadline_ms: 1500, first_event_action: 'fallback_message', terminal_failure_action: 'fallback_message', evidence: { text_session_conformance: true, accepted_transition: true, endpoint_state_continuity: false, cancellation_verified: true, recording_verified: true }, endpoint_url: 'https://example.com', credential_reference: 'credential-1', operations: { invoke: '/invoke' }, limits: { event_bytes: 1024 }, ownership: { prompts: 'mural', endpoint_internal_tools: 'endpoint' },
};

describe('LangGraphWorkflowConfiguration', () => {
  it('shows ownership, latency/tool warnings, realtime rejection, immutable feedback, and transition collisions', () => {
    render(<LangGraphWorkflowConfiguration value={binding} onChange={vi.fn()} realtime immutable transitionLabels={['Move to Billing', 'move-to-billing']} />);
    expect(screen.getByText('prompts: Mural-owned')).toBeTruthy();
    expect(screen.getByText('endpoint internal tools: Endpoint-owned')).toBeTruthy();
    expect(screen.getByText(/Tool-call turns can create caller silence/)).toBeTruthy();
    expect(screen.getByText(/outside Mural's authorization guarantee/)).toBeTruthy();
    expect(screen.getByText(/unavailable for realtime speech-to-speech/)).toBeTruthy();
    expect(screen.getByText(/Published versions are immutable/)).toBeTruthy();
    expect(screen.getByText(/Transition names collide.*move_to_billing/)).toBeTruthy();
  });

  it('detects only normalized duplicate transition names', () => {
    expect(transitionNameCollisions(['Billing Help', 'billing-help', 'General'])).toEqual(['billing_help']);
    expect(transitionNameCollisions(['Billing', 'General'])).toEqual([]);
  });
});
