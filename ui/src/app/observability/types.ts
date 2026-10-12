/**
 * Shapes returned by /api/v1/observability.
 *
 * Metric rows come back as flat records keyed by the dimension and metric
 * names the backend asked Langfuse for. They are deliberately loose: a panel
 * that groups by a dimension gains rows when a new tool or model appears, and
 * typing the rows to a fixed set of keys would be the one thing that stops
 * that working.
 *
 * The per-call and per-span shapes below are the opposite -- the backend
 * builds them, so they are named exactly and the compiler checks every field.
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
    avg_first_token: number | null;
    p95_first_token: number | null;
}

/** One call. The row a person actually came here to find. */
export interface CallRow {
    trace_id: string;
    started_at: string | null;
    workflow: string | null;
    /** Browser, Telephony or Text chat -- derived from the transport. */
    channel: string;
    /** The raw transport, e.g. smallwebrtc or twilio. */
    transport: string | null;
    session_id: string | null;
    user_id: string | null;
    duration: number | null;
    turns: number;
    avg_turn_latency: number | null;
    max_turn_latency: number | null;
    /** Wait before the model's first token. */
    avg_first_token: number | null;
    /** Wait before the first audio frame -- what the caller actually hears. */
    avg_first_audio: number | null;
    avg_llm_latency: number | null;
    avg_stt_latency: number | null;
    avg_tts_latency: number | null;
    tool_calls: number;
    tool_seconds: number | null;
    failures: number;
    tokens: number | null;
    spans: number;
}

/** One step inside a call, for the drill-down timeline. */
export interface SpanRow {
    id: string | null;
    name: string | null;
    layer: string;
    /** Seconds from the start of the call, so a slow step can be placed. */
    offset: number | null;
    duration: number | null;
    first_byte: number | null;
    level: string | null;
    status_message: string | null;
    model: string | null;
    tokens: number | null;
    node: string | null;
    tool_server: string | null;
    tool_name: string | null;
    tool_outcome: string | null;
    error_kind: string | null;
    failed: boolean;
}

export interface CallDetail {
    trace_id: string;
    workflow: string | null;
    started_at: string | null;
    channel: string;
    transport: string | null;
    session_id: string | null;
    user_id: string | null;
    duration: number | null;
    tags: string[];
    turns: number;
    avg_turn_latency: number | null;
    avg_first_token: number | null;
    avg_first_audio: number | null;
    timeline: SpanRow[];
}

export interface CallSummary {
    configured: boolean;
    window_hours: number;
    generated_at: string;
    /** Browser against telephony, directly comparable. */
    channels: MetricRow[];
    calls: CallRow[];
    /** Calls grouped by the workflow that ran. */
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
    /** True when the window held more spans than one render pulls. */
    truncated: boolean;
    message: string | null;
}

/** Metric keys the backend emits, so panels read them by name. */
export const METRIC = {
    count: 'count_count',
    latencyAvg: 'avg_latency',
    latencyP95: 'p95_latency',
    latencyMax: 'max_latency',
    tokensSum: 'sum_totalTokens',
    firstByteAvg: 'avg_first_token',
    firstByteP95: 'p95_first_token',
    failures: 'failures',
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

/**
 * Seconds, rendered the way a latency figure is normally read.
 *
 * Sub-second figures go to milliseconds because that is the unit anyone
 * discussing time-to-first-token uses, and "0.18s" invites a second look to
 * count the zeros.
 */
export function formatSeconds(value: number | null | undefined): string {
    if (value === null || value === undefined) return '—';
    if (value < 1) return `${Math.round(value * 1000)}ms`;
    return `${value.toFixed(2)}s`;
}

/**
 * A call length, which is read in minutes once it passes one.
 *
 * Deliberately different from {@link formatSeconds}: "198.24s" is a latency
 * format applied to a duration, and it makes a three-minute call look like a
 * number that needs investigating.
 */
export function formatDuration(value: number | null | undefined): string {
    if (value === null || value === undefined) return '—';
    if (value < 60) return `${value.toFixed(1)}s`;
    const minutes = Math.floor(value / 60);
    const seconds = Math.round(value % 60);
    return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
}

export function formatCount(value: number | null | undefined): string {
    if (value === null || value === undefined) return '—';
    return value.toLocaleString();
}

/** Date and time, in the reader's own timezone. */
export function formatWhen(value: string | null | undefined): string {
    if (!value) return '—';
    const when = new Date(value);
    if (Number.isNaN(when.getTime())) return '—';
    return when.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

/** "4m ago", for the freshness line under a figure. */
export function formatAgo(value: string | null | undefined): string {
    if (!value) return '';
    const when = new Date(value);
    if (Number.isNaN(when.getTime())) return '';
    const seconds = Math.round((Date.now() - when.getTime()) / 1000);
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
    return `${Math.round(seconds / 86400)}d ago`;
}
