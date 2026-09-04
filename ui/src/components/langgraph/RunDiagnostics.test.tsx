import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { RunDiagnosticsResponse } from '@/client/types.gen';

import { redactDiagnosticDetails, RunDiagnostics } from './RunDiagnostics';

vi.mock('@/lib/auth', () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));

describe('RunDiagnostics', () => {
  it('renders causal order and trace links without sensitive detail values', () => {
    const data: RunDiagnosticsResponse = {
      workflow_run_id: 9,
      endpoint_registration_uuid: 'endpoint-1',
      contract_version: '1.1',
      compatibility_profile: 'chat',
      state_mode: 'mural_authoritative',
      external_identifiers: { external_run_id: 'opaque', checkpoint: '[REDACTED]' },
      events: [
        { id: 'one', category: 'runtime_event', occurred_at: '2026-01-01T00:00:00Z', order: 0, title: 'Text accepted', invocation_id: 'inv-1', attempt_id: null, sequence: 0, trace_id: 'trace-1', trace_url: '/traces/trace-1', details: { prompt: 'should never render' } },
        { id: 'two', category: 'transition', occurred_at: '2026-01-01T00:00:01Z', order: 1, title: 'Transition to billing', invocation_id: 'inv-1', attempt_id: null, sequence: null, trace_id: 'trace-1', trace_url: '/traces/trace-1', details: {} },
      ],
    };
    render(<RunDiagnostics runId={9} initialData={data} />);
    expect(screen.getByText(/1\. Text accepted/)).toBeTruthy();
    expect(screen.getByText(/2\. Transition to billing/)).toBeTruthy();
    expect(screen.getAllByRole('link', { name: /Open trace trace-1/ })[0].getAttribute('href')).toBe('/traces/trace-1');
    expect(screen.queryByText('should never render')).toBeNull();
    expect(screen.getAllByText(/\[REDACTED\]/).length).toBeGreaterThan(0);
  });

  it('redacts sensitive keys recursively and bounds strings', () => {
    const projected = redactDiagnosticDetails({ nested: { token: 'secret' }, safe: 'x'.repeat(600) }) as { nested: { token: string }; safe: string };
    expect(projected.nested.token).toBe('[REDACTED]');
    expect(projected.safe.length).toBe(512);
  });
});
