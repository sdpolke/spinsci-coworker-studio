'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { AgentBuilderChat } from '@/app/workflow/create/components/AgentBuilderChat';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useWorkflowGeneration } from '@/hooks/useWorkflowGeneration';
import { useAuth } from '@/lib/auth';

export default function CreateWorkflowPage() {
    const router = useRouter();
    const { user, getAccessToken } = useAuth();
    const [showSuccessModal, setShowSuccessModal] = useState(false);
    const [workflowId, setWorkflowId] = useState<string | null>(null);

    const [callType, setCallType] = useState<'inbound' | 'outbound'>('inbound');
    const [useCase, setUseCase] = useState('');
    const [activityDescription, setActivityDescription] = useState('');

    const {
        phase,
        session,
        draft,
        setDraft,
        error,
        isBusy,
        startSession,
        sendMessage,
        generateWorkflow,
    } = useWorkflowGeneration({ getAccessToken });

    const handleStart = async () => {
        if (!useCase.trim() || !activityDescription.trim()) {
            return;
        }
        if (!user) {
            return;
        }

        await startSession({
            call_type: callType,
            use_case: useCase.trim(),
            activity_description: activityDescription.trim(),
        });
    };

    const handleGenerate = async () => {
        const id = await generateWorkflow();
        if (!id) return;
        setWorkflowId(String(id));
        setShowSuccessModal(true);
    };

    const handleModalContinue = () => {
        if (!workflowId) return;
        router.push(`/workflow/${workflowId}?onboarding=web_call`);
    };

    const showBriefForm = phase === 'brief';
    const showChat = phase !== 'brief';

    return (
        <div className="min-h-screen">
            <div className="container mx-auto px-4 py-8 max-w-2xl">
                <div className="mb-6">
                    <h1 className="text-3xl font-bold mb-2">Create Voice Agent</h1>
                    <p className="text-muted-foreground">
                        Describe your use case, answer a few clarifying questions, then generate a workflow.
                    </p>
                </div>

                {showBriefForm ? (
                    <Card>
                        <CardHeader>
                            <CardTitle>Agent Details</CardTitle>
                            <CardDescription>
                                Start with a brief description of what your voice agent should do.
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-6">
                            <div className="space-y-2">
                                <Label htmlFor="call-type">Call Type</Label>
                                <Select
                                    value={callType}
                                    onValueChange={(value) => setCallType(value as 'inbound' | 'outbound')}
                                >
                                    <SelectTrigger id="call-type">
                                        <SelectValue placeholder="Select type" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="inbound">
                                            Inbound (Users call AI)
                                        </SelectItem>
                                        <SelectItem value="outbound">
                                            Outbound (AI calls users)
                                        </SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>

                            <div className="space-y-2">
                                <Label htmlFor="use-case">Use Case</Label>
                                <Input
                                    id="use-case"
                                    placeholder="e.g., Lead Qualification, HR Screening, Customer Support"
                                    value={useCase}
                                    onChange={(event) => setUseCase(event.target.value)}
                                />
                            </div>

                            <div className="space-y-2">
                                <Label htmlFor="activity-description">Activity Description</Label>
                                <Textarea
                                    id="activity-description"
                                    placeholder="Describe what the voice agent should accomplish on the call."
                                    value={activityDescription}
                                    onChange={(event) => setActivityDescription(event.target.value)}
                                    className="min-h-[100px]"
                                />
                            </div>

                            {error ? <p className="text-sm text-red-500">{error}</p> : null}

                            <Button
                                type="button"
                                className="w-full"
                                disabled={isBusy || !useCase.trim() || !activityDescription.trim() || !user}
                                onClick={() => void handleStart()}
                            >
                                {isBusy ? 'Starting...' : 'Continue to clarifications'}
                            </Button>
                        </CardContent>
                    </Card>
                ) : (
                    <Card>
                        <CardHeader>
                            <CardTitle>Agent Builder</CardTitle>
                            <CardDescription>
                                {phase === 'ready'
                                    ? 'Review the plan, then generate your workflow.'
                                    : 'Answer the assistant’s questions to refine the workflow plan.'}
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <AgentBuilderChat
                                messages={session?.messages ?? []}
                                summary={session?.summary ?? null}
                                plan={session?.plan ?? null}
                                draft={draft}
                                isBusy={isBusy}
                                showComposer={phase === 'clarifying'}
                                showGenerate={phase === 'ready'}
                                onDraftChange={setDraft}
                                onSend={() => void sendMessage()}
                                onGenerate={() => void handleGenerate()}
                            />

                            {error ? <p className="text-sm text-red-500">{error}</p> : null}
                        </CardContent>
                    </Card>
                )}
            </div>

            {isBusy && phase === 'generating' ? (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
                    <Card className="w-full max-w-md p-8">
                        <div className="flex flex-col items-center space-y-6">
                            <div className="relative">
                                <div className="w-16 h-16 border-4 border-muted rounded-full" />
                                <div className="absolute top-0 left-0 w-16 h-16 border-4 border-transparent border-t-primary rounded-full animate-spin" />
                            </div>
                            <div className="text-center space-y-2">
                                <h3 className="text-lg font-semibold">Generating Your Workflow</h3>
                                <p className="text-sm text-muted-foreground max-w-xs">
                                    Compiling and validating your voice agent workflow...
                                </p>
                            </div>
                        </div>
                    </Card>
                </div>
            ) : null}

            <Dialog open={showSuccessModal} onOpenChange={setShowSuccessModal}>
                <DialogContent className="sm:max-w-lg">
                    <DialogHeader>
                        <DialogTitle>Workflow Created Successfully</DialogTitle>
                        <DialogDescription asChild>
                            <div className="mt-4 space-y-3">
                                <p>Your workflow has been generated and saved.</p>
                                <p>Open the editor to review nodes, test the agent, and refine prompts.</p>
                            </div>
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter className="mt-6">
                        <Button type="button" onClick={handleModalContinue} className="w-full">
                            Open and Test Agent
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
