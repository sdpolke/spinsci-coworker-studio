'use client';

import { Skeleton } from '@/components/ui/skeleton';

interface StatTileProps {
    label: string;
    value: string;
    /** One line saying what the number means. A figure without this invites a guess. */
    hint?: string;
    loading?: boolean;
    /** Reserved status role, used with the text label beside it, never alone. */
    tone?: 'default' | 'good' | 'warning' | 'critical';
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
 */
export function StatTile({ label, value, hint, loading = false, tone = 'default' }: StatTileProps) {
    return (
        <div className="rounded-lg border border-border bg-card p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {label}
            </p>
            {loading ? (
                <Skeleton className="mt-2 h-8 w-20" />
            ) : (
                <p
                    className="mt-1 font-mono text-2xl font-semibold tabular-nums"
                    style={tone === 'default' ? undefined : { color: TONE_VAR[tone] }}
                >
                    {value}
                </p>
            )}
            {hint && <p className="mt-1 text-xs leading-snug text-muted-foreground">{hint}</p>}
        </div>
    );
}
