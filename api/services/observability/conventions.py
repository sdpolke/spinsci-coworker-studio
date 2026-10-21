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

from api.enums import WorkflowRunMode


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
#
# The tenant discriminator, and the one attribute the telemetry read path must
# never be wrong about: it is what keeps one organisation's calls off another
# organisation's dashboard.
#
# The value here must match what ``_OrgAttributeSpanProcessor`` stamps on every
# span in ``api/services/pipecat/tracing_config.py``. It previously read
# ``spinsci.organization_id``, which nothing emits, so anything filtering by the
# constant matched no spans at all. A test asserts the two agree.
ORG_ID = "spinsci.org_id"


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


# --- Channel classification ----------------------------------------------
#
# The pipeline records the *transport* a call arrived on (``webrtc``,
# ``twilio``, ``telnyx`` ...) because that is what it actually knows.
# A dashboard reader wants the coarser question answered: was this a browser
# call or a phone call? Deriving one from the other here, from the transport
# enum itself, means a newly supported telephony provider is classified
# correctly the moment it is added to ``WorkflowRunMode`` -- no dashboard edit,
# no second list to keep in step.

#: Transports that are a person in a web browser.
BROWSER_TRANSPORTS = frozenset({WorkflowRunMode.WEBRTC.value, WorkflowRunMode.SMALLWEBRTC.value})

#: Transports that are not voice at all. ``CHAT`` is the historical spelling.
TEXT_TRANSPORTS = frozenset({WorkflowRunMode.TEXTCHAT.value, WorkflowRunMode.CHAT.value})

#: Transports that reached us over a carrier.
#:
#: Derived from the enum by subtraction so that adding a provider to
#: ``WorkflowRunMode`` classifies it as telephony automatically -- the common
#: case, and the one most likely to be forgotten. ``VOICE`` is excluded because
#: the historical value says only "a voice call" and not over what, and a wrong
#: row in a channel split is worse than an honest unclassified one.
_AMBIGUOUS_TRANSPORTS = frozenset({WorkflowRunMode.VOICE.value})
TELEPHONY_TRANSPORTS = frozenset(
    mode.value
    for mode in WorkflowRunMode
    if mode.value not in BROWSER_TRANSPORTS | TEXT_TRANSPORTS | _AMBIGUOUS_TRANSPORTS
)

#: Lowercased lookup, because the historical enum values are not all lowercase
#: and the tag is read back from a trace rather than constructed here.
_CHANNEL_BY_TRANSPORT = {
    **{value.lower(): CallChannel.BROWSER for value in BROWSER_TRANSPORTS},
    **{value.lower(): CallChannel.TEXT_CHAT for value in TEXT_TRANSPORTS},
    **{value.lower(): CallChannel.TELEPHONY for value in TELEPHONY_TRANSPORTS},
}


def channel_for_transport(transport: str | None) -> CallChannel:
    """Which channel a transport belongs to.

    An unrecognised transport is ``UNKNOWN`` rather than being guessed into
    telephony: a wrong row in a channel split is worse than an honest one.
    """
    if not transport:
        return CallChannel.UNKNOWN
    return _CHANNEL_BY_TRANSPORT.get(str(transport).strip().lower(), CallChannel.UNKNOWN)


#: How each channel is written in the dashboard.
CHANNEL_LABELS = {
    CallChannel.BROWSER: "Browser",
    CallChannel.TELEPHONY: "Telephony",
    CallChannel.TEXT_CHAT: "Text chat",
    CallChannel.UNKNOWN: "Unclassified",
}
