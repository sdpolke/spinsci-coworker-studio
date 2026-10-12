'use client';

import { AlertTriangle } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';

import { CallDetail, formatCount, formatSeconds, SpanRow } from '../types';

interface CallTimelineProps {
    detail: CallDetail | null;
    loading: boolean;
    error: string | null;
}

/**
 * Layers worth placing on the timeline.
 *
 * `Turn` and `Conversation` are containers around the others -- a turn span
 * covers the stt, llm and tts spans inside it -- so drawing them alongside
 * would stack every child's time on top of its parent's and make the call look
 * several times longer than it was.
 */
const LEAF_LAYERS = new Set(['LLM', 'Speech to text', 'Text to speech', 'Tools']);

/** Short badge text, because the full layer names do not fit a narrow column. */
const LAYER_BADGE: Record<string, string> = {
    LLM: 'LLM',
    'Speech to text': 'STT',
    'Text to speech': 'TTS',
    Tools: 'TOOL',
    Turn: 'TURN',
    Conversation: 'CALL',
    Other: '—',
};

function describe(span: SpanRow): string {
    if (span.tool_server && span.tool_name)
        return `${span.tool_server} · ${span.tool_name}`;
    if (span.model) return span.model;
    if (span.node) return `node: ${span.node}`;
    return span.name ?? 'unnamed';
}

/**
 * What one call did, in order, as a time-positioned bar per step.
 *
 * Positioned rather than merely listed: the question a slow call raises is
 * *when* it went slow, and a list of durations cannot answer that. With each
 * bar placed at its offset from the start of the call, a pause between two
 * steps is visible as a gap, which is the one thing a table of the same
 * numbers cannot show.
 *
 * Every bar is the same measure, so they share one sequential hue and the
 * length does the encoding. The layer is carried by the text badge beside each
 * row, not by colour -- four categorical hues cannot be told apart reliably in
 * both light and dark modes, and a legend of four colours would be read as
 * four measures. The one exception is the reserved critical colour on a failed
 * step, which travels with an icon and the failure text.
 */
