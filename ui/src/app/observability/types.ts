/**
 * Shapes returned by /api/v1/observability.
 *
 * Metric rows come back as flat records keyed by the dimension and metric
 * names the backend asked Langfuse for. They are deliberately loose: a panel
 * that groups by a dimension gains rows when a new tool or model appears, and
 * typing the rows to a fixed set of keys would be the one thing that stops
 * that working.
 */

export type MetricRow = Record<string, string | number | null>;

export interface TurnStats {
    turns: number;
    conversations: number;
    avg_turn_latency: number | null;
    p95_turn_latency: number | null;
    max_turn_latency: number | null;
    avg_turns_per_conversation: number | null;
    avg_conversation_latency: number | null;
}

export interface CallSummary {
    configured: boolean;
    window_hours: number;
    generated_at: string;
    call_volume: MetricRow[];
    pipeline_stages: MetricRow[];
    /** Speech in, model, speech out, tools - with time to first byte. */
    layers: MetricRow[];
    turns: TurnStats;
    tools: MetricRow[];
    tool_outcomes: MetricRow[];
    /** Anything that raised, plus tool calls that ended other than "ok". */
    failures: MetricRow[];
    models: MetricRow[];
    message: string | null;
}

/** Metric keys the backend requests, so panels read them by name. */
export const METRIC = {
    count: 'count_count',
    latencyAvg: 'avg_latency',
    latencyP95: 'p95_latency',
    latencyMax: 'max_latency',
    tokensSum: 'sum_totalTokens',
    costSum: 'sum_totalCost',
    firstByteAvg: 'avg_first_token',
    firstByteP95: 'p95_first_token',
} as const;

/**
 * Read a value that Langfuse may key by any of several names.
 *
 * Langfuse names a metric column after the aggregation and measure, and the
 * exact spelling has varied between versions. Trying the known spellings keeps
 * a panel rendering through an upgrade rather than silently showing dashes.
 */
export function pick(row: MetricRow, ...keys: string[]): number | null {
    for (const key of keys) {
        const value = row[key];
        if (typeof value === 'number') return value;
        if (typeof value === 'string' && value !== '' && !Number.isNaN(Number(value))) {
            return Number(value);
        }
    }
    return null;
}

/** First non-empty string among the given keys, for dimension columns. */
export function label(row: MetricRow, ...keys: string[]): string | null {
    for (const key of keys) {
        const value = row[key];
        if (typeof value === 'string' && value.trim() !== '') return value;
    }
    return null;
}

/** Seconds, rendered the way a latency figure is normally read. */
export function formatSeconds(value: number | null): string {
    if (value === null) return '—';
    if (value < 1) return `${Math.round(value * 1000)}ms`;
    return `${value.toFixed(2)}s`;
}

/** Langfuse reports latency in seconds; spans record duration in milliseconds. */
export function formatMillis(value: number | null): string {
    if (value === null) return '—';
    return formatSeconds(value / 1000);
}

export function formatCount(value: number | null): string {
    if (value === null) return '—';
    return value.toLocaleString();
}
