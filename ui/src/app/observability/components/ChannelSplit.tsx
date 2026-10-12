'use client';

import { Globe, MessageSquare, Phone } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

import {
    formatCount,
    formatDuration,
    formatSeconds,
    label,
    METRIC,
    MetricRow,
    pick,
} from '../types';

interface ChannelSplitProps {
    channels: MetricRow[];
    loading: boolean;
}

function ChannelIcon({ channel }: { channel: string }) {
    const className = 'h-4 w-4 shrink-0';
    if (channel === 'Telephony') return <Phone className={className} />;
    if (channel === 'Text chat') return <MessageSquare className={className} />;
    return <Globe className={className} />;
}

/**
 * Browser against telephony, side by side.
 *
 * Worth a panel of its own because the two run the identical pipeline and
 * differ only in how the audio arrives. That makes them directly comparable,
 * and a gap between them in first-token or turn latency points at the network
 * or the codec rather than at the model -- a distinction that is invisible once
 * the two are averaged together, which is what every other panel does.
 *
 * Cards rather than a grouped bar chart: with two or three channels there is
 * no shape to see, and each channel carries five different measures, which a
 * bar chart would have to become five charts to show.
 */
export function ChannelSplit({ channels, loading }: ChannelSplitProps) {
    if (loading) {
        return (
            <div className="grid gap-4 sm:grid-cols-2">
                {[0, 1].map((i) => (
                    <Skeleton key={i} className="h-36 w-full rounded-xl" />
                ))}
            </div>
        );
    }

    if (channels.length === 0) {
        return (
            <Card className="p-6 text-center">
                <p className="text-sm text-muted-foreground">
                    No calls in this period, so there is nothing to compare.
                </p>
            </Card>
        );
    }

    const busiest = Math.max(...channels.map((row) => pick(row, METRIC.count) ?? 0), 1);

    return (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {channels.map((row, index) => {
                const name = label(row, 'channel') ?? 'Unclassified';
                const count = pick(row, METRIC.count) ?? 0;
                const share = (count / busiest) * 100;
                const transports = label(row, 'transports');
                const failures = pick(row, METRIC.failures) ?? 0;

                return (
                    <Card key={index} className="p-4">
                        <div className="flex items-center justify-between gap-2">
                            <span className="flex items-center gap-2 text-sm font-semibold">
                                <ChannelIcon channel={name} />
                                {name}
                            </span>
                            <span className="font-mono text-xl font-semibold tabular-nums">
                                {formatCount(count)}
                            </span>
                        </div>

                        <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                            {transports ? `via ${transports}` : 'transport not recorded'}
                        </p>

                        {/* Share of the busiest channel, so the cards read as a
                            comparison rather than as three unrelated numbers. */}
                        <div
                            className="mt-3 h-1.5 w-full rounded-full"
                            style={{ background: 'var(--viz-track)' }}
                        >
                            <div
                                className="h-1.5 rounded-full"
                                style={{
                                    width: `${Math.max(share, 2)}%`,
                                    background: 'var(--viz-seq-450)',
                                }}
                            />
                        </div>

                        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
                            <Measure
                                term="Avg length"
                                value={formatDuration(pick(row, METRIC.latencyAvg))}
                            />
                            <Measure
                                term="Avg turn"
                                value={formatSeconds(pick(row, 'avg_turn_latency'))}
                                note={`p95 ${formatSeconds(pick(row, 'p95_turn_latency'))}`}
                            />
                            <Measure
                                term="First token"
                                value={formatSeconds(pick(row, METRIC.firstByteAvg))}
                            />
                            <Measure
                                term="Turns"
                                value={formatCount(pick(row, 'turns'))}
                                note={
                                    count > 0
                                        ? `${((pick(row, 'turns') ?? 0) / count).toFixed(1)} per call`
                                        : undefined
                                }
                            />
                        </dl>

                        {failures > 0 && (
                            <p
                                className="mt-3 text-[11px] font-medium"
                                style={{ color: 'var(--viz-critical)' }}
                            >
                                {formatCount(failures)} of these calls hit a problem
                            </p>
                        )}
                    </Card>
                );
            })}
        </div>
    );
}

function Measure({ term, value, note }: { term: string; value: string; note?: string }) {
    return (
        <div>
            <dt className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {term}
            </dt>
            <dd className="font-mono text-sm tabular-nums">
                {value}
                {note && (
                    <span className="ml-1 block font-sans text-[10px] text-muted-foreground">
                        {note}
                    </span>
                )}
            </dd>
        </div>
    );
}
