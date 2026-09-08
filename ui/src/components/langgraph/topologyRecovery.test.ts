import { describe, expect, it, vi } from 'vitest';

import type { EndpointResponse, ValidationReportResponse } from '@/client/types.gen';

import { runTopologyRecovery } from './topologyRecovery';

const endpoint = (lifecycle_status: EndpointResponse['lifecycle_status']): EndpointResponse => ({
  endpoint_uuid: 'saved-endpoint',
  name: 'Endpoint',
  endpoint_url: 'https://example.test',
  selected_profile: 'chat',
  selected_capabilities: ['streaming'],
  lifecycle_status,
  credential: { credential_type: 'bearer', reference_id: 'credential', last_updated_at: null },
  current_validation_report_uuid: lifecycle_status === 'pending_validation' ? null : 'report-current',
  current_capability_snapshot: lifecycle_status === 'pending_validation' ? null : { snapshot_uuid: 'snapshot-current', schema_version: '1.2', manifest: {}, manifest_digest: 'digest', discovered_at: new Date().toISOString() },
  private_network_enabled: false,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  retired_at: null,
});

const report = (status = 'passed'): ValidationReportResponse => ({
  report_uuid: 'report-current', capability_snapshot_uuid: 'snapshot-current', matrix_version: '1', suite_version: '1', contract_version: '1.2', selected_profile: 'chat', status,
  started_at: new Date().toISOString(), completed_at: new Date().toISOString(), evidence: {}, report_digest: 'digest', created_at: new Date().toISOString(), results: [],
});

const normalizeError = (error: unknown, fallback: string) => typeof error === 'object' && error && 'detail' in error ? String(error.detail) : fallback;

describe('runTopologyRecovery', () => {
  it('uses the saved endpoint and chains validate, polling, activation, and update binding', async () => {
    vi.useFakeTimers();
    const validate = vi.fn(async () => ({ data: { lifecycle_status: 'pending_validation' } }));
    const getEndpoint = vi.fn()
      .mockResolvedValueOnce({ data: endpoint('pending_validation') })
      .mockResolvedValueOnce({ data: endpoint('validation_only') });
    const listReports = vi.fn(async () => ({ data: [report()] }));
    const activate = vi.fn(async () => ({ data: { lifecycle_status: 'active' } }));
    const updateBinding = vi.fn(async () => ({ data: { status: 'available' as const, topology: null } }));
    const progress = vi.fn();

    const pending = runTopologyRecovery({ endpointUuid: 'saved-endpoint', validate, getEndpoint, listReports, activate, updateBinding, normalizeError, onProgress: progress });
    await vi.advanceTimersByTimeAsync(2_000);
    await expect(pending).resolves.toMatchObject({ status: 'available' });
    expect(validate).toHaveBeenCalledWith(expect.objectContaining({ path: { endpoint_uuid: 'saved-endpoint' } }));
    expect(getEndpoint).toHaveBeenCalledTimes(2);
    expect(activate).toHaveBeenCalledWith(expect.objectContaining({ path: { endpoint_uuid: 'saved-endpoint' } }));
    expect(updateBinding).toHaveBeenCalledTimes(1);
    expect(progress.mock.calls.map(([stage]) => stage)).toEqual(['validation_pending', 'validation_passed', 'activation_pending', 'binding_update_pending']);
    vi.useRealTimers();
  });

  it('does not activate endpoint evidence that is already active', async () => {
    const activate = vi.fn();
    const updateBinding = vi.fn(async () => ({ data: { status: 'available' as const } }));
    await runTopologyRecovery({
      endpointUuid: 'saved-endpoint',
      validate: vi.fn(async () => ({ data: {} })),
      getEndpoint: vi.fn(async () => ({ data: endpoint('active') })),
      listReports: vi.fn(async () => ({ data: [report('live_voice_eligible')] })),
      activate,
      updateBinding,
      normalizeError,
    });
    expect(activate).not.toHaveBeenCalled();
    expect(updateBinding).toHaveBeenCalledTimes(1);
  });

  it('stops before activation and binding update on terminal validation failure', async () => {
    const activate = vi.fn();
    const updateBinding = vi.fn();
    await expect(runTopologyRecovery({
      endpointUuid: 'saved-endpoint',
      validate: vi.fn(async () => ({ data: {} })),
      getEndpoint: vi.fn(async () => ({ data: endpoint('incompatible') })),
      listReports: vi.fn(async () => ({ data: [report('failed')] })),
      activate,
      updateBinding,
      normalizeError,
    })).rejects.toThrow(/validation failed/i);
    expect(activate).not.toHaveBeenCalled();
    expect(updateBinding).not.toHaveBeenCalled();
  });

  it('stops after an in-flight poll when the dialog aborts recovery', async () => {
    const controller = new AbortController();
    let resolveEndpoint!: (value: { data: EndpointResponse }) => void;
    let capturedOptions: unknown;
    const getEndpoint = vi.fn((options: unknown) => {
      capturedOptions = options;
      return new Promise<{ data: EndpointResponse }>((resolve) => { resolveEndpoint = resolve; });
    });
    const listReports = vi.fn();
    const activate = vi.fn();
    const updateBinding = vi.fn();
    const pending = runTopologyRecovery({
      endpointUuid: 'saved-endpoint',
      validate: vi.fn(async () => ({ data: {} })),
      getEndpoint,
      listReports,
      activate,
      updateBinding,
      normalizeError,
      signal: controller.signal,
    });
    await vi.waitFor(() => expect(getEndpoint).toHaveBeenCalledTimes(1));
    controller.abort();
    resolveEndpoint({ data: endpoint('validation_only') });
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(listReports).not.toHaveBeenCalled();
    expect(activate).not.toHaveBeenCalled();
    expect(updateBinding).not.toHaveBeenCalled();
    expect(capturedOptions).toMatchObject({ signal: controller.signal });
  });

  it('normalizes generated-client errors instead of treating them as successful responses', async () => {
    await expect(runTopologyRecovery({
      endpointUuid: 'saved-endpoint',
      validate: vi.fn(async () => ({ error: { detail: [{ msg: 'Permission denied' }] } })),
      getEndpoint: vi.fn(), listReports: vi.fn(), activate: vi.fn(), updateBinding: vi.fn(),
      normalizeError: () => 'Permission denied',
    })).rejects.toThrow('Permission denied');
  });
});
