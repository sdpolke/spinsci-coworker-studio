'use client';

import { EyeOff } from 'lucide-react';

import { Card } from '@/components/ui/card';

import { formatCount, formatSeconds, TurnRow } from '../types';

interface TurnTableProps {
    turns: TurnRow[];
    /** True when transcripts exist but configuration withholds them. */
    transcriptsHidden: boolean;
}

/**
 * The four stages a caller waits through, in the order they happen.
 *
 * Fixed order, assigned to a stage and never cycled. Validated as a stacked
 * palette in both themes: worst adjacent CVD delta E 9.1 light / 8.4 dark
 * against a target of 8, normal-vision 22.9 / 19.8 against a floor of 15. Two
 * light-mode steps fall below 3:1 against the surface, which is why every
 * segment also carries a written figure beneath the bar rather than relying on
 * the fill to identify it.
 */
const STAGES = [
    { key: 'stt' as const, label: 'Transcribe', varName: '--viz-stage-stt' },
    { key: 'llm' as const, label: 'Model', varName: '--viz-stage-llm' },
    { key: 'tool' as const, label: 'Tool', varName: '--viz-stage-tool' },
    { key: 'tts' as const, label: 'Speak', varName: '--viz-stage-tts' },
];

/** Status colour for a latency, always shown with the figure beside it. */
function latencyTone(seconds: number | null): string | undefined {
    if (seconds === null) return undefined;
    if (seconds < 1.5) return 'var(--viz-good)';
    if (seconds < 2.5) return 'var(--viz-warning)';
    return 'var(--viz-critical)';
}

function outcomeTone(outcome: string | null): string {
    if (outcome === 'ok') return 'var(--viz-good)';
    if (outcome === 'unavailable') return 'var(--viz-warning)';
    return 'var(--viz-critical)';
}

/**
 * One row per exchange: what ran, which integration it called, and where each
 * second of the caller's wait went.
 *
 * The bar is the caller's wait, not the turn. A turn span also contains the
 * caller speaking and the pause before they start, which on a real call is
 * most of it -- one turn measured 21.5s around about 6s of work. Drawing the
 * turn would make every bar a sliver and say nothing.
 *
 * For the same reason the speech stages contribute their *lag* rather than
 * their whole span: a transcription span runs while the caller is still
 * talking, and a synthesis span runs while the agent is still being heard.
 * Neither is time anybody waits.
 */
