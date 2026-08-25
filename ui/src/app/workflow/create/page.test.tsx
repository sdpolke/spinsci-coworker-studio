import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import CreateWorkflowPage from '@/app/workflow/create/page';

const {
    startGenerationSessionMock,
    submitGenerationMessageMock,
    generateWorkflowFromSessionMock,
} = vi.hoisted(() => ({
    startGenerationSessionMock: vi.fn(),
    submitGenerationMessageMock: vi.fn(),
    generateWorkflowFromSessionMock: vi.fn(),
}));

vi.mock('@/client/sdk.gen', async (importOriginal) => {
    const actual = await importOriginal<typeof import('@/client/sdk.gen')>();
    return {
        ...actual,
        startGenerationSessionApiV1WorkflowGenerationSessionsPost: startGenerationSessionMock,
        postGenerationMessageApiV1WorkflowGenerationSessionsSessionIdMessagesPost:
            submitGenerationMessageMock,
        generateWorkflowFromSessionApiV1WorkflowGenerationSessionsSessionIdGeneratePost:
            generateWorkflowFromSessionMock,
    };
});

vi.mock('@/lib/auth', () => ({
    useAuth: () => ({
        user: { id: 1 },
        getAccessToken: vi.fn().mockResolvedValue('token'),
    }),
}));

const pushMock = vi.fn();
vi.mock('next/navigation', () => ({
    useRouter: () => ({ push: pushMock }),
}));

describe('CreateWorkflowPage agent builder flow', () => {
    it('walks through clarifications and generates a workflow', async () => {
        startGenerationSessionMock.mockResolvedValue({
            data: {
                session_id: 'sess-1',
                status: 'clarifying',
                brief: {
                    call_type: 'inbound',
                    use_case: 'Lead intake',
                    activity_description: 'Collect contact details.',
                },
                messages: [
                    {
                        role: 'assistant',
                        content: 'Which fields are required?',
                        created_at: '2026-01-01T00:00:00Z',
                    },
                ],
                summary: null,
                plan: null,
                workflow_id: null,
                error: null,
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
            },
            error: undefined,
        });

        submitGenerationMessageMock.mockResolvedValue({
            data: {
                session_id: 'sess-1',
                status: 'ready',
                brief: {
                    call_type: 'inbound',
                    use_case: 'Lead intake',
                    activity_description: 'Collect contact details.',
                },
                messages: [
                    {
                        role: 'assistant',
                        content: 'Which fields are required?',
                        created_at: '2026-01-01T00:00:00Z',
                    },
                    {
                        role: 'user',
                        content: 'Name and email',
                        created_at: '2026-01-01T00:00:01Z',
                    },
                ],
                summary: 'Collect name and email from callers.',
                plan: 'Greet, collect, end.',
                workflow_id: null,
                error: null,
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:01Z',
            },
            error: undefined,
        });

        generateWorkflowFromSessionMock.mockResolvedValue({
            data: {
                session: {
                    session_id: 'sess-1',
                    status: 'completed',
                    brief: {
                        call_type: 'inbound',
                        use_case: 'Lead intake',
                        activity_description: 'Collect contact details.',
                    },
                    messages: [],
                    summary: 'Collect name and email from callers.',
                    plan: 'Greet, collect, end.',
                    workflow_id: 42,
                    error: null,
                    created_at: '2026-01-01T00:00:00Z',
                    updated_at: '2026-01-01T00:00:02Z',
                },
                workflow: { id: 42 },
            },
            error: undefined,
        });

        render(<CreateWorkflowPage />);

        fireEvent.change(screen.getByLabelText(/Use Case/i), {
            target: { value: 'Lead intake' },
        });
        fireEvent.change(screen.getByLabelText(/Activity Description/i), {
            target: { value: 'Collect contact details.' },
        });
        fireEvent.click(screen.getByRole('button', { name: /Continue to clarifications/i }));

        await waitFor(() => {
            expect(screen.getByText('Which fields are required?')).toBeTruthy();
        });

        fireEvent.change(screen.getByPlaceholderText(/Type your answer/i), {
            target: { value: 'Name and email' },
        });
        fireEvent.click(screen.getByRole('button', { name: /^Send$/i }));

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /Generate workflow/i })).toBeTruthy();
        });

        fireEvent.click(screen.getByRole('button', { name: /Generate workflow/i }));

        await waitFor(() => {
            expect(screen.getByText(/Workflow Created Successfully/i)).toBeTruthy();
        });
    });
});
