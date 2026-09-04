'use client';

import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import { FormEvent, useEffect, useState } from 'react';

import { updateLanggraphFeatureStatusApiV1LanggraphFeaturePatch } from '@/client/sdk.gen';
import type { LangGraphFeatureUpdateRequest } from '@/client/types.gen';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { useOrgConfig } from '@/context/OrgConfigContext';
import { detailFromError } from '@/lib/apiError';

const displayStatus = (value: boolean) => (value ? 'Enabled' : 'Disabled');
const displayRolloutStage = (value: string) => value.replaceAll('_', ' ');

export function LangGraphFeatureSettingsCard() {
  const { langGraphFeature, loading, refreshConfig } = useOrgConfig();
  const [enabled, setEnabled] = useState(false);
  const [privateNetworkEnabled, setPrivateNetworkEnabled] = useState(false);
  const [experimentalAcknowledged, setExperimentalAcknowledged] = useState(false);
  const [privateNetworkAcknowledged, setPrivateNetworkAcknowledged] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!langGraphFeature || saving) return;
    setEnabled(langGraphFeature.enabled);
    setPrivateNetworkEnabled(langGraphFeature.private_network_enabled);
  }, [langGraphFeature, saving]);

  const enablingFeature = enabled && !langGraphFeature?.enabled;
  const enablingPrivateNetwork =
    privateNetworkEnabled && !langGraphFeature?.private_network_enabled;
  const hasChanges = Boolean(
    langGraphFeature &&
      (enabled !== langGraphFeature.enabled ||
        (langGraphFeature.private_network_configurable &&
          privateNetworkEnabled !== langGraphFeature.private_network_enabled)),
  );
  const acknowledgmentMissing = enabled && !experimentalAcknowledged;
  const privateAcknowledgmentMissing =
    langGraphFeature?.private_network_configurable &&
    enablingPrivateNetwork &&
    !privateNetworkAcknowledged;
  const controlsDisabled = loading || saving || !langGraphFeature;
  const submitDisabled =
    controlsDisabled ||
    !hasChanges ||
    acknowledgmentMissing ||
    Boolean(privateAcknowledgmentMissing);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitDisabled || !langGraphFeature || saving) return;

    setSaving(true);
    setError(null);
    setSuccess(null);

    const body: LangGraphFeatureUpdateRequest = {
      enabled,
      experimental_risk_acknowledged: enabled && experimentalAcknowledged,
    };
    if (langGraphFeature.private_network_configurable) {
      body.private_network_enabled = privateNetworkEnabled;
      body.private_network_risk_acknowledged =
        enablingPrivateNetwork && privateNetworkAcknowledged;
    }

    try {
      const response = await updateLanggraphFeatureStatusApiV1LanggraphFeaturePatch({ body });
      if (response.error) {
        setError(detailFromError(response.error, 'Failed to update LangGraph integration settings'));
        return;
      }

      await refreshConfig();
      setExperimentalAcknowledged(false);
      setPrivateNetworkAcknowledged(false);
      setSuccess('LangGraph integration settings updated.');
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Failed to update LangGraph integration settings',
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card id="langgraph-integration" className="scroll-mt-6">
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle>LangGraph integration</CardTitle>
          <Badge variant="secondary">Experimental</Badge>
        </div>
        <CardDescription>
          Configure organization-wide access to contract-compatible remote reasoning endpoints.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading || !langGraphFeature ? (
          <div
            role="status"
            aria-live="polite"
            className="flex items-center gap-2 text-sm text-muted-foreground"
          >
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Loading LangGraph integration settings…
          </div>
        ) : (
          <form className="space-y-5" onSubmit={submit}>
            <dl className="grid grid-cols-2 gap-3 rounded-md border p-3 text-sm sm:grid-cols-4">
              <div>
                <dt className="text-muted-foreground">Status</dt>
                <dd className="font-medium">{displayStatus(langGraphFeature.enabled)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Acknowledged</dt>
                <dd className="font-medium">{langGraphFeature.acknowledged ? 'Yes' : 'No'}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Release</dt>
                <dd className="font-medium">
                  {langGraphFeature.experimental ? 'Experimental' : 'General'}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Rollout</dt>
                <dd className="font-medium capitalize">
                  {displayRolloutStage(langGraphFeature.rollout_stage)}
                </dd>
              </div>
            </dl>

            <div className="flex gap-3 rounded-md border border-amber-400/50 bg-amber-50 p-3 text-sm text-amber-950 dark:bg-amber-950/30 dark:text-amber-100">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <p>
                Compatibility is limited to supported contracts. External endpoint latency affects
                callers, and configured prompts, transcripts, context, and tool data may leave
                Mural under the workflow&apos;s Data Sharing Policy.
              </p>
            </div>

            {!langGraphFeature.can_configure ? (
              <p className="text-sm text-muted-foreground">
                These settings are read-only. Contact an organization administrator to change
                LangGraph integration access.
              </p>
            ) : (
              <>
                <div className="flex items-center justify-between gap-4 rounded-md border p-3">
                  <div>
                    <Label htmlFor="langgraph-feature-enabled">Enable LangGraph integration</Label>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Controls endpoint onboarding and workflow configuration for this organization.
                    </p>
                  </div>
                  <Switch
                    id="langgraph-feature-enabled"
                    checked={enabled}
                    onCheckedChange={(checked) => {
                      setEnabled(checked);
                      setError(null);
                      setSuccess(null);
                    }}
                    disabled={controlsDisabled}
                  />
                </div>

                {enabled && (
                  <div className="flex items-start gap-2">
                    <Checkbox
                      id="langgraph-experimental-acknowledgment"
                      checked={experimentalAcknowledged}
                      onCheckedChange={(checked) =>
                        setExperimentalAcknowledged(checked === true)
                      }
                      disabled={controlsDisabled}
                    />
                    <Label
                      htmlFor="langgraph-experimental-acknowledgment"
                      className="items-start font-normal leading-5"
                    >
                      I acknowledge the experimental status, contract compatibility boundaries,
                      external latency responsibility, and external data-sharing scope. This
                      acknowledgment is required for every enable request.
                    </Label>
                  </div>
                )}

                {langGraphFeature.private_network_configurable && (
                  <div className="space-y-3 rounded-md border p-3">
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <Label htmlFor="langgraph-private-network-enabled">
                          Allow private-network endpoints
                        </Label>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Self-hosted only. Existing URL, redirect, DNS, and connection-time checks
                          remain enforced.
                        </p>
                      </div>
                      <Switch
                        id="langgraph-private-network-enabled"
                        checked={privateNetworkEnabled}
                        onCheckedChange={(checked) => {
                          setPrivateNetworkEnabled(checked);
                          setError(null);
                          setSuccess(null);
                        }}
                        disabled={controlsDisabled}
                      />
                    </div>
                    {enablingPrivateNetwork && (
                      <div className="flex items-start gap-2">
                        <Checkbox
                          id="langgraph-private-network-acknowledgment"
                          checked={privateNetworkAcknowledged}
                          onCheckedChange={(checked) =>
                            setPrivateNetworkAcknowledged(checked === true)
                          }
                          disabled={controlsDisabled}
                        />
                        <Label
                          htmlFor="langgraph-private-network-acknowledgment"
                          className="items-start font-normal leading-5"
                        >
                          I accept the separate SSRF and trusted-network exposure risk of allowing
                          private-network endpoint access.
                        </Label>
                      </div>
                    )}
                  </div>
                )}

                {error && (
                  <div
                    role="alert"
                    className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
                  >
                    {error}
                  </div>
                )}
                {success && (
                  <div
                    role="status"
                    aria-live="polite"
                    className="flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-300"
                  >
                    <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                    {success}
                  </div>
                )}

                <Button type="submit" disabled={submitDisabled}>
                  {saving ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                      Saving…
                    </>
                  ) : enablingFeature ? (
                    'Enable integration'
                  ) : (
                    'Save settings'
                  )}
                </Button>
              </>
            )}
          </form>
        )}
      </CardContent>
    </Card>
  );
}
