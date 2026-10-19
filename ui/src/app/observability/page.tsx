'use client';

import './components/viz.css';

import { Activity, AlertTriangle, Info, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { callSummaryApiV1ObservabilityCallsSummaryGet } from '@/client/sdk.gen';
import type { CallChannel } from '@/client/types.gen';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';

import { CallDetail } from './components/CallDetail';
import { CallsTable } from './components/CallsTable';
import { StatTile } from './components/StatTile';
import {
    CallRow,
    CallSummary,
    formatAgo,
    formatCount,
    formatDuration,
    formatSeconds,
    label,
    METRIC,
    MetricRow,
    pick,
} from './types';

const WINDOWS = [
    { value: '1', label: 'Last hour' },
    { value: '6', label: 'Last 6 hours' },
    { value: '24', label: 'Last 24 hours' },
    { value: '72', label: 'Last 3 days' },
    { value: '168', label: 'Last 7 days' },
];

/**
 * Channel options.
 *
 * The values are the channels the backend classifies to, not the transports a
 * call arrives on: a reader wants "phone calls", not a list naming every
 * carrier we have ever integrated.
 */
type ChannelFilter = CallChannel | 'all';

const CHANNELS: { value: ChannelFilter; label: string }[] = [
    { value: 'all', label: 'All channels' },
    { value: 'browser', label: 'Browser' },
    { value: 'telephony', label: 'Telephony' },
    { value: 'text_chat', label: 'Text chat' },
];

function sum(rows: MetricRow[], key: string): number {
    return rows.reduce((total, row) => total + (pick(row, key) ?? 0), 0);
}

export default function ObservabilityPage() {
    const { user, loading: authLoading } = useAuth();

    const [summary, setSummary] = useState<CallSummary | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [windowHours, setWindowHours] = useState('24');
    const [channel, setChannel] = useState<ChannelFilter>('all');
    const [selected, setSelected] = useState<CallRow | null>(null);
    const hasFetched = useRef(false);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await callSummaryApiV1ObservabilityCallsSummaryGet({
                query: {
                    window_hours: Number(windowHours),
                    ...(channel === 'all' ? {} : { channel }),
                },
            });
            // The generated client resolves rather than throws on 4xx/5xx, so
            // checking only `data` would render an error as an empty page.
            if (response.error) {
                setError(detailFromError(response.error, 'Could not load call telemetry'));
                return;
            }
            setSummary(response.data as unknown as CallSummary);
        } catch (err) {
            setError(
                err instanceof Error ? err.message : 'Could not reach the telemetry service',
            );
        } finally {
            setLoading(false);
        }
    }, [windowHours, channel]);

    // The auth interceptor attaches the token only once auth has loaded;
    // fetching earlier sends an unauthenticated request that quietly fails.
    useEffect(() => {
        if (authLoading || !user) return;
        if (!hasFetched.current) hasFetched.current = true;
        load();
    }, [authLoading, user, load]);

    const calls = summary?.calls ?? [];
    const failures = summary?.failures ?? [];
    const turns = summary?.turns;

    const totalFailures = sum(failures, METRIC.count);
    const affectedCalls = calls.filter((call) => call.failures > 0).length;
    const toolCalls = calls.reduce((total, call) => total + call.tool_calls, 0);
    const toolSeconds = calls.reduce((total, call) => total + (call.tool_seconds ?? 0), 0);
    const channelSplit = (summary?.channels ?? [])
        .map((row) => `${formatCount(pick(row, METRIC.count))} ${label(row, 'channel')?.toLowerCase()}`)
        .join(' · ');
    const notConfigured = summary !== null && !summary.configured;

    return (
        <div className="viz-root mx-auto max-w-[88rem] p-6">
            <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
                <div>
                    <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
                        <Activity className="h-5 w-5" />
                        Call Telemetry
                    </h1>
                    <p className="mt-1 text-sm text-muted-foreground">
                        {selected
                            ? 'What the agent did, turn by turn, and where each second went.'
                            : 'Every call, every layer. Browser and telephony side by side, down to the individual tool call.'}
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    <Select
                        value={channel}
                        onValueChange={(value) => {
                            setChannel(value as ChannelFilter);
                            setSelected(null);
                        }}
                    >
                        <SelectTrigger className="w-[150px]">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {CHANNELS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>

                    <Select
                        value={windowHours}
                        onValueChange={(value) => {
                            setWindowHours(value);
                            setSelected(null);
                        }}
                    >
                        <SelectTrigger className="w-[160px]">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {WINDOWS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>

                    <Button variant="outline" size="icon" onClick={load} disabled={loading}>
                        <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                    </Button>
                </div>
            </header>

            {error && (
                <Card className="mb-5 flex items-start gap-3 border-destructive/40 p-4">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                    <div className="text-sm">
                        <p className="font-medium">Could not load telemetry</p>
                        <p className="mt-1 text-muted-foreground">{error}</p>
                    </div>
                </Card>
            )}

            {/* An unconfigured backend and a quiet one both produce empty
                panels. Saying which stops anyone concluding the platform
                handled no calls. */}
            {notConfigured && (
                <Card
                    className="mb-5 flex items-start gap-3 p-4"
                    style={{ borderColor: 'var(--viz-warning)' }}
                >
                    <AlertTriangle
                        className="mt-0.5 h-4 w-4 shrink-0"
                        style={{ color: 'var(--viz-warning)' }}
                    />
                    <div className="text-sm">
                        <p className="font-medium">Telemetry is not configured</p>
                        <p className="mt-1 text-muted-foreground">{summary?.message}</p>
                    </div>
                </Card>
            )}

            {selected ? (
                <CallDetail call={selected} onBack={() => setSelected(null)} />
            ) : (
                <div className="space-y-5">
                    {/* Headline figures. First word leads because it is the one
                        number that decides whether a call feels alive; call
                        length is a fact about the conversation, not about our
                        speed, so it sits further along. */}
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                        <StatTile
                            label="Calls"
                            value={formatCount(calls.length)}
                            sub={channelSplit || undefined}
                            hint="Real calls only; health checks excluded"
                            loading={loading}
                        />
                        <StatTile
                            label="First word"
                            value={formatSeconds(turns?.p50_first_word ?? null)}
                            sub={`p95 ${formatSeconds(turns?.p95_first_word ?? null)} · p99 ${formatSeconds(turns?.p99_first_word ?? null)}`}
                            hint={
                                turns?.first_word_samples
                                    ? `Caller stops speaking to first audible word · n=${formatCount(turns.first_word_samples)}`
                                    : 'Caller stops speaking to first audible word'
                            }
                            loading={loading}
                            emphasis
                        />
                        <StatTile
                            label="Model TTFT"
                            value={formatSeconds(turns?.p50_first_token ?? null)}
                            sub={`p95 ${formatSeconds(turns?.p95_first_token ?? null)} · p99 ${formatSeconds(turns?.p99_first_token ?? null)}`}
                            hint={
                                turns?.first_token_samples
                                    ? `Prompt sent to first token · n=${formatCount(turns.first_token_samples)}`
                                    : 'Prompt sent to first token'
                            }
                            loading={loading}
                        />
                        <StatTile
                            label="Tool time"
                            value={formatSeconds(toolSeconds || null)}
                            sub={
                                toolCalls
                                    ? `${formatCount(toolCalls)} calls across every integration`
                                    : undefined
                            }
                            hint="Time spent waiting on integrations"
                            loading={loading}
                        />
                        <StatTile
                            label="Avg call length"
                            value={formatDuration(turns?.avg_conversation_latency ?? null)}
                            sub={
                                turns?.avg_turns_per_conversation
                                    ? `${turns.avg_turns_per_conversation.toFixed(1)} turns per call`
                                    : undefined
                            }
                            hint="Connect to hang up, not a latency"
                            loading={loading}
                        />
                        <StatTile
                            label="Issues"
                            value={formatCount(totalFailures)}
                            sub={
                                totalFailures > 0
                                    ? `${formatCount(affectedCalls)} calls affected`
                                    : 'nothing to look at'
                            }
                            hint="Errors plus calls that degraded quietly"
                            loading={loading}
                            tone={totalFailures > 0 ? 'critical' : 'good'}
                        />
                    </div>

                    {/* Failures first when there are any: the thing somebody
                        opened this page to find should not sit below the
                        healthy rows. */}
                    {failures.length > 0 && (
                        <Card className="p-5" style={{ borderColor: 'var(--viz-critical)' }}>
                            <h2 className="flex items-center gap-2 text-sm font-semibold">
                                <AlertTriangle
                                    className="h-4 w-4"
                                    style={{ color: 'var(--viz-critical)' }}
                                />
                                Needs attention
                            </h2>
                            <div className="mt-4 overflow-x-auto">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                                            <th className="pb-2 text-left font-medium">Layer</th>
                                            <th className="pb-2 text-left font-medium">Where</th>
                                            <th className="pb-2 text-left font-medium">
                                                What happened
                                            </th>
                                            <th className="pb-2 text-right font-medium">Times</th>
                                            <th className="pb-2 text-right font-medium">Calls</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {failures.map((row, index) => (
                                            <tr
                                                key={index}
                                                className="border-b border-border/50 last:border-0"
                                            >
                                                <td className="py-2">{label(row, 'layer')}</td>
                                                <td className="py-2">{label(row, 'source')}</td>
                                                <td className="py-2">{label(row, 'detail')}</td>
                                                <td className="py-2 text-right font-mono tabular-nums">
                                                    {formatCount(pick(row, METRIC.count))}
                                                </td>
                                                <td className="py-2 text-right font-mono tabular-nums">
                                                    {formatCount(pick(row, 'calls'))}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </Card>
                    )}

                    {/* A truncated scan reports real figures over part of the
                        window. Saying so is the difference between a partial
                        answer and a wrong one. */}
                    {summary?.truncated && (
                        <Card className="flex items-start gap-3 p-4">
                            <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                            <p className="text-sm text-muted-foreground">{summary.message}</p>
                        </Card>
                    )}

                    <CallsTable calls={calls} loading={loading} onSelect={setSelected} />
                </div>
            )}

            {summary && (
                <p className="pt-5 text-xs text-muted-foreground">
                    Updated {formatAgo(summary.generated_at)} · {summary.window_hours}h window ·
                    read live from Langfuse
                </p>
            )}
        </div>
    );
}
