"""Tests for tool-call tracing.

Two things are worth guarding here. One is that the span records what a
dashboard needs. The other, and the reason these tests are not optional, is
that it does *not* record what it must never record: tool arguments on this
platform carry patient names, dates of birth and phone numbers, and an
exception message routinely quotes the arguments that caused it.
"""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from api.services.observability import capture
from api.services.observability.conventions import (
    TOOL_ARGUMENT_COUNT,
    TOOL_ARGUMENTS,
    TOOL_DURATION_MS,
    TOOL_ERROR_KIND,
    TOOL_NAME,
    TOOL_OUTCOME,
    TOOL_RESULT,
    TOOL_RESULT_BYTES,
    TOOL_SERVER,
    SpanName,
    ToolKind,
    ToolOutcome,
)
from api.services.observability import tool_spans as tool_spans_module
from api.services.observability.tool_spans import tool_call_span

PATIENT_ARGS = {
    "Name": "Theodore Mychart",
    "DateOfBirth": "1948-07-07",
    "phone": "608-213-5806",
}


@pytest.fixture
def spans(monkeypatch):
    """Capture spans in memory for the duration of one test.

    Patches the module's own ``trace.get_tracer`` rather than installing a
    global tracer provider. ``set_tracer_provider`` only takes effect once per
    process, and writing the private global instead leaks into every test that
    follows -- restoring the default proxy provider there makes it resolve to
    itself, and the next real tool call dies with a recursion error rather than
    anything that points at the cause.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        tool_spans_module.trace, "get_tracer", lambda _name: provider.get_tracer(_name)
    )
    yield exporter


def only_span(exporter):
    finished = exporter.get_finished_spans()
    assert len(finished) == 1, f"expected one span, got {len(finished)}"
    return finished[0]


def test_records_the_dimensions_a_dashboard_groups_by(spans):
    with tool_call_span(
        tool_name="epic_get_open_slots",
        server="Epic Direct Scheduling",
        server_id="4c6a1fce",
        kind=ToolKind.MCP,
        arguments=PATIENT_ARGS,
    ) as recorder:
        recorder.set_result('{"slots": []}')

    attrs = dict(only_span(spans).attributes)
    assert attrs[TOOL_NAME] == "epic_get_open_slots"
    assert attrs[TOOL_SERVER] == "Epic Direct Scheduling"
    assert attrs[TOOL_OUTCOME] == str(ToolOutcome.OK)
    assert attrs[TOOL_ARGUMENT_COUNT] == len(PATIENT_ARGS)
    assert attrs[TOOL_RESULT_BYTES] > 0
    assert attrs[TOOL_DURATION_MS] >= 0


def test_span_name_is_stable(spans):
    """Dashboards and saved filters key off the name, so it must not drift."""
    with tool_call_span(tool_name="find_patient"):
        pass
    assert only_span(spans).name == str(SpanName.MCP_TOOL_CALL)


def test_patient_data_is_not_captured_by_default(spans):
    """The default must be safe without anyone configuring anything."""
    assert capture.CAPTURE_PAYLOADS is False

    with tool_call_span(tool_name="find_patient", arguments=PATIENT_ARGS) as recorder:
        recorder.set_result("Theodore Mychart, born 1948-07-07")

    attrs = dict(only_span(spans).attributes)
    assert TOOL_ARGUMENTS not in attrs
    assert TOOL_RESULT not in attrs
    # The sizes a latency dashboard needs survive without the content.
    assert attrs[TOOL_ARGUMENT_COUNT] == 3
    assert attrs[TOOL_RESULT_BYTES] > 0

    serialised = str(attrs)
    assert "Theodore" not in serialised
    assert "1948-07-07" not in serialised
    assert "608-213-5806" not in serialised


def test_exception_message_is_not_recorded(spans):
    """Error messages quote the arguments that caused them."""
    with pytest.raises(RuntimeError):
        with tool_call_span(tool_name="book_appointment"):
            raise RuntimeError("rejected appointment for patient E2734 Theodore Mychart")

    attrs = dict(only_span(spans).attributes)
    assert attrs[TOOL_ERROR_KIND] == "RuntimeError"
    assert attrs[TOOL_OUTCOME] == str(ToolOutcome.ERROR)
    assert "Theodore" not in str(attrs)
    assert "E2734" not in str(attrs)


def test_exception_propagates_unchanged(spans):
    """Tracing observes; it must never alter control flow."""
    sentinel = ValueError("boom")
    with pytest.raises(ValueError) as caught:
        with tool_call_span(tool_name="whatever"):
            raise sentinel
    assert caught.value is sentinel


def test_unavailable_is_distinct_from_error(spans):
    """A server being down and a tool failing need telling apart."""
    with tool_call_span(tool_name="find_patient") as recorder:
        recorder.set_outcome(ToolOutcome.UNAVAILABLE)

    span = only_span(spans)
    assert dict(span.attributes)[TOOL_OUTCOME] == str(ToolOutcome.UNAVAILABLE)
    # Deliberately not an ERROR span status: the server was unreachable and the
    # call carried on, which is a healthy degradation rather than a fault. A
    # dashboard separates the two on the outcome attribute, not on span status.
    assert span.status.status_code is not StatusCode.ERROR


def test_caller_set_outcome_is_not_overwritten(spans):
    with tool_call_span(tool_name="find_patient") as recorder:
        recorder.set_outcome(ToolOutcome.NOT_FOUND)
    assert dict(only_span(spans).attributes)[TOOL_OUTCOME] == str(ToolOutcome.NOT_FOUND)


def test_payload_capture_redacts_then_truncates(monkeypatch, spans):
    """Enabled deliberately, secrets are still redacted and payloads bounded."""
    monkeypatch.setattr(capture, "CAPTURE_PAYLOADS", True)
    monkeypatch.setattr(capture, "REDACT_PAYLOADS", True)
    monkeypatch.setattr(capture, "PAYLOAD_MAX_BYTES", 80)

    with tool_call_span(
        tool_name="find_patient",
        arguments={"Name": "Theodore", "api_key": "mcpf_SECRET", "password": "hunter2"},
    ) as recorder:
        recorder.set_result("x" * 500)

    attrs = dict(only_span(spans).attributes)
    assert "mcpf_SECRET" not in attrs[TOOL_ARGUMENTS]
    assert "hunter2" not in attrs[TOOL_ARGUMENTS]
    assert "[REDACTED]" in attrs[TOOL_ARGUMENTS]
    # Truncated for the span, but the true size is still reported.
    assert len(attrs[TOOL_RESULT]) <= 80
    assert attrs[TOOL_RESULT_BYTES] == 500


def test_unserialisable_payload_does_not_leak_repr(monkeypatch):
    """repr() of an object is how unredacted data escapes a redactor."""
    monkeypatch.setattr(capture, "CAPTURE_PAYLOADS", True)

    class Unserialisable:
        def __repr__(self):
            return "<Patient Theodore Mychart 1948-07-07>"

        def __str__(self):
            return repr(self)

    class Exploding(dict):
        def items(self):
            raise TypeError("cannot iterate")

    prepared = capture.prepare_payload(Exploding())
    assert prepared == "[unserialisable]"
    assert "Theodore" not in (prepared or "")


def test_works_with_tracing_unavailable(monkeypatch):
    """Tracing off must take the same code path, not a second one."""

    def no_tracer(_name):
        raise RuntimeError("no provider")

    monkeypatch.setattr(tool_spans_module.trace, "get_tracer", no_tracer)
    with tool_call_span(tool_name="find_patient", arguments={"a": 1}) as recorder:
        recorder.set_result("ok")
        recorder.set_outcome(ToolOutcome.OK)
        recorder.set_attribute("anything", "accepted")
    # Reaching here without raising is the assertion.
