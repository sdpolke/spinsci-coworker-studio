'use client';

import { Skeleton } from '@/components/ui/skeleton';

interface StatTileProps {
    label: string;
    value: string;
    /** One line saying what the number means. A figure without this invites a guess. */
    hint?: string;
    /** A second figure that qualifies the first, e.g. the p95 behind an average. */
    sub?: string;
    loading?: boolean;
    /** Reserved status role, used with the text label beside it, never alone. */
    tone?: 'default' | 'good' | 'warning' | 'critical';
    /** Draws the eye to the one figure the page is really about. */
    emphasis?: boolean;
}

const TONE_VAR: Record<string, string> = {
    good: 'var(--viz-good)',
    warning: 'var(--viz-warning)',
    critical: 'var(--viz-critical)',
};

/**
 * A single headline figure.
 *
 * A stat tile rather than a one-bar chart: for a current value there is nothing
 * to compare along an axis, and a bar implies a comparison that is not there.
 *
 * The `sub` line exists because almost every latency figure on this page is an
 * average, and an average on its own is the number most likely to be believed
 * and least likely to be true. Putting the p95 directly beneath it costs one
 * line and stops a healthy-looking mean hiding a tail.
 */
export function StatTile({
    label,
    value,
    hint,
    sub,
    loading = false,
    tone = 'default',
    emphasis = false,
}: StatTileProps) {
    return (
        <div
            className={`flex flex-col rounded-xl border bg-card p-4 transition-colors ${
                emphasis ? 'border-border shadow-sm' : 'border-border/70'
            }`}
            style={emphasis ? { borderLeft: '3px solid var(--viz-seq-450)' } : undefined}
        >
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                {label}
            </p>

            {loading ? (
                <Skeleton className="mt-2 h-8 w-20" />
            ) : (
                <p
                    className="mt-1.5 font-mono text-[26px] font-semibold leading-none tabular-nums"
                    style={tone === 'default' ? undefined : { color: TONE_VAR[tone] }}
                >
                    {value}
                </p>
            )}

            {sub && !loading && (
                <p className="mt-1.5 font-mono text-[11px] tabular-nums text-muted-foreground">
                    {sub}
                </p>
            )}

            {hint && (
                <p className="mt-auto pt-2 text-[11px] leading-snug text-muted-foreground">
                    {hint}
                </p>
            )}
        </div>
    );
}
