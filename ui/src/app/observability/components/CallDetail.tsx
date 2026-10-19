'use client';

import { ArrowLeft, Globe, Info, MessageSquare, Phone } from 'lucide-react';
import { useEffect, useState } from 'react';

import { callDetailApiV1ObservabilityCallsTraceIdGet } from '@/client/sdk.gen';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { detailFromError } from '@/lib/apiError';

import {
    CallDetail as CallDetailShape,
    CallRow,
    formatCount,
    formatDuration,
    formatSeconds,
    formatWhen,
} from '../types';
import { CallTimeline } from './CallTimeline';
import { StatTile } from './StatTile';
import { TurnTable } from './TurnTable';

interface CallDetailProps {
    call: CallRow;
    onBack: () => void;
}

function ChannelIcon({ channel }: { channel: string }) {
    const className = 'h-4 w-4 shrink-0 text-muted-foreground';
    if (channel === 'Telephony') return <Phone className={className} />;
    if (channel === 'Text chat') return <MessageSquare className={className} />;
    return <Globe className={className} />;
}

/**
 * One line saying what shaped this call.
 *
 * Averages describe a call; they do not explain it. The thing a reader wants
 * from a slow call is the one step that made it slow, and from a failed call
 * the point it went wrong. Working that out here saves them scanning for it.
 */
function headline(detail: CallDetailShape): string | null {
    if (detail.failures > 0) {
        const broken = detail.turn_rows.find((turn) => turn.failures > 0);
        return broken
            ? `Something went wrong at turn ${broken.index} — ${broken.route}.`
            : `${formatCount(detail.failures)} steps failed during this call.`;
    }

    const slowest = detail.slowest_tool;
    if (slowest?.duration && slowest.duration >= 1) {
        const turn = detail.turn_rows.find((row) =>
            row.tools.some((tool) => tool.name === slowest.name),
        );
        const share =
            turn && turn.agent_seconds > 0
                ? Math.round((slowest.duration / turn.agent_seconds) * 100)
                : null;
        return `Slowest step was ${slowest.name} at ${formatSeconds(slowest.duration)}${
            turn ? ` on turn ${turn.index}` : ''
        }${share !== null ? ` — ${share}% of that turn's response time` : ''}.`;
    }

    if (detail.tool_calls > 0) {
        return `${formatCount(detail.tool_calls)} integration calls, none slower than ${formatSeconds(
            slowest?.duration ?? null,
        )}.`;
    }
    return null;
}

/**
 * Everything one call did.
 *
 * A screen of its own rather than a row that expands. The per-turn table is
 * wide and the call needs its own summary above it, neither of which fits
 * inside a list without the list stopping being readable.
 */
