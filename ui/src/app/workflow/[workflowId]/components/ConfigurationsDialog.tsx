import { Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
    activateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidActivatePost,
    getExternalLanggraphTopologyApiV1WorkflowWorkflowIdVersionsDefinitionIdLanggraphTopologyGet,
    getLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidGet,
    getWorkflowVersionsApiV1WorkflowWorkflowIdVersionsGet,
    listLanggraphValidationReportsApiV1LanggraphEndpointsEndpointUuidValidationReportsGet,
    refreshExternalLanggraphTopologyApiV1WorkflowWorkflowIdVersionsDefinitionIdLanggraphTopologyRefreshPost,
    updateExternalLanggraphTopologyBindingApiV1WorkflowWorkflowIdVersionsDefinitionIdLanggraphTopologyUpdateBindingPost,
    validateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidValidatePost,
} from "@/client/sdk.gen";
import { LangGraphWorkflowConfiguration } from "@/components/flow/LangGraphWorkflowConfiguration";
import { adaptExternalTopologyResponse, type ExternalTopologyResponse } from "@/components/langgraph/topology";
import { type RecoveryProgress, runTopologyRecovery } from "@/components/langgraph/topologyRecovery";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";
import {
    AmbientNoiseConfiguration,
    DEFAULT_PROVISIONAL_VAD_PAUSE_SECS,
    DEFAULT_TURN_START_MIN_WORDS,
    ExternalPBXFieldMapping,
    type LangGraphEndpointBinding,
    resolveWorkflowConfigurations,
    TURN_START_STRATEGY_OPTIONS,
    TurnStartStrategy,
    TurnStopStrategy,
    WorkflowConfigurations,
} from "@/types/workflow-configurations";

interface ConfigurationsDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    workflowConfigurations: WorkflowConfigurations | null;
    workflowName: string;
    onSave: (configurations: WorkflowConfigurations, workflowName: string) => Promise<void>;
    onCreateDraft?: () => Promise<void>;
    immutable?: boolean;
    workflowId?: number;
    definitionId?: number | null;
    transitionLabels?: string[];
}

