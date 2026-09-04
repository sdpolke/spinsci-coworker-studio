'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { createLanggraphEndpointApiV1LanggraphEndpointsPost } from '@/client/sdk.gen';
import { EndpointFormValue, LangGraphEndpointForm } from '@/components/langgraph/LangGraphEndpointForm';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { detailFromError } from '@/lib/apiError';

export default function NewLangGraphEndpointPage() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const submit = async (value: EndpointFormValue) => {
    setSubmitting(true);
    try {
      const response = await createLanggraphEndpointApiV1LanggraphEndpointsPost({ body: value });
      if (response.error) throw new Error(detailFromError(response.error, 'Failed to create endpoint'));
      router.push(`/langgraph-endpoints/${response.data?.endpoint_uuid}`);
    } finally { setSubmitting(false); }
  };
  return <div className="container mx-auto max-w-3xl px-4 py-8"><Card><CardHeader><CardTitle>Register experimental endpoint</CardTitle></CardHeader><CardContent><LangGraphEndpointForm onSubmit={submit} submitting={submitting} /></CardContent></Card></div>;
}