export function CallTimeline({ detail, loading, error }: CallTimelineProps) {
    if (loading) {
        return (
            <div className="space-y-2 py-2">
                {[0, 1, 2, 3, 4].map((i) => (
                    <Skeleton key={i} className="h-6 w-full" />
                ))}
            </div>
        );
    }

    if (error) {
        return (
            <p className="py-4 text-sm" style={{ color: 'var(--viz-critical)' }}>
                {error}
            </p>
        );
    }

    if (!detail) return null;

    const steps = detail.timeline.filter((span) => LEAF_LAYERS.has(span.layer));

    if (steps.length === 0) {
        return (
            <p className="py-4 text-sm text-muted-foreground">
                This call recorded no pipeline steps. It may have ended before the agent
                spoke.
            </p>
        );
    }

    // The timeline is scaled to the last step that finished rather than to the
    // trace duration: a call left open by a browser tab that was never closed
    // has a duration far longer than anything that happened in it, which would
    // squeeze every bar into the first inch of the track.
    const span = Math.max(
        ...steps.map((step) => (step.offset ?? 0) + (step.duration ?? 0)),
        0.001,
    );

    return (
        <div className="space-y-3">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
                <Fact term="Steps" value={formatCount(steps.length)} />
                <Fact term="Turns" value={formatCount(detail.turns)} />
                <Fact
                    term="First token"
                    value={formatSeconds(detail.avg_first_token)}
                    note="model"
                />
                <Fact
                    term="First audio"
                    value={formatSeconds(detail.avg_first_audio)}
                    note="heard by caller"
                />
            </dl>

            <div className="space-y-px">
                {steps.map((step, index) => {
                    const offset = step.offset ?? 0;
                    const duration = step.duration ?? 0;
                    const left = Math.min((offset / span) * 100, 100);
                    // A floor of 0.6% keeps a 50ms step visible on a
                    // four-minute call rather than rounding it out of
                    // existence.
                    const width = Math.max(
                        Math.min((duration / span) * 100, 100 - left),
                        0.6,
                    );
                    const firstByte = step.first_byte;
                    const firstBytePct =
                        firstByte !== null && duration > 0
                            ? Math.min((firstByte / duration) * 100, 100)
                            : null;

                    return (
                        <div
                            key={step.id ?? index}
                            className="group grid grid-cols-[3rem_minmax(0,11rem)_1fr_4.5rem] items-center gap-2 rounded px-1 py-1 hover:bg-muted/60"
                            title={[
                                describe(step),
                                `starts ${formatSeconds(offset)} into the call`,
                                `takes ${formatSeconds(step.duration)}`,
                                firstByte !== null
                                    ? `first byte ${formatSeconds(firstByte)}`
                                    : null,
                                step.tool_outcome ? `outcome ${step.tool_outcome}` : null,
                                step.status_message ?? step.error_kind ?? null,
                            ]
                                .filter(Boolean)
                                .join('\n')}
                        >
                            <span className="font-mono text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                                {LAYER_BADGE[step.layer] ?? step.layer}
                            </span>

                            <span className="truncate text-xs">
                                {step.failed && (
                                    <AlertTriangle
                                        className="mr-1 inline h-3 w-3 shrink-0 align-[-2px]"
                                        style={{ color: 'var(--viz-critical)' }}
                                    />
                                )}
                                {describe(step)}
                            </span>

                            <div
                                className="relative h-3.5 w-full rounded-sm"
                                style={{ background: 'var(--viz-track)' }}
                            >
                                <div
                                    className="absolute inset-y-0 rounded-sm"
                                    style={{
                                        left: `${left}%`,
                                        width: `${width}%`,
                                        background: step.failed
                                            ? 'var(--viz-critical)'
                                            : 'var(--viz-seq-450)',
                                    }}
                                />
                                {/* Where the first byte landed inside the step.
                                    A 2px surface ring keeps the mark readable
                                    against the bar it sits on. */}
                                {firstBytePct !== null && (
                                    <div
                                        className="absolute inset-y-0 w-[2px] rounded-full"
                                        style={{
                                            left: `calc(${left}% + ${(width * firstBytePct) / 100}% - 1px)`,
                                            background: 'var(--viz-seq-100)',
                                            boxShadow: '0 0 0 1px var(--viz-seq-550)',
                                        }}
                                    />
                                )}
                            </div>

                            <span className="text-right font-mono text-[11px] tabular-nums">
                                {formatSeconds(step.duration)}
                            </span>
                        </div>
                    );
                })}
            </div>

            <p className="text-[11px] text-muted-foreground">
                Bars are placed at their offset from the start of the call, so a gap
                between two bars is a gap in the call. The light mark inside a bar is the
                first byte.
            </p>

            {steps.some((step) => step.failed) && (
                <ul
                    className="space-y-1 rounded-lg border p-3 text-xs"
                    style={{ borderColor: 'var(--viz-critical)' }}
                >
                    {steps
                        .filter((step) => step.failed)
                        .map((step, index) => (
                            <li key={step.id ?? index} className="flex items-start gap-2">
                                <AlertTriangle
                                    className="mt-0.5 h-3 w-3 shrink-0"
                                    style={{ color: 'var(--viz-critical)' }}
                                />
                                <span>
                                    <span className="font-medium">{describe(step)}</span>
                                    {' — '}
                                    {step.status_message ??
                                        step.error_kind ??
                                        step.tool_outcome ??
                                        'failed'}
                                </span>
                            </li>
                        ))}
                </ul>
            )}
        </div>
    );
}

function Fact({ term, value, note }: { term: string; value: string; note?: string }) {
    return (
        <div>
            <dt className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {term}
            </dt>
            <dd className="mt-0.5 font-mono text-sm tabular-nums">
                {value}
                {note && (
                    <span className="ml-1 font-sans text-[10px] text-muted-foreground">
                        {note}
                    </span>
                )}
            </dd>
        </div>
    );
}
