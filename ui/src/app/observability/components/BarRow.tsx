'use client';

interface BarRowProps {
    label: string;
    /** Sublabel shown under the name, e.g. the server a tool belongs to. */
    sublabel?: string;
    value: number;
    /** Largest value in the group, so bars share one scale. */
    max: number;
    /** Rendered at the end of the bar. */
    display: string;
    /** A second, lighter mark on the same track, e.g. p95 behind the average. */
    secondary?: { value: number; display: string; title: string };
}

/**
 * One horizontal bar in a magnitude comparison.
 *
 * Horizontal because the labels are names of tools and stages, which are long
 * and would otherwise be rotated. One hue, more-is-darker is not used here:
 * every bar is the same measure, so a single sequential step keeps the length
 * doing the encoding rather than the colour.
 *
 * The p95 mark sits on the same track as the average rather than in a second
 * chart, because the two share a scale and the gap between them is the point --
 * a tool whose p95 is far past its average is one that is occasionally slow,
 * which an average alone hides.
 */
export function BarRow({ label, sublabel, value, max, display, secondary }: BarRowProps) {
    const pct = max > 0 ? Math.max((value / max) * 100, 1.5) : 0;
    const secondaryPct =
        secondary && max > 0
            ? Math.min(Math.max((secondary.value / max) * 100, 0), 100)
            : null;

    return (
        <div className="grid grid-cols-[minmax(0,13rem)_1fr_auto] items-center gap-3 py-1.5">
            <div className="min-w-0">
                <p className="truncate text-sm">{label}</p>
                {sublabel && (
                    <p className="truncate text-xs text-muted-foreground">{sublabel}</p>
                )}
            </div>

            <div
                className="relative h-5 w-full rounded-sm"
                style={{ background: 'var(--viz-track)' }}
            >
                <div
                    className="viz-bar absolute inset-y-0 left-0"
                    style={{ width: `${pct}%`, background: 'var(--viz-seq-450)' }}
                />
                {secondaryPct !== null && secondary && (
                    // A 2px surface-coloured ring keeps the marker readable where
                    // it overlaps the bar beneath it.
                    <div
                        className="absolute inset-y-0 w-[3px] rounded-full"
                        style={{
                            left: `calc(${secondaryPct}% - 1.5px)`,
                            background: 'var(--viz-seq-550)',
                            boxShadow: '0 0 0 2px var(--viz-track)',
                        }}
                        title={secondary.title}
                    />
                )}
            </div>

            <div className="text-right">
                <p className="font-mono text-sm tabular-nums">{display}</p>
                {secondary && (
                    <p className="font-mono text-[11px] tabular-nums text-muted-foreground">
                        p95 {secondary.display}
                    </p>
                )}
            </div>
        </div>
    );
}
