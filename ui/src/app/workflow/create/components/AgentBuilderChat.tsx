'use client';

import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import type { GenerationMessageResponse } from '@/client/types.gen';
import { cn } from '@/lib/utils';

interface AgentBuilderChatProps {
    messages: GenerationMessageResponse[];
    summary: string | null;
    plan: string | null;
    draft: string;
    isBusy: boolean;
    showComposer: boolean;
    showGenerate: boolean;
    onDraftChange: (value: string) => void;
    onSend: () => void;
    onGenerate: () => void;
}

export function AgentBuilderChat({
    messages,
    summary,
    plan,
    draft,
    isBusy,
    showComposer,
    showGenerate,
    onDraftChange,
    onSend,
    onGenerate,
}: AgentBuilderChatProps) {
    return (
        <div className="space-y-4">
            <div className="rounded-lg border bg-muted/20 p-4 space-y-3 max-h-[420px] overflow-y-auto">
                {messages.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                        Answer a few questions so we can shape your workflow.
                    </p>
                ) : (
                    messages.map((message, index) => (
                        <div
                            key={`${message.created_at}-${index}`}
                            className={cn(
                                'rounded-lg px-3 py-2 text-sm max-w-[90%]',
                                message.role === 'assistant'
                                    ? 'bg-background border text-foreground'
                                    : 'bg-primary text-primary-foreground ml-auto',
                            )}
                        >
                            {message.content}
                        </div>
                    ))
                )}

                {isBusy && showComposer ? (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Thinking...
                    </div>
                ) : null}
            </div>

            {summary ? (
                <div className="rounded-lg border p-4 space-y-2">
                    <h3 className="font-medium">Planned workflow</h3>
                    <p className="text-sm text-muted-foreground">{summary}</p>
                    {plan ? (
                        <pre className="whitespace-pre-wrap text-xs text-muted-foreground bg-muted/30 rounded p-3">
                            {plan}
                        </pre>
                    ) : null}
                </div>
            ) : null}

            {showComposer ? (
                <div className="relative">
                    <Textarea
                        value={draft}
                        onChange={(event) => onDraftChange(event.target.value)}
                        placeholder="Type your answer..."
                        rows={2}
                        className="min-h-11 resize-none pr-24"
                        disabled={isBusy}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter' && !event.shiftKey) {
                                event.preventDefault();
                                if (!isBusy && draft.trim()) {
                                    onSend();
                                }
                            }
                        }}
                    />
                    <Button
                        type="button"
                        size="sm"
                        className="absolute bottom-2 right-2"
                        disabled={isBusy || !draft.trim()}
                        onClick={onSend}
                    >
                        {isBusy ? 'Sending...' : 'Send'}
                    </Button>
                </div>
            ) : null}

            {showGenerate ? (
                <Button
                    type="button"
                    className="w-full"
                    disabled={isBusy}
                    onClick={onGenerate}
                >
                    {isBusy ? 'Generating workflow...' : 'Generate workflow'}
                </Button>
            ) : null}
        </div>
    );
}
