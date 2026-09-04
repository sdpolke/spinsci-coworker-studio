import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import LangGraphEndpointDetailPage from './page';

const api = vi.hoisted(() => ({ get: vi.fn(), reports: vi.fn(), validate: vi.fn(), activate: vi.fn(), deactivate: vi.fn(), remove: vi.fn(), toastError: vi.fn() }));
vi.mock('next/navigation', () => ({ useParams: () => ({ endpointUuid: 'endpoint-1' }), useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: api.toastError } }));
vi.mock('@/client/sdk.gen', () => ({
  getLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidGet: api.get,
  listLanggraphValidationReportsApiV1LanggraphEndpointsEndpointUuidValidationReportsGet: api.reports,
  validateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidValidatePost: api.validate,
  activateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidActivatePost: api.activate,
  deactivateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidDeactivatePost: api.deactivate,
  deleteLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidDelete: api.remove,
}));

const endpoint = {
  endpoint_uuid: 'endpoint-1', name: 'Support', endpoint_url: 'https://example.com', selected_profile: 'chat', selected_capabilities: ['streaming'], lifecycle_status: 'active', credential: { credential_type: 'bearer', reference_id: 'credential-super-secret', last_updated_at: '2026-01-01T00:00:00Z' }, current_validation_report_uuid: 'report-1', current_capability_snapshot: { snapshot_uuid: 'snapshot-1', manifest_digest: 'digest', schema_version: '1.1', manifest: { contract_versions: ['1.1'], invocation_modes: ['streaming'], state_modes: ['mural_authoritative'], data_regions: ['us-east'] }, discovered_at: '2026-01-01T00:00:00Z' }, private_network_enabled: false, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', retired_at: null,
};
const reports = [{ report_uuid: 'report-1', capability_snapshot_uuid: 'snapshot-1', matrix_version: '1', suite_version: '1', contract_version: '1.1', selected_profile: 'chat', status: 'passed', started_at: '2026-01-01T00:00:00Z', completed_at: '2026-01-01T00:00:01Z', evidence: {}, report_digest: 'digest', created_at: '2026-01-01T00:00:01Z', results: [{ test_identifier: 'streaming', test_version: '1', required: true, outcome: 'passed', duration_ms: 2, measurements: {}, redacted_error: null }] }];

describe('LangGraph endpoint detail', () => {
  beforeEach(() => { vi.clearAllMocks(); api.get.mockResolvedValue({ data: endpoint }); api.reports.mockResolvedValue({ data: reports }); api.validate.mockResolvedValue({ error: { detail: 'Not authorized' } }); });
  it('shows masked credential, immutable history, lifecycle controls, and normalized authorization errors', async () => {
    render(<LangGraphEndpointDetailPage />);
    expect(await screen.findByText('Support')).toBeTruthy();
    expect(screen.getByText('••••cret')).toBeTruthy();
    expect(screen.queryByText('credential-super-secret')).toBeNull();
    expect(screen.getByText('Immutable validation history')).toBeTruthy();
    expect(screen.getAllByText('streaming').length).toBeGreaterThan(0);
    expect((screen.getByRole('button', { name: 'Deactivate' }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    await waitFor(() => expect(api.toastError).toHaveBeenCalledWith('Not authorized'));
  });
});
