"""Tracing for tool calls, in one place.

Every integration the agent can call -- an MCP server, an HTTP tool, a built-in
-- records the same attributes through this module. That uniformity is the
whole point: a new MCP server becomes a new *value* of ``spinsci.tool.server``,
not a new span shape, so it appears in existing dashboards the day it is
registered with no dashboard change and no instrumentation work.

Three rules this module exists to enforce:

**Instrumentation never breaks a call.** Every failure path here swallows its
own exception. A tracing backend being down, an attribute failing to serialise,
a context that cannot be built -- none of that is worth dropping a live call
for. The work runs whether or not the span does.

**One code path.** Tracing on and tracing off run the same lines, differing
only in whether a real span or a no-op is in hand. Writing the call twice, once
inside a span and once outside, is how the two drift until the traced path
behaves differently from the one in production.

**Timing is ours, not the backend's.** Duration is measured here with a
monotonic clock and recorded as an attribute, so a dashboard can aggregate it
directly rather than deriving it from span start and end timestamps, which
tracing backends round and clock skew distorts.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

from loguru import logger
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from api.services.observability import capture
from api.services.observability.conventions import (
    ORG_ID,
    TOOL_ARGUMENT_COUNT,
    TOOL_ARGUMENTS,
    TOOL_DURATION_MS,
    TOOL_ERROR_KIND,
    TOOL_FUNCTION,
    TOOL_KIND,
    TOOL_NAME,
    TOOL_OUTCOME,
    TOOL_RESULT,
    TOOL_RESULT_BYTES,
    TOOL_SERVER,
    TOOL_SERVER_ID,
    SpanName,
    ToolKind,
    ToolOutcome,
)

_TRACER_NAME = "pipecat"  # shared with the rest of the voice pipeline


class ToolCallRecorder:
    """Handle for the in-flight tool span.

    Handed to the caller so it can record the outcome it alone knows about --
    an empty result, a degraded server, the size of what came back -- without
    the span helper needing to understand any particular tool's semantics.

    Every method is safe to call when tracing is off; the underlying span is
    then a no-op and the calls cost a branch.
    """

    def __init__(self, span: Span | None) -> None:
        self._span = span
        self._outcome_set = False

    def _set(self, key: str, value: Any) -> None:
        if self._span is None or value is None:
            return
        try:
            self._span.set_attribute(key, value)
        except Exception:  # noqa: BLE001 - never break a call for an attribute
            logger.debug(f"tool span: could not set {key}")

    def set_outcome(self, outcome: ToolOutcome) -> None:
        """Record how the call ended.

        Explicit rather than inferred from whether an exception escaped: a tool
        that returns a structured error, or an MCP server that is unreachable
        and degrades gracefully, raises nothing yet did not succeed.
        """
        self._set(TOOL_OUTCOME, str(outcome))
        self._outcome_set = True

    def set_result(self, result: Any) -> None:
        """Record the size of what came back, and its content only if enabled."""
        self._set(TOOL_RESULT_BYTES, capture.payload_size(result))
        payload = capture.prepare_payload(result)
        if payload is not None:
            self._set(TOOL_RESULT, payload)

    def set_attribute(self, key: str, value: Any) -> None:
        """Record an integration-specific attribute.

        Use a name from ``conventions`` where one fits. Anything added here
        becomes a dashboard dimension, so it must be low cardinality -- a
        status, a category, a count. Never an identifier or free text.
        """
        self._set(key, value)

    @property
    def outcome_recorded(self) -> bool:
        return self._outcome_set


@contextmanager
def tool_call_span(
    *,
    tool_name: str,
    server: str | None = None,
    server_id: str | None = None,
    function_name: str | None = None,
    kind: ToolKind = ToolKind.MCP,
    arguments: Mapping[str, Any] | None = None,
    organization_id: int | str | None = None,
    span_name: SpanName = SpanName.MCP_TOOL_CALL,
) -> Iterator[ToolCallRecorder]:
    """Trace one tool call.

    Yields a :class:`ToolCallRecorder` for the caller to record the outcome on.
    If the body raises, the exception is recorded and re-raised unchanged --
    tracing observes, it does not alter control flow.

    If the body neither raises nor sets an outcome, the call is recorded as
    successful: a tool that returned without complaint did its job.

    Args:
        tool_name: Raw tool name as the server knows it, e.g. ``find_patient``.
        server: Registered name of the server, e.g. ``Epic Direct Scheduling``.
        server_id: Tool uuid, so a span joins back to the registered row.
        function_name: Namespaced name the model actually called.
        kind: Which sort of integration this is.
        arguments: Call arguments. Only the count is recorded unless payload
            capture is enabled.
        organization_id: Owning organisation, for per-tenant aggregation.
        span_name: Stable span name; dashboards key off it.
    """
    tracer = None
    try:
        tracer = trace.get_tracer(_TRACER_NAME)
    except Exception:  # noqa: BLE001
        logger.debug("tool span: no tracer available")

    if tracer is None:
        # Tracing unavailable: same code path, inert recorder.
        yield ToolCallRecorder(None)
        return

    started = time.monotonic()
    with tracer.start_as_current_span(str(span_name)) as span:
        recorder = ToolCallRecorder(span)
        recorder.set_attribute(TOOL_KIND, str(kind))
        recorder.set_attribute(TOOL_NAME, tool_name)
        recorder.set_attribute(TOOL_SERVER, server)
        recorder.set_attribute(TOOL_SERVER_ID, server_id)
        recorder.set_attribute(TOOL_FUNCTION, function_name)
        recorder.set_attribute(ORG_ID, str(organization_id) if organization_id is not None else None)

        if arguments is not None:
            recorder.set_attribute(TOOL_ARGUMENT_COUNT, len(arguments))
            payload = capture.prepare_payload(arguments)
            if payload is not None:
                recorder.set_attribute(TOOL_ARGUMENTS, payload)

        try:
            yield recorder
        except Exception as exc:
            _finish(span, recorder, started, ToolOutcome.ERROR)
            # The class name is a bounded set and safe to aggregate on. The
            # message is not: it routinely carries the arguments that caused
            # the failure, which is how patient data reaches a trace backend
            # that was never meant to hold any.
            recorder.set_attribute(TOOL_ERROR_KIND, type(exc).__name__)
            try:
                span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            except Exception:  # noqa: BLE001
                pass
            raise
        else:
            _finish(
                span,
                recorder,
                started,
                None if recorder.outcome_recorded else ToolOutcome.OK,
            )


def _finish(
    span: Span,
    recorder: ToolCallRecorder,
    started: float,
    outcome: ToolOutcome | None,
) -> None:
    """Stamp duration, and an outcome if the caller did not set one."""
    try:
        recorder.set_attribute(TOOL_DURATION_MS, round((time.monotonic() - started) * 1000, 2))
        if outcome is not None:
            recorder.set_outcome(outcome)
    except Exception:  # noqa: BLE001
        logger.debug("tool span: could not finalise")
