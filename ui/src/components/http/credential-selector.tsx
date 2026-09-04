"use client";

import { AlertCircle, Loader2, PlusIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { listCredentialsApiV1CredentialsGet } from "@/client";
import type { CredentialResponse } from "@/client/types.gen";
import { CreateCredentialDialog } from "@/components/http/create-credential-dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

interface CredentialSelectorProps {
    value: string;
    onChange: (uuid: string) => void;
    disabled?: boolean;
    placeholder?: string;
    label?: string;
    description?: string;
    showLabel?: boolean;
    required?: boolean;
    currentCredential?: {
        uuid: string;
        label: string;
    };
}

export function CredentialSelector({
    value,
    onChange,
    disabled = false,
    placeholder = "No authentication",
    label = "Credential",
    description = "Select a credential for authentication, or leave empty for no auth.",
    showLabel = true,
    required = false,
    currentCredential,
}: CredentialSelectorProps) {
    const { user, loading: authLoading } = useAuth();
    const hasFetched = useRef(false);
    const [credentials, setCredentials] = useState<CredentialResponse[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);

    const fetchCredentials = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await listCredentialsApiV1CredentialsGet({});
            if (response.error) {
                setCredentials([]);
                setError(detailFromError(response.error, "Failed to load credentials"));
                return;
            }
            setCredentials(response.data ?? []);
        } catch (cause) {
            setCredentials([]);
            setError(detailFromError(cause, "Failed to load credentials"));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (authLoading || !user || hasFetched.current) return;
        hasFetched.current = true;
        void fetchCredentials();
    }, [authLoading, fetchCredentials, user]);

    const handleCredentialCreated = async (credential: CredentialResponse) => {
        await fetchCredentials();
        onChange(credential.uuid);
    };

    const currentCredentialMissing = Boolean(
        currentCredential
        && currentCredential.uuid === value
        && !credentials.some((credential) => credential.uuid === currentCredential.uuid),
    );
    const selectorLoading = authLoading || loading;
    const selectValue = value || (required ? undefined : "none");

    return (
        <div className="grid gap-2">
            {showLabel && (
                <>
                    <Label htmlFor="credential-selector">{label}</Label>
                    {description && (
                        <p id="credential-selector-description" className="text-xs text-muted-foreground">
                            {description}
                        </p>
                    )}
                </>
            )}
            <div className="flex gap-2">
                <Select
                    value={selectValue}
                    onValueChange={(selected) => onChange(selected === "none" ? "" : selected)}
                    disabled={disabled || selectorLoading || !user}
                    required={required}
                >
                    <SelectTrigger
                        id="credential-selector"
                        className="flex-1"
                        aria-describedby={showLabel && description ? "credential-selector-description" : undefined}
                        aria-busy={selectorLoading}
                    >
                        {selectorLoading ? (
                            <span className="flex items-center gap-2" role="status">
                                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                                Loading credentials…
                            </span>
                        ) : (
                            <SelectValue placeholder={placeholder} />
                        )}
                    </SelectTrigger>
                    <SelectContent>
                        {!required && <SelectItem value="none">{placeholder}</SelectItem>}
                        {currentCredentialMissing && currentCredential && (
                            <SelectItem value={currentCredential.uuid}>{currentCredential.label}</SelectItem>
                        )}
                        {credentials.map((credential) => (
                            <SelectItem key={credential.uuid} value={credential.uuid}>
                                {credential.name} ({credential.credential_type})
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    onClick={() => setIsAddDialogOpen(true)}
                    title="Add new credential"
                    aria-label="Add new credential"
                    disabled={disabled || selectorLoading || !user}
                >
                    <PlusIcon className="h-4 w-4" aria-hidden="true" />
                </Button>
            </div>

            {error && (
                <div role="alert" className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    <span>{error}</span>
                </div>
            )}

            {!error && credentials.length === 0 && !selectorLoading && user && !currentCredentialMissing && (
                <div className="rounded-md border bg-muted/20 p-3">
                    <p className="text-sm text-muted-foreground">
                        No credentials found for this organization. Use Add new credential to create one.
                    </p>
                </div>
            )}

            <CreateCredentialDialog
                open={isAddDialogOpen}
                onOpenChange={setIsAddDialogOpen}
                onCreated={handleCredentialCreated}
            />
        </div>
    );
}