export function CallDetail({ call, onBack }: CallDetailProps) {
    const [detail, setDetail] = useState<CallDetailShape | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError(null);

        (async () => {
            try {
                const response = await callDetailApiV1ObservabilityCallsTraceIdGet({
                    path: { trace_id: call.trace_id },
                });
                if (cancelled) return;
                // The generated client resolves rather than throws on 4xx/5xx.
                if (response.error) {
                    setError(detailFromError(response.error, 'Could not load this call'));
                    return;
                }
                setDetail(response.data as unknown as CallDetailShape);
            } catch (err) {
                if (!cancelled) {
                    setError(
                        err instanceof Error
                            ? err.message
                            : 'Could not reach the telemetry service',
                    );
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();

        return () => {
            cancelled = true;
        };
    }, [call.trace_id]);

    const story = detail ? headline(detail) : null;

    return (
        <div className="space-y-5">
            <div>
                <button
                    onClick={onBack}
                    className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
                >
                    <ArrowLeft className="h-4 w-4" />
                    All calls
                </button>

                <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <h2 className="text-lg font-semibold tracking-tight">
                        {call.workflow ?? 'Untitled workflow'}
                    </h2>
                    <span className="inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
                        <ChannelIcon channel={call.channel} />
                        {call.channel}
                        {call.transport && ` · ${call.transport}`} ·{' '}
                        {formatWhen(call.started_at)} · {formatDuration(call.duration)}
                    </span>
                </div>
            </div>

            {error && (
                <Card className="border-destructive/40 p-4 text-sm">
                    <p className="font-medium">Could not load this call</p>
                    <p className="mt-1 text-muted-foreground">{error}</p>
                </Card>
            )}

            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                <StatTile
                    label="Turns"
                    value={formatCount(detail?.turns ?? call.turns)}
                    sub={
                        detail?.turns_with_tool
                            ? `${formatCount(detail.turns_with_tool)} called a tool`
                            : undefined
                    }
                    loading={loading}
                />
                <StatTile
                    label="First word"
                    value={formatSeconds(detail?.median_first_word ?? null)}
                    sub={`slowest ${formatSeconds(detail?.max_first_word ?? null)}`}
                    hint="Caller stops speaking to first audible word"
                    loading={loading}
                    emphasis
                />
                <StatTile
                    label="Model TTFT"
                    value={formatSeconds(detail?.median_ttft ?? null)}
                    sub={`slowest ${formatSeconds(detail?.max_ttft ?? null)}`}
                    hint="Prompt sent to first token"
                    loading={loading}
                />
                <StatTile
                    label="Tool time"
                    value={formatSeconds(detail?.tool_seconds ?? null)}
                    sub={
                        detail?.tool_calls
                            ? `${formatCount(detail.tool_calls)} calls · slowest ${formatSeconds(
                                  detail.slowest_tool?.duration ?? null,
                              )}`
                            : undefined
                    }
                    hint="Time waiting on integrations"
                    loading={loading}
                />
                <StatTile
                    label="LLM tokens"
                    value={formatCount(detail?.tokens_in ?? null)}
                    sub={
                        detail?.tokens_out
                            ? `${formatCount(detail.tokens_out)} out`
                            : undefined
                    }
                    loading={loading}
                />
                <StatTile
                    label="Issues"
                    value={formatCount(detail?.failures ?? 0)}
                    sub={detail?.failures ? undefined : 'nothing to look at'}
                    tone={detail?.failures ? 'critical' : 'good'}
                    loading={loading}
                />
            </div>

            {loading && <Skeleton className="h-12 w-full rounded-xl" />}

            {story && (
                <Card
                    className="flex items-start gap-3 p-4"
                    style={{ borderLeft: '3px solid var(--viz-seq-450)' }}
                >
                    <Info
                        className="mt-0.5 h-4 w-4 shrink-0"
                        style={{ color: 'var(--viz-seq-450)' }}
                    />
                    <p className="text-sm text-muted-foreground">{story}</p>
                </Card>
            )}

            {loading ? (
                <Card className="space-y-2 p-5">
                    {[0, 1, 2, 3, 4].map((index) => (
                        <Skeleton key={index} className="h-10 w-full" />
                    ))}
                </Card>
            ) : (
                detail && (
                    <TurnTable
                        turns={detail.turn_rows}
                        transcriptsEnabled={detail.transcripts_enabled}
                    />
                )
            )}

            {/* The span timeline stays reachable but folded: it is the
                debugging view, and the per-turn table is the reading one. */}
            {detail && (
                <details>
                    <summary className="cursor-pointer text-xs text-muted-foreground transition-colors hover:text-foreground">
                        Raw span timeline
                    </summary>
                    <div className="mt-3">
                        <CallTimeline detail={detail} loading={false} error={null} />
                    </div>
                </details>
            )}

            {detail && (
                <p className="font-mono text-[10px] text-muted-foreground">
                    trace {detail.trace_id}
                    {detail.session_id && ` · session ${detail.session_id}`}
                    {detail.tts_characters &&
                        ` · ${formatCount(detail.tts_characters)} characters synthesised`}
                </p>
            )}
        </div>
    );
}
