"""Read call telemetry back out of Langfuse for the admin dashboard.

Langfuse already stores every span the voice pipeline emits, so the dashboard
queries it rather than keeping a second copy. No new tables, no rollup job, and
no risk of the dashboard disagreeing with the traces it links to.

**Why this talks HTTP rather than using the Langfuse SDK.** The installed SDK
calls the v2 observations and metrics endpoints, which a Langfuse running in
the default mode answers with ``404: only available in a Langfuse v4 write
mode``. The public REST endpoints it is built on work normally. Going straight
to them also removes a version coupling: this keeps working across SDK upgrades
because it depends only on the documented HTTP surface.

**Why aggregation happens here.** Langfuse's metrics endpoint groups only by
its own fixed dimension list -- name, type, model, user, session and a few more
-- and custom span attributes are not among them. The one grouping this
dashboard exists for, *by tool server and tool*, therefore cannot be asked of
it. Observations are fetched with their attributes and reduced in Python.

**Why one fetch feeds every panel.** A dashboard render needs the same traces
and the same observations for all of its panels. Fetching per panel meant eight
scans of the same window, which is slow for the person waiting, unkind to a
shared Langfuse, and -- because the scans happen at slightly different moments
-- lets two panels disagree about the same call. :class:`CallData` is loaded
once and every panel reduces it.

Credentials come from the environment (``LANGFUSE_HOST``,
``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``). When they are absent the
service reports itself unconfigured and the dashboard says so plainly, rather
than rendering zeroes that look like a quiet system.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

import httpx
from loguru import logger

from api.constants import (
    LANGFUSE_HOST,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
)
from api.services.observability.conventions import (
    CALL_NODE,
    CHANNEL_LABELS,
    TOOL_DURATION_MS,
    TOOL_ERROR_KIND,
    TOOL_NAME,
    TOOL_OUTCOME,
    TOOL_SERVER,
    CallChannel,
    SpanName,
    ToolOutcome,
    channel_for_transport,
)

# One page of observations. Langfuse caps a page well below this; the loop
# below pages until the window is covered or the ceiling is reached.
_PAGE_SIZE = 100
_TIMEOUT_SECONDS = 20.0


def _row_ceiling() -> int:
    """Most rows pulled for one dashboard render.

    A single fifteen-turn call emits a few hundred spans, so this is a ceiling
    on *calls per render* as much as on rows. It is configurable because the
    right value depends on traffic: too low silently truncates a busy window,
    too high makes a week-long window slow. When it does bite, the snapshot
    says so rather than quietly reporting partial figures as complete.
    """
    try:
        return max(int(os.getenv("SPINSCI_TELEMETRY_MAX_ROWS", "8000")), _PAGE_SIZE)
    except ValueError:
        return 8000


class LangfuseNotConfigured(RuntimeError):
    """Langfuse credentials are absent. The dashboard renders an explanation."""


def is_configured() -> bool:
    return bool(LANGFUSE_HOST and LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)


@dataclass(frozen=True)
class TimeWindow:
    """The period a panel covers."""

    start: datetime
    end: datetime

    @classmethod
    def last_hours(cls, hours: int) -> "TimeWindow":
        end = datetime.now(timezone.utc)
        return cls(start=end - timedelta(hours=hours), end=end)


def _get(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """One authenticated GET against the Langfuse public API.

    Returns None on any failure. A panel that cannot load should leave the rest
    of the dashboard standing, so nothing here raises except a genuinely
    missing configuration, which the caller reports differently.
    """
    if not is_configured():
        raise LangfuseNotConfigured(
            "LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must all be set"
        )
    url = f"{str(LANGFUSE_HOST).rstrip('/')}{path}"
    try:
        response = httpx.get(
            url,
            params=params,
            auth=(str(LANGFUSE_PUBLIC_KEY), str(LANGFUSE_SECRET_KEY)),
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001 - one panel failing is not fatal
        logger.warning(f"Langfuse request failed ({path}): {exc}")
        return None


def _paged(
    path: str, params: dict[str, Any], limit: int
) -> tuple[list[dict[str, Any]], bool]:
    """Every page of a listing endpoint, up to ``limit`` rows.

    Returns the rows and whether more existed than were taken, so a caller can
    tell the reader that the figures cover part of the window rather than
    presenting a truncated scan as the whole picture.
    """
    rows: list[dict[str, Any]] = []
    page = 1
    truncated = False
    while True:
        payload = _get(path, {**params, "limit": _PAGE_SIZE, "page": page})
        if not payload:
            break
        batch = payload.get("data") or []
        rows.extend(row for row in batch if isinstance(row, dict))
        meta = payload.get("meta") or {}
        if page >= (meta.get("totalPages") or 1) or not batch:
            break
        if len(rows) >= limit:
            truncated = True
            break
        page += 1
    return rows[:limit], truncated


def _attributes(observation: dict[str, Any]) -> dict[str, Any]:
    """Span attributes, which Langfuse nests under metadata."""
    metadata = observation.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    attributes = metadata.get("attributes")
    return attributes if isinstance(attributes, dict) else {}


# ------------------------------------------------------------------- channel
#
# The channel is not a span attribute: the pipeline records it as a trace tag
# (``channel:<transport>``) alongside the model and provider tags, and the
# transport is the raw one -- ``smallwebrtc``, ``twilio``, ``telnyx``. Reading
# the tag and classifying the transport is what makes a browser-versus-
# telephony split possible without the pipeline emitting anything new.

_CHANNEL_TAG = "channel"


def _trace_tags(trace: dict[str, Any]) -> dict[str, str]:
    """``key:value`` trace tags as a mapping. A bare tag maps to an empty value."""
    tags = trace.get("tags")
    if not isinstance(tags, list):
        return {}
    parsed: dict[str, str] = {}
    for tag in tags:
        key, separator, value = str(tag).partition(":")
        parsed[key.strip()] = value.strip() if separator else ""
    return parsed


def transport_of(trace: dict[str, Any]) -> str | None:
    """The transport a call arrived on, e.g. ``smallwebrtc`` or ``twilio``."""
    return _trace_tags(trace).get(_CHANNEL_TAG) or None


def channel_of(trace: dict[str, Any]) -> CallChannel:
    """Browser, telephony or text chat, for one trace."""
    return channel_for_transport(transport_of(trace))


def channel_label(trace: dict[str, Any]) -> str:
    channel = channel_of(trace)
    return CHANNEL_LABELS.get(channel, str(channel))


def _is_call(trace: dict[str, Any]) -> bool:
    """Whether a trace is a real call rather than something else we traced.

    A health check and a seeding script land in the same project as the calls,
    and averaging them in produces an "average call duration" that no caller
    ever experienced. A call is identified positively -- it carries the channel
    tag the pipeline stamps, or a session -- so anything else is excluded
    without this module needing to know the name of every synthetic trace.
    """
    return bool(transport_of(trace) or trace.get("sessionId"))


# --------------------------------------------------------------------- layers
#
#: Span name -> the layer of the pipeline it belongs to.
#:
#: Pipecat names its spans ``llm``/``llm-<node>``, ``tts``, ``stt``, ``turn-N``
#: and ``conversation``; tool calls carry our own name. Classifying here, in
#: one place, is what lets the dashboard answer "where did the time go" by
#: layer rather than by a list of span names nobody outside the pipeline
#: recognises. An unrecognised name falls to ``Other`` and is still counted, so
#: a new span type shows up as soon as it is emitted rather than vanishing.
LAYER_LLM = "LLM"
LAYER_STT = "Speech to text"
LAYER_TTS = "Text to speech"
LAYER_TOOL = "Tools"
LAYER_TURN = "Turn"
LAYER_CONVERSATION = "Conversation"
LAYER_OTHER = "Other"


def classify_layer(span_name: str) -> str:
    """Which pipeline layer a span belongs to."""
    name = (span_name or "").lower()
    if name.startswith("llm"):
        return LAYER_LLM
    if name.startswith("stt"):
        return LAYER_STT
    if name.startswith("tts"):
        return LAYER_TTS
    if name.startswith("mcp.") or name.startswith("http.tool"):
        return LAYER_TOOL
    if name.startswith("turn"):
        return LAYER_TURN
    if name == "conversation":
        return LAYER_CONVERSATION
    return LAYER_OTHER


#: Layers that make up the time a caller actually waits. Turn and conversation
#: are containers around these, so counting them too would double every figure.
RESPONSE_LAYERS = (LAYER_LLM, LAYER_STT, LAYER_TTS, LAYER_TOOL)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


#: Pipecat stamps time-to-first-byte on the span itself, in seconds.
#:
#: Preferred over deriving it from ``completionStartTime``, which these spans
#: do not carry: the pipeline measures it at the point the first token or the
#: first audio frame actually arrives, which is the moment the caller stops
#: waiting. It is recorded for TTS as well as the model, so "first audio out"
#: is measurable alongside "first token in".
TTFB_ATTRIBUTE = "metrics.ttfb"

#: Characters handed to the voice, on a tts span.
CHARACTER_COUNT_ATTRIBUTE = "metrics.character_count"
#: Seconds of caller audio, on an stt span.
AUDIO_SECONDS_ATTRIBUTE = "metrics.audio_seconds"
#: What was said. Both are conversation content, see ``show_transcripts``.
TRANSCRIPT_ATTRIBUTE = "transcript"
SPOKEN_TEXT_ATTRIBUTE = "text"


def show_transcripts() -> bool:
    """Whether a per-turn row may carry what was actually said.

    Off unless explicitly enabled. On this platform a turn's transcript is a
    patient saying their name, their date of birth and their symptoms, and an
    admin dashboard is a wider audience than the call itself had. The timings,
    the route and the outcomes -- everything the page exists to show -- are
    unaffected by this flag; only the two text columns are.
    """
    return os.getenv("SPINSCI_TELEMETRY_TRANSCRIPTS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def time_to_first_token(observation: dict[str, Any]) -> float | None:
    """Seconds until the first token or first audio frame.

    The number that decides whether a call feels responsive. Total latency
    includes producing a whole reply, but a caller stops waiting the moment
    speech starts, so this is what they actually experience.
    """
    raw = _attributes(observation).get(TTFB_ATTRIBUTE)
    if raw is not None:
        try:
            value = float(raw)
            return value if value >= 0 else None
        except (TypeError, ValueError):
            pass

    # Fall back to the OTEL/Langfuse field for providers that report it that
    # way instead, so this keeps working if the pipeline stops stamping ttfb.
    start = _parse_time(observation.get("startTime"))
    first = _parse_time(observation.get("completionStartTime"))
    if start is None or first is None:
        return None
    delta = (first - start).total_seconds()
    return delta if delta >= 0 else None


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile.

    Nearest-rank rather than interpolated: with the handful of samples a quiet
    tool produces, interpolation invents a number no call actually took.
    """
    if not values:
        return None
    ordered = sorted(values)
    index = min(int(round(fraction * len(ordered) + 0.5)) - 1, len(ordered) - 1)
    return ordered[max(index, 0)]


