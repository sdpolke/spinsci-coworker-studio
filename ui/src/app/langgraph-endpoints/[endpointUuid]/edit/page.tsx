'use client';

import { useParams, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { getLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidGet, updateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidPatch } from '@/client/sdk.gen';
import type { EndpointResponse } from '@/client/types.gen';
import { EndpointFormValue, LangGraphEndpointForm } from '@/components/langgraph/LangGraphEndpointForm';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';

export default function EditLangGraphEndpointPage() {
  const { endpointUuid } = useParams<{ endpointUuid: string }>();
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [endpoint, setEndpoint] = useState<EndpointResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  useEffect(() => { if (authLoading || !user) return; void (async () => { const response = await getLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidGet({ path: { endpoint_uuid: endpointUuid } }); if (response.error) setError(detailFromError(response.error)); else setEndpoint(response.data ?? null); })(); }, [authLoading, endpointUuid, user]);
  const submit = async (value: EndpointFormValue) => { setSubmitting(true); try { const response = await updateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidPatch({ path: { endpoint_uuid: endpointUuid }, body: value }); if (response.error) throw new Error(detailFromError(response.error, 'Failed to update endpoint')); router.push(`/langgraph-endpoints/${endpointUuid}`); } finally { setSubmitting(false); } };
  return <div className="container mx-auto max-w-3xl px-4 py-8">{error ? <div role="alert" className="text-destructive">{error}</div> : endpoint ? <Card><CardHeader><CardTitle>Edit {endpoint.name}</CardTitle></CardHeader><CardContent><LangGraphEndpointForm endpoint={endpoint} onSubmit={submit} submitting={submitting} /></CardContent></Card> : <p>Loading…</p>}</div>;
}
