'use client';

import './components/viz.css';

import { Activity, AlertTriangle, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { callSummaryApiV1ObservabilityCallsSummaryGet } from '@/client/sdk.gen';
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

import { BarRow } from './components/BarRow';
import { MetricTable } from './components/MetricTable';
import { StatTile } from './components/StatTile';
import {
    CallSummary,
    formatCount,
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

const CHANNELS = [
    { value: 'all', label: 'All channels' },
    { value: 'browser', label: 'Browser' },
    { value: 'telephony', label: 'Telephony' },
];

/** Dimension columns arrive prefixed or bare depending on Langfuse version. */
const DIM = {
    channel: ['metadata.spinsci.call.channel', 'spinsci.call.channel'],
    server: ['metadata.spinsci.tool.server', 'spinsci.tool.server'],
    tool: ['metadata.spinsci.tool.name', 'spinsci.tool.name'],
    outcome: ['metadata.spinsci.tool.outcome', 'spinsci.tool.outcome'],
};

function sum(rows: MetricRow[], key: string): number {
    return rows.reduce((total, row) => total + (pick(row, key) ?? 0), 0);
}

/** Mean weighted by call count, so a busy row counts for more than a quiet one. */
function weightedAverage(rows: MetricRow[], valueKey: string): number | null {
    let weighted = 0;
    let weight = 0;
    for (const row of rows) {
        const value = pick(row, valueKey);
        const count = pick(row, METRIC.count) ?? 0;
        if (value !== null && count > 0) {
            weighted += value * count;
            weight += count;
        }
    }
    return weight > 0 ? weighted / weight : null;
}

function maxOf(rows: MetricRow[], key: string): number {
    return rows.reduce((best, row) => Math.max(best, pick(row, key) ?? 0), 0);
}

export default function ObservabilityPage() {
    const { user, loading: authLoading } = useAuth();

    const [summary, setSummary] = useState<CallSummary | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [windowHours, setWindowHours] = useState('24');
    const [channel, setChannel] = useState('all');
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

    const calls = summary?.call_volume ?? [];
    const stages = summary?.pipeline_stages ?? [];
    const tools = summary?.tools ?? [];
    const outcomes = summary?.tool_outcomes ?? [];
    const models = summary?.models ?? [];

    const totalCalls = sum(calls, METRIC.count);
    const totalToolCalls = sum(tools, METRIC.count);
    const avgCall = weightedAverage(calls, METRIC.latencyAvg);
    const worstTool = maxOf(tools, METRIC.latencyP95);

    const turns = summary?.turns;
    const layers = summary?.layers ?? [];
    const failures = summary?.failures ?? [];
    const totalFailures = failures.reduce(
        (total, row) => total + (pick(row, METRIC.count) ?? 0),
        0,
    );
    const layerMax = maxOf(layers, METRIC.latencyAvg);
    const stageMax = maxOf(stages, METRIC.latencyAvg);
    const toolMax = maxOf(tools, METRIC.latencyP95);
    const notConfigured = summary !== null && !summary.configured;

    return (
        <div className="viz-root mx-auto max-w-7xl space-y-5 p-6">
            <header className="flex flex-wrap items-start justify-between gap-4">
                <div>
                    <h1 className="flex items-center gap-2 text-xl font-semibold">
                        <Activity className="h-5 w-5" />
                        Call Telemetry
                    </h1>
                    <p className="mt-1 text-sm text-muted-foreground">
                        Latency and reliability for every layer of the voice pipeline, across
                        browser and telephony calls.
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    <Select value={channel} onValueChange={setChannel}>
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

                    <Select value={windowHours} onValueChange={setWindowHours}>
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
                <Card className="flex items-start gap-3 border-destructive/40 p-4">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                    <div className="text-sm">
                        <p className="font-medium">Could not load telemetry</p>
                        <p className="mt-1 text-muted-foreground">{error}</p>
                    </div>
                </Card>
            )}

            {/* An unconfigured backend and a quiet one both produce empty panels.
                Saying which stops anyone concluding the platform handled no calls. */}
            {notConfigured && (
                <Card
                    className="flex items-start gap-3 p-4"
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

            {/* Headline figures. A current value has nothing to compare along an
                axis, so these are tiles rather than a one-bar chart each. */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                <StatTile
                    label="Calls"
                    value={formatCount(totalCalls)}
                    hint="Completed sessions"
                    loading={loading}
                />
                <StatTile
                    label="Avg call"
                    value={formatSeconds(avgCall)}
                    hint="Connect to hang up"
                    loading={loading}
                />
                <StatTile
                    label="Tool calls"
                    value={formatCount(totalToolCalls)}
                    hint="Across every integration"
                    loading={loading}
                />
                <StatTile
                    label="Slowest tool p95"
                    value={formatSeconds(worstTool || null)}
                    hint="Worst integration"
                    loading={loading}
                    tone={worstTool > 3 ? 'warning' : 'default'}
                />
                <StatTile
                    label="Avg turn"
                    value={formatSeconds(turns?.avg_turn_latency ?? null)}
                    hint={
                        turns?.avg_turns_per_conversation
                            ? `${turns.avg_turns_per_conversation.toFixed(1)} turns per call`
                            : 'Caller stops speaking to reply'
                    }
                    loading={loading}
                />
                <StatTile
                    label="Failures"
                    value={totalFailures > 0 ? formatCount(totalFailures) : '0'}
                    hint="Errors and degraded calls"
                    loading={loading}
                    tone={totalFailures > 0 ? 'critical' : 'good'}
                />
            </div>

            {/* Failures first when there are any: the thing somebody opened this
                page to find should not be below five healthy panels. */}
            {failures.length > 0 && (
                <Card className="p-5" style={{ borderColor: 'var(--viz-critical)' }}>
                    <h2 className="flex items-center gap-2 text-sm font-semibold">
                        <AlertTriangle
                            className="h-4 w-4"
                            style={{ color: 'var(--viz-critical)' }}
                        />
                        Failures
                    </h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                        Anything that raised, plus tool calls that ended other than
                        successfully. A degraded call carries on, so these would otherwise
                        be invisible.
                    </p>
                    <div className="mt-4 overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-border">
                                    <th className="pb-2 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                        Layer
                                    </th>
                                    <th className="pb-2 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                        Where
                                    </th>
                                    <th className="pb-2 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                        What happened
                                    </th>
                                    <th className="pb-2 text-right text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                        Count
                                    </th>
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
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </Card>
            )}

            {/* The layer view answers "where did the time go" without the reader
                needing to know what any span is called. */}
            <Card className="p-5">
                <h2 className="text-sm font-semibold">Time by pipeline layer</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                    Speech in, the model, speech out, and tools. The bar is total time; the
                    marker is the p95. First byte is when the caller stops waiting &mdash;
                    total time includes producing the whole reply.
                </p>
                <div className="mt-4">
                    {layers.length === 0 ? (
                        <p className="py-6 text-sm text-muted-foreground">
                            No pipeline activity in this period.
                        </p>
                    ) : (
                        <>
                            <div className="grid grid-cols-[minmax(0,13rem)_1fr_auto] gap-3 pb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                                <span>Layer</span>
                                <span>Average &middot; p95 marked</span>
                                <span className="text-right">First byte</span>
                            </div>
                            {layers.map((row, index) => {
                                const avg = pick(row, METRIC.latencyAvg) ?? 0;
                                const p95 = pick(row, METRIC.latencyP95);
                                const ttfb = pick(row, METRIC.firstByteAvg);
                                const calls = pick(row, METRIC.count);
                                return (
                                    <div key={index} className="grid grid-cols-[1fr_auto] gap-3">
                                        <BarRow
                                            label={label(row, 'layer') ?? 'unknown'}
                                            sublabel={`${formatCount(calls)} calls`}
                                            value={avg}
                                            max={layerMax}
                                            display={formatSeconds(avg)}
                                            secondary={
                                                p95 === null
                                                    ? undefined
                                                    : {
                                                          value: p95,
                                                          display: formatSeconds(p95),
                                                          title: `p95 ${formatSeconds(p95)}`,
                                                      }
                                            }
                                        />
                                        <div className="flex items-center justify-end">
                                            <span className="font-mono text-sm tabular-nums">
                                                {ttfb === null ? '—' : formatSeconds(ttfb)}
                                            </span>
                                        </div>
                                    </div>
                                );
                            })}
                        </>
                    )}
                </div>
            </Card>

            <div className="grid gap-5 lg:grid-cols-2">
                <Card className="p-5">
                    <h2 className="text-sm font-semibold">Where the time goes</h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                        Average latency per pipeline stage, with the p95 marked. A stage whose
                        p95 sits far past its average is one that is occasionally slow.
                    </p>
                    <div className="mt-4">
                        {stages.length === 0 ? (
                            <p className="py-6 text-sm text-muted-foreground">
                                No pipeline activity in this period.
                            </p>
                        ) : (
                            stages.slice(0, 10).map((row, index) => {
                                const avg = pick(row, METRIC.latencyAvg) ?? 0;
                                const p95 = pick(row, METRIC.latencyP95);
                                return (
                                    <BarRow
                                        key={index}
                                        label={label(row, 'name') ?? 'unknown'}
                                        value={avg}
                                        max={stageMax}
                                        display={formatSeconds(avg)}
                                        secondary={
                                            p95 === null
                                                ? undefined
                                                : {
                                                      value: p95,
                                                      display: formatSeconds(p95),
                                                      title: `p95 ${formatSeconds(p95)}`,
                                                  }
                                        }
                                    />
                                );
                            })
                        )}
                    </div>
                </Card>

                <Card className="p-5">
                    <h2 className="text-sm font-semibold">Slowest integrations</h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                        Ranked by p95. Nothing here is hardcoded, so a tool server registered
                        today appears the first time it is used.
                    </p>
                    <div className="mt-4">
                        {tools.length === 0 ? (
                            <p className="py-6 text-sm text-muted-foreground">
                                No tool calls in this period.
                            </p>
                        ) : (
                            [...tools]
                                .sort(
                                    (a, b) =>
                                        (pick(b, METRIC.latencyP95) ?? 0) -
                                        (pick(a, METRIC.latencyP95) ?? 0),
                                )
                                .slice(0, 10)
                                .map((row, index) => {
                                    const p95 = pick(row, METRIC.latencyP95) ?? 0;
                                    const avg = pick(row, METRIC.latencyAvg);
                                    return (
                                        <BarRow
                                            key={index}
                                            label={label(row, ...DIM.tool) ?? 'unknown'}
                                            sublabel={label(row, ...DIM.server) ?? undefined}
                                            value={p95}
                                            max={toolMax}
                                            display={formatSeconds(p95)}
                                            secondary={
                                                avg === null
                                                    ? undefined
                                                    : {
                                                          value: avg,
                                                          display: formatSeconds(avg),
                                                          title: `avg ${formatSeconds(avg)}`,
                                                      }
                                            }
                                        />
                                    );
                                })
                        )}
                    </div>
                </Card>
            </div>

            <MetricTable<MetricRow>
                title="Every tool call"
                description="Volume and latency for each tool on each server. The full table, for when a bar chart has hidden the row you need."
                loading={loading}
                rows={tools}
                emptyMessage="No tool calls recorded in this period."
                columns={[
                    { header: 'Server', cell: (row) => label(row, ...DIM.server) },
                    { header: 'Tool', cell: (row) => label(row, ...DIM.tool) },
                    {
                        header: 'Calls',
                        align: 'right',
                        numeric: true,
                        cell: (row) => formatCount(pick(row, METRIC.count)),
                    },
                    {
                        header: 'Avg',
                        align: 'right',
                        numeric: true,
                        cell: (row) => formatSeconds(pick(row, METRIC.latencyAvg)),
                    },
                    {
                        header: 'p95',
                        align: 'right',
                        numeric: true,
                        cell: (row) => formatSeconds(pick(row, METRIC.latencyP95)),
                    },
                    {
                        header: 'Max',
                        align: 'right',
                        numeric: true,
                        cell: (row) => formatSeconds(pick(row, METRIC.latencyMax)),
                    },
                ]}
            />

            <div className="grid gap-5 lg:grid-cols-2">
                <MetricTable<MetricRow>
                    title="Tool outcomes"
                    description="Unavailable means the server could not be reached and the call carried on. Error means the tool itself failed. The two need different fixes."
                    loading={loading}
                    rows={outcomes}
                    emptyMessage="No tool calls recorded in this period."
                    columns={[
                        { header: 'Server', cell: (row) => label(row, ...DIM.server) },
                        {
                            header: 'Outcome',
                            // Status colour always travels with its label, so the
                            // state is never carried by colour alone.
                            cell: (row) => {
                                const outcome = label(row, ...DIM.outcome) ?? 'unknown';
                                const colour =
                                    outcome === 'ok'
                                        ? 'var(--viz-good)'
                                        : outcome === 'unavailable'
                                          ? 'var(--viz-warning)'
                                          : 'var(--viz-critical)';
                                return (
                                    <span className="inline-flex items-center gap-2">
                                        <span
                                            aria-hidden
                                            className="h-2 w-2 shrink-0 rounded-full"
                                            style={{ background: colour }}
                                        />
                                        {outcome}
                                    </span>
                                );
                            },
                        },
                        {
                            header: 'Count',
                            align: 'right',
                            numeric: true,
                            cell: (row) => formatCount(pick(row, METRIC.count)),
                        },
                    ]}
                />

                <MetricTable<MetricRow>
                    title="Models"
                    description="Latency and token usage per model. Swapping a model on the Models page changes these rows with no edit here."
                    loading={loading}
                    rows={models}
                    emptyMessage="No model activity recorded in this period."
                    columns={[
                        { header: 'Model', cell: (row) => label(row, 'providedModelName', 'name') },
                        {
                            header: 'Calls',
                            align: 'right',
                            numeric: true,
                            cell: (row) => formatCount(pick(row, METRIC.count)),
                        },
                        {
                            header: 'Avg',
                            align: 'right',
                            numeric: true,
                            cell: (row) => formatSeconds(pick(row, METRIC.latencyAvg)),
                        },
                        {
                            header: 'Tokens',
                            align: 'right',
                            numeric: true,
                            cell: (row) => formatCount(pick(row, METRIC.tokensSum)),
                        },
                    ]}
                />
            </div>

            <MetricTable<MetricRow>
                title="Calls by channel"
                description="Browser and telephony run the same pipeline and differ only by this tag, so these are directly comparable."
                loading={loading}
                rows={calls}
                columns={[
                    { header: 'Channel', cell: (row) => label(row, ...DIM.channel) ?? 'unknown' },
                    {
                        header: 'Calls',
                        align: 'right',
                        numeric: true,
                        cell: (row) => formatCount(pick(row, METRIC.count)),
                    },
                    {
                        header: 'Avg duration',
                        align: 'right',
                        numeric: true,
                        cell: (row) => formatSeconds(pick(row, METRIC.latencyAvg)),
                    },
                    {
                        header: 'p95',
                        align: 'right',
                        numeric: true,
                        cell: (row) => formatSeconds(pick(row, METRIC.latencyP95)),
                    },
                ]}
            />

            {summary && (
                <p className="text-xs text-muted-foreground">
                    Last updated {new Date(summary.generated_at).toLocaleString()} · window{' '}
                    {summary.window_hours}h
                </p>
            )}
        </div>
    );
}
