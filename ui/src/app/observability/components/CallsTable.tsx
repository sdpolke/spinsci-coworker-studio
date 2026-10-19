'use client';

import { AlertTriangle, ChevronRight, Globe, MessageSquare, Phone } from 'lucide-react';
import { Fragment, useCallback, useState } from 'react';

import { callDetailApiV1ObservabilityCallsTraceIdGet } from '@/client/sdk.gen';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { detailFromError } from '@/lib/apiError';

import {
    CallDetail,
    CallRow,
    formatCount,
    formatDuration,
    formatSeconds,
    formatWhen,
} from '../types';
import { CallTimeline } from './CallTimeline';
import { TurnTable } from './TurnTable';

interface CallsTableProps {
    calls: CallRow[];
    loading: boolean;
}

/** The icon beside a channel. Always with the channel's name, never alone. */
function ChannelIcon({ channel }: { channel: string }) {
    const className = 'h-3.5 w-3.5 shrink-0 text-muted-foreground';
    if (channel === 'Telephony') return <Phone className={className} />;
    if (channel === 'Text chat') return <MessageSquare className={className} />;
    return <Globe className={className} />;
}

/**
 * Every call in the window, one row each, expandable into its own timeline.
 *
 * The view the dashboard was missing. Averages tell you the system is healthy;
 * they cannot tell you which call was not, and on a platform where a single bad
 * call is what someone is complaining about, that is the question being asked.
 *
 * Detail is fetched per row on expand rather than arriving with the summary. A
 * window of a hundred calls holds tens of thousands of spans, and sending them
 * all so that one row can be opened would make the page slower for everyone to
 * serve the one case.
 */
