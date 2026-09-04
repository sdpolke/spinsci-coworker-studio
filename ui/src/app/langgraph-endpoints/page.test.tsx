import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import LangGraphEndpointsPage from './page';

const { listEndpointsMock, orgState } = vi.hoisted(() => ({
  listEndpointsMock: vi.fn(),
  orgState: {
    enabled: false,
    canConfigure: false,
  },
}));

vi.mock('@/lib/auth', () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }));
vi.mock('@/context/OrgConfigContext', () => ({
  useOrgConfig: () => ({
    langGraphEnabled: orgState.enabled,
    langGraphFeature: {
      enabled: orgState.enabled,
      can_configure: orgState.canConfigure,
      rollout_stage: 'internal_test_tenant',
    },
    loading: false,
  }),
}));
vi.mock('@/client/sdk.gen', () => ({
  listLanggraphEndpointsApiV1LanggraphEndpointsGet: listEndpointsMock,
}));

describe('LangGraph endpoint registry visibility', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    orgState.enabled = false;
    orgState.canConfigure = false;
    listEndpointsMock.mockResolvedValue({ data: [] });
  });

  it('links authorized configuration users to the authoritative Platform Settings card', () => {
    orgState.canConfigure = true;

    render(<LangGraphEndpointsPage />);

    expect(screen.getByText('LangGraph integration is disabled')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Configure in Platform Settings' }).getAttribute('href'))
      .toBe('/settings#langgraph-integration');
    expect(screen.queryByRole('link', { name: /Add endpoint/ })).toBeNull();
    expect(screen.queryByRole('switch')).toBeNull();
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(listEndpointsMock).not.toHaveBeenCalled();
  });

  it('shows read-only guidance without settings navigation or mutation controls for other users', () => {
    render(<LangGraphEndpointsPage />);

    expect(screen.getByText(/organization administrator must enable/i)).toBeTruthy();
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('switch')).toBeNull();
    expect(listEndpointsMock).not.toHaveBeenCalled();
  });

  it('loads onboarding data only after refreshed organization context enables the feature', async () => {
    const { rerender } = render(<LangGraphEndpointsPage />);
    expect(listEndpointsMock).not.toHaveBeenCalled();

    orgState.enabled = true;
    rerender(<LangGraphEndpointsPage />);

    await waitFor(() => expect(listEndpointsMock).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('link', { name: /Add endpoint/ })).toBeTruthy();
  });
});
