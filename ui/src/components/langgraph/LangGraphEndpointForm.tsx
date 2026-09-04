'use client';

import { useState } from 'react';

import type { EndpointCreateRequest, EndpointResponse } from '@/client/types.gen';
import { CredentialSelector } from '@/components/http/credential-selector';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

export type EndpointFormValue = EndpointCreateRequest;

export function LangGraphEndpointForm({
  endpoint,
  onSubmit,
  submitting,
}: {
  endpoint?: EndpointResponse;
  onSubmit: (value: EndpointFormValue) => Promise<void>;
  submitting?: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState(endpoint?.name ?? '');
  const [endpointUrl, setEndpointUrl] = useState(endpoint?.endpoint_url ?? '');
  const [credentialUuid, setCredentialUuid] = useState(endpoint?.credential.reference_id ?? '');
  const [profile, setProfile] = useState<'chat' | 'stateful_run'>((endpoint?.selected_profile as 'chat' | 'stateful_run') ?? 'chat');
  const [capabilities, setCapabilities] = useState(endpoint?.selected_capabilities.join(', ') ?? 'streaming');

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const selectedCapabilities = capabilities.split(',').map((value) => value.trim()).filter(Boolean);
    if (!credentialUuid) {
      setError('Select a credential before saving the endpoint.');
      return;
    }
    if (selectedCapabilities.length === 0) {
      setError('Select at least one capability.');
      return;
    }
    try {
      await onSubmit({
        name,
        endpoint_url: endpointUrl,
        credential_uuid: credentialUuid,
        selected_profile: profile,
        selected_capabilities: Array.from(new Set(selectedCapabilities)),
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Failed to save endpoint');
    }
  };

  return (
    <form className="space-y-5" onSubmit={submit}>
      {error && <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}
      <div className="space-y-2"><Label htmlFor="endpoint-name">Identity name</Label><Input id="endpoint-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={255} /></div>
      <div className="space-y-2"><Label htmlFor="endpoint-url">Endpoint URL</Label><Input id="endpoint-url" type="url" value={endpointUrl} onChange={(e) => setEndpointUrl(e.target.value)} required maxLength={2048} /></div>
      <CredentialSelector
        value={credentialUuid}
        onChange={setCredentialUuid}
        disabled={submitting}
        required
        placeholder="Select a credential"
        description="Select an organization credential for this endpoint. Secrets stay encrypted and are never returned to this form."
        currentCredential={endpoint ? {
          uuid: endpoint.credential.reference_id,
          label: `Current credential (${endpoint.credential.credential_type})`,
        } : undefined}
      />
      <div className="space-y-2"><Label htmlFor="endpoint-profile">Compatibility profile</Label><Select value={profile} onValueChange={(value) => setProfile(value as 'chat' | 'stateful_run')}><SelectTrigger id="endpoint-profile"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="chat">Chat Compatibility</SelectItem><SelectItem value="stateful_run">Stateful Run</SelectItem></SelectContent></Select></div>
      <div className="space-y-2"><Label htmlFor="endpoint-capabilities">Selected capabilities</Label><Input id="endpoint-capabilities" value={capabilities} onChange={(e) => setCapabilities(e.target.value)} placeholder="streaming, cancellation, tools" /><p className="text-xs text-muted-foreground">Comma-separated declared behaviors to validate. Streaming is required for live voice.</p></div>
      <Button type="submit" disabled={submitting || !credentialUuid}>{submitting ? 'Saving…' : endpoint ? 'Save and revalidate' : 'Create endpoint'}</Button>
    </form>
  );
}
