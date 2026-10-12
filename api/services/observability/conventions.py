"""Span attribute names for SpinSci voice telemetry.

One place for every attribute name we emit, so a dashboard can be written
against constants rather than string literals scattered through the codebase.
Renaming an attribute here is a single edit that the type checker and the
tests follow; a literal typed into three call sites is a metric that silently
stops being recorded.

Naming follows OpenTelemetry conventions where they exist. ``gen_ai.*`` is the
GenAI semantic convention, which Langfuse already understands and which the LLM,
STT and TTS spans Pipecat emits already use. Everything SpinSci-specific sits
under ``spinsci.*`` so it can never collide with a convention OpenTelemetry
adds later.

Cardinality matters: these become dashboard dimensions. Values here must be
bounded sets (a tool name, a server name, a channel) and never unbounded ones
(a patient id, a phone number, a free-text reason). Unbounded values belong in
events or in redacted payloads, not in attributes.
"""

from __future__ import annotations

from enum import StrEnum


class SpanName(StrEnum):
    """Span names. Stable, low-cardinality, and treated like an API.

    Dashboards, saved filters and evaluators key off these, so renaming one
    breaks saved views. Add a new name rather than repurposing an old one.
    """

    MCP_TOOL_CALL = "mcp.tool.call"
    MCP_SESSION_START = "mcp.session.start"
    HTTP_TOOL_CALL = "http.tool.call"


class ToolKind(StrEnum):
    """What sort of tool a span describes.

    Lets one dashboard panel cover every integration while still being able to
    separate MCP servers from plain HTTP tools or built-ins.
    """

    MCP = "mcp"
    HTTP_API = "http_api"
    BUILTIN = "builtin"


class CallChannel(StrEnum):
    """How the caller reached us.

    Browser and telephony calls run the same pipeline and differ only by this
    tag, so one dashboard serves both and they stay comparable.
    """

    BROWSER = "browser"
    TELEPHONY = "telephony"
    TEXT_CHAT = "text_chat"
    UNKNOWN = "unknown"


# --- Tool-call attributes -------------------------------------------------
# Deliberately the same shape for every integration. A new MCP server or HTTP
# tool is a new *value* of TOOL_SERVER, never a new attribute, so it appears in
# existing dashboards with no schema change and no dashboard edit.

TOOL_KIND = "spinsci.tool.kind"              # ToolKind
TOOL_SERVER = "spinsci.tool.server"          # registered tool name, e.g. "Epic Direct Scheduling"
TOOL_SERVER_ID = "spinsci.tool.server_id"    # tool uuid, for joining back to the row
TOOL_NAME = "spinsci.tool.name"              # raw tool name, e.g. "epic_get_open_slots"
TOOL_FUNCTION = "spinsci.tool.function"      # namespaced name the model actually called
TOOL_OUTCOME = "spinsci.tool.outcome"        # ToolOutcome
TOOL_DURATION_MS = "spinsci.tool.duration_ms"
TOOL_ARGUMENT_COUNT = "spinsci.tool.argument_count"
TOOL_RESULT_BYTES = "spinsci.tool.result_bytes"
TOOL_ERROR_KIND = "spinsci.tool.error_kind"  # exception class, never the message

# Payloads, captured only when explicitly enabled. See capture.py.
TOOL_ARGUMENTS = "spinsci.tool.arguments"
TOOL_RESULT = "spinsci.tool.result"

# An MCP tool that returned no content. Usually wrong arguments rather than a
# genuine empty answer, and it reaches the caller as an apology rather than an
# error, so without this flag nothing on a dashboard shows it happened.
MCP_EMPTY_RESULT = "spinsci.tool.empty_result"

# --- Call-level attributes ------------------------------------------------
CALL_CHANNEL = "spinsci.call.channel"        # CallChannel
CALL_WORKFLOW_ID = "spinsci.call.workflow_id"
CALL_WORKFLOW_RUN_ID = "spinsci.call.workflow_run_id"
CALL_NODE = "spinsci.call.node"              # workflow node the call was on

# --- Organisation ---------------------------------------------------------
ORG_ID = "spinsci.organization_id"


class ToolOutcome(StrEnum):
    """How a tool call ended.

    Separate from the OTEL span status on purpose. ``UNAVAILABLE`` is a healthy
    degradation — the server was unreachable and the call carried on — while
    ``ERROR`` is the tool itself failing. Collapsing the two hides the
    difference between "their server is down" and "we called it wrong", which
    is exactly the distinction an on-call engineer needs at 3am.
    """

    OK = "ok"
    ERROR = "error"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
