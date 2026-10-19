'use client';

import { AlertTriangle, ChevronRight, Globe, MessageSquare, Phone } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

import { CallRow, formatCount, formatDuration, formatSeconds, formatWhen } from '../types';

interface CallsTableProps {
    calls: CallRow[];
    loading: boolean;
    onSelect: (call: CallRow) => void;
}

/** The icon beside a channel. Always with the channel's name, never alone. */
function ChannelIcon({ channel }: { channel: string }) {
    const className = 'h-3.5 w-3.5 shrink-0 text-muted-foreground';
    if (channel === 'Telephony') return <Phone className={className} />;
    if (channel === 'Text chat') return <MessageSquare className={className} />;
    return <Globe className={className} />;
}

/**
 * Every call in the window, one row each.
 *
 * Averages say the system is healthy; they cannot say which call was not, and
 * on a platform where one bad call is what somebody is complaining about, that
 * is the question being asked.
 *
 * Channel leads, because browser and telephony run the same pipeline and the
 * first thing worth knowing about a slow call is which one it arrived on.
 * Selecting a row opens the call rather than expanding it in place: the
 * per-turn table is wide, and a list that unfolds into one stops being a list.
 */
export function CallsTable({ calls, loading, onSelect }: CallsTableProps) {
    if (loading) {
        return (
            <Card className="space-y-2 p-5">
                {[0, 1, 2, 3, 4].map((index) => (
                    <Skeleton key={index} className="h-9 w-full" />
                ))}
            </Card>
        );
    }

    if (calls.length === 0) {
        return (
            <Card className="p-8 text-center">
                <p className="text-sm text-muted-foreground">
                    No calls in this period. Health checks and seeded traces are excluded, so a
                    quiet window is genuinely quiet.
                </p>
            </Card>
        );
    }

    return (
        <Card className="overflow-hidden p-0">
            <div className="overflow-x-auto">
                <table className="w-full min-w-[56rem] text-sm">
                    <thead>
                        <tr className="border-b border-border bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                            <Th>Channel</Th>
                            <Th>When</Th>
                            <Th>Workflow</Th>
                            <Th right>Length</Th>
                            <Th right>Turns</Th>
                            <Th right title="Prompt sent to the model's first token, median over the call">
                                TTFT
                            </Th>
                            <Th right title="Caller stops speaking to the agent's first audible word">
                                First word
                            </Th>
                            <Th right title="Total time this call spent waiting on integrations">
                                Tool time
                            </Th>
                            <Th right>TTS</Th>
                            <Th right>Issues</Th>
                            <Th className="w-8" />
                        </tr>
                    </thead>
                    <tbody>
                        {calls.map((call) => (
                            <tr
                                key={call.trace_id}
                                onClick={() => onSelect(call)}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter' || event.key === ' ') {
                                        event.preventDefault();
                                        onSelect(call);
                                    }
                                }}
                                tabIndex={0}
                                className="cursor-pointer border-b border-border/50 transition-colors last:border-0 hover:bg-muted/50"
                            >
                                <Td>
                                    <span className="flex items-center gap-1.5 whitespace-nowrap">
                                        <ChannelIcon channel={call.channel} />
                                        {call.channel}
                                    </span>
                                </Td>
                                <Td className="whitespace-nowrap text-muted-foreground">
                                    {formatWhen(call.started_at)}
                                </Td>
                                <Td className="max-w-[16rem] truncate" title={call.workflow ?? ''}>
                                    {call.workflow ?? '—'}
                                </Td>
                                <Td numeric right>
                                    {formatDuration(call.duration)}
                                </Td>
                                <Td numeric right>
                                    {formatCount(call.turns)}
                                </Td>
                                <Td numeric right>
                                    {formatSeconds(call.median_ttft)}
                                </Td>
                                <Td numeric right>
                                    {formatSeconds(call.median_first_word)}
                                </Td>
                                <Td numeric right>
                                    {call.tool_calls === 0 ? (
                                        <span className="text-muted-foreground">—</span>
                                    ) : (
                                        <>
                                            {formatSeconds(call.tool_seconds)}
                                            <span className="ml-1 font-sans text-[11px] text-muted-foreground">
                                                · {call.tool_calls}
                                            </span>
                                        </>
                                    )}
                                </Td>
                                <Td numeric right className="text-muted-foreground">
                                    {call.tts_characters === null
                                        ? '—'
                                        : formatCount(call.tts_characters)}
                                </Td>
                                <Td right>
                                    {call.failures === 0 ? (
                                        <span className="text-muted-foreground">—</span>
                                    ) : (
                                        // Status colour with its count beside it, never
                                        // colour alone.
                                        <span
                                            className="inline-flex items-center gap-1 font-mono tabular-nums"
                                            style={{ color: 'var(--viz-critical)' }}
                                        >
                                            <AlertTriangle className="h-3 w-3" />
                                            {call.failures}
                                        </span>
                                    )}
                                </Td>
                                <Td>
                                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                                </Td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </Card>
    );
}

function Th({
    children,
    right,
    className,
    title,
}: {
    children?: React.ReactNode;
    right?: boolean;
    className?: string;
    title?: string;
}) {
    return (
        <th
            title={title}
            className={`px-3 py-2 font-medium ${right ? 'text-right' : 'text-left'} ${
                className ?? ''
            }`}
        >
            {children}
        </th>
    );
}

function Td({
    children,
    right,
    numeric,
    className,
    title,
}: {
    children?: React.ReactNode;
    right?: boolean;
    numeric?: boolean;
    className?: string;
    title?: string;
}) {
    return (
        <td
            title={title}
            className={`px-3 py-2 ${right ? 'text-right' : 'text-left'} ${
                numeric ? 'font-mono text-[13px] tabular-nums' : ''
            } ${className ?? ''}`}
        >
            {children}
        </td>
    );
}