def _mean(values: Sequence[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _latency_seconds(observation: dict[str, Any]) -> float | None:
    """Seconds for one span, preferring our own measurement.

    Tool spans record their duration with a monotonic clock. Langfuse derives
    latency from start and end timestamps, which clock skew distorts, so the
    recorded value wins where present.
    """
    recorded = _attributes(observation).get(TOOL_DURATION_MS)
    if recorded is not None:
        try:
            return float(recorded) / 1000.0
        except (TypeError, ValueError):
            pass
    try:
        latency = observation.get("latency")
        return float(latency) if latency is not None else None
    except (TypeError, ValueError):
        return None


def _tokens_of(observation: dict[str, Any]) -> int:
    usage = observation.get("usage") or {}
    if not isinstance(usage, dict):
        return 0
    try:
        return int(usage.get("total") or usage.get("totalTokens") or 0)
    except (TypeError, ValueError):
        return 0


def _is_failure(observation: dict[str, Any]) -> bool:
    """Whether a span represents something going wrong.

    Two conditions, because they are genuinely different. A span marked ERROR
    or WARNING raised. A tool whose outcome is not ``ok`` returned without
    raising -- an unreachable server, a lookup that found nothing -- and the
    call degraded politely and carried on, so it is invisible without this.
    """
    if str(observation.get("level") or "").upper() in {"ERROR", "WARNING"}:
        return True
    outcome = _attributes(observation).get(TOOL_OUTCOME)
    return bool(outcome and str(outcome) != str(ToolOutcome.OK))


# ------------------------------------------------------------------ the fetch


@dataclass
class CallData:
    """One window of telemetry, fetched once and reduced by every panel."""

    window: TimeWindow
    #: Traces that are real calls, newest first.
    calls: list[dict[str, Any]]
    #: Observations in scope for the aggregate panels.
    observations: list[dict[str, Any]]
    #: Those observations grouped by call, in time order.
    by_call: dict[str, list[dict[str, Any]]]
    truncated: bool = False


def load(window: TimeWindow, channel: str | None = None) -> CallData:
    """Fetch the window once.

    The channel filter is applied to *traces* and then propagated to their
    observations, so narrowing to browser calls narrows every panel -- the
    tools, the models and the layers included. Filtering on a span attribute,
    which is what this did before, matched nothing: the channel lives on the
    trace, not on each span.
    """
    ceiling = _row_ceiling()
    traces, traces_truncated = _paged(
        "/api/public/traces",
        {
            "fromTimestamp": window.start.isoformat(),
            "toTimestamp": window.end.isoformat(),
        },
        ceiling,
    )
    observations, observations_truncated = _paged(
        "/api/public/observations",
        {
            "fromStartTime": window.start.isoformat(),
            "toStartTime": window.end.isoformat(),
        },
        ceiling,
    )

    wanted = channel.strip().lower() if channel else None
    calls: list[dict[str, Any]] = []
    excluded: set[str] = set()
    for trace in traces:
        trace_id = str(trace.get("id") or "")
        if not _is_call(trace) or (wanted and str(channel_of(trace)) != wanted):
            excluded.add(trace_id)
            continue
        calls.append(trace)

    call_ids = {str(trace.get("id") or "") for trace in calls}

    kept: list[dict[str, Any]] = []
    by_call: dict[str, list[dict[str, Any]]] = {trace_id: [] for trace_id in call_ids}
    for observation in observations:
        trace_id = str(observation.get("traceId") or "")
        if trace_id in call_ids:
            by_call[trace_id].append(observation)
            kept.append(observation)
        elif trace_id not in excluded and not wanted:
            # A span whose trace was excluded is dropped. One whose trace we
            # never saw -- its call began before the window -- is kept, because
            # dropping it would lose real work rather than filter out noise.
            kept.append(observation)

    for spans in by_call.values():
        spans.sort(key=lambda span: str(span.get("startTime") or ""))
    calls.sort(key=lambda trace: str(trace.get("timestamp") or ""), reverse=True)

    return CallData(
        window=window,
        calls=calls,
        observations=kept,
        by_call=by_call,
        truncated=traces_truncated or observations_truncated,
    )


@dataclass
class _Bucket:
    """Running aggregate for one group."""

    count: int = 0
    samples: list[float] = field(default_factory=list)
    first_byte: list[float] = field(default_factory=list)
    tokens: int = 0
    failures: int = 0

    def add(
        self,
        seconds: float | None,
        tokens: int = 0,
        first_byte: float | None = None,
        failed: bool = False,
    ) -> None:
        self.count += 1
        self.tokens += tokens
        self.failures += 1 if failed else 0
        if seconds is not None:
            self.samples.append(seconds)
        if first_byte is not None:
            self.first_byte.append(first_byte)

    def as_row(self, **dimensions: Any) -> dict[str, Any]:
        return {
            **dimensions,
            "count_count": self.count,
            "avg_latency": _mean(self.samples),
            "p95_latency": _percentile(self.samples, 0.95),
            "max_latency": max(self.samples) if self.samples else None,
            "avg_first_token": _mean(self.first_byte),
            "p95_first_token": _percentile(self.first_byte, 0.95),
            "sum_totalTokens": self.tokens or None,
            "failures": self.failures,
        }


def _reduce(
    observations: Iterable[dict[str, Any]],
    key: Any,
    *,
    with_tokens: bool = False,
) -> list[dict[str, Any]]:
    """Group observations by ``key(observation)`` and aggregate each group."""
    buckets: dict[tuple, _Bucket] = {}
    dimensions: dict[tuple, dict[str, Any]] = {}
    for observation in observations:
        dims = key(observation)
        if dims is None:
            continue
        bucket_key = tuple(dims.values())
        buckets.setdefault(bucket_key, _Bucket())
        dimensions[bucket_key] = dims
        buckets[bucket_key].add(
            _latency_seconds(observation),
            tokens=_tokens_of(observation) if with_tokens else 0,
            first_byte=time_to_first_token(observation),
            failed=_is_failure(observation),
        )

    rows = [buckets[k].as_row(**dimensions[k]) for k in buckets]
    rows.sort(key=lambda row: row["count_count"], reverse=True)
    return rows


# -------------------------------------------------------------------- panels
#
# Each groups by a dimension rather than enumerating a known list, so new
# tools, servers and models appear on their own.


def _tool_spans(data: CallData) -> list[dict[str, Any]]:
    return [
        observation
        for observation in data.observations
        if str(observation.get("name") or "") == str(SpanName.MCP_TOOL_CALL)
    ]


def tool_performance(data: CallData) -> list[dict[str, Any]]:
    """Latency and volume for every tool, grouped by server and tool.

    The panel that covers "each MCP, each Epic, each tool". Nothing here names
    a specific server, so the first call to a newly registered one adds a row.
    """

    def key(observation: dict[str, Any]) -> dict[str, Any]:
        attributes = _attributes(observation)
        return {
            TOOL_SERVER: str(attributes.get(TOOL_SERVER) or "unknown"),
            TOOL_NAME: str(attributes.get(TOOL_NAME) or "unknown"),
        }

    return _reduce(_tool_spans(data), key)


def tool_outcomes(data: CallData) -> list[dict[str, Any]]:
    """How tool calls ended, grouped by server and outcome.

    Separating ``unavailable`` from ``error`` is the point: one means their
    server is down and the call degraded, the other means we called it wrong,
    and the two need different fixes.
    """

    def key(observation: dict[str, Any]) -> dict[str, Any]:
        attributes = _attributes(observation)
        return {
            TOOL_SERVER: str(attributes.get(TOOL_SERVER) or "unknown"),
            TOOL_OUTCOME: str(attributes.get(TOOL_OUTCOME) or "unknown"),
        }

    return _reduce(_tool_spans(data), key)


def model_performance(data: CallData) -> list[dict[str, Any]]:
    """Latency, time to first token and token usage per model.

    Grouped by the model each generation reports, so a model swapped on the
    Models page shows up here without touching this. First token sits beside
    total latency because they answer different questions: total decides cost
    and throughput, first token decides whether the caller thinks the line has
    gone dead.
    """
    generations = [
        observation
        for observation in data.observations
        if (observation.get("type") or "").upper() == "GENERATION"
    ]

    def key(observation: dict[str, Any]) -> dict[str, Any] | None:
        model = observation.get("model") or observation.get("providedModelName")
        return {"providedModelName": str(model)} if model else None

    return _reduce(generations, key, with_tokens=True)


def pipeline_stage_latency(data: CallData) -> list[dict[str, Any]]:
    """Average and p95 latency for each pipeline stage.

    Grouped by span name, which is how the LLM, speech and tool stages separate
    without this needing to know what any of them are called.
    """

    def key(observation: dict[str, Any]) -> dict[str, Any] | None:
        name = observation.get("name")
        return {"name": str(name)} if name else None

    return _reduce(data.observations, key)


def layer_breakdown(data: CallData) -> list[dict[str, Any]]:
    """Latency per pipeline layer: speech in, model, speech out, tools.

    The panel that answers "where did the time go" without the reader needing
    to know what a span is called. Rows carry time to first byte as well as
    total latency, which is the figure that decides whether a call feels
    responsive: total LLM latency includes generating the whole reply, but the
    caller stops waiting as soon as speech begins.
    """

    def key(observation: dict[str, Any]) -> dict[str, Any] | None:
        layer = classify_layer(str(observation.get("name") or ""))
        return {"layer": layer} if layer in RESPONSE_LAYERS else None

    rows = _reduce(data.observations, key)
    # Slowest first: the layer to look at is the one taking the most time.
    rows.sort(key=lambda row: row["avg_latency"] or 0, reverse=True)
    return rows


def _turn_latencies(spans: Iterable[dict[str, Any]]) -> list[float]:
    return [
        value
        for span in spans
        if classify_layer(str(span.get("name") or "")) == LAYER_TURN
        for value in [_latency_seconds(span)]
        if value is not None
    ]


def _first_bytes(spans: Iterable[dict[str, Any]], layer: str) -> list[float]:
    return [
        value
        for span in spans
        if classify_layer(str(span.get("name") or "")) == layer
        for value in [time_to_first_token(span)]
        if value is not None
    ]


def _duration_of(trace: dict[str, Any], spans: Sequence[dict[str, Any]]) -> float | None:
    """How long a call lasted, in seconds.

    The trace latency where Langfuse has computed one, otherwise the span of
    the conversation. A call still in progress has no trace latency, so without
    the fallback a live call would show no duration at all.
    """
    try:
        latency = trace.get("latency")
        if latency is not None:
            return float(latency)
    except (TypeError, ValueError):
        pass
    for span in spans:
        if classify_layer(str(span.get("name") or "")) == LAYER_CONVERSATION:
            seconds = _latency_seconds(span)
            if seconds is not None:
                return seconds
    return None


def channel_breakdown(data: CallData) -> list[dict[str, Any]]:
    """Calls, duration and responsiveness split by browser and telephony.

    The two run the same pipeline and differ only in transport, which is what
    makes comparing them worth doing: a gap between browser and telephony in
    first-token or turn latency is a network or codec problem, not a model one.
    """
    buckets: dict[str, _Bucket] = {}
    transports: dict[str, set[str]] = {}
    turns: dict[str, list[float]] = {}

    for trace in data.calls:
        label = channel_label(trace)
        spans = data.by_call.get(str(trace.get("id") or ""), [])
        buckets.setdefault(label, _Bucket()).add(
            _duration_of(trace, spans),
            tokens=sum(_tokens_of(span) for span in spans),
            first_byte=_mean(_first_bytes(spans, LAYER_LLM)),
            failed=any(_is_failure(span) for span in spans),
        )
        transport = transport_of(trace)
        if transport:
            transports.setdefault(label, set()).add(transport)
        turns.setdefault(label, []).extend(_turn_latencies(spans))

    rows = []
    for label, bucket in buckets.items():
        row = bucket.as_row(channel=label)
        row["transports"] = ", ".join(sorted(transports.get(label, ()))) or None
        row["turns"] = len(turns.get(label, []))
        row["avg_turn_latency"] = _mean(turns.get(label, []))
        row["p95_turn_latency"] = _percentile(turns.get(label, []), 0.95)
        rows.append(row)
    rows.sort(key=lambda row: row["count_count"], reverse=True)
    return rows


def _attr_float(observation: dict[str, Any], key: str) -> float | None:
    raw = _attributes(observation).get(key)
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _node_of(span_name: str) -> str | None:
    """The workflow node a span belongs to, from its name.

    Pipecat names a generation ``llm-<node>``, truncated to the span-name
    limit, so this is the node as far as anything downstream can know it.
    """
    name = span_name or ""
    if not name.startswith("llm-"):
        return None
    return name[4:].replace("-", " ").strip() or None


def _span_window(observation: dict[str, Any]) -> tuple[datetime, datetime] | None:
    start = _parse_time(observation.get("startTime"))
    if start is None:
        return None
    return start, start + timedelta(seconds=_latency_seconds(observation) or 0.0)


def turn_breakdown(spans: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per turn: what ran, which tool, and where the time went.

    Spans are matched to a turn by **time overlap** rather than by walking
    parents. Parenting is not reliable here -- a generation that calls a tool
    parents the tool span under itself, and some generations hang off the
    conversation rather than off a turn -- so following the tree silently drops
    rows. A clock does not.

    The four stage figures are summed, never subtracted from one another. A
    tool span is nested under its generation but is *not* contained by it in
    time: one booking generation reports 2.086s with a 3.644s Epic call inside
    it. Treating the nesting as containment produces negative model time.
    """
    turns = sorted(
        (s for s in spans if classify_layer(str(s.get("name") or "")) == LAYER_TURN),
        key=lambda s: str(s.get("startTime") or ""),
    )
    if not turns:
        return []

    windows = [(_span_window(t), t) for t in turns]
    windows = [(w, t) for w, t in windows if w is not None]
    buckets: list[dict[str, Any]] = [
        {
            "index": index,
            "started_at": turn.get("startTime"),
            "duration": _latency_seconds(turn),
            "stt_seconds": 0.0,
            "stt_lag": None,
            "llm_seconds": 0.0,
            "tool_seconds": 0.0,
            "tts_seconds": 0.0,
            "ttft": None,
            "first_audio": None,
            "caller_audio_seconds": None,
            "tokens_in": 0,
            "tokens_out": 0,
            "tts_characters": 0,
            "caller": [],
            "agent": [],
            "node": None,
            "tools": [],
            "failures": 0,
        }
        for index, (_, turn) in enumerate(windows, start=1)
    ]

    for span in spans:
        layer = classify_layer(str(span.get("name") or ""))
        if layer not in RESPONSE_LAYERS:
            continue
        start = _parse_time(span.get("startTime"))
        if start is None:
            continue
        # The turn that was open when this span began. Later turns cannot own
        # it, and the most recent open one is the right answer when windows
        # overlap slightly at the seam.
        # The turn that was open when this span began. Where windows overlap at
        # the seam the most recent open one wins. A span that falls in no
        # window at all -- a tool call that outlived its turn, which happens --
        # goes to the last turn that had started, because dropping it would
        # quietly lose Epic time from the totals.
        owner = None
        for position, ((window_start, window_end), _) in enumerate(windows):
            if window_start > start:
                break
            if window_start <= start <= window_end:
                owner = position
            elif owner is None or position > owner:
                owner = position
        if owner is None:
            continue

        row = buckets[owner]
        seconds = _latency_seconds(span) or 0.0
        attributes = _attributes(span)

        if layer == LAYER_STT:
            row["stt_seconds"] += seconds
            # The span runs while the caller is still talking, so its latency
            # is mostly their speech. Its ttfb is the part that is ours: how
            # long after they stopped before the transcript arrived.
            lag = time_to_first_token(span)
            if lag is not None and row["stt_lag"] is None:
                row["stt_lag"] = lag
            row["caller_audio_seconds"] = (
                row["caller_audio_seconds"] or 0.0
            ) + (_attr_float(span, AUDIO_SECONDS_ATTRIBUTE) or 0.0)
            said = attributes.get(TRANSCRIPT_ATTRIBUTE) or span.get("output")
            if isinstance(said, str) and said.strip():
                row["caller"].append(said.strip())
        elif layer == LAYER_LLM:
            row["llm_seconds"] += seconds
            first_token = time_to_first_token(span)
            if first_token is not None and row["ttft"] is None:
                row["ttft"] = first_token
            row["tokens_in"] += int(
                (span.get("usage") or {}).get("input") or 0
            )
            row["tokens_out"] += int(
                (span.get("usage") or {}).get("output") or 0
            )
            row["node"] = row["node"] or _node_of(str(span.get("name") or ""))
        elif layer == LAYER_TTS:
            row["tts_seconds"] += seconds
            first_audio = time_to_first_token(span)
            if first_audio is not None and row["first_audio"] is None:
                row["first_audio"] = first_audio
            row["tts_characters"] += int(_attr_float(span, CHARACTER_COUNT_ATTRIBUTE) or 0)
            spoken = attributes.get(SPOKEN_TEXT_ATTRIBUTE) or span.get("input")
            if isinstance(spoken, str) and spoken.strip():
                row["agent"].append(spoken.strip())
        elif layer == LAYER_TOOL:
            row["tool_seconds"] += seconds
            row["tools"].append(
                {
                    "server": attributes.get(TOOL_SERVER),
                    "name": attributes.get(TOOL_NAME),
                    "duration": seconds,
                    "outcome": attributes.get(TOOL_OUTCOME),
                }
            )
        if _is_failure(span):
            row["failures"] += 1

    transcripts = show_transcripts()
    rows: list[dict[str, Any]] = []
    for row in buckets:
        ttft = row["ttft"]
        first_audio = row["first_audio"]
        # What the caller waits through: transcription, then the model's first
        # token, then the first audio frame. Not the whole turn, which also
        # holds the caller talking and the silence before they start.
        first_word = None
        if ttft is not None or first_audio is not None:
            first_word = (row["stt_lag"] or 0.0) + (ttft or 0.0) + (first_audio or 0.0)

        rows.append(
            {
                **{k: v for k, v in row.items() if k not in {"caller", "agent"}},
                "caller": " ".join(row["caller"]) if transcripts else None,
                "agent": " ".join(row["agent"]) if transcripts else None,
                "transcripts_hidden": not transcripts
                and bool(row["caller"] or row["agent"]),
                "first_word": first_word,
                "agent_seconds": (
                    (row["stt_lag"] or 0.0)
                    + row["llm_seconds"]
                    + row["tool_seconds"]
                    + (row["first_audio"] or 0.0)
                ),
                # The four figures the bar is drawn from. Speech in and speech
                # out contribute the wait they cause, not the whole span: an
                # stt span runs while the caller is still speaking and a tts
                # span runs while the agent is still being heard.
                "segments": {
                    "stt": row["stt_lag"] or 0.0,
                    "llm": row["llm_seconds"],
                    "tool": row["tool_seconds"],
                    "tts": row["first_audio"] or 0.0,
                },
                "route": (
                    " · ".join(
                        str(t["name"]) for t in row["tools"] if t.get("name")
                    )
                    or row["node"]
                    or "no tool"
                ),
                "tool_calls": len(row["tools"]),
                "tokens_in": row["tokens_in"] or None,
                "tokens_out": row["tokens_out"] or None,
                "tts_characters": row["tts_characters"] or None,
            }
        )
    return rows


def per_call(data: CallData) -> list[dict[str, Any]]:
    """One row per call: channel, duration, turns, first token and failures.

    The view that was missing. Averages say the system is healthy; this says
    which call was not, and carries enough of each call's shape -- how many
    turns it took, how long the caller waited for the first word, how many tool
    calls it made and how many failed -- to decide whether to open the trace.
    """
    rows: list[dict[str, Any]] = []
    for trace in data.calls:
        trace_id = str(trace.get("id") or "")
        spans = data.by_call.get(trace_id, [])

        by_layer: dict[str, list[float]] = {}
        tool_calls = 0
        failures = 0
        for span in spans:
            layer = classify_layer(str(span.get("name") or ""))
            seconds = _latency_seconds(span)
            if seconds is not None and layer in RESPONSE_LAYERS:
                by_layer.setdefault(layer, []).append(seconds)
            if layer == LAYER_TOOL:
                tool_calls += 1
            if _is_failure(span):
                failures += 1

        turn_latencies = _turn_latencies(spans)
        rows_for_call = turn_breakdown(spans)
        rows.append(
            {
                "trace_id": trace_id,
                "started_at": trace.get("timestamp"),
                "workflow": trace.get("name"),
                "channel": channel_label(trace),
                "transport": transport_of(trace),
                "session_id": trace.get("sessionId"),
                "user_id": trace.get("userId"),
                "duration": _duration_of(trace, spans),
                "turns": len(turn_latencies),
                "avg_turn_latency": _mean(turn_latencies),
                "max_turn_latency": max(turn_latencies) if turn_latencies else None,
                # Two different waits, both worth seeing per call: the model's
                # first token, and the first audio frame the caller can hear.
                "avg_first_token": _mean(_first_bytes(spans, LAYER_LLM)),
                "avg_first_audio": _mean(_first_bytes(spans, LAYER_TTS)),
                "avg_llm_latency": _mean(by_layer.get(LAYER_LLM, [])),
                "avg_stt_latency": _mean(by_layer.get(LAYER_STT, [])),
                "avg_tts_latency": _mean(by_layer.get(LAYER_TTS, [])),
                "tool_calls": tool_calls,
                "tool_seconds": sum(by_layer.get(LAYER_TOOL, [])) or None,
                # What the caller waits through, per turn, summarised for the
                # list: transcription, then first token, then first audio.
                "median_first_word": _percentile(
                    [r["first_word"] for r in rows_for_call if r["first_word"] is not None],
                    0.5,
                ),
                "median_ttft": _percentile(
                    [r["ttft"] for r in rows_for_call if r["ttft"] is not None], 0.5
                ),
                "tts_characters": sum(r["tts_characters"] or 0 for r in rows_for_call)
                or None,
                "failures": failures,
                "tokens": sum(_tokens_of(span) for span in spans) or None,
                "tokens_in": sum(r["tokens_in"] or 0 for r in rows_for_call) or None,
                "tokens_out": sum(r["tokens_out"] or 0 for r in rows_for_call) or None,
                "spans": len(spans),
            }
        )
    return rows


def turn_stats(data: CallData) -> dict[str, Any]:
    """How a conversation is made up: turns per call and time per turn.

    A turn is one exchange -- the caller stops speaking, the agent replies --
    so turn latency is the closest single number to what a caller experiences.
    Reported alongside turns per call, because a short turn time on a call that
    needed twenty turns is not a good call.
    """
    turn_latencies: list[float] = []
    turns_per_call: list[float] = []
    durations: list[float] = []
    first_token: list[float] = []

    for trace in data.calls:
        spans = data.by_call.get(str(trace.get("id") or ""), [])
        latencies = _turn_latencies(spans)
        turn_latencies.extend(latencies)
        turns_per_call.append(float(len(latencies)))
        duration = _duration_of(trace, spans)
        if duration is not None:
            durations.append(duration)
        first_token.extend(_first_bytes(spans, LAYER_LLM))

    # Percentiles travel with the sample count they were taken over. A p99 of
    # twenty turns is the slowest turn by another name, and a figure that looks
    # authoritative but is not is worse than no figure: the reader cannot tell.
    first_words = [
        row["first_word"]
        for trace in data.calls
        for row in turn_breakdown(data.by_call.get(str(trace.get("id") or ""), []))
        if row["first_word"] is not None
    ]

    return {
        "turns": len(turn_latencies),
        "conversations": len(data.calls),
        "avg_turn_latency": _mean(turn_latencies),
        "p95_turn_latency": _percentile(turn_latencies, 0.95),
        "p99_turn_latency": _percentile(turn_latencies, 0.99),
        "max_turn_latency": max(turn_latencies) if turn_latencies else None,
        "avg_turns_per_conversation": _mean(turns_per_call),
        "avg_conversation_latency": _mean(durations),
        # The model's own first token.
        "avg_first_token": _mean(first_token),
        "p50_first_token": _percentile(first_token, 0.5),
        "p95_first_token": _percentile(first_token, 0.95),
        "p99_first_token": _percentile(first_token, 0.99),
        "first_token_samples": len(first_token),
        # What the caller actually waits through.
        "p50_first_word": _percentile(first_words, 0.5),
        "p95_first_word": _percentile(first_words, 0.95),
        "p99_first_word": _percentile(first_words, 0.99),
        "first_word_samples": len(first_words),
    }


def failures(data: CallData) -> list[dict[str, Any]]:
    """Everything that went wrong, from both places failure shows up.

    Two sources, because they are genuinely different. A span marked ERROR or
    WARNING is something that raised. A tool whose outcome is not ``ok``
    returned without raising -- an unreachable server, a tool that found
    nothing -- and would otherwise be invisible, since the call degraded
    politely and carried on.

    Rows carry how many distinct calls were affected as well as how many times
    it happened: one call retrying five times and five calls each failing once
    need different responses.
    """
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}

    for observation in data.observations:
        name = str(observation.get("name") or "unknown")
        level = str(observation.get("level") or "DEFAULT").upper()
        attributes = _attributes(observation)

        if level in {"ERROR", "WARNING"}:
            detail = str(
                observation.get("statusMessage")
                or attributes.get(TOOL_ERROR_KIND)
                or level.title()
            )
            key = (classify_layer(name), name, detail)
        else:
            outcome = attributes.get(TOOL_OUTCOME)
            if not outcome or str(outcome) == str(ToolOutcome.OK):
                continue
            server = str(attributes.get(TOOL_SERVER) or "unknown")
            tool = str(attributes.get(TOOL_NAME) or name)
            detail = str(attributes.get(TOOL_ERROR_KIND) or outcome)
            key = (LAYER_TOOL, f"{server} / {tool}", detail)

        row = rows.setdefault(
            key,
            {
                "layer": key[0],
                "source": key[1],
                "detail": key[2],
                "count_count": 0,
                "_calls": set(),
                "last_seen": None,
            },
        )
        row["count_count"] += 1
        trace_id = str(observation.get("traceId") or "")
        if trace_id:
            row["_calls"].add(trace_id)
        seen = str(observation.get("startTime") or "")
        if seen and (row["last_seen"] is None or seen > row["last_seen"]):
            row["last_seen"] = seen

    ordered = sorted(rows.values(), key=lambda row: row["count_count"], reverse=True)
    return [
        {**{k: v for k, v in row.items() if k != "_calls"}, "calls": len(row["_calls"])}
        for row in ordered
    ]


def call_volume(data: CallData) -> list[dict[str, Any]]:
    """Calls and their duration, grouped by workflow.

    Grouped by the trace name, which is the workflow that ran. This is *not*
    the channel split -- that is :func:`channel_breakdown`, which reads the
    transport tag. Presenting this one as the channel was the bug behind a
    dashboard full of ``unknown``.
    """
    buckets: dict[str, _Bucket] = {}
    for trace in data.calls:
        spans = data.by_call.get(str(trace.get("id") or ""), [])
        name = str(trace.get("name") or "unnamed")
        buckets.setdefault(name, _Bucket()).add(
            _duration_of(trace, spans),
            first_byte=_mean(_first_bytes(spans, LAYER_LLM)),
            failed=any(_is_failure(span) for span in spans),
        )
    rows = [bucket.as_row(workflow=name) for name, bucket in buckets.items()]
    rows.sort(key=lambda row: row["count_count"], reverse=True)
    return rows


def call_detail(trace_id: str) -> dict[str, Any] | None:
    """Every span of one call, in order, with its own timings.

    The drill-down behind a row of the per-call table: what the agent did, in
    sequence, and how long each step took. Offsets are relative to the start of
    the call, so a reader can see where in the conversation a slow step fell
    without doing arithmetic on timestamps.
    """
    trace = _get(f"/api/public/traces/{trace_id}", {})
    if not trace:
        return None

    spans = trace.get("observations")
    if not isinstance(spans, list) or not spans:
        spans, _ = _paged(
            "/api/public/observations", {"traceId": trace_id}, _row_ceiling()
        )
    spans = [span for span in spans if isinstance(span, dict)]
    spans.sort(key=lambda span: str(span.get("startTime") or ""))

    call_start = _parse_time(trace.get("timestamp")) or (
        _parse_time(spans[0].get("startTime")) if spans else None
    )

    timeline: list[dict[str, Any]] = []
    for span in spans:
        attributes = _attributes(span)
        start = _parse_time(span.get("startTime"))
        timeline.append(
            {
                "id": span.get("id"),
                "name": span.get("name"),
                "layer": classify_layer(str(span.get("name") or "")),
                "offset": (
                    (start - call_start).total_seconds() if start and call_start else None
                ),
                "duration": _latency_seconds(span),
                "first_byte": time_to_first_token(span),
                "level": span.get("level"),
                "status_message": span.get("statusMessage"),
                "model": span.get("model") or span.get("providedModelName"),
                "tokens": _tokens_of(span) or None,
                "node": attributes.get(CALL_NODE),
                "tool_server": attributes.get(TOOL_SERVER),
                "tool_name": attributes.get(TOOL_NAME),
                "tool_outcome": attributes.get(TOOL_OUTCOME),
                "error_kind": attributes.get(TOOL_ERROR_KIND),
                "failed": _is_failure(span),
            }
        )

    rows = turn_breakdown(spans)
    first_words = [r["first_word"] for r in rows if r["first_word"] is not None]
    ttfts = [r["ttft"] for r in rows if r["ttft"] is not None]
    tool_seconds = sum(r["tool_seconds"] for r in rows)
    tool_calls = sum(r["tool_calls"] for r in rows)
    slowest = max(
        (t for r in rows for t in r["tools"] if t.get("duration") is not None),
        key=lambda t: t["duration"],
        default=None,
    )

    return {
        "trace_id": trace_id,
        "workflow": trace.get("name"),
        "started_at": trace.get("timestamp"),
        "channel": channel_label(trace),
        "transport": transport_of(trace),
        "session_id": trace.get("sessionId"),
        "user_id": trace.get("userId"),
        "duration": _duration_of(trace, spans),
        "tags": [str(tag) for tag in (trace.get("tags") or [])],
        "turns": len(rows),
        "turns_with_tool": sum(1 for r in rows if r["tool_calls"]),
        "avg_turn_latency": _mean(_turn_latencies(spans)),
        # Median and worst, not a percentile. A call has a handful of turns, and
        # a nearest-rank p95 over nine samples is the slowest one wearing a
        # statistic's name.
        "median_first_word": _percentile(first_words, 0.5),
        "max_first_word": max(first_words) if first_words else None,
        "median_ttft": _percentile(ttfts, 0.5),
        "max_ttft": max(ttfts) if ttfts else None,
        "avg_first_token": _mean(ttfts),
        "avg_first_audio": _mean(_first_bytes(spans, LAYER_TTS)),
        "tool_seconds": tool_seconds or None,
        "tool_calls": tool_calls,
        "slowest_tool": slowest,
        "tokens_in": sum(r["tokens_in"] or 0 for r in rows) or None,
        "tokens_out": sum(r["tokens_out"] or 0 for r in rows) or None,
        "tts_characters": sum(r["tts_characters"] or 0 for r in rows) or None,
        "failures": sum(r["failures"] for r in rows),
        "transcripts_available": any(r.get("transcripts_hidden") for r in rows),
        "turn_rows": rows,
        "timeline": timeline,
    }


@dataclass
class DashboardSnapshot:
    """Everything one dashboard render needs."""

    configured: bool
    window_hours: int
    generated_at: datetime
    channels: list[dict[str, Any]]
    calls: list[dict[str, Any]]
    call_volume: list[dict[str, Any]]
    pipeline_stages: list[dict[str, Any]]
    layers: list[dict[str, Any]]
    turns: dict[str, Any]
    tools: list[dict[str, Any]]
    tool_outcomes: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    models: list[dict[str, Any]]
    truncated: bool = False
    message: str | None = None


def build_snapshot(window_hours: int = 24, channel: str | None = None) -> DashboardSnapshot:
    """Gather every panel for one dashboard render.

    One fetch, then every panel reduces the same rows, so no two panels can
    disagree about the same window and a render costs two paged requests rather
    than sixteen.
    """
    now = datetime.now(timezone.utc)
    if not is_configured():
        return DashboardSnapshot(
            configured=False,
            window_hours=window_hours,
            generated_at=now,
            channels=[],
            calls=[],
            call_volume=[],
            pipeline_stages=[],
            layers=[],
            turns={},
            tools=[],
            tool_outcomes=[],
            failures=[],
            models=[],
            message=(
                "Langfuse is not configured. Set LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY "
                "and LANGFUSE_SECRET_KEY to enable call telemetry."
            ),
        )

    window = TimeWindow.last_hours(window_hours)
    data = load(window, channel=channel)

    return DashboardSnapshot(
        configured=True,
        window_hours=window_hours,
        generated_at=now,
        channels=channel_breakdown(data),
        calls=per_call(data),
        call_volume=call_volume(data),
        pipeline_stages=pipeline_stage_latency(data),
        layers=layer_breakdown(data),
        turns=turn_stats(data),
        tools=tool_performance(data),
        tool_outcomes=tool_outcomes(data),
        failures=failures(data),
        models=model_performance(data),
        truncated=data.truncated,
        message=(
            f"Showing the most recent {len(data.observations):,} spans in this window. "
            "Narrow the window for exact figures."
            if data.truncated
            else None
        ),
    )
