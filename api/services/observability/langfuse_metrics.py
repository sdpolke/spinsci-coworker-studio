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

Credentials come from the environment (``LANGFUSE_HOST``,
``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``). When they are absent the
service reports itself unconfigured and the dashboard says so plainly, rather
than rendering zeroes that look like a quiet system.
"""

from __future__ import annotations

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
    CALL_CHANNEL,
    TOOL_DURATION_MS,
    TOOL_NAME,
    TOOL_OUTCOME,
    TOOL_SERVER,
    SpanName,
)

# One page of observations. Langfuse caps a page well below this; the loop
# below pages until the window is covered or the ceiling is reached.
_PAGE_SIZE = 100
# Ceiling on rows pulled for one dashboard render. A window with more tool
# calls than this reports what it counted rather than hanging on a long scan.
_MAX_ROWS = 2000
_TIMEOUT_SECONDS = 20.0


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


def _iter_observations(
    window: TimeWindow, *, name: str | None = None
) -> list[dict[str, Any]]:
    """Observations in the window, paged, optionally filtered to one span name."""
    rows: list[dict[str, Any]] = []
    page = 1
    while len(rows) < _MAX_ROWS:
        params: dict[str, Any] = {
            "fromStartTime": window.start.isoformat(),
            "toStartTime": window.end.isoformat(),
            "limit": _PAGE_SIZE,
            "page": page,
        }
        if name:
            params["name"] = name
        payload = _get("/api/public/observations", params)
        if not payload:
            break
        batch = payload.get("data") or []
        rows.extend(batch)
        meta = payload.get("meta") or {}
        if page >= (meta.get("totalPages") or 1) or not batch:
            break
        page += 1
    return rows[:_MAX_ROWS]


def _attributes(observation: dict[str, Any]) -> dict[str, Any]:
    """Span attributes, which Langfuse nests under metadata."""
    metadata = observation.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    attributes = metadata.get("attributes")
    return attributes if isinstance(attributes, dict) else {}


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


@dataclass
class _Bucket:
    """Running aggregate for one group."""

    count: int = 0
    samples: list[float] = field(default_factory=list)
    tokens: int = 0

    def add(self, seconds: float | None, tokens: int = 0) -> None:
        self.count += 1
        self.tokens += tokens
        if seconds is not None:
            self.samples.append(seconds)

    def as_row(self, **dimensions: Any) -> dict[str, Any]:
        return {
            **dimensions,
            "count_count": self.count,
            "avg_latency": (sum(self.samples) / len(self.samples)) if self.samples else None,
            "p95_latency": _percentile(self.samples, 0.95),
            "max_latency": max(self.samples) if self.samples else None,
            "sum_totalTokens": self.tokens or None,
        }


def _reduce(
    observations: Iterable[dict[str, Any]],
    key: Any,
    *,
    tokens_of: Any = None,
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
        tokens = tokens_of(observation) if tokens_of else 0
        buckets[bucket_key].add(_latency_seconds(observation), tokens)

    rows = [buckets[k].as_row(**dimensions[k]) for k in buckets]
    rows.sort(key=lambda row: row["count_count"], reverse=True)
    return rows


# -------------------------------------------------------------------- panels
#
# Each groups by a dimension rather than enumerating a known list, so new
# tools, servers and models appear on their own.


def tool_performance(window: TimeWindow, channel: str | None = None) -> list[dict[str, Any]]:
    """Latency and volume for every tool, grouped by server and tool.

    The panel that covers "each MCP, each Epic, each tool". Nothing here names
    a specific server, so the first call to a newly registered one adds a row.
    """
    spans = _iter_observations(window, name=str(SpanName.MCP_TOOL_CALL))

    def key(observation: dict[str, Any]) -> dict[str, Any] | None:
        attributes = _attributes(observation)
        if channel and attributes.get(CALL_CHANNEL) != channel:
            return None
        return {
            TOOL_SERVER: str(attributes.get(TOOL_SERVER) or "unknown"),
            TOOL_NAME: str(attributes.get(TOOL_NAME) or "unknown"),
        }

    return _reduce(spans, key)


def tool_outcomes(window: TimeWindow) -> list[dict[str, Any]]:
    """How tool calls ended, grouped by server and outcome.

    Separating ``unavailable`` from ``error`` is the point: one means their
    server is down and the call degraded, the other means we called it wrong,
    and the two need different fixes.
    """
    spans = _iter_observations(window, name=str(SpanName.MCP_TOOL_CALL))

    def key(observation: dict[str, Any]) -> dict[str, Any]:
        attributes = _attributes(observation)
        return {
            TOOL_SERVER: str(attributes.get(TOOL_SERVER) or "unknown"),
            TOOL_OUTCOME: str(attributes.get(TOOL_OUTCOME) or "unknown"),
        }

    return [
        {k: v for k, v in row.items() if k != "sum_totalTokens"}
        for row in _reduce(spans, key)
    ]


def model_performance(window: TimeWindow) -> list[dict[str, Any]]:
    """Latency and token usage per model.

    Grouped by the model each generation reports, so a model swapped on the
    Models page shows up here without touching this.
    """
    generations = [
        o for o in _iter_observations(window) if (o.get("type") or "").upper() == "GENERATION"
    ]

    def key(observation: dict[str, Any]) -> dict[str, Any] | None:
        model = observation.get("model") or observation.get("providedModelName")
        return {"providedModelName": str(model)} if model else None

    def tokens_of(observation: dict[str, Any]) -> int:
        usage = observation.get("usage") or {}
        if isinstance(usage, dict):
            total = usage.get("total") or usage.get("totalTokens")
            try:
                return int(total or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    return _reduce(generations, key, tokens_of=tokens_of)


def pipeline_stage_latency(window: TimeWindow) -> list[dict[str, Any]]:
    """Average and p95 latency for each pipeline stage.

    Grouped by span name, which is how the LLM, speech and tool stages separate
    without this needing to know what any of them are called.
    """
    observations = _iter_observations(window)

    def key(observation: dict[str, Any]) -> dict[str, Any] | None:
        name = observation.get("name")
        return {"name": str(name)} if name else None

    return _reduce(observations, key)


def layer_breakdown(window: TimeWindow) -> list[dict[str, Any]]:
    """Latency per pipeline layer: speech in, model, speech out, tools.

    The panel that answers "where did the time go" without the reader needing
    to know what a span is called. LLM rows also carry time to first token,
    which is the figure that decides whether a call feels responsive -- total
    LLM latency includes generating the whole reply, but the caller stops
    waiting as soon as speech begins.
    """
    observations = _iter_observations(window)

    buckets: dict[str, _Bucket] = {}
    ttft: dict[str, list[float]] = {}
    for observation in observations:
        layer = classify_layer(str(observation.get("name") or ""))
        if layer not in RESPONSE_LAYERS:
            continue
        buckets.setdefault(layer, _Bucket()).add(_latency_seconds(observation))
        first_token = time_to_first_token(observation)
        if first_token is not None:
            ttft.setdefault(layer, []).append(first_token)

    rows = []
    for layer, bucket in buckets.items():
        row = bucket.as_row(layer=layer)
        samples = ttft.get(layer, [])
        row["avg_first_token"] = (sum(samples) / len(samples)) if samples else None
        row["p95_first_token"] = _percentile(samples, 0.95)
        rows.append(row)

    # Slowest first: the layer to look at is the one taking the most time.
    rows.sort(key=lambda row: row["avg_latency"] or 0, reverse=True)
    return rows


def turn_stats(window: TimeWindow) -> dict[str, Any]:
    """How a conversation is made up: turns per call and time per turn.

    A turn is one exchange -- the caller stops speaking, the agent replies --
    so turn latency is the closest single number to what a caller experiences.
    Reported alongside turns per call, because a short turn time on a call that
    needed twenty turns is not a good call.
    """
    observations = _iter_observations(window)

    turn_latencies: list[float] = []
    turns_per_conversation: dict[str, int] = {}
    conversation_latencies: list[float] = []

    for observation in observations:
        layer = classify_layer(str(observation.get("name") or ""))
        seconds = _latency_seconds(observation)
        if layer == LAYER_TURN:
            if seconds is not None:
                turn_latencies.append(seconds)
            trace_id = str(observation.get("traceId") or "")
            if trace_id:
                turns_per_conversation[trace_id] = turns_per_conversation.get(trace_id, 0) + 1
        elif layer == LAYER_CONVERSATION and seconds is not None:
            conversation_latencies.append(seconds)

    turn_counts = list(turns_per_conversation.values())
    return {
        "turns": len(turn_latencies),
        "conversations": len(turns_per_conversation) or len(conversation_latencies),
        "avg_turn_latency": (
            sum(turn_latencies) / len(turn_latencies) if turn_latencies else None
        ),
        "p95_turn_latency": _percentile(turn_latencies, 0.95),
        "max_turn_latency": max(turn_latencies) if turn_latencies else None,
        "avg_turns_per_conversation": (
            sum(turn_counts) / len(turn_counts) if turn_counts else None
        ),
        "avg_conversation_latency": (
            sum(conversation_latencies) / len(conversation_latencies)
            if conversation_latencies
            else None
        ),
    }


def failures(window: TimeWindow) -> list[dict[str, Any]]:
    """Everything that went wrong, from both places failure shows up.

    Two sources, because they are genuinely different. A span marked ERROR or
    WARNING is something that raised. A tool whose outcome is not ``ok``
    returned without raising -- an unreachable server, a tool that found
    nothing -- and would otherwise be invisible, since the call degraded
    politely and carried on.
    """
    observations = _iter_observations(window)
    rows: dict[tuple[str, str, str], int] = {}

    for observation in observations:
        name = str(observation.get("name") or "unknown")
        layer = classify_layer(name)
        level = str(observation.get("level") or "DEFAULT").upper()
        attributes = _attributes(observation)

        if level in {"ERROR", "WARNING"}:
            detail = str(
                observation.get("statusMessage")
                or attributes.get("spinsci.tool.error_kind")
                or level.title()
            )
            key = (layer, name, detail)
            rows[key] = rows.get(key, 0) + 1
            continue

        outcome = attributes.get(TOOL_OUTCOME)
        if outcome and outcome != "ok":
            server = str(attributes.get(TOOL_SERVER) or "unknown")
            tool = str(attributes.get(TOOL_NAME) or name)
            detail = str(attributes.get("spinsci.tool.error_kind") or outcome)
            key = (LAYER_TOOL, f"{server} / {tool}", detail)
            rows[key] = rows.get(key, 0) + 1

    return [
        {"layer": layer, "source": source, "detail": detail, "count_count": count}
        for (layer, source, detail), count in sorted(
            rows.items(), key=lambda item: item[1], reverse=True
        )
    ]


def call_volume(window: TimeWindow) -> list[dict[str, Any]]:
    """Calls and their duration, grouped by trace name.

    Traces are named per conversation type, so browser, telephony and text
    chat separate here without a second query.
    """
    rows: list[dict[str, Any]] = []
    page = 1
    while len(rows) < _MAX_ROWS:
        payload = _get(
            "/api/public/traces",
            {
                "fromTimestamp": window.start.isoformat(),
                "toTimestamp": window.end.isoformat(),
                "limit": _PAGE_SIZE,
                "page": page,
            },
        )
        if not payload:
            break
        batch = payload.get("data") or []
        rows.extend(batch)
        meta = payload.get("meta") or {}
        if page >= (meta.get("totalPages") or 1) or not batch:
            break
        page += 1

    def key(trace: dict[str, Any]) -> dict[str, Any]:
        return {"name": str(trace.get("name") or "unnamed")}

    return [
        {k: v for k, v in row.items() if k != "sum_totalTokens"}
        for row in _reduce(rows[:_MAX_ROWS], key)
    ]


@dataclass
class DashboardSnapshot:
    """Everything one dashboard render needs."""

    configured: bool
    window_hours: int
    generated_at: datetime
    call_volume: list[dict[str, Any]]
    pipeline_stages: list[dict[str, Any]]
    layers: list[dict[str, Any]]
    turns: dict[str, Any]
    tools: list[dict[str, Any]]
    tool_outcomes: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    models: list[dict[str, Any]]
    message: str | None = None


def build_snapshot(window_hours: int = 24, channel: str | None = None) -> DashboardSnapshot:
    """Gather every panel for one dashboard render.

    Panels are gathered independently: one that fails returns empty and the
    rest still render, because four panels and a gap are far more useful to
    someone debugging than a single error.
    """
    now = datetime.now(timezone.utc)
    if not is_configured():
        return DashboardSnapshot(
            configured=False,
            window_hours=window_hours,
            generated_at=now,
            call_volume=[], pipeline_stages=[], layers=[], turns={},
            tools=[], tool_outcomes=[], failures=[], models=[],
            message=(
                "Langfuse is not configured. Set LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY "
                "and LANGFUSE_SECRET_KEY to enable call telemetry."
            ),
        )

    window = TimeWindow.last_hours(window_hours)
    return DashboardSnapshot(
        configured=True,
        window_hours=window_hours,
        generated_at=now,
        call_volume=call_volume(window),
        pipeline_stages=pipeline_stage_latency(window),
        layers=layer_breakdown(window),
        turns=turn_stats(window),
        tools=tool_performance(window, channel=channel),
        tool_outcomes=tool_outcomes(window),
        failures=failures(window),
        models=model_performance(window),
    )
