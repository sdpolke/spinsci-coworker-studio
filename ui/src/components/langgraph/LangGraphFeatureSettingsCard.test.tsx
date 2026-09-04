import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { LangGraphFeatureStatusResponse } from '@/client/types.gen';

import { LangGraphFeatureSettingsCard } from './LangGraphFeatureSettingsCard';

const { updateFeatureMock, useOrgConfigMock } = vi.hoisted(() => ({
  updateFeatureMock: vi.fn(),
  useOrgConfigMock: vi.fn(),
}));

vi.mock('@/client/sdk.gen', () => ({
  updateLanggraphFeatureStatusApiV1LanggraphFeaturePatch: updateFeatureMock,
}));
vi.mock('@/context/OrgConfigContext', () => ({ useOrgConfig: useOrgConfigMock }));

const status = (
  changes: Partial<LangGraphFeatureStatusResponse> = {},
): LangGraphFeatureStatusResponse => ({
  enabled: false,
  acknowledged: false,
  experimental: true,
  rollout_stage: 'internal_test_tenant',
  can_configure: true,
  private_network_configurable: false,
  private_network_enabled: false,
  ...changes,
});

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
};

describe('LangGraphFeatureSettingsCard', () => {
  const refreshConfig = vi.fn(async () => undefined);

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    useOrgConfigMock.mockReturnValue({
      langGraphFeature: status(),
      loading: false,
      refreshConfig,
    });
    updateFeatureMock.mockResolvedValue({ data: status({ enabled: true, acknowledged: true }) });
  });

  it('shows loading and then the current experimental rollout status for administrators', () => {
    useOrgConfigMock.mockReturnValue({ langGraphFeature: null, loading: true, refreshConfig });
    const { rerender } = render(<LangGraphFeatureSettingsCard />);
    expect(screen.getByRole('status').textContent).toContain('Loading LangGraph');
    expect(screen.queryByRole('switch')).toBeNull();

    useOrgConfigMock.mockReturnValue({
      langGraphFeature: status({ enabled: true, acknowledged: true }),
      loading: false,
      refreshConfig,
    });
    rerender(<LangGraphFeatureSettingsCard />);
    expect(screen.getByText('Enabled')).toBeTruthy();
    expect(screen.getByText('Yes')).toBeTruthy();
    expect(screen.getAllByText('Experimental').length).toBeGreaterThan(0);
    expect(screen.getByText('internal test tenant')).toBeTruthy();
    expect(screen.getByLabelText('Enable LangGraph integration')).toBeTruthy();
    expect(screen.getByText(/External endpoint latency affects callers/)).toBeTruthy();
  });

  it('renders a read-only variant without mutation controls', () => {
    useOrgConfigMock.mockReturnValue({
      langGraphFeature: status({ can_configure: false }),
      loading: false,
      refreshConfig,
    });
    render(<LangGraphFeatureSettingsCard />);
    expect(screen.getByText(/settings are read-only/i)).toBeTruthy();
    expect(screen.queryByRole('switch')).toBeNull();
    expect(screen.queryByRole('button', { name: /save|enable/i })).toBeNull();
  });

  it('requires explicit acknowledgment and submits the generated PATCH request', async () => {
    render(<LangGraphFeatureSettingsCard />);
    fireEvent.click(screen.getByLabelText('Enable LangGraph integration'));

    const submit = screen.getByRole('button', { name: 'Enable integration' });
    expect(submit.hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByLabelText(/I acknowledge the experimental status/));
    expect(submit.hasAttribute('disabled')).toBe(false);
    fireEvent.click(submit);

    await waitFor(() =>
      expect(updateFeatureMock).toHaveBeenCalledWith({
        body: {
          enabled: true,
          experimental_risk_acknowledged: true,
        },
      }),
    );
  });

  it('shows private-network controls only for self-hosted deployments and requires distinct risk acknowledgment', async () => {
    useOrgConfigMock.mockReturnValue({
      langGraphFeature: status({ private_network_configurable: true }),
      loading: false,
      refreshConfig,
    });
    render(<LangGraphFeatureSettingsCard />);
    const privateSwitch = screen.getByLabelText('Allow private-network endpoints');
    fireEvent.click(privateSwitch);
    expect(screen.getByRole('button', { name: 'Save settings' }).hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByLabelText(/separate SSRF and trusted-network exposure risk/));
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));

    await waitFor(() =>
      expect(updateFeatureMock).toHaveBeenCalledWith({
        body: {
          enabled: false,
          experimental_risk_acknowledged: false,
          private_network_enabled: true,
          private_network_risk_acknowledged: true,
        },
      }),
    );
  });

  it('omits private-network controls and fields for hosted deployments', async () => {
    render(<LangGraphFeatureSettingsCard />);
    expect(screen.queryByLabelText('Allow private-network endpoints')).toBeNull();
    fireEvent.click(screen.getByLabelText('Enable LangGraph integration'));
    fireEvent.click(screen.getByLabelText(/I acknowledge the experimental status/));
    fireEvent.click(screen.getByRole('button', { name: 'Enable integration' }));

    await waitFor(() => expect(updateFeatureMock).toHaveBeenCalledTimes(1));
    expect(updateFeatureMock.mock.calls[0][0].body).not.toHaveProperty('private_network_enabled');
  });

  it('normalizes API errors and preserves the last confirmed status', async () => {
    updateFeatureMock.mockResolvedValue({
      error: { detail: [{ loc: ['body', 'enabled'], msg: 'Enablement was rejected' }] },
    });
    render(<LangGraphFeatureSettingsCard />);
    fireEvent.click(screen.getByLabelText('Enable LangGraph integration'));
    fireEvent.click(screen.getByLabelText(/I acknowledge the experimental status/));
    fireEvent.click(screen.getByRole('button', { name: 'Enable integration' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Enablement was rejected');
    expect(screen.getByText('Disabled')).toBeTruthy();
    expect(refreshConfig).not.toHaveBeenCalled();
  });

  it('prevents duplicate saves and waits for context refresh before showing success', async () => {
    const updatePending = deferred<{ data: LangGraphFeatureStatusResponse }>();
    const refreshPending = deferred<undefined>();
    updateFeatureMock.mockReturnValue(updatePending.promise);
    refreshConfig.mockReturnValueOnce(refreshPending.promise);
    render(<LangGraphFeatureSettingsCard />);
    fireEvent.click(screen.getByLabelText('Enable LangGraph integration'));
    fireEvent.click(screen.getByLabelText(/I acknowledge the experimental status/));
    const submit = screen.getByRole('button', { name: 'Enable integration' });
    fireEvent.click(submit);

    expect(screen.getByRole('button', { name: 'Saving…' }).hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Saving…' }));
    expect(updateFeatureMock).toHaveBeenCalledTimes(1);

    updatePending.resolve({ data: status({ enabled: true, acknowledged: true }) });
    await waitFor(() => expect(refreshConfig).toHaveBeenCalledTimes(1));
    expect(screen.queryByText('LangGraph integration settings updated.')).toBeNull();

    refreshPending.resolve(undefined);
    expect(await screen.findByText('LangGraph integration settings updated.')).toBeTruthy();
  });
});
