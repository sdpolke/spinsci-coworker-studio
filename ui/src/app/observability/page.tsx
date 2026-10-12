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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { detailFromError } from '@/lib/apiError';
import { useAuth } from '@/lib/auth';

import { BarRow } from './components/BarRow';
import { CallsTable } from './components/CallsTable';
import { ChannelSplit } from './components/ChannelSplit';
import { MetricTable } from './components/MetricTable';
import { SectionHeading } from './components/SectionHeading';
import { StatTile } from './components/StatTile';
import {
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

/** Dimension columns, named by the key the backend emits. */
const DIM = {
    server: ['spinsci.tool.server'],
    tool: ['spinsci.tool.name'],
    outcome: ['spinsci.tool.outcome'],
};

function sum(rows: MetricRow[], key: string): number {
    return rows.reduce((total, row) => total + (pick(row, key) ?? 0), 0);
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
    const [channel, setChannel] = useState<ChannelFilter>('all');
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
                setError(
                    detailFromError(response.error, 'Could not load call telemetry'),
                );
                return;
            }
            setSummary(response.data as unknown as CallSummary);
        } catch (err) {
            setError(
                err instanceof Error
                    ? err.message
                    : 'Could not reach the telemetry service',
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

    const channels = summary?.channels ?? [];
    const calls = summary?.calls ?? [];
    const workflows = summary?.call_volume ?? [];
    const stages = summary?.pipeline_stages ?? [];
    const layers = summary?.layers ?? [];
    const tools = summary?.tools ?? [];
    const outcomes = summary?.tool_outcomes ?? [];
    const models = summary?.models ?? [];
    const failures = summary?.failures ?? [];
    const turns = summary?.turns;

    const totalCalls = calls.length;
    const totalToolCalls = sum(tools, METRIC.count);
    const totalFailures = sum(failures, METRIC.count);
    // Counted from the call rows rather than by summing the failure table's own
    // per-row call counts: a call that hit two different problems appears in two
    // rows there, and adding them would report more affected calls than exist.
    const affectedCalls = calls.filter((call) => call.failures > 0).length;
    const layerMax = maxOf(layers, METRIC.latencyAvg);
    const stageMax = maxOf(stages, METRIC.latencyAvg);
    const toolMax = maxOf(tools, METRIC.latencyP95);
    const notConfigured = summary !== null && !summary.configured;

    return (
        <div className="viz-root mx-auto max-w-[88rem] p-6">
            {/* Sticky, because every tab below is long enough to scroll the
                filters off screen, and a figure read without knowing which
                window it covers is a figure read wrong. */}
            <header className="sticky top-0 z-10 -mx-6 mb-6 border-b border-border bg-background/95 px-6 pb-4 pt-1 backdrop-blur">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
                            <Activity className="h-5 w-5" />
                            Call Telemetry
                        </h1>
                        <p className="mt-1 text-sm text-muted-foreground">
                            Every call, every layer. Browser and telephony side by side,
                            down to the individual tool call.
                        </p>
                    </div>

                    <div className="flex items-center gap-2">
                        <Select
                            value={channel}
                            onValueChange={(value) => setChannel(value as ChannelFilter)}
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

                        <Button
                            variant="outline"
                            size="icon"
                            onClick={load}
                            disabled={loading}
                        >
                            <RefreshCw
                                className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`}
                            />
                        </Button>
                    </div>
                </div>
            </header>

            <div className="space-y-6">
                {error && (
                    <Card className="flex items-start gap-3 border-destructive/40 p-4">
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
                        className="flex items-start gap-3 p-4"
                        style={{ borderColor: 'var(--viz-warning)' }}
                    >
                        <AlertTriangle
                            className="mt-0.5 h-4 w-4 shrink-0"
                            style={{ color: 'var(--viz-warning)' }}
                        />
                        <div className="text-sm">
                            <p className="font-medium">Telemetry is not configured</p>
                            <p className="mt-1 text-muted-foreground">
                                {summary?.message}
                            </p>
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

                {/* Headline figures. First token leads because it is the one
                    number that decides whether a call feels alive; call length
                    is a fact about the conversation, not about our speed, so it
                    sits further along. */}
                <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                    <StatTile
                        label="Calls"
                        value={formatCount(totalCalls)}
                        sub={
                            turns?.turns ? `${formatCount(turns.turns)} turns` : undefined
                        }
                        hint="Real calls only; health checks excluded"
                        loading={loading}
                    />
                    <StatTile
                        label="First token"
                        value={formatSeconds(turns?.avg_first_token ?? null)}
                        sub={`p95 ${formatSeconds(turns?.p95_first_token ?? null)}`}
                        hint="How long before the agent starts replying"
                        loading={loading}
                        emphasis
                    />
                    <StatTile
                        label="Avg turn"
                        value={formatSeconds(turns?.avg_turn_latency ?? null)}
                        sub={`p95 ${formatSeconds(turns?.p95_turn_latency ?? null)}`}
                        hint="Caller stops speaking to full reply"
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
                        label="Tool calls"
                        value={formatCount(totalToolCalls)}
                        sub={
                            tools.length > 0
                                ? `${tools.length} distinct tools`
                                : undefined
                        }
                        hint="Across every integration"
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

                {/* Failures first when there are any: the thing somebody opened
                    this page to find should not be below five healthy panels. */}
                {failures.length > 0 && (
                    <Card className="p-5" style={{ borderColor: 'var(--viz-critical)' }}>
                        <h2 className="flex items-center gap-2 text-sm font-semibold">
                            <AlertTriangle
                                className="h-4 w-4"
                                style={{ color: 'var(--viz-critical)' }}
                            />
                            Needs attention
                        </h2>
                        <p className="mt-1 text-xs text-muted-foreground">
                            Anything that raised, plus tool calls that ended other than
                            successfully. A degraded call carries on, so these would
                            otherwise be invisible.
                        </p>
                        <div className="mt-4 overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                                        <th className="pb-2 text-left font-medium">
                                            Layer
                                        </th>
                                        <th className="pb-2 text-left font-medium">
                                            Where
                                        </th>
                                        <th className="pb-2 text-left font-medium">
                                            What happened
                                        </th>
                                        <th className="pb-2 text-right font-medium">
                                            Times
                                        </th>
                                        <th className="pb-2 text-right font-medium">
                                            Calls
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {failures.map((row, index) => (
                                        <tr
                                            key={index}
                                            className="border-b border-border/50 last:border-0"
                                        >
                                            <td className="py-2">
                                                {label(row, 'layer')}
                                            </td>
                                            <td className="py-2">
                                                {label(row, 'source')}
                                            </td>
                                            <td className="py-2">
                                                {label(row, 'detail')}
                                            </td>
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

                {/* Four sections rather than nine stacked cards. The page had no
                    structure because every panel claimed equal importance;
                    separating "which call" from "which layer" from "which
                    integration" is how a reader gets to one of them. */}
                <Tabs defaultValue="overview">
                    <TabsList>
                        <TabsTrigger value="overview">Overview</TabsTrigger>
                        <TabsTrigger value="calls">
                            Calls
                            {totalCalls > 0 && (
                                <span className="ml-1.5 font-mono text-[11px] text-muted-foreground">
                                    {totalCalls}
                                </span>
                            )}
                        </TabsTrigger>
                        <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
                        <TabsTrigger value="integrations">
                            Integrations
                            {tools.length > 0 && (
                                <span className="ml-1.5 font-mono text-[11px] text-muted-foreground">
                                    {tools.length}
                                </span>
                            )}
                        </TabsTrigger>
                    </TabsList>

                    <TabsContent value="overview" className="mt-5 space-y-5">
                        <SectionHeading
                            title="Browser and telephony"
                            description="The same pipeline, reached two different ways. A gap between them in first token or turn latency is a network or codec problem, not a model one."
                        />
                        <ChannelSplit channels={channels} loading={loading} />

                        <SectionHeading
                            title="Where the time goes"
                            description="Speech in, the model, speech out, tools. The bar is total time and the marker is the p95; first byte is the point the caller stops waiting."
                        />
                        <Card className="p-5">
                            {layers.length === 0 ? (
                                <p className="py-6 text-sm text-muted-foreground">
                                    No pipeline activity in this period.
                                </p>
                            ) : (
                                <>
                                    <div className="grid grid-cols-[minmax(0,13rem)_1fr_auto] gap-3 pb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                                        <span>Layer</span>
                                        <span>Average &middot; p95 marked</span>
                                        <span className="text-right">First byte</span>
                                    </div>
                                    {layers.map((row, index) => {
                                        const avg = pick(row, METRIC.latencyAvg) ?? 0;
                                        const p95 = pick(row, METRIC.latencyP95);
                                        const ttfb = pick(row, METRIC.firstByteAvg);
                                        const count = pick(row, METRIC.count);
                                        return (
                                            <div
                                                key={index}
                                                className="grid grid-cols-[1fr_auto] gap-3"
                                            >
                                                <BarRow
                                                    label={
                                                        label(row, 'layer') ?? 'unknown'
                                                    }
                                                    sublabel={`${formatCount(count)} spans`}
                                                    value={avg}
                                                    max={layerMax}
                                                    display={formatSeconds(avg)}
                                                    secondary={
                                                        p95 === null
                                                            ? undefined
                                                            : {
                                                                  value: p95,
                                                                  display:
                                                                      formatSeconds(p95),
                                                                  title: `p95 ${formatSeconds(p95)}`,
                                                              }
                                                    }
                                                />
                                                <div className="flex w-20 items-center justify-end">
                                                    <span className="font-mono text-sm tabular-nums">
                                                        {ttfb === null
                                                            ? '—'
                                                            : formatSeconds(ttfb)}
                                                    </span>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </>
                            )}
                        </Card>

                        <SectionHeading
                            title="Workflows"
                            description="Which agent ran, how often, and how long its calls lasted."
                        />
                        <MetricTable<MetricRow>
                            title="Calls by workflow"
                            description="Grouped by the agent that answered. Call length is the whole conversation, not a response time."
                            loading={loading}
                            rows={workflows}
                            columns={[
                                {
                                    header: 'Workflow',
                                    cell: (row) => label(row, 'workflow'),
                                },
                                {
                                    header: 'Calls',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) => formatCount(pick(row, METRIC.count)),
                                },
                                {
                                    header: 'Avg length',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatDuration(pick(row, METRIC.latencyAvg)),
                                },
                                {
                                    header: 'Longest',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatDuration(pick(row, METRIC.latencyMax)),
                                },
                                {
                                    header: 'First token',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.firstByteAvg)),
                                },
                            ]}
                        />
                    </TabsContent>

                    <TabsContent value="calls" className="mt-5 space-y-5">
                        <SectionHeading
                            title="Every call"
                            description="One row per call. Open a row for its timeline: what the agent did, in order, with the time each step took."
                            aside={
                                totalCalls > 0
                                    ? `${formatCount(totalCalls)} calls`
                                    : undefined
                            }
                        />
                        <CallsTable calls={calls} loading={loading} />
                    </TabsContent>

                    <TabsContent value="pipeline" className="mt-5 space-y-5">
                        <SectionHeading
                            title="Layers"
                            description="Total time and time to first byte for each layer of the pipeline, with the tail beside the average."
                        />
                        <MetricTable<MetricRow>
                            title="Layer latency"
                            description="First byte is when output starts arriving. The gap between it and the average is time spent finishing a reply the caller is already hearing."
                            loading={loading}
                            rows={layers}
                            columns={[
                                { header: 'Layer', cell: (row) => label(row, 'layer') },
                                {
                                    header: 'Spans',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) => formatCount(pick(row, METRIC.count)),
                                },
                                {
                                    header: 'Avg',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.latencyAvg)),
                                },
                                {
                                    header: 'p95',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.latencyP95)),
                                },
                                {
                                    header: 'Max',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.latencyMax)),
                                },
                                {
                                    header: 'First byte',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.firstByteAvg)),
                                },
                                {
                                    header: 'First byte p95',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.firstByteP95)),
                                },
                            ]}
                        />

                        <SectionHeading
                            title="Stages"
                            description="The same time, broken out by the span the pipeline actually emitted, so a single slow workflow node is findable."
                        />
                        <Card className="p-5">
                            {stages.length === 0 ? (
                                <p className="py-6 text-sm text-muted-foreground">
                                    No pipeline activity in this period.
                                </p>
                            ) : (
                                stages.slice(0, 14).map((row, index) => {
                                    const avg = pick(row, METRIC.latencyAvg) ?? 0;
                                    const p95 = pick(row, METRIC.latencyP95);
                                    return (
                                        <BarRow
                                            key={index}
                                            label={label(row, 'name') ?? 'unknown'}
                                            sublabel={`${formatCount(pick(row, METRIC.count))} spans`}
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
                        </Card>

                        <SectionHeading
                            title="Models"
                            description="Latency, time to first token and token usage per model. Swapping a model on the Models page changes these rows with no edit here."
                        />
                        <MetricTable<MetricRow>
                            title="Model performance"
                            description="Covers the speech models too: transcription and synthesis are generations like any other, and their first-byte times are what the caller hears."
                            loading={loading}
                            rows={models}
                            emptyMessage="No model activity recorded in this period."
                            columns={[
                                {
                                    header: 'Model',
                                    cell: (row) =>
                                        label(row, 'providedModelName', 'name'),
                                },
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
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.latencyAvg)),
                                },
                                {
                                    header: 'p95',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.latencyP95)),
                                },
                                {
                                    header: 'First token',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.firstByteAvg)),
                                },
                                {
                                    header: 'First token p95',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.firstByteP95)),
                                },
                                {
                                    header: 'Tokens',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatCount(pick(row, METRIC.tokensSum)),
                                },
                            ]}
                        />
                    </TabsContent>

                    <TabsContent value="integrations" className="mt-5 space-y-5">
                        <SectionHeading
                            title="Slowest integrations"
                            description="Ranked by p95. Nothing here is hardcoded, so a tool server registered today appears the first time it is used."
                        />
                        <Card className="p-5">
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
                                    .slice(0, 12)
                                    .map((row, index) => {
                                        const p95 = pick(row, METRIC.latencyP95) ?? 0;
                                        const avg = pick(row, METRIC.latencyAvg);
                                        return (
                                            <BarRow
                                                key={index}
                                                label={
                                                    label(row, ...DIM.tool) ?? 'unknown'
                                                }
                                                sublabel={
                                                    label(row, ...DIM.server) ?? undefined
                                                }
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
                        </Card>

                        <SectionHeading
                            title="Every tool call"
                            description="The full table, for when a bar chart has hidden the row you need."
                        />
                        <MetricTable<MetricRow>
                            title="Tool latency"
                            description="Volume and latency for each tool on each server, measured on a monotonic clock inside the call rather than from span timestamps."
                            loading={loading}
                            rows={tools}
                            emptyMessage="No tool calls recorded in this period."
                            columns={[
                                {
                                    header: 'Server',
                                    cell: (row) => label(row, ...DIM.server),
                                },
                                {
                                    header: 'Tool',
                                    cell: (row) => label(row, ...DIM.tool),
                                },
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
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.latencyAvg)),
                                },
                                {
                                    header: 'p95',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.latencyP95)),
                                },
                                {
                                    header: 'Max',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.latencyMax)),
                                },
                                {
                                    header: 'Failed',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) => {
                                        const failed = pick(row, METRIC.failures) ?? 0;
                                        if (failed === 0)
                                            return (
                                                <span className="text-muted-foreground">
                                                    —
                                                </span>
                                            );
                                        return (
                                            <span
                                                style={{ color: 'var(--viz-critical)' }}
                                            >
                                                {formatCount(failed)}
                                            </span>
                                        );
                                    },
                                },
                            ]}
                        />

                        <SectionHeading
                            title="Outcomes"
                            description="How tool calls ended, which is not the same question as how long they took."
                        />
                        <MetricTable<MetricRow>
                            title="Tool outcomes"
                            description="Unavailable means the server could not be reached and the call carried on. Error means the tool itself failed. The two need different fixes."
                            loading={loading}
                            rows={outcomes}
                            emptyMessage="No tool calls recorded in this period."
                            columns={[
                                {
                                    header: 'Server',
                                    cell: (row) => label(row, ...DIM.server),
                                },
                                {
                                    header: 'Outcome',
                                    // Status colour always travels with its
                                    // label, so the state is never carried by
                                    // colour alone.
                                    cell: (row) => {
                                        const outcome =
                                            label(row, ...DIM.outcome) ?? 'unknown';
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
                                {
                                    header: 'Avg',
                                    align: 'right',
                                    numeric: true,
                                    cell: (row) =>
                                        formatSeconds(pick(row, METRIC.latencyAvg)),
                                },
                            ]}
                        />
                    </TabsContent>
                </Tabs>

                {summary && (
                    <p className="pt-2 text-xs text-muted-foreground">
                        Updated {formatAgo(summary.generated_at)} ·{' '}
                        {new Date(summary.generated_at).toLocaleString()} ·{' '}
                        {summary.window_hours}h window · read live from Langfuse
                    </p>
                )}
            </div>
        </div>
    );
}