export function CallsTable({ calls, loading }: CallsTableProps) {
    const [openId, setOpenId] = useState<string | null>(null);
    const [details, setDetails] = useState<Record<string, CallDetail>>({});
    const [detailLoading, setDetailLoading] = useState<string | null>(null);
    const [detailError, setDetailError] = useState<string | null>(null);

    const toggle = useCallback(
        async (traceId: string) => {
            if (openId === traceId) {
                setOpenId(null);
                return;
            }
            setOpenId(traceId);
            setDetailError(null);
            if (details[traceId]) return;

            setDetailLoading(traceId);
            try {
                const response = await callDetailApiV1ObservabilityCallsTraceIdGet({
                    path: { trace_id: traceId },
                });
                // The generated client resolves rather than throws on 4xx/5xx.
                if (response.error) {
                    setDetailError(
                        detailFromError(response.error, 'Could not load this call'),
                    );
                    return;
                }
                setDetails((current) => ({
                    ...current,
                    [traceId]: response.data as unknown as CallDetail,
                }));
            } catch (err) {
                setDetailError(
                    err instanceof Error
                        ? err.message
                        : 'Could not reach the telemetry service',
                );
            } finally {
                setDetailLoading(null);
            }
        },
        [openId, details],
    );

    if (loading) {
        return (
            <Card className="p-5">
                <div className="space-y-2">
                    {[0, 1, 2, 3, 4].map((i) => (
                        <Skeleton key={i} className="h-9 w-full" />
                    ))}
                </div>
            </Card>
        );
    }

    if (calls.length === 0) {
        return (
            <Card className="p-8 text-center">
                <p className="text-sm text-muted-foreground">
                    No calls in this period. Health checks and seeded traces are excluded,
                    so a quiet window is genuinely quiet.
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
                            <Th className="w-8" />
                            <Th>Started</Th>
                            <Th>Channel</Th>
                            <Th>Workflow</Th>
                            <Th right>Length</Th>
                            <Th right>Turns</Th>
                            <Th
                                right
                                title="Average time from the caller finishing to the agent replying"
                            >
                                Avg turn
                            </Th>
                            <Th right title="Average wait before the model's first token">
                                TTFT
                            </Th>
                            <Th
                                right
                                title="Average wait before the first audio frame the caller hears"
                            >
                                First audio
                            </Th>
                            <Th right>Tools</Th>
                            <Th right>Issues</Th>
                        </tr>
                    </thead>
                    <tbody>
                        {calls.map((call) => {
                            const open = openId === call.trace_id;
                            return (
                                <Fragment key={call.trace_id}>
                                    <tr
                                        onClick={() => toggle(call.trace_id)}
                                        className={`cursor-pointer border-b border-border/50 transition-colors hover:bg-muted/50 ${
                                            open ? 'bg-muted/50' : ''
                                        }`}
                                    >
                                        <Td>
                                            <ChevronRight
                                                className={`h-4 w-4 text-muted-foreground transition-transform ${
                                                    open ? 'rotate-90' : ''
                                                }`}
                                            />
                                        </Td>
                                        <Td className="whitespace-nowrap">
                                            {formatWhen(call.started_at)}
                                        </Td>
                                        <Td>
                                            <span className="flex items-center gap-1.5 whitespace-nowrap">
                                                <ChannelIcon channel={call.channel} />
                                                {call.channel}
                                            </span>
                                        </Td>
                                        <Td
                                            className="max-w-[16rem] truncate"
                                            title={call.workflow ?? ''}
                                        >
                                            {call.workflow ?? '—'}
                                        </Td>
                                        <Td numeric right>
                                            {formatDuration(call.duration)}
                                        </Td>
                                        <Td numeric right>
                                            {formatCount(call.turns)}
                                        </Td>
                                        <Td numeric right>
                                            {formatSeconds(call.avg_turn_latency)}
                                        </Td>
                                        <Td numeric right>
                                            {formatSeconds(call.avg_first_token)}
                                        </Td>
                                        <Td numeric right>
                                            {formatSeconds(call.avg_first_audio)}
                                        </Td>
                                        <Td numeric right>
                                            {call.tool_calls === 0
                                                ? '—'
                                                : call.tool_calls}
                                        </Td>
                                        <Td right>
                                            {call.failures === 0 ? (
                                                <span className="text-muted-foreground">
                                                    —
                                                </span>
                                            ) : (
                                                // Status colour with its count beside
                                                // it, never colour alone.
                                                <span
                                                    className="inline-flex items-center gap-1 font-mono tabular-nums"
                                                    style={{
                                                        color: 'var(--viz-critical)',
                                                    }}
                                                >
                                                    <AlertTriangle className="h-3 w-3" />
                                                    {call.failures}
                                                </span>
                                            )}
                                        </Td>
                                    </tr>

                                    {open && (
                                        <tr className="border-b border-border/50 bg-muted/20">
                                            <td colSpan={12} className="px-4 py-4">
                                                {details[call.trace_id] && (
                                                    <TurnTable
                                                        turns={
                                                            details[call.trace_id]
                                                                .turn_rows
                                                        }
                                                        transcriptsHidden={
                                                            details[call.trace_id]
                                                                .transcripts_available
                                                        }
                                                    />
                                                )}
                                                {/* The span timeline stays available
                                                    for the cases the per-turn view
                                                    cannot explain, but folded away:
                                                    it is the debugging view, not the
                                                    reading one. */}
                                                <details className="mt-3">
                                                    <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
                                                        Raw span timeline
                                                    </summary>
                                                    <div className="mt-3">
                                                        <CallTimeline
                                                            detail={
                                                                details[call.trace_id] ??
                                                                null
                                                            }
                                                            loading={
                                                                detailLoading ===
                                                                call.trace_id
                                                            }
                                                            error={detailError}
                                                        />
                                                    </div>
                                                </details>
                                                <p className="mt-3 font-mono text-[10px] text-muted-foreground">
                                                    trace {call.trace_id}
                                                    {call.transport &&
                                                        ` · ${call.transport}`}
                                                    {call.session_id &&
                                                        ` · session ${call.session_id}`}
                                                    {call.tokens &&
                                                        ` · ${formatCount(call.tokens)} tokens`}
                                                </p>
                                            </td>
                                        </tr>
                                    )}
                                </Fragment>
                            );
                        })}
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
            className={`px-3 py-2 font-medium ${right ? 'text-right' : 'text-left'} ${className ?? ''}`}
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
