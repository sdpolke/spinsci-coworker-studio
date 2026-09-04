'use client';

import { AlertTriangle, Network, Plus } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';

import { listLanggraphEndpointsApiV1LanggraphEndpointsGet } from '@/client/sdk.gen';
import type { EndpointResponse } from '@/client/types.gen';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useOrgConfig } from '@/context/OrgConfigContext';
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';

export default function LangGraphEndpointsPage() {
  const { user, loading: authLoading } = useAuth();
  const { langGraphEnabled, langGraphFeature, loading: configLoading } = useOrgConfig();
  const [endpoints, setEndpoints] = useState<EndpointResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (authLoading || configLoading || !user) return;
    if (!langGraphEnabled) { setLoading(false); return; }
    void (async () => {
      const response = await listLanggraphEndpointsApiV1LanggraphEndpointsGet();
      if (response.error) setError(detailFromError(response.error, 'Failed to load endpoints'));
      else setEndpoints(response.data ?? []);
      setLoading(false);
    })();
  }, [authLoading, configLoading, langGraphEnabled, user]);

  if (!configLoading && !langGraphEnabled) {
    const canConfigure = langGraphFeature?.can_configure === true;
    return (
      <div className="container mx-auto max-w-4xl px-4 py-10">
        <Card>
          <CardHeader>
            <CardTitle>LangGraph integration is disabled</CardTitle>
            <CardDescription>
              {canConfigure
                ? 'Enable the experimental integration in Platform Settings before onboarding endpoints.'
                : 'An organization administrator must enable the experimental integration before endpoint onboarding is available.'}
            </CardDescription>
          </CardHeader>
          {canConfigure && (
            <CardContent>
              <Button asChild>
                <Link href="/settings#langgraph-integration">Configure in Platform Settings</Link>
              </Button>
            </CardContent>
          )}
        </Card>
      </div>
    );
  }

  return <div className="container mx-auto px-4 py-8">
    <div className="mb-6 flex items-start justify-between gap-4"><div><div className="flex items-center gap-2"><h1 className="text-3xl font-bold">LangGraph endpoints</h1><Badge variant="secondary">Experimental</Badge></div><p className="mt-2 text-muted-foreground">Contract-compatible remote chat reasoners. Mural retains media, telephony, workflow, and tool authority.</p><p className="mt-1 text-xs text-muted-foreground">Rollout: {langGraphFeature?.rollout_stage?.replaceAll('_', ' ')}</p></div><Button asChild><Link href="/langgraph-endpoints/new"><Plus className="mr-2 h-4 w-4" />Add endpoint</Link></Button></div>
    {error && <div role="alert" className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-destructive">{error}</div>}
    {loading ? <p className="text-muted-foreground">Loading endpoints…</p> : endpoints.length === 0 ? <Card><CardHeader><CardTitle>No endpoints registered</CardTitle><CardDescription>Register a remote endpoint, validate its manifest and behavior, then activate it before workflow attachment.</CardDescription></CardHeader></Card> : <div className="grid gap-3">{endpoints.map((endpoint) => <Link key={endpoint.endpoint_uuid} href={`/langgraph-endpoints/${endpoint.endpoint_uuid}`}><Card className="transition-colors hover:bg-muted/40"><CardContent className="flex items-center gap-4 py-5"><Network className="h-5 w-5 text-muted-foreground" /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{endpoint.name}</span><Badge>{endpoint.lifecycle_status.replaceAll('_', ' ')}</Badge>{endpoint.lifecycle_status === 'degraded' && <AlertTriangle className="h-4 w-4 text-amber-500" />}</div><p className="truncate text-sm text-muted-foreground">{endpoint.endpoint_url}</p><p className="mt-1 text-xs text-muted-foreground">{endpoint.selected_profile} · {endpoint.current_capability_snapshot?.manifest.contract_versions?.toString() ?? 'version pending'} · {endpoint.selected_capabilities.join(', ')}</p></div></CardContent></Card></Link>)}</div>}
  </div>;
}