export const ConfigurationsDialog = ({
    open,
    onOpenChange,
    workflowConfigurations,
    workflowName,
    onSave,
    onCreateDraft,
    immutable = false,
    workflowId,
    definitionId,
    transitionLabels = [],
}: ConfigurationsDialogProps) => {
    const { externalPbxIntegrationsEnabled, langGraphEnabled } = useOrgConfig();
    const resolvedWorkflowConfigurations = resolveWorkflowConfigurations(workflowConfigurations);
    const [name, setName] = useState<string>(workflowName);
    const [ambientNoiseConfig, setAmbientNoiseConfig] = useState<AmbientNoiseConfiguration>(
        resolvedWorkflowConfigurations.ambient_noise_configuration
    );
    const [maxCallDuration, setMaxCallDuration] = useState<number>(
        resolvedWorkflowConfigurations.max_call_duration
    );
    const [maxUserIdleTimeout, setMaxUserIdleTimeout] = useState<number>(
        resolvedWorkflowConfigurations.max_user_idle_timeout
    );
    const [smartTurnStopSecs, setSmartTurnStopSecs] = useState<number>(
        resolvedWorkflowConfigurations.smart_turn_stop_secs
    );
    const [turnStartStrategy, setTurnStartStrategy] = useState<TurnStartStrategy>(
        resolvedWorkflowConfigurations.turn_start_strategy
    );
    const [turnStartMinWords, setTurnStartMinWords] = useState<number>(
        resolvedWorkflowConfigurations.turn_start_min_words
    );
    const [provisionalVadPauseSecs, setProvisionalVadPauseSecs] = useState<number>(
        resolvedWorkflowConfigurations.provisional_vad_pause_secs
    );
    const [turnStopStrategy, setTurnStopStrategy] = useState<TurnStopStrategy>(
        resolvedWorkflowConfigurations.turn_stop_strategy
    );
    const [contextCompactionEnabled, setContextCompactionEnabled] = useState<boolean>(
        resolvedWorkflowConfigurations.context_compaction_enabled
    );
    const [externalPbxFieldMappings, setExternalPbxFieldMappings] = useState<ExternalPBXFieldMapping[]>(
        resolvedWorkflowConfigurations.external_pbx_field_mappings
    );
    const [langGraphEndpoint, setLangGraphEndpoint] = useState(resolvedWorkflowConfigurations.langgraph_endpoint ?? null);
    const [savedLangGraphEndpoint, setSavedLangGraphEndpoint] = useState(resolvedWorkflowConfigurations.langgraph_endpoint ?? null);
    const [topologyBindingNeedsReload, setTopologyBindingNeedsReload] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const selectedTurnStartStrategy = TURN_START_STRATEGY_OPTIONS.find(
        (option) => option.value === turnStartStrategy
    );
    const externalPbxFieldMappingsValid = externalPbxFieldMappings.every(
        (mapping) =>
            Boolean(mapping.context_path.trim()) &&
            /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(mapping.destination_field.trim())
    );
    const savedRegistrationUuid = savedLangGraphEndpoint?.registration_uuid;
    const endpointBindingHasUnsavedChanges = useMemo(
        () => JSON.stringify(langGraphEndpoint) !== JSON.stringify(savedLangGraphEndpoint),
        [langGraphEndpoint, savedLangGraphEndpoint],
    );
    const topologyMutationBlockedReason = topologyBindingNeedsReload
        ? 'The topology update committed, but the saved binding could not be reloaded. Close and reopen the workflow before saving.'
        : endpointBindingHasUnsavedChanges
            ? 'Save or discard endpoint configuration changes before updating topology. Recovery always uses the saved Current Draft binding.'
            : undefined;
    const ensureTopologyMutationAllowed = useCallback(() => {
        if (topologyMutationBlockedReason) throw new Error(topologyMutationBlockedReason);
    }, [topologyMutationBlockedReason]);
    const topologyPath = useMemo(() => workflowId !== undefined && definitionId !== null && definitionId !== undefined
        ? { workflow_id: workflowId, definition_id: definitionId }
        : null, [definitionId, workflowId]);
    const topologyLoader = useCallback(async (): Promise<ExternalTopologyResponse> => {
        // Never fabricate a backend reason here: a missing workflow version is an editor
        // state problem, and reporting it as snapshot_unavailable makes it look like the
        // endpoint has no pinned topology while no request was ever sent.
        if (!topologyPath) throw new Error('The workflow version is still loading. Reopen this dialog to view endpoint topology.');
        const response = await getExternalLanggraphTopologyApiV1WorkflowWorkflowIdVersionsDefinitionIdLanggraphTopologyGet({ path: topologyPath });
        if (response.error) throw new Error(detailFromError(response.error, 'Failed to retrieve endpoint topology'));
        return adaptExternalTopologyResponse(response.data ?? { status: 'unavailable', reason: 'snapshot_unavailable' });
    }, [topologyPath]);

    const synchronizeSavedBinding = useCallback(async () => {
        if (workflowId === undefined || definitionId === null || definitionId === undefined) return;
        const versions = await getWorkflowVersionsApiV1WorkflowWorkflowIdVersionsGet({ path: { workflow_id: workflowId } });
        if (versions.error) throw new Error(detailFromError(versions.error, 'Topology updated, but the editor could not reload the saved draft binding'));
        const current = versions.data?.find((version) => version.id === definitionId);
        const binding = current?.workflow_configurations?.langgraph_endpoint;
        if (!binding || typeof binding !== 'object' || Array.isArray(binding)) {
            throw new Error('Topology updated, but the saved draft binding could not be reloaded. Close this dialog before saving other changes.');
        }
        const synchronizedBinding = binding as unknown as LangGraphEndpointBinding;
        setSavedLangGraphEndpoint(synchronizedBinding);
        setLangGraphEndpoint(synchronizedBinding);
        setTopologyBindingNeedsReload(false);
    }, [definitionId, workflowId]);

    const refreshTopology = useCallback(async (signal?: AbortSignal): Promise<ExternalTopologyResponse> => {
        ensureTopologyMutationAllowed();
        if (!topologyPath) throw new Error('The workflow version is still loading. Reopen this dialog before refreshing topology.');
        const response = await refreshExternalLanggraphTopologyApiV1WorkflowWorkflowIdVersionsDefinitionIdLanggraphTopologyRefreshPost({ path: topologyPath, signal });
        if (response.error) throw new Error(detailFromError(response.error, 'Failed to refresh endpoint topology'));
        const adapted = adaptExternalTopologyResponse(response.data ?? { status: 'unavailable', reason: 'snapshot_unavailable' });
        if (adapted.status === 'available') {
            setTopologyBindingNeedsReload(true);
            await synchronizeSavedBinding();
        }
        return adapted;
    }, [ensureTopologyMutationAllowed, synchronizeSavedBinding, topologyPath]);

    const updateTopologyBinding = useCallback(async (signal?: AbortSignal): Promise<ExternalTopologyResponse> => {
        ensureTopologyMutationAllowed();
        if (!topologyPath) throw new Error('The workflow version is still loading. Reopen this dialog before updating the endpoint binding.');
        const response = await updateExternalLanggraphTopologyBindingApiV1WorkflowWorkflowIdVersionsDefinitionIdLanggraphTopologyUpdateBindingPost({ path: topologyPath, signal });
        if (response.error) throw new Error(detailFromError(response.error, 'Failed to update the draft endpoint binding'));
        const adapted = adaptExternalTopologyResponse(response.data ?? { status: 'unavailable', reason: 'snapshot_unavailable' });
        if (adapted.status === 'available') {
            setTopologyBindingNeedsReload(true);
            await synchronizeSavedBinding();
        }
        return adapted;
    }, [ensureTopologyMutationAllowed, synchronizeSavedBinding, topologyPath]);

    const recoverTopologyBinding = useCallback(async (
        signal: AbortSignal,
        onProgress: (progress: RecoveryProgress) => void,
    ): Promise<ExternalTopologyResponse> => {
        ensureTopologyMutationAllowed();
        if (!savedRegistrationUuid) throw new Error('The saved Current Draft has no endpoint binding to revalidate.');
        const recovered = adaptExternalTopologyResponse(await runTopologyRecovery({
            endpointUuid: savedRegistrationUuid,
            validate: validateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidValidatePost,
            getEndpoint: getLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidGet,
            listReports: listLanggraphValidationReportsApiV1LanggraphEndpointsEndpointUuidValidationReportsGet,
            activate: activateLanggraphEndpointApiV1LanggraphEndpointsEndpointUuidActivatePost,
            updateBinding: async (requestSignal) => {
                if (!topologyPath) throw new Error('The workflow version is still loading. Reopen this dialog before updating the endpoint binding.');
                const result = await updateExternalLanggraphTopologyBindingApiV1WorkflowWorkflowIdVersionsDefinitionIdLanggraphTopologyUpdateBindingPost({ path: topologyPath, signal: requestSignal });
                if (result.data?.status === 'available') setTopologyBindingNeedsReload(true);
                return result;
            },
            normalizeError: detailFromError,
            onProgress,
            signal,
        }));
        if (recovered.status === 'available') await synchronizeSavedBinding();
        return recovered;
    }, [ensureTopologyMutationAllowed, savedRegistrationUuid, synchronizeSavedBinding, topologyPath]);

    const handleSave = async () => {
        if (topologyBindingNeedsReload) return;
        setIsSaving(true);
        try {
            await onSave({
                ...resolvedWorkflowConfigurations,
                ambient_noise_configuration: ambientNoiseConfig,
                max_call_duration: maxCallDuration,
                max_user_idle_timeout: maxUserIdleTimeout,
                smart_turn_stop_secs: smartTurnStopSecs,
                turn_start_strategy: turnStartStrategy,
                turn_start_min_words: turnStartMinWords,
                provisional_vad_pause_secs: provisionalVadPauseSecs,
                turn_stop_strategy: turnStopStrategy,
                transcript_configuration: resolvedWorkflowConfigurations.transcript_configuration,
                context_compaction_enabled: contextCompactionEnabled,
                external_pbx_field_mappings: externalPbxFieldMappings,
                langgraph_endpoint: langGraphEndpoint,
            }, name);
            onOpenChange(false);
        } catch (error) {
            console.error("Failed to save configurations:", error);
        } finally {
            setIsSaving(false);
        }
    };

    // Sync state with props when dialog opens
    useEffect(() => {
        if (open) {
            const nextWorkflowConfigurations = resolveWorkflowConfigurations(workflowConfigurations);
            setName(workflowName);
            setAmbientNoiseConfig(nextWorkflowConfigurations.ambient_noise_configuration);
            setMaxCallDuration(nextWorkflowConfigurations.max_call_duration);
            setMaxUserIdleTimeout(nextWorkflowConfigurations.max_user_idle_timeout);
            setSmartTurnStopSecs(nextWorkflowConfigurations.smart_turn_stop_secs);
            setTurnStartStrategy(nextWorkflowConfigurations.turn_start_strategy);
            setTurnStartMinWords(nextWorkflowConfigurations.turn_start_min_words);
            setProvisionalVadPauseSecs(nextWorkflowConfigurations.provisional_vad_pause_secs);
            setTurnStopStrategy(nextWorkflowConfigurations.turn_stop_strategy);
            setContextCompactionEnabled(nextWorkflowConfigurations.context_compaction_enabled);
            setExternalPbxFieldMappings(nextWorkflowConfigurations.external_pbx_field_mappings);
            setSavedLangGraphEndpoint(nextWorkflowConfigurations.langgraph_endpoint ?? null);
            setLangGraphEndpoint(nextWorkflowConfigurations.langgraph_endpoint ?? null);
        }
    }, [open, workflowName, workflowConfigurations]);

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>Configurations</DialogTitle>
                </DialogHeader>

                <div className="space-y-6">
                    {/* Workflow Name Section */}
                    <div className="space-y-4">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Agent Name</h3>
                            <p className="text-xs text-muted-foreground">
                                The name of your agent
                            </p>
                        </div>
                        <div className="space-y-2">
                            <Label htmlFor="workflow_name" className="text-xs">
                                Name
                            </Label>
                            <Input
                                id="workflow_name"
                                type="text"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                placeholder="Enter Agent name"
                            />
                        </div>
                    </div>

                    {/* Ambient Noise Section */}
                    <div className="space-y-4">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Ambient Noise</h3>
                            <p className="text-xs text-muted-foreground">
                                Add background office ambient noise to make the conversation sound more natural.
                            </p>
                        </div>

                        <div className="space-y-4">
                            <div className="flex items-center justify-between">
                                <Label htmlFor="ambient-noise-enabled" className="text-sm">
                                    Use Ambient Noise
                                </Label>
                                <Switch
                                    id="ambient-noise-enabled"
                                    checked={ambientNoiseConfig.enabled}
                                    onCheckedChange={(checked) =>
                                        setAmbientNoiseConfig(prev => ({ ...prev, enabled: checked }))
                                    }
                                />
                            </div>

                            {ambientNoiseConfig.enabled && (
                                <div className="space-y-2">
                                    <Label htmlFor="ambient-volume" className="text-xs">
                                        Volume
                                    </Label>
                                    <Input
                                        id="ambient-volume"
                                        type="number"
                                        step="0.1"
                                        min="0"
                                        max="1"
                                        value={ambientNoiseConfig.volume}
                                        onChange={(e) => {
                                            const value = parseFloat(e.target.value);
                                            if (!isNaN(value)) {
                                                setAmbientNoiseConfig(prev => ({ ...prev, volume: value }));
                                            }
                                        }}
                                    />
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Turn Detection Section */}
                    <div className="space-y-4">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Turn Detection</h3>
                            <p className="text-xs text-muted-foreground">
                                Configure how the agent detects when the user has finished speaking.
                            </p>
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="turn_stop_strategy" className="text-xs">
                                Detection Strategy
                            </Label>
                            <Select
                                value={turnStopStrategy}
                                onValueChange={(value: TurnStopStrategy) => setTurnStopStrategy(value)}
                            >
                                <SelectTrigger id="turn_stop_strategy">
                                    <SelectValue placeholder="Select strategy" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="transcription">
                                        Transcription-based
                                    </SelectItem>
                                    <SelectItem value="turn_analyzer">
                                        Smart Turn Analyzer
                                    </SelectItem>
                                </SelectContent>
                            </Select>
                            <p className="text-xs text-muted-foreground">
                                {turnStopStrategy === 'transcription'
                                    ? "Best for short responses (1-2 word statements). Ends turn when transcription indicates completion."
                                    : "Best for longer responses with natural pauses. Uses ML model to detect end of turn."}
                            </p>
                        </div>

                        {turnStopStrategy === 'turn_analyzer' && (
                            <div className="space-y-2">
                                <Label htmlFor="smart_turn_stop_secs" className="text-xs">
                                    Incomplete Turn Timeout (seconds)
                                </Label>
                                <Input
                                    id="smart_turn_stop_secs"
                                    type="number"
                                    step="0.5"
                                    min="0.5"
                                    max="10"
                                    value={smartTurnStopSecs}
                                    onChange={(e) => {
                                        const value = parseFloat(e.target.value);
                                        if (!isNaN(value) && value >= 0.5) {
                                            setSmartTurnStopSecs(value);
                                        }
                                    }}
                                />
                                <p className="text-xs text-muted-foreground">
                                    Max silence duration before ending an incomplete turn. Default: 2 seconds
                                </p>
                            </div>
                        )}
                    </div>

                    {/* Interruption Section */}
                    <div className="space-y-4">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Interruption</h3>
                            <p className="text-xs text-muted-foreground">
                                Configure when user speech should interrupt the agent while it is speaking.
                            </p>
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="turn_start_strategy" className="text-xs">
                                Interruption Strategy
                            </Label>
                            <Select
                                value={turnStartStrategy}
                                onValueChange={(value: TurnStartStrategy) => setTurnStartStrategy(value)}
                            >
                                <SelectTrigger id="turn_start_strategy">
                                    <SelectValue placeholder="Select strategy" />
                                </SelectTrigger>
                                <SelectContent>
                                    {TURN_START_STRATEGY_OPTIONS.map((option) => (
                                        <SelectItem key={option.value} value={option.value}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <p className="text-xs text-muted-foreground">
                                {selectedTurnStartStrategy?.description}
                            </p>
                        </div>

                        {turnStartStrategy === 'min_words' && (
                            <div className="space-y-2">
                                <Label htmlFor="turn_start_min_words" className="text-xs">
                                    Minimum Words Before Interruption
                                </Label>
                                <Input
                                    id="turn_start_min_words"
                                    type="number"
                                    step="1"
                                    min="1"
                                    max="10"
                                    value={turnStartMinWords}
                                    onChange={(e) => {
                                        const value = parseInt(e.target.value);
                                        if (!isNaN(value) && value >= 1) {
                                            setTurnStartMinWords(value);
                                        }
                                    }}
                                />
                                <p className="text-xs text-muted-foreground">
                                    Number of transcribed words needed to interrupt while the bot is speaking. Default: {DEFAULT_TURN_START_MIN_WORDS}
                                </p>
                            </div>
                        )}

                        {turnStartStrategy === 'provisional_vad' && (
                            <div className="space-y-2">
                                <Label htmlFor="provisional_vad_pause_secs" className="text-xs">
                                    Provisional Pause (seconds)
                                </Label>
                                <Input
                                    id="provisional_vad_pause_secs"
                                    type="number"
                                    step="0.1"
                                    min="0.1"
                                    max="5"
                                    value={provisionalVadPauseSecs}
                                    onChange={(e) => {
                                        const value = parseFloat(e.target.value);
                                        if (!isNaN(value) && value >= 0.1) {
                                            setProvisionalVadPauseSecs(value);
                                        }
                                    }}
                                />
                                <p className="text-xs text-muted-foreground">
                                    Seconds to pause bot audio while waiting for transcript confirmation. Default: {DEFAULT_PROVISIONAL_VAD_PAUSE_SECS}
                                </p>
                            </div>
                        )}
                    </div>

                    {/* Context Management Section */}
                    <div className="space-y-4">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Context Compaction</h3>
                            <p className="text-xs text-muted-foreground">
                                Automatically summarize conversation context when transitioning between nodes. Removes stale tool calls and keeps the context clean for the new node.
                            </p>
                        </div>

                        <div className="flex items-center justify-between">
                            <Label htmlFor="context-compaction-enabled" className="text-sm">
                                Enable Context Compaction
                            </Label>
                            <Switch
                                id="context-compaction-enabled"
                                checked={contextCompactionEnabled}
                                onCheckedChange={setContextCompactionEnabled}
                            />
                        </div>
                    </div>

                    {/* Call Management Section */}
                    <div className="space-y-4">
                        <div>
                            <h3 className="text-sm font-semibold mb-1">Call Management</h3>
                            <p className="text-xs text-muted-foreground">
                                Configure call duration limits and idle timeout settings.
                            </p>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <Label htmlFor="max_call_duration" className="text-xs">
                                    Max Call Duration (seconds)
                                </Label>
                                <Input
                                    id="max_call_duration"
                                    type="number"
                                    step="1"
                                    min="1"
                                    value={maxCallDuration}
                                    onChange={(e) => {
                                        const value = parseInt(e.target.value);
                                        if (!isNaN(value) && value > 0) {
                                            setMaxCallDuration(value);
                                        }
                                    }}
                                />
                                <p className="text-xs text-muted-foreground">Default: 600 (10 minutes)</p>
                            </div>

                            <div className="space-y-2">
                                <Label htmlFor="max_user_idle_timeout" className="text-xs">
                                    Max User Idle Timeout (seconds)
                                </Label>
                                <Input
                                    id="max_user_idle_timeout"
                                    type="number"
                                    step="1"
                                    min="1"
                                    value={maxUserIdleTimeout}
                                    onChange={(e) => {
                                        const value = parseInt(e.target.value);
                                        if (!isNaN(value) && value > 0) {
                                            setMaxUserIdleTimeout(value);
                                        }
                                    }}
                                />
                                <p className="text-xs text-muted-foreground">Default: 10 seconds</p>
                            </div>
                        </div>
                    </div>

                    {externalPbxIntegrationsEnabled && (
                        <div className="space-y-4 border-t pt-4">
                            <div>
                                <h3 className="text-sm font-semibold mb-1">External PBX Field Updates</h3>
                                <p className="text-xs text-muted-foreground">
                                    Optionally copy final gathered-context values into provider-native fields before transfer or hangup.
                                </p>
                            </div>
                            <div className="flex items-center justify-between">
                                <Label className="text-sm">Field Mappings</Label>
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setExternalPbxFieldMappings((current) => [
                                        ...current,
                                        { context_path: "", destination_field: "" },
                                    ])}
                                >
                                    <Plus className="mr-1 h-4 w-4" /> Add mapping
                                </Button>
                            </div>
                            <div className="space-y-2">
                                {externalPbxFieldMappings.map((mapping, index) => (
                                    <div key={index} className="grid grid-cols-[1fr_1fr_auto] gap-2">
                                        <Input
                                            aria-label={`Gathered context field ${index + 1}`}
                                            value={mapping.context_path}
                                            onChange={(event) => setExternalPbxFieldMappings((current) =>
                                                current.map((item, itemIndex) =>
                                                    itemIndex === index
                                                        ? { ...item, context_path: event.target.value }
                                                        : item
                                                )
                                            )}
                                            placeholder="qualified"
                                        />
                                        <Input
                                            aria-label={`External PBX destination field ${index + 1}`}
                                            value={mapping.destination_field}
                                            onChange={(event) => setExternalPbxFieldMappings((current) =>
                                                current.map((item, itemIndex) =>
                                                    itemIndex === index
                                                        ? { ...item, destination_field: event.target.value }
                                                        : item
                                                )
                                            )}
                                            placeholder="address3"
                                        />
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="icon"
                                            aria-label={`Remove external PBX field mapping ${index + 1}`}
                                            onClick={() => setExternalPbxFieldMappings((current) =>
                                                current.filter((_, itemIndex) => itemIndex !== index)
                                            )}
                                        >
                                            <Trash2 className="h-4 w-4" />
                                        </Button>
                                    </div>
                                ))}
                                {externalPbxFieldMappings.length === 0 && (
                                    <p className="text-xs text-muted-foreground">
                                        No external fields will be updated. Context names may be direct extracted-variable names or paths such as extracted_variables.qualified.
                                    </p>
                                )}
                                {!externalPbxFieldMappingsValid && (
                                    <p className="text-xs text-destructive">
                                        Each mapping needs a context field and a destination field containing only letters, numbers, and underscores.
                                    </p>
                                )}
                            </div>
                        </div>
                    )}

                    {langGraphEnabled && (
                        <LangGraphWorkflowConfiguration
                            value={langGraphEndpoint}
                            onChange={setLangGraphEndpoint}
                            onCreateDraft={onCreateDraft}
                            realtime={resolvedWorkflowConfigurations.model_overrides?.is_realtime === true}
                            immutable={immutable}
                            transitionLabels={transitionLabels}
                            topologyLoader={topologyLoader}
                            topologyRefresh={refreshTopology}
                            topologyUpdateBinding={updateTopologyBinding}
                            topologyRecoverBinding={recoverTopologyBinding}
                            topologyMutationBlockedReason={topologyMutationBlockedReason}
                        />
                    )}
                </div>

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        Cancel
                    </Button>
                    <Button
                        onClick={handleSave}
                        disabled={isSaving || topologyBindingNeedsReload || (externalPbxIntegrationsEnabled && !externalPbxFieldMappingsValid)}
                    >
                        {isSaving ? "Saving..." : "Save"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