export function TurnTable({ turns, transcriptsHidden }: TurnTableProps) {
    if (turns.length === 0) {
        return (
            <Card className="p-8 text-center">
                <p className="text-sm text-muted-foreground">
                    This call recorded no turns. It may have ended before the agent spoke.
                </p>
            </Card>
        );
    }

    // One scale across every row, so bar lengths are comparable down the column.
    const widest = Math.max(...turns.map((turn) => turn.agent_seconds), 0.001);

    return (
        <Card className="overflow-hidden p-0">
            <div className="flex flex-wrap items-center gap-4 border-b border-border bg-muted/40 px-4 py-2.5 text-xs text-muted-foreground">
                {STAGES.map((stage) => (
                    <span key={stage.key} className="inline-flex items-center gap-1.5">
                        <span
                            aria-hidden
                            className="h-2.5 w-2.5 rounded-[2px]"
                            style={{ background: `var(${stage.varName})` }}
                        />
                        {stage.label}
                    </span>
                ))}
                <span className="inline-flex items-center gap-1.5">
                    <span
                        aria-hidden
                        className="h-3 w-[2px] rounded-full bg-foreground"
                    />
                    first token
                </span>
                {transcriptsHidden && (
                    <span className="ml-auto inline-flex items-center gap-1.5">
                        <EyeOff className="h-3.5 w-3.5" />
                        Transcripts withheld
                    </span>
                )}
            </div>

            <div className="overflow-x-auto">
                <table className="w-full min-w-[60rem] text-sm">
                    <thead>
                        <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                            <Th right>#</Th>
                            {!transcriptsHidden && <Th>Caller</Th>}
                            {!transcriptsHidden && <Th>Agent</Th>}
                            <Th>Route</Th>
                            <Th>Where the time went</Th>
                            <Th right title="Prompt sent to the model's first token">
                                TTFT
                            </Th>
                            <Th
                                right
                                title="Caller stops speaking to the agent's first audible word"
                            >
                                First word
                            </Th>
                            <Th right>Tokens</Th>
                            <Th right>Tool call</Th>
                            <Th right>TTS</Th>
                        </tr>
                    </thead>
                    <tbody>
                        {turns.map((turn) => {
                            const total = turn.agent_seconds || 0.001;
                            return (
                                <tr
                                    key={turn.index}
                                    className="border-b border-border/50 last:border-0 align-top hover:bg-muted/40"
                                >
                                    <Td right numeric className="text-muted-foreground">
                                        {turn.index}
                                    </Td>

                                    {!transcriptsHidden && (
                                        <Td className="max-w-[14rem] text-muted-foreground">
                                            {turn.caller || '—'}
                                        </Td>
                                    )}
                                    {!transcriptsHidden && (
                                        <Td className="max-w-[16rem]">
                                            {turn.agent || '—'}
                                        </Td>
                                    )}

                                    <Td>
                                        <span
                                            className="inline-block rounded border px-1.5 py-0.5 font-mono text-[11px]"
                                            style={
                                                turn.tool_calls > 0
                                                    ? {
                                                          borderColor:
                                                              'var(--viz-stage-tool)',
                                                          color: 'var(--viz-stage-tool)',
                                                      }
                                                    : undefined
                                            }
                                        >
                                            {turn.route}
                                        </span>
                                        {turn.tools.length > 0 &&
                                            turn.tools[0].server && (
                                                <span className="mt-1 block text-[11px] text-muted-foreground">
                                                    {turn.tools[0].server}
                                                    {turn.tools.length > 1 &&
                                                        ` · ${turn.tools.length} calls`}
                                                </span>
                                            )}
                                    </Td>

                                    <Td className="min-w-[15rem]">
                                        <div
                                            className="flex h-4 gap-[2px] overflow-hidden rounded-sm"
                                            style={{
                                                width: `${Math.max((total / widest) * 100, 10)}%`,
                                                background: 'var(--viz-track)',
                                            }}
                                        >
                                            {STAGES.map((stage) => {
                                                const value = turn.segments[stage.key];
                                                if (!value || value <= 0) return null;
                                                // The first token lands inside the
                                                // model segment, so the mark is
                                                // placed within that segment.
                                                const tick =
                                                    stage.key === 'llm' &&
                                                    turn.ttft !== null &&
                                                    turn.ttft < value
                                                        ? (turn.ttft / value) * 100
                                                        : null;
                                                return (
                                                    <div
                                                        key={stage.key}
                                                        className="relative h-full"
                                                        style={{
                                                            width: `${(value / total) * 100}%`,
                                                            background: `var(${stage.varName})`,
                                                        }}
                                                        title={`${stage.label} ${formatSeconds(value)}`}
                                                    >
                                                        {tick !== null && (
                                                            <span
                                                                className="absolute -inset-y-[2px] w-[2px] rounded-full bg-foreground"
                                                                style={{
                                                                    left: `${tick}%`,
                                                                    boxShadow:
                                                                        '0 0 0 2px var(--viz-track)',
                                                                }}
                                                                title={`first token at ${formatSeconds(turn.ttft)}`}
                                                            />
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px] tabular-nums text-muted-foreground">
                                            {STAGES.map((stage) => {
                                                const value = turn.segments[stage.key];
                                                if (!value || value <= 0) return null;
                                                return (
                                                    <span key={stage.key}>
                                                        {stage.label}{' '}
                                                        {formatSeconds(value)}
                                                    </span>
                                                );
                                            })}
                                        </div>
                                    </Td>

                                    <Td right numeric>
                                        {formatSeconds(turn.ttft)}
                                    </Td>
                                    <Td right numeric>
                                        <span
                                            style={{
                                                color: latencyTone(turn.first_word),
                                            }}
                                        >
                                            {formatSeconds(turn.first_word)}
                                        </span>
                                    </Td>
                                    <Td right numeric className="text-muted-foreground">
                                        {turn.tokens_in === null
                                            ? '—'
                                            : `${formatCount(turn.tokens_in)} / ${formatCount(turn.tokens_out)}`}
                                    </Td>
                                    <Td right numeric>
                                        {turn.tools.length === 0 ? (
                                            <span className="text-muted-foreground">
                                                —
                                            </span>
                                        ) : (
                                            turn.tools.map((tool, index) => (
                                                <span key={index} className="block">
                                                    {formatSeconds(tool.duration)}{' '}
                                                    <span
                                                        className="font-sans text-[10px]"
                                                        style={{
                                                            color: outcomeTone(
                                                                tool.outcome,
                                                            ),
                                                        }}
                                                    >
                                                        {tool.outcome ?? 'unknown'}
                                                    </span>
                                                </span>
                                            ))
                                        )}
                                    </Td>
                                    <Td right numeric className="text-muted-foreground">
                                        {turn.tts_characters === null
                                            ? '—'
                                            : formatCount(turn.tts_characters)}
                                    </Td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>

            <p className="border-t border-border/50 px-4 py-3 text-[11px] leading-relaxed text-muted-foreground">
                The bar is what the caller waits through, not the whole turn — a turn also
                holds the caller speaking and the pause before they start. Transcribe and
                Speak contribute their lag rather than their whole span, because neither
                the caller talking nor the agent being heard is time anyone waits.{' '}
                <strong>TTFT</strong> is the model&apos;s own first token; with a
                reasoning model the thinking happens before it, so that is where reasoning
                time shows up. <strong>First word</strong> adds transcription ahead of it
                and speech synthesis after.
            </p>
        </Card>
    );
}

function Th({
    children,
    right,
    title,
}: {
    children?: React.ReactNode;
    right?: boolean;
    title?: string;
}) {
    return (
        <th
            title={title}
            className={`px-3 py-2 font-medium ${right ? 'text-right' : 'text-left'}`}
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
}: {
    children?: React.ReactNode;
    right?: boolean;
    numeric?: boolean;
    className?: string;
}) {
    return (
        <td
            className={`px-3 py-2.5 ${right ? 'text-right' : 'text-left'} ${
                numeric
                    ? 'font-mono text-[12px] tabular-nums'
                    : 'text-[12.5px] leading-snug'
            } ${className ?? ''}`}
        >
            {children}
        </td>
    );
}
