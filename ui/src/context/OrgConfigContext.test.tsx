import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { OrgConfigProvider, useOrgConfig } from './OrgConfigContext';

const {
    getCurrentOrganizationContextMock,
    getPreferencesMock,
    getUserConfigurationsMock,
    getLanggraphFeatureStatusMock,
    useAuthMock,
} = vi.hoisted(() => ({
    getCurrentOrganizationContextMock: vi.fn(),
    getPreferencesMock: vi.fn(),
    getUserConfigurationsMock: vi.fn(),
    getLanggraphFeatureStatusMock: vi.fn(),
    useAuthMock: vi.fn(),
}));

vi.mock('@/client/sdk.gen', () => ({
    getCurrentOrganizationContextApiV1OrganizationsContextGet: getCurrentOrganizationContextMock,
    getPreferencesApiV1OrganizationsPreferencesGet: getPreferencesMock,
    getUserConfigurationsApiV1UserConfigurationsUserGet: getUserConfigurationsMock,
    getLanggraphFeatureStatusApiV1LanggraphFeatureGet: getLanggraphFeatureStatusMock,
}));

vi.mock('@/lib/apiClient', () => ({
    createClientConfig: (config: unknown) => config,
    setupAuthInterceptor: vi.fn(),
}));

vi.mock('@/lib/auth', () => ({
    useAuth: useAuthMock,
}));

function ContextState() {
    const { error, loading } = useOrgConfig();

    return (
        <div>
            <span data-testid="loading">{String(loading)}</span>
            <span data-testid="error">{error?.message ?? ''}</span>
        </div>
    );
}

function FeatureVisibility() {
    const { langGraphEnabled, refreshConfig } = useOrgConfig();

    return (
        <div>
            {langGraphEnabled && <span>Sidebar LangGraph Endpoints</span>}
            {langGraphEnabled && <span>Workflow Reasoning endpoint</span>}
            <button type="button" onClick={() => void refreshConfig()}>Refresh feature</button>
        </div>
    );
}

describe('OrgConfigProvider', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        useAuthMock.mockReturnValue({
            user: { id: 'user-1', provider: 'local' },
            isAuthenticated: true,
            loading: false,
            getAccessToken: vi.fn(async () => 'token'),
            redirectToLogin: vi.fn(),
            logout: vi.fn(async () => undefined),
            provider: 'local',
        });
        getCurrentOrganizationContextMock.mockResolvedValue({
            data: {
                organization_id: 1,
                organization_provider_id: null,
                model_services: {
                    config_source: 'empty',
                    has_model_configuration_v2: false,
                    managed_service_version: null,
                    uses_managed_service_v2: false,
                },
            },
            error: undefined,
        });
        getUserConfigurationsMock.mockResolvedValue({
            data: {},
            error: undefined,
        });
        getLanggraphFeatureStatusMock.mockResolvedValue({
            data: { enabled: false, experimental: true, acknowledged: false, rollout_stage: 'internal_test_tenant' },
            error: undefined,
        });
        getPreferencesMock.mockResolvedValue({
            data: { external_pbx_integrations_enabled: false },
            error: undefined,
        });
    });

    it('refreshes sidebar and workflow Reasoning endpoint visibility without a reload', async () => {
        getLanggraphFeatureStatusMock
            .mockResolvedValueOnce({
                data: { enabled: false, experimental: true, acknowledged: false, rollout_stage: 'internal_test_tenant' },
                error: undefined,
            })
            .mockResolvedValueOnce({
                data: { enabled: true, experimental: true, acknowledged: true, rollout_stage: 'internal_test_tenant' },
                error: undefined,
            });

        render(
            <OrgConfigProvider>
                <FeatureVisibility />
            </OrgConfigProvider>,
        );

        await waitFor(() => expect(getLanggraphFeatureStatusMock).toHaveBeenCalledTimes(1));
        expect(screen.queryByText('Sidebar LangGraph Endpoints')).toBeNull();
        expect(screen.queryByText('Workflow Reasoning endpoint')).toBeNull();

        fireEvent.click(screen.getByRole('button', { name: 'Refresh feature' }));

        expect(await screen.findByText('Sidebar LangGraph Endpoints')).toBeTruthy();
        expect(screen.getByText('Workflow Reasoning endpoint')).toBeTruthy();
        expect(getLanggraphFeatureStatusMock).toHaveBeenCalledTimes(2);
    });

    it('surfaces an HTTP error returned while loading organization preferences', async () => {
        getPreferencesMock.mockResolvedValue({
            data: undefined,
            error: { detail: 'Preferences unavailable' },
        });

        render(
            <OrgConfigProvider>
                <ContextState />
            </OrgConfigProvider>,
        );

        await waitFor(() => {
            expect(screen.getByTestId('loading').textContent).toBe('false');
        });
        expect(screen.getByTestId('error').textContent).toBe('Preferences unavailable');
    });
});
