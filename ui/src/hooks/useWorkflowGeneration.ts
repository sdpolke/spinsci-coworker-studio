'use client';

import { useCallback, useRef, useState } from 'react';

import {
    generateWorkflowFromSessionApiV1WorkflowGenerationSessionsSessionIdGeneratePost,
    postGenerationMessageApiV1WorkflowGenerationSessionsSessionIdMessagesPost,
    startGenerationSessionApiV1WorkflowGenerationSessionsPost,
} from '@/client/sdk.gen';
import type { CreateGenerationSessionRequest, GenerationSessionResponse } from '@/client/types.gen';
import { detailFromError } from '@/lib/apiError';

type WorkflowGenerationPhase = 'brief' | 'clarifying' | 'ready' | 'generating';

interface UseWorkflowGenerationOptions {
    getAccessToken: () => Promise<string>;
}

export function useWorkflowGeneration({ getAccessToken }: UseWorkflowGenerationOptions) {
    const [phase, setPhase] = useState<WorkflowGenerationPhase>('brief');
    const [session, setSession] = useState<GenerationSessionResponse | null>(null);
    const [draft, setDraft] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [isBusy, setIsBusy] = useState(false);
    const inFlight = useRef(false);

    const authHeaders = useCallback(async () => {
        const token = await getAccessToken();
        return { Authorization: `Bearer ${token}` };
    }, [getAccessToken]);

    const startSession = useCallback(async (brief: CreateGenerationSessionRequest) => {
        if (inFlight.current) return;
        inFlight.current = true;
        setIsBusy(true);
        setError(null);

        try {
            const response = await startGenerationSessionApiV1WorkflowGenerationSessionsPost({
                body: brief,
                headers: await authHeaders(),
            });
            if (response.error) {
                setError(detailFromError(response.error, 'Failed to start workflow generation'));
                return;
            }
            if (!response.data) {
                setError('Failed to start workflow generation');
                return;
            }

            setSession(response.data);
            setPhase(response.data.status === 'ready' ? 'ready' : 'clarifying');
        } finally {
            inFlight.current = false;
            setIsBusy(false);
        }
    }, [authHeaders]);

    const sendMessage = useCallback(async () => {
        if (!session || inFlight.current) return;
        const content = draft.trim();
        if (!content) return;

        inFlight.current = true;
        setIsBusy(true);
        setError(null);

        try {
            const response =
                await postGenerationMessageApiV1WorkflowGenerationSessionsSessionIdMessagesPost({
                    path: { session_id: session.session_id },
                    body: { content },
                    headers: await authHeaders(),
                });
            if (response.error) {
                setError(detailFromError(response.error, 'Failed to send message'));
                return;
            }
            if (!response.data) {
                setError('Failed to send message');
                return;
            }

            setSession(response.data);
            setDraft('');
            setPhase(response.data.status === 'ready' ? 'ready' : 'clarifying');
        } finally {
            inFlight.current = false;
            setIsBusy(false);
        }
    }, [authHeaders, draft, session]);

    const generateWorkflow = useCallback(async () => {
        if (!session || inFlight.current) return null;

        inFlight.current = true;
        setIsBusy(true);
        setError(null);
        setPhase('generating');

        try {
            const response =
                await generateWorkflowFromSessionApiV1WorkflowGenerationSessionsSessionIdGeneratePost({
                    path: { session_id: session.session_id },
                    headers: await authHeaders(),
                });
            if (response.error) {
                setError(detailFromError(response.error, 'Failed to generate workflow'));
                setPhase('ready');
                return null;
            }
            if (!response.data?.workflow?.id) {
                setError('Failed to generate workflow');
                setPhase('ready');
                return null;
            }

            setSession(response.data.session);
            return response.data.workflow.id;
        } finally {
            inFlight.current = false;
            setIsBusy(false);
        }
    }, [authHeaders, session]);

    return {
        phase,
        session,
        draft,
        setDraft,
        error,
        isBusy,
        startSession,
        sendMessage,
        generateWorkflow,
    };
}
